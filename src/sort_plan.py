"""Read-only "list sorting" plan builder.

Groups all-stores Pending offers (list 9, no store filter) by the Move-to-List
target that :func:`src.aks_lists.suggest_target_list` derives from each offer's
deterministic categorical skip reason (:func:`src.matcher.precheck_skip`).

Pure and deterministic — no network, no browser, no mutation. The scan that
feeds it is read-only; the moves it plans stay behind the Stage-6 gate (per-list
bulk validation + RV2 proof + versioned authorization + Romain's go). Building
or printing a plan NEVER moves anything.

A plan classifies every offer into exactly one of:
  - **routed**   — a skip reason that maps to a target list (→ ``by_list``);
  - **unrouted** — a skip reason with no confident target (garder / operator);
  - **candidate**— passes precheck (a creation candidate, not our call here).
"""

from __future__ import annotations

from dataclasses import replace

from collections.abc import Iterable

from src.aks_lists import label_for, suggest_target_list
from src.merchants.registry import merchant_for_store
from src.contracts import NormalizedOffer
from src.matcher import is_account_offer, is_software_title, precheck_skip

# Account offers pass precheck (the submit pipeline resolves them to their
# dedicated AKS account page) — but the sort routes them out of the creation
# queue into the account list (Romain 2026-07-23). This is a sort-layer policy,
# deliberately NOT a precheck skip, so the submit pipeline is unchanged.
_ACCOUNT_LIST_ID = "30"


def _entry(offer: NormalizedOffer, reason: str) -> dict:
    return {
        "offer_id": offer.offer_id,
        "store_id": offer.store_id,
        "name": offer.name,
        "url": offer.url,
        "reason": reason,
    }


def _with_canonical_merchant(offer: NormalizedOffer) -> NormalizedOffer:
    """The same offer with its MERCHANT restored from ``store_id`` when the feed label is
    not a merchant name (the all-stores scan). Returns the offer untouched otherwise."""

    canonical = merchant_for_store(getattr(offer, "store_id", None))
    if canonical is None or canonical == offer.merchant:
        return offer
    return replace(offer, merchant=canonical)


def coverage_from_stats(stats: dict, *, first_page: int = 1, sliced: bool = False) -> dict:
    """Le bloc ``coverage`` d'un plan de tri, jugé sur ce que la marche a OBSERVÉ.

    AUDIT DU 2026-09-21. ``feed_last_page`` est un MAXIMUM courant : il retient la plus
    grande pagination vue depuis le début. Une longue marche voit la liste RÉTRÉCIR sous
    elle — le scan du 21/09 a lu 566 pages annoncées en page 1, puis 488 en page 489, où la
    liste s'est terminée. Comparer 566 aux 489 pages lues déclarait la couverture tronquée,
    et la console taisait alors TOUTE proposition de requête (garde du 18/09, `sort_sql_view`).
    On juge donc sur deux témoins observés : avoir vu la page d'après-la-fin
    (``ended_past_end``), ou avoir lu au moins autant de pages que la dernière pagination
    RÉELLEMENT lue (``feed_last_page_final``). Une tranche explicite reste tronquée par
    nature, et de vieilles statistiques sans les témoins retombent sur l'ancien verdict."""

    covered = int(stats.get("pages_fetched") or 0)
    feed_pages = int(stats.get("feed_last_page") or 0)
    feed_final = int(stats.get("feed_last_page_final") or 0) or feed_pages
    reached_end = bool(stats.get("ended_past_end")) or (
        feed_final <= first_page - 1 + covered)
    return {
        "partial": True,
        "pages_fetched": covered,
        "feed_last_page": feed_pages,
        "feed_last_page_final": feed_final,
        "ended_past_end": bool(stats.get("ended_past_end")),
        "truncated": bool(sliced) or not reached_end,
    }


def build_sort_plan(
    offers: Iterable[NormalizedOffer],
    *,
    run_id: str = "",
    source_feed_page: str = "aks-merchant-feeds-9",
) -> dict:
    """Group offers by suggested target list. See module docstring for classes."""

    offers = list(offers)
    by_list: dict[str, list[dict]] = {}
    unrouted: list[dict] = []
    candidates = 0

    for offer in offers:
        # The all-stores scan reads the feed WITHOUT a store filter, so every row is
        # labelled "all-stores" and `merchant_config()` finds nothing — the merchant rules
        # never fire (audit de Romain, 2026-09-16: an MMOGA "… RU Key" row routed Blacklist
        # under its real merchant became an un-routed creation candidate here; same for BR
        # and CN). Restore the canonical identity from the store id the feed DOES give.
        # Unknown store → the row keeps its label and the generic behaviour applies.
        offer = _with_canonical_merchant(offer)
        reason = precheck_skip(offer)
        if reason is None and is_software_title(offer):
            # R31: software is no longer pre-skipped for ENTRY (match_offer's
            # software path enters it with the page licence edition), but the SORT
            # still groups it under the Softwares list — a title classifier, no
            # page fetch. Kept distinct so the two workflows don't fight.
            reason = "skip category: SOFTWARE (software/app — sort routing)"
        if reason is None:
            # Passes precheck → a creation candidate, UNLESS it is an account (the one
            # detector: merchant grammar, title word, URL path token — 2026-09-25), which
            # the sort routes to the account list. Only a merchant that DECLARES its
            # accounts (`account_row`) still reaches here: every other account is already
            # refused by the precheck, and routed to 30 by its reason.
            if is_account_offer(offer.name, offer.url, offer.merchant):
                by_list.setdefault(_ACCOUNT_LIST_ID, []).append(
                    _entry(offer, "account offer (marqueur (Account))"))
            else:
                candidates += 1
            continue
        target = suggest_target_list(reason)
        if target is None:
            unrouted.append(_entry(offer, reason))
        else:
            by_list.setdefault(target, []).append(_entry(offer, reason))

    # Largest routable groups first — that is the order Romain validates in.
    ordered = sorted(by_list.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    routed = sum(len(rows) for _, rows in ordered)

    return {
        "run_id": run_id,
        "source_feed_page": source_feed_page,
        "counts": {
            "total": len(offers),
            "routed": routed,
            "unrouted_skips": len(unrouted),
            "candidates": candidates,
            "target_lists": len(ordered),
        },
        "by_list": {
            list_id: {
                "list_id": list_id,
                "label": label_for(list_id),
                "count": len(rows),
                "offers": rows,
            }
            for list_id, rows in ordered
        },
        "unrouted": unrouted,
    }


def render_report(plan: dict, *, per_list_limit: int | None = None) -> str:
    """Human report grouped by target list. ``per_list_limit`` caps the rows
    shown per list (the full set always lives in ``sort_plan.json``); None =
    show every offer (what Romain needs to validate a list in bulk)."""

    c = plan["counts"]
    lines = [
        f"# Plan de tri — Pending tous stores — {plan['run_id'] or '(sans run_id)'}",
        "",
        f"{c['total']} offres — {c['routed']} routables vers {c['target_lists']} "
        f"liste(s) | {c['unrouted_skips']} skips sans liste (garder) | "
        f"{c['candidates']} candidats création",
        "",
    ]
    for group in plan["by_list"].values():
        lines.append(f"## → {group['label'] or '?'} (liste {group['list_id']}) — {group['count']}")
        rows = group["offers"]
        shown = rows if per_list_limit is None else rows[:per_list_limit]
        for entry in shown:
            store = entry["store_id"] or "?"
            lines.append(f"  • [store {store}] {entry['name']}  ⟶  {entry['reason']}")
        if per_list_limit is not None and len(rows) > per_list_limit:
            lines.append(f"  … (+{len(rows) - per_list_limit} autres, voir sort_plan.json)")
        lines.append("")
    return "\n".join(lines)

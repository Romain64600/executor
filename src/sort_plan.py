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

from collections.abc import Iterable

from src.aks_lists import label_for, suggest_target_list
from src.contracts import NormalizedOffer
from src.matcher import is_account_offer, precheck_skip

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
        reason = precheck_skip(offer)
        if reason is None:
            # Passes precheck → a creation candidate, UNLESS it carries the
            # account-delivery marker, which the sort routes to the account list.
            if is_account_offer(offer.name):
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

"""Unified per-page triage — ADD / MOVE-to-list / SKIP (Romain 2026-08-13).

Romain's page-by-page workflow: *"vu qu'on passe page par page, on peut ajouter des
offres safe. Par la même, cela pourrait aussi ... envoyer certaines offres dans
certaines listes ... et on skippe ce qu'on a à skipper. Puis on passe à la
suivante."* One pass over a merchant feed page classifies every offer into exactly
one action:

  - **ADD**  — ``match_offer`` returned a Candidate → enter it (safe-auto submit);
  - **MOVE** — ``match_offer`` skipped it AND the skip reason maps to a target list
               (:func:`src.aks_lists.suggest_target_list`) → move it out of the feed;
  - **SKIP** — skipped with no confident target list → leave in place (garder).

It wraps the FULL matcher decision (:func:`src.matcher.match_offer`), not just
``precheck_skip``, so a signal visible only on the merchant's OWN offer page routes
correctly — e.g. an Instant Gaming *Steam RU* offer becomes MOVE→Blacklist, not a
silent GLOBAL ADD. (The all-stores sort — :mod:`src.sort_plan` — deliberately stays
precheck-only: it scans list 9 at account scale and cannot fetch a page per offer.)

Pure and deterministic given its injected matcher — no browser here. The
side-effecting per-page orchestration (submit the ADDs, move the MOVEs, then next
page) is wired by the sweep runner, exactly as :mod:`src.data_entry_auto` injects
its stages.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from src.aks_lists import label_for, suggest_target_list
from src.contracts import NormalizedOffer
from src.matcher import Candidate, SkippedOffer, match_offer

ADD = "add"
MOVE = "move"
SKIP = "skip"


@dataclass(frozen=True)
class Triage:
    """One offer's deterministic disposition for the per-page pass."""

    action: str                            # ADD | MOVE | SKIP
    offer: NormalizedOffer
    reason: str = ""                       # skip/move reason ("" for ADD)
    list_id: str | None = None             # MOVE target list id
    list_label: str = ""                   # MOVE target list label
    candidate: Candidate | None = None     # ADD candidate (the match result)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "action": self.action,
            "offer_id": self.offer.offer_id,
            "store_id": self.offer.store_id,
            "name": self.offer.name,
            "url": self.offer.url,
        }
        if self.action == MOVE:
            d["list_id"], d["list_label"], d["reason"] = self.list_id, self.list_label, self.reason
        elif self.action == SKIP:
            d["reason"] = self.reason
        else:  # ADD
            d["candidate"] = self.candidate.to_dict() if self.candidate else None
        return d


def triage_offer(
    offer: NormalizedOffer,
    matcher: Callable[..., Candidate | SkippedOffer] = match_offer,
    **match_kwargs: Any,
) -> Triage:
    """Classify a single offer. ``matcher`` (default :func:`match_offer`) does the
    real work — including any merchant offer-page fetch — and its result decides:
    a Candidate → ADD; a SkippedOffer whose reason routes to a list → MOVE; else
    SKIP. ``match_kwargs`` are forwarded to the matcher (its resolvers)."""

    result = matcher(offer, **match_kwargs)
    if isinstance(result, Candidate):
        return Triage(ADD, offer, candidate=result)
    # SkippedOffer — a routable reason becomes a MOVE, everything else a SKIP.
    target = suggest_target_list(result.reason)
    if target is not None:
        return Triage(MOVE, offer, reason=result.reason,
                      list_id=target, list_label=label_for(target))
    return Triage(SKIP, offer, reason=result.reason)


def plan_moves_from_skipped(skipped: list[dict[str, Any]]) -> dict[str, Any]:
    """Group a run's ``skipped.json`` (matcher SkippedOffer dicts:
    ``{"offer": {...}, "reason": str}``) into Move-to-List targets, keyed on
    :func:`suggest_target_list` of each reason. Non-routable skips (garder) are
    excluded. Returns ``{by_list, movable, target_lists}`` (largest group first).

    This is the sweep's move-planning input: the reasons already reflect the FULL
    match decision, so an Instant Gaming region read from the offer PAGE (invisible
    to ``precheck_skip``) still routes here — unlike :mod:`src.sort_plan`, which
    re-derives reasons from the title only for the account-scale all-stores sort."""

    by_list: dict[str, list[dict[str, Any]]] = {}
    for entry in skipped or []:
        if not isinstance(entry, dict):
            continue
        reason = str(entry.get("reason", ""))
        target = suggest_target_list(reason)
        if target is None:
            continue
        offer = entry.get("offer") or {}
        by_list.setdefault(target, []).append({
            "offer_id": str(offer.get("offer_id", "")),
            "store_id": str(offer.get("store_id") or ""),
            "name": offer.get("name", ""),
            "url": offer.get("url", ""),
            "reason": reason,
            "list_id": target,
            "list_label": label_for(target),
        })
    ordered = {
        list_id: rows
        for list_id, rows in sorted(by_list.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    }
    return {
        "by_list": ordered,
        "movable": sum(len(rows) for rows in ordered.values()),
        "target_lists": len(ordered),
    }


# A learning CANARY stops with "limit_reached" the instant it moves its 1 offer —
# that is its SUCCESS signal, not a fault; "operator_stop" is a cooperative stop.
# Both are benign (mirrors data_entry_auto._BENIGN_STOPPED). Any OTHER stopped value
# (feed_unreadable / guard_blocked / ten_consecutive_failures) is a broken session.
_BENIGN_MOVE_STOPS = frozenset({"limit_reached", "operator_stop"})


def _move_phase_broken(res: dict[str, Any]) -> bool:
    """True when a canary/batch phase is a broken/blocked failure: it did not finish
    clean, or aborted, or stopped on a NON-benign signal (a benign limit_reached /
    operator_stop is handled by the caller)."""
    if not res.get("ok") or res.get("aborted"):
        return True
    stopped = res.get("stopped")
    return bool(stopped) and stopped not in _BENIGN_MOVE_STOPS


def execute_page_moves(
    by_list: dict[str, list[dict[str, Any]]],
    *,
    run_canary: Callable[[str, list[dict[str, Any]]], dict[str, Any]],
    run_batch: Callable[[str, list[dict[str, Any]]], dict[str, Any]],
) -> dict[str, Any]:
    """Per-page Move-to-List execution, one target list at a time: CANARY then BATCH.

    The move-batch authorization (`src.move_auth`) is bound to the exact extraction
    (a hash of the run's ``skipped.json``), so it cannot be pre-granted for a future
    sweep page — each page must self-authorize. For each target list we therefore
    run a **canary** (``run_canary`` — a ``06_move --mode learning`` move of 1 that
    proves the list is movable RV2 and grants the authorization for THIS extraction),
    then a **batch** (``run_batch`` — ``06_move --mode safe --i-authorize-batch`` of
    the rest, now covered).

    Both callables take ``(list_id, rows)`` and return a dict with ``ok`` (process
    finished clean), ``moved`` (int), ``aborted``/``stopped`` (or None). A learning
    canary's SUCCESS signal is ``stopped="limit_reached"`` (it moved its 1 and
    stopped at the cap), and ``operator_stop`` is cooperative — both are BENIGN
    (mirrors ``data_entry_auto._BENIGN_STOPPED``); every OTHER stopped
    (feed_unreadable / guard_blocked / ten_consecutive_failures) is a broken session.
    FAIL-CLOSED: the first broken phase — a canary that aborts / stops on a
    non-benign signal / moves 0 (the list could not be validated), or such a batch —
    returns ``ok=False`` (the caller halts the sweep). An ``operator_stop`` halts
    cleanly (no further list/batch). The ``moved>=1`` gate plus 06_move's own
    per-list authorization check (``batch_authorized``) both guard against an
    un-vetted batch. Returns ``{ok, moved, aborted, stopped, detail, phases:[…]}``."""

    total = 0
    phases: list[dict[str, Any]] = []

    def _fail(phase: str, list_id: str, res: dict[str, Any], why: str) -> dict[str, Any]:
        return {
            "ok": False, "moved": total,
            "aborted": res.get("aborted"), "stopped": res.get("stopped"),
            "detail": f"{phase} for list {list_id} not clean: {why}",
            "phases": phases,
        }

    def _operator_halt() -> dict[str, Any]:
        return {
            "ok": True, "moved": total, "aborted": None, "stopped": "operator_stop",
            "detail": f"operator stop during moves (moved {total} so far)",
            "phases": phases,
        }

    for list_id, rows in by_list.items():
        c = run_canary(list_id, rows)
        phases.append({"list_id": list_id, "phase": "canary", **c})
        if _move_phase_broken(c):
            return _fail("canary", list_id, c, c.get("aborted") or c.get("stopped") or "exit≠0")
        if int(c.get("moved") or 0) < 1:
            # A canary that moved nothing did NOT validate the list (no RV3 grant) —
            # the batch would abort as unauthorized. Fail closed, don't batch blind.
            return _fail("canary", list_id, c, "moved 0 (list not validated)")
        total += int(c.get("moved") or 0)
        if c.get("stopped") == "operator_stop":
            return _operator_halt()

        b = run_batch(list_id, rows)
        phases.append({"list_id": list_id, "phase": "batch", **b})
        if _move_phase_broken(b):
            return _fail("batch", list_id, b, b.get("aborted") or b.get("stopped") or "exit≠0")
        total += int(b.get("moved") or 0)
        if b.get("stopped") == "operator_stop":
            return _operator_halt()

    return {
        "ok": True, "moved": total, "aborted": None, "stopped": None,
        "detail": f"moved {total} across {len(by_list)} list(s) (canary+batch each)",
        "phases": phases,
    }


def build_page_triage(
    offers: list[NormalizedOffer],
    matcher: Callable[..., Candidate | SkippedOffer] = match_offer,
    **match_kwargs: Any,
) -> dict[str, Any]:
    """Triage a whole page, grouped by action. Returns ``{add, move_by_list, skip,
    all, counts}`` — ``add``/``skip`` are lists of :class:`Triage`; ``move_by_list``
    maps a target list id → its :class:`Triage` rows (largest group first, the order
    Romain validates in). Pure: the caller performs the writes."""

    triaged = [triage_offer(o, matcher=matcher, **match_kwargs) for o in offers]
    adds = [t for t in triaged if t.action == ADD]
    skips = [t for t in triaged if t.action == SKIP]

    grouped: dict[str, list[Triage]] = {}
    for t in triaged:
        if t.action == MOVE and t.list_id is not None:
            grouped.setdefault(t.list_id, []).append(t)
    move_by_list = {
        list_id: rows
        for list_id, rows in sorted(grouped.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    }

    return {
        "add": adds,
        "move_by_list": move_by_list,
        "skip": skips,
        "all": triaged,
        "counts": {
            "total": len(triaged),
            "add": len(adds),
            "move": sum(len(rows) for rows in move_by_list.values()),
            "skip": len(skips),
            "target_lists": len(move_by_list),
        },
    }

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

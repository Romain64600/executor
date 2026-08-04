"""Safe-auto data-entry sweep engine (pure, testable core).

Romain's "mode rapide safe auto" (2026-08-04): for a merchant, sweep the feed
page by page — extract → match → auto-approve EVERY matcher candidate → submit
(``--mode safe``) — with NO human validation, keeping a per-page recap. The
matcher is the safety gate (it already skips console / no-AKS-page / ambiguous
offers); Romain audits the recap and deletes any mistake afterwards.

This module is the deterministic loop ONLY — every side-effecting stage (extract,
match, approve, submit) is injected, so the loop's stop conditions and recap
shape are unit-tested without a browser. ``scripts/10_data_entry_auto.py`` wires
the real stages (subprocess 02/03/05 + apply_overrides_and_validate).

Fail-closed by construction: extract/match/submit that do not finish clean HALT
the whole sweep (no plowing through a broken session); a cooperative stop halts
between pages; end-of-feed (a short/empty page) ends it normally.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class SweepConfig:
    merchant: str
    store_id: str
    start_page: int = 1
    max_pages: int = 200      # safety cap (a full shop is far fewer; guards a runaway)
    page_size: int = 100      # a full feed page; fewer rows ⇒ last page (end of feed)


@dataclass
class ExtractOutcome:
    ok: bool
    offers: int = 0
    detail: str = ""


@dataclass
class MatchOutcome:
    ok: bool
    candidates: int = 0
    detail: str = ""


@dataclass
class SubmitOutcome:
    ok: bool                              # process finished clean (exit 0)
    aborted: str | None = None            # submit_plan.aborted (feed_unreadable / not_logged_in / …)
    created: int = 0                      # offers proven gone-from-feed
    offers: list[dict[str, Any]] = field(default_factory=list)
    detail: str = ""


@dataclass
class Stages:
    """Injected side-effecting stages, each keyed by the page's run id."""
    extract: Callable[[int, str], ExtractOutcome]     # (page, run_id) -> ExtractOutcome
    match: Callable[[str], MatchOutcome]              # (run_id) -> MatchOutcome
    approve: Callable[[str], int]                     # (run_id) -> approved_count (auto-approve ALL)
    submit: Callable[[str], SubmitOutcome]            # (run_id) -> SubmitOutcome


def run_sweep(
    cfg: SweepConfig,
    stages: Stages,
    *,
    page_run_id: Callable[[int], str],
    should_stop: Callable[[], bool] = lambda: False,
    on_page: Callable[[dict[str, Any]], None] = lambda e: None,
) -> dict[str, Any]:
    """Sweep pages start_page..start_page+max_pages-1, halting fail-closed.

    Returns the recap dict: ``{merchant, store_id, pages:[…], total_created,
    halted}``. ``on_page`` is called after each page entry is finalized (persist
    the recap incrementally). Stop conditions, in order of check:

    * ``should_stop()`` before a page  → ``halted="operator_stop"``.
    * extract fails                     → record + ``halted="extract_failed_pN"``.
    * extract returns 0 offers          → ``end_of_feed`` (normal end, no halt).
    * match fails                       → record + ``halted="match_failed_pN"``.
    * 0 candidates                      → page recorded, sweep CONTINUES.
    * submit not clean (exit≠0/aborted) → record + ``halted="submit_not_clean_pN"``.
    * page had < page_size offers       → ``last_page`` (normal end after processing).
    * max_pages reached                 → normal end.
    """

    recap: dict[str, Any] = {
        "merchant": cfg.merchant, "store_id": cfg.store_id,
        "pages": [], "total_created": 0, "halted": None,
    }

    def finish_page(entry: dict[str, Any]) -> None:
        recap["pages"].append(entry)
        recap["total_created"] = sum(p.get("created", 0) for p in recap["pages"])
        on_page(entry)

    last = cfg.start_page + cfg.max_pages - 1
    for page in range(cfg.start_page, last + 1):
        if should_stop():
            recap["halted"] = "operator_stop"
            break
        run_id = page_run_id(page)
        entry: dict[str, Any] = {"page": page, "run": run_id}

        ex = stages.extract(page, run_id)
        entry["offers"] = ex.offers
        if not ex.ok:
            entry["error"] = "extract: " + (ex.detail or "failed")
            recap["halted"] = f"extract_failed_p{page}"
            finish_page(entry)
            break
        if ex.offers == 0:
            entry["end_of_feed"] = True
            finish_page(entry)
            break  # normal end: no more offers

        mt = stages.match(run_id)
        entry["candidates"] = mt.candidates
        if not mt.ok:
            entry["error"] = "match: " + (mt.detail or "failed")
            recap["halted"] = f"match_failed_p{page}"
            finish_page(entry)
            break

        if mt.candidates > 0:
            entry["approved"] = stages.approve(run_id)
            sub = stages.submit(run_id)
            entry["created"] = sub.created
            entry["offers_created"] = sub.offers
            entry["aborted"] = sub.aborted
            if not sub.ok or sub.aborted:
                entry["error"] = "submit: " + (sub.aborted or sub.detail or "not clean")
                recap["halted"] = f"submit_not_clean_p{page}"
                finish_page(entry)
                break
        else:
            entry["created"] = 0
            entry["offers_created"] = []

        # A short page means we just processed the last page of the feed.
        if ex.offers < cfg.page_size:
            entry["last_page"] = True
            finish_page(entry)
            break

        finish_page(entry)

    return recap

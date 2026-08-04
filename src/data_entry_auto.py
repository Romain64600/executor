"""Safe-auto data-entry sweep engine (pure, testable core) — v2.

Romain's "mode rapide safe auto" (2026-08-04): for a merchant, sweep the feed
page by page — extract → match → auto-approve EVERY matcher candidate → submit
(``--mode safe``) — with NO human validation, keeping a per-page recap. The
matcher is the safety gate (it already skips console / no-AKS-page / ambiguous
offers); Romain audits the recap and deletes any mistake afterwards.

This module is the deterministic loop ONLY — every side-effecting stage is
injected, so the loop's stop conditions and recap shape are unit-tested without a
browser. ``scripts/10_data_entry_auto.py`` wires the real stages.

Design after the 2026-08-04 adversarial review (which found real defects):

* REFLOW-SAFE HIGHEST-FIRST. Creating an offer removes it from the merchant
  feed, so the feed SHRINKS as we submit. Paging 1→N positionally would let
  offers slide down into already-processed pages and be skipped. We instead
  process pages from the feed's advertised last page DOWN to the first (like the
  P1.6 mover): removing offers from a higher page never shifts a LOWER,
  not-yet-processed page. ``feed_last_page`` comes from the extractor (authoritative
  nav), never the offers<page_size proxy (a throttled short page must not be read
  as end-of-feed).

* FAIL-CLOSED on EVERY non-clean stage — including a mid-batch submitter STOP.
  The submitter signals a broken session mid-page via ``stopped`` (feed_unreadable
  / guard_blocked / ten_consecutive_failures), NOT ``aborted``; both must halt the
  whole sweep. ``limit_reached`` is the only benign ``stopped`` (never in safe
  mode). A NotLoggedIn/feed-unreadable is a STOP, never an auto re-auth.

* COVERAGE HONESTY. Hitting the ``max_pages`` cap while the feed advertises more
  pages is flagged (``coverage_incomplete_max_pages``), never a silent clean end.

* OPERATOR STOP is re-checked between stages (and before the real submit), so a
  stop that lands mid-page still prevents that page's writes when it can.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

# ``stopped`` values that are NOT a broken/blocked session. ``limit_reached``
# never occurs in safe mode (no limit); ``operator_stop`` = a cooperative stop the
# submitter honored at an offer boundary — its partial page is recorded clean and
# the sweep then halts via its OWN should_stop() check. Every OTHER stopped value
# (feed_unreadable / guard_blocked / ten_consecutive_failures) halts fail-closed.
_BENIGN_STOPPED = {"limit_reached", "operator_stop"}


@dataclass
class SweepConfig:
    merchant: str
    store_id: str
    start_page: int = 1
    max_pages: int = 400      # safety cap on pages processed (a full shop is fewer)


@dataclass
class ExtractOutcome:
    ok: bool
    offers: int = 0
    feed_last_page: int | None = None   # authoritative last page from the extractor's nav
    detail: str = ""


@dataclass
class MatchOutcome:
    ok: bool
    candidates: int = 0
    detail: str = ""


@dataclass
class SubmitOutcome:
    ok: bool                              # process finished clean (exit 0)
    aborted: str | None = None            # submit_plan.aborted (pre-write abort)
    stopped: str | None = None            # submit_plan.stopped (mid-batch stop signal)
    created: int = 0                      # offers proven gone-from-feed
    offers: list[dict[str, Any]] = field(default_factory=list)
    detail: str = ""

    def clean(self) -> bool:
        """A submit is clean only if it exited 0, did not abort, and did not stop
        on a broken/blocked session (a non-benign ``stopped``)."""
        if not self.ok or self.aborted:
            return False
        return not (self.stopped and self.stopped not in _BENIGN_STOPPED)

    def halt_reason(self) -> str | None:
        if not self.ok:
            return self.detail or "exit≠0"
        if self.aborted:
            return self.aborted
        if self.stopped and self.stopped not in _BENIGN_STOPPED:
            return self.stopped
        return None


@dataclass
class Stages:
    """Injected side-effecting stages, each keyed by the page's run id."""
    extract: Callable[[int, str], ExtractOutcome]     # (page, run_id) -> ExtractOutcome
    match: Callable[[str], MatchOutcome]              # (run_id) -> MatchOutcome
    approve: Callable[[str], int]                     # (run_id) -> approved_count (raises on failure)
    submit: Callable[[str], SubmitOutcome]            # (run_id) -> SubmitOutcome


class StageError(Exception):
    """A stage (e.g. auto-approve) failed — recorded as a fail-closed halt."""


def run_sweep(
    cfg: SweepConfig,
    stages: Stages,
    *,
    page_run_id: Callable[[int], str],
    should_stop: Callable[[], bool] = lambda: False,
    on_page: Callable[[dict[str, Any]], None] = lambda e: None,
) -> dict[str, Any]:
    """Sweep a merchant's feed reflow-safe (highest page first), halting fail-closed.

    Returns ``{merchant, store_id, pages:[…], total_created, halted, feed_last_page}``.
    ``on_page`` is called after each page entry is finalized (persist incrementally).
    """

    recap: dict[str, Any] = {
        "merchant": cfg.merchant, "store_id": cfg.store_id,
        "pages": [], "total_created": 0, "halted": None, "feed_last_page": None,
    }

    def finish_page(entry: dict[str, Any]) -> None:
        recap["pages"].append(entry)
        recap["total_created"] = sum(p.get("created", 0) for p in recap["pages"])
        on_page(entry)

    if should_stop():
        recap["halted"] = "operator_stop"
        return recap

    # Probe the start page to learn the feed's authoritative last page.
    probe_id = page_run_id(cfg.start_page)
    probe = stages.extract(cfg.start_page, probe_id)
    if not probe.ok:
        recap["halted"] = f"extract_failed_p{cfg.start_page}"
        finish_page({"page": cfg.start_page, "run": probe_id, "offers": probe.offers,
                     "error": "extract: " + (probe.detail or "failed")})
        return recap
    feed_last = probe.feed_last_page if probe.feed_last_page else cfg.start_page
    recap["feed_last_page"] = feed_last
    if probe.offers == 0 and feed_last <= cfg.start_page:
        finish_page({"page": cfg.start_page, "run": probe_id, "offers": 0, "end_of_feed": True})
        return recap

    top = min(feed_last, cfg.start_page + cfg.max_pages - 1)
    capped = feed_last > top

    # Highest page first (reflow-safe): a higher page's removals never shift a
    # lower, not-yet-processed page.
    for page in range(top, cfg.start_page - 1, -1):
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
            entry["empty"] = True   # feed shrank past this page — nothing to do here
            finish_page(entry)
            continue

        mt = stages.match(run_id)
        entry["candidates"] = mt.candidates
        if not mt.ok:
            entry["error"] = "match: " + (mt.detail or "failed")
            recap["halted"] = f"match_failed_p{page}"
            finish_page(entry)
            break

        if mt.candidates > 0:
            if should_stop():   # re-check right before any real write
                entry["stopped_before_submit"] = True
                recap["halted"] = "operator_stop"
                finish_page(entry)
                break
            try:
                entry["approved"] = stages.approve(run_id)
            except StageError as exc:
                entry["error"] = "approve: " + str(exc)
                recap["halted"] = f"approve_failed_p{page}"
                finish_page(entry)
                break
            sub = stages.submit(run_id)
            entry["created"] = sub.created
            entry["offers_created"] = sub.offers
            entry["aborted"] = sub.aborted
            entry["stopped"] = sub.stopped
            if not sub.clean():
                entry["error"] = "submit: " + (sub.halt_reason() or "not clean")
                recap["halted"] = f"submit_not_clean_p{page}"
                finish_page(entry)
                break
        else:
            entry["created"] = 0
            entry["offers_created"] = []

        finish_page(entry)

    # Coverage honesty: a max_pages cap over a longer feed is NOT a clean end.
    if recap["halted"] is None and capped:
        recap["halted"] = f"coverage_incomplete_max_pages (feed has {feed_last} pages)"

    return recap

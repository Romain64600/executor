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
from pathlib import Path
from typing import Any, Callable

from src.validation import candidate_fingerprint

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
    movable: int = 0          # routable skips on this page (→ Move-to-List step)
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
class MoveOutcome:
    """Result of a page's Move-to-List step (the routable skips → their target
    lists). Same clean/halt discipline as :class:`SubmitOutcome` — a move that does
    not finish clean halts the whole sweep fail-closed (a broken/blocked session
    must not let later pages plow through)."""
    ok: bool                              # process finished clean (exit 0)
    aborted: str | None = None            # move plan aborted (pre-write abort / gate)
    stopped: str | None = None            # mid-batch stop signal
    moved: int = 0                        # offers proven relocated (RV2: gone-from-source)
    offers: list[dict[str, Any]] = field(default_factory=list)
    detail: str = ""

    def clean(self) -> bool:
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
    # Optional Move-to-List step: relocate the page's routable skips to their target
    # lists AFTER the ADDs are submitted+verified (Romain 2026-08-13, unified
    # per-page workflow). None = ADD-only sweep (unchanged legacy behaviour).
    move: Callable[[str], MoveOutcome] | None = None


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
    ``on_page`` is called after each page with the LIVE recap dict (mutated in
    place) so the caller can persist per-page progress before the sweep returns.
    """

    recap: dict[str, Any] = {
        "merchant": cfg.merchant, "store_id": cfg.store_id,
        "pages": [], "total_created": 0, "total_moved": 0,
        "halted": None, "feed_last_page": None,
    }

    def finish_page(entry: dict[str, Any]) -> None:
        recap["pages"].append(entry)
        recap["total_created"] = sum(p.get("created", 0) for p in recap["pages"])
        recap["total_moved"] = sum(p.get("moved", 0) for p in recap["pages"])
        on_page(recap)   # the LIVE recap (this dict, mutated in place) — so a
                         # caller can persist per-page progress before the sweep
                         # returns (the console's live recap panel).

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
    max_seen = feed_last   # largest feed_last_page any extract advertised (feed growth)

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
        if ex.feed_last_page and ex.feed_last_page > max_seen:
            max_seen = ex.feed_last_page   # a re-import grew the feed mid-sweep
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
        if mt.movable:
            entry["movable"] = mt.movable
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

        # Move-to-List: after the ADDs are submitted+verified, relocate this page's
        # routable skips (blacklist regions, softwares, gift cards, …) to their
        # target lists. Runs even when the page had 0 ADDs — a page can be all
        # skips. Fail-closed like submit: an unclean move halts the whole sweep.
        if stages.move is not None and mt.movable > 0:
            if should_stop():   # re-check right before any real write
                entry["stopped_before_move"] = True
                recap["halted"] = "operator_stop"
                finish_page(entry)
                break
            mv = stages.move(run_id)
            entry["moved"] = mv.moved
            entry["offers_moved"] = mv.offers
            entry["move_aborted"] = mv.aborted
            entry["move_stopped"] = mv.stopped
            if not mv.clean():
                entry["error"] = "move: " + (mv.halt_reason() or "not clean")
                recap["halted"] = f"move_not_clean_p{page}"
                finish_page(entry)
                break

        finish_page(entry)

    # Coverage honesty: a max_pages cap over a longer feed, OR a feed that GREW
    # past the probed last page mid-sweep (a re-import), is NOT a clean full sweep.
    # The tail pages beyond ``top`` were never processed — flag it, never a silent
    # clean end (the operator re-runs on the fresh feed to catch the new tail).
    if recap["halted"] is None:
        if capped:
            recap["halted"] = f"coverage_incomplete_max_pages (feed has {feed_last} pages)"
        elif max_seen > feed_last:
            recap["halted"] = f"coverage_incomplete_feed_grew ({feed_last}→{max_seen} pages)"

    return recap


def _candidates_by_store(from_recap: dict) -> "list[dict[str, Any]]":
    """Group a by-urls dry-run's candidates by merchant STORE, deduped by
    candidate_fingerprint (a merchant can appear across several games; a re-import
    can also surface the same offer twice). Returns ordered
    ``[{merchant, store_id, candidates:[...]}, ...]`` — the unit of a safe submit."""
    order: list[str] = []
    groups: dict[str, dict[str, Any]] = {}
    for game in from_recap.get("games") or []:
        if not game.get("resolved") or game.get("error"):
            continue
        for per in game.get("merchants") or []:
            sid = str(per.get("store_id") or "")
            if not sid:
                continue
            g = groups.get(sid)
            if g is None:
                g = groups[sid] = {"merchant": per.get("merchant", ""),
                                   "store_id": sid, "candidates": [], "_seen": set()}
                order.append(sid)
            for c in per.get("candidates") or []:
                fp = candidate_fingerprint(c)
                if fp in g["_seen"]:
                    continue
                g["_seen"].add(fp)
                g["candidates"].append(c)
    out = []
    for sid in order:
        g = groups[sid]
        if g["candidates"]:
            out.append({"merchant": g["merchant"], "store_id": sid, "candidates": g["candidates"]})
    return out


def run_by_urls_submit(
    from_recap: dict, *, available: str,
    submit_merchant: Callable[[str, str, "list[dict[str, Any]]", Path], SubmitOutcome],
    make_sub_run: Callable[[str], Path],
    flush: Callable[[dict], None] = lambda r: None,
    should_stop: Callable[[], bool] | None = None,
) -> dict:
    """Submit a by-urls dry-run's match-validated candidates, grouped by merchant,
    each as a standard safe batch (R24). ``submit_merchant`` builds the validation
    triple and runs 05_submit for one store; ``make_sub_run`` mints its run dir. The
    first NON-CLEAN merchant HALTS the whole batch fail-closed (same discipline as
    run_sweep). Stops cooperatively only BETWEEN merchants (never mid-Create)."""

    groups = _candidates_by_store(from_recap)
    recap: dict[str, Any] = {
        "mode": "submit", "available": available, "aborted": None,
        "merchants": [],
        "totals": {"merchants": len(groups),
                   "attempted": sum(len(g["candidates"]) for g in groups),
                   "created": 0}}
    flush(recap)

    for g in groups:
        if should_stop is not None and should_stop():
            recap["aborted"] = "operator_stop"
            flush(recap)
            break
        merchant, store_id, cands = g["merchant"], g["store_id"], g["candidates"]
        sub_run = make_sub_run(store_id)
        outcome = submit_merchant(merchant, store_id, cands, sub_run)
        entry = {"merchant": merchant, "store_id": store_id, "run": sub_run.name,
                 "attempted": len(cands), "created": outcome.created,
                 "offers": outcome.offers, "halted": outcome.halt_reason()}
        recap["merchants"].append(entry)
        recap["totals"]["created"] += outcome.created
        flush(recap)
        if not outcome.clean():
            # A broken/blocked submit halts the batch — never plow on to the next
            # merchant on a dropped session / unreadable feed (fail-closed).
            recap["aborted"] = f"submit_not_clean:{merchant}: {outcome.halt_reason()}"
            flush(recap)
            break

    return recap

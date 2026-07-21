#!/usr/bin/env python3
"""Stage 6 — Move-to-List writer (brique B). The submitter's sibling for triage.

Builds a Move-to-List plan from a run's confirmed Learning dispositions
(``learning.json`` → `move_plan.py`), then, for each offer, relocates it out of
its source list into the annotated target list. Success = the offer disappeared
from the source list (docs/AKS_LISTS.md, EXECUTOR_RULES §13).

Gates (fail-closed, identical discipline to Stage 5): invariants green AND
authoritative, one CDP tab under the cross-process browser lock, dry-run by
default (``--execute`` writes), the R24 data-entry mode decides the batch size
(``safe`` = full plan; ``learning``/``advanced`` = canary of 1), a per-run
BlockLedger for guard blocks, JSONL logs for every action. NEVER fire-and-forget.

Examples (on the VPS):
  python3 scripts/06_move.py runs/<id> --store-id 38                       # dry-run (plan only)
  python3 scripts/06_move.py runs/<id> --store-id 38 --execute --mode learning   # canary of 1 (REAL)
  python3 scripts/06_move.py runs/<id> --store-id 38 --execute --mode safe       # full confirmed plan (REAL)
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.aks_env import OFFICIAL_CDP_ENDPOINT  # noqa: E402
from src.browser_lock import BrowserBusyError, browser_lock  # noqa: E402
from src.invariants import build_report  # noqa: E402
from src.mover import DryRunMover, Mover, FEED_UNREADABLE_EXCS  # noqa: E402
from src.move_plan import build_move_plan  # noqa: E402
from src.pacing import Pacer  # noqa: E402
from src.run_log import RunLogger  # noqa: E402
from src.step_guard import BlockLedger, StepGuard  # noqa: E402
from src.submit_session import SubmitSession, WriteSubmitSession  # noqa: E402

DEFAULT_MAX_PAGES = 40
AUTO_MAX_PAGES_HEADROOM = 1.3
# Same R24 semantics as Stage 5: a canary mode is a cap, not a default.
CANARY_MODES = ("learning", "advanced")
CANARY_LIMIT = 1


def mode_limit(mode: str, requested: int | None) -> int | None:
    if mode not in CANARY_MODES:
        return requested
    return CANARY_LIMIT if requested is None else min(requested, CANARY_LIMIT)


def derive_max_pages(explicit: int | None, run_dir: Path) -> tuple[int, str]:
    if explicit is not None:
        return explicit, f"explicit --max-pages {explicit}"
    feed_pages = 0
    try:
        feed = json.loads((run_dir / "offers.json").read_text(encoding="utf-8"))
        feed_pages = int(feed.get("feed_last_page") or 0)
    except (OSError, ValueError, TypeError):
        feed_pages = 0
    if feed_pages <= 0:
        return DEFAULT_MAX_PAGES, f"auto: feed page count unknown → default {DEFAULT_MAX_PAGES}"
    derived = max(DEFAULT_MAX_PAGES, math.ceil(feed_pages * AUTO_MAX_PAGES_HEADROOM))
    return derived, f"auto: feed advertises {feed_pages} page(s) → max_pages {derived}"


def _status(entry: dict, write: bool) -> str:
    if entry.get("skipped"):
        return f"SKIP ({entry['skipped']})"
    if not entry.get("ready"):
        return f"BLOCKED ({entry.get('blocker')})"
    if not write:
        return "READY" + (f" → {entry.get('would_move_to')}" if entry.get("would_move_to") else "")
    if entry.get("moved"):
        return f"MOVED ({entry.get('post_verify')})"
    return f"FAILED ({entry.get('blocker') or entry.get('post_verify')})"


def main() -> int:
    try:
        with browser_lock(ROOT, label="06_move " + " ".join(sys.argv[1:])[:160]):
            return _main()
    except BrowserBusyError as exc:
        print(json.dumps({"aborted": True, "reason": str(exc)}, indent=2))
        return 2


def _main() -> int:
    parser = argparse.ArgumentParser(description="AKS Move-to-List writer (Stage 6).")
    parser.add_argument("run_dir", help="Path to the run directory (runs/<id>).")
    parser.add_argument("--store-id", default=None, help="AKS store id (default: from raw.json).")
    parser.add_argument("--source-list", default=None,
                        help="Source list page (aks-merchant-feeds-<id>); default: from raw.json.")
    parser.add_argument("--available", default="all", choices=["all", "pending"])
    parser.add_argument("--endpoint", default=OFFICIAL_CDP_ENDPOINT)
    parser.add_argument("--execute", action="store_true", help="REAL move (default: dry-run).")
    parser.add_argument("--mode", default="safe", choices=["safe", "learning", "advanced"],
                        help="R24 batch size: safe = full confirmed plan; learning/advanced = canary of 1.")
    parser.add_argument("--limit", type=int, default=None,
                        help="Max moves. Narrows what --mode allows, never widens a canary.")
    parser.add_argument("--max-pages", type=int, default=None)
    parser.add_argument("--pace-pages", default="0.4-0.6")
    parser.add_argument("--pace-offers", default="0.5-1.5")
    parser.add_argument("--acknowledge-block", action="store_true",
                        help="Acknowledge two consecutive guard-blocked passes (FC3).")
    args = parser.parse_args()

    run_dir = Path(args.run_dir).resolve()
    if not run_dir.is_dir():
        print(json.dumps({"aborted": True, "reason": f"run dir absent: {run_dir}"}, indent=2))
        return 2

    # A canary mode is a cap, not a default (R24) — refuse a widening --limit.
    if args.mode in CANARY_MODES and args.limit is not None and args.limit > CANARY_LIMIT:
        print(json.dumps({"aborted": True, "reason": (
            f"--mode {args.mode} is capped at a canary of {CANARY_LIMIT} "
            f"(--limit {args.limit} would widen it). Use --mode safe for the full plan.")},
            indent=2))
        return 2

    # Build the plan from the run's confirmed Learning dispositions.
    plan_doc = build_move_plan(run_dir)
    (run_dir / "move_plan_source.json").write_text(json.dumps(plan_doc, indent=2, ensure_ascii=False),
                                                   encoding="utf-8")
    entries = plan_doc["entries"]
    store_id = args.store_id or plan_doc.get("store_id")
    source_list = args.source_list or plan_doc.get("source_feed_page")
    if not store_id:
        print(json.dumps({"aborted": True, "reason": "store id inconnu (ni --store-id ni raw.json)"}, indent=2))
        return 2
    if not entries:
        print(json.dumps({"aborted": False, "reason": "aucune disposition Move-to-list confirmée",
                          "excluded": plan_doc["excluded"], "counts": plan_doc["counts"]}, indent=2))
        return 0

    write = args.execute
    # Fail-closed gate: invariants green AND authoritative (on the VPS target).
    report = None
    for attempt in range(3):
        report = build_report(endpoint=args.endpoint)
        if report["ok"] and report["authoritative"]:
            break
        if attempt < 2:
            time.sleep(2)
    if not (report["ok"] and report["authoritative"]):
        print(json.dumps({"aborted": True, "reason": "invariants not green/authoritative after retries",
                          "ok": report["ok"], "authoritative": report["authoritative"]}, indent=2))
        return 2

    max_pages, max_pages_note = derive_max_pages(args.max_pages, run_dir)
    limit = mode_limit(args.mode, args.limit)
    run_id = plan_doc.get("run_id") or run_dir.name
    logger = RunLogger(run_id, log_dir=str(ROOT / "logs"))

    if write:
        print(f"REAL MOVE (mode={args.mode}) — up to {limit if limit is not None else 'ALL'} "
              f"offer(s) → their target lists. Source={source_list}, {max_pages_note}.", file=sys.stderr)
    else:
        print(f"DRY-RUN — {len(entries)} confirmed disposition(s), source={source_list}, "
              f"{max_pages_note}.", file=sys.stderr)

    # FC3: cross-process guard ledger (per-run, own file — never the submit's).
    ledger = BlockLedger(run_dir / "move_guard_ledger.json")
    if write:
        if args.acknowledge_block:
            ledger.acknowledge("operator --acknowledge-block on the CLI")
        elif ledger.requires_ack():
            print(json.dumps({"aborted": True, "reason": (
                "the previous TWO real move passes of this run both ended guard-blocked "
                "— inspect the feed then re-run with --acknowledge-block (FC3)"),
                "last_block": ledger.load().get("last_block") or {}}, indent=2))
            return 2

    try:
        page_pacer = Pacer.from_spec(args.pace_pages)
        offer_pacer = Pacer.from_spec(args.pace_offers)
    except ValueError as exc:
        print(json.dumps({"aborted": True, "reason": f"bad --pace spec: {exc}"}, indent=2))
        return 2

    guard = StepGuard(max_attempts_per_signature=1, max_failures_per_signature=2,
                      max_consecutive_failures=10, max_failures_per_task=10 ** 9)
    session_cls = WriteSubmitSession if write else SubmitSession
    mover_cls = Mover if write else DryRunMover
    try:
        with session_cls(args.endpoint) as session:
            result = mover_cls(session, logger=logger, guard=guard,
                               page_pacer=page_pacer, offer_pacer=offer_pacer).run(
                run_id=run_id, store_id=store_id, plan=entries,
                source_feed_page=source_list, available=args.available,
                max_pages=max_pages, limit=limit)
    except FEED_UNREADABLE_EXCS as exc:
        print(json.dumps({"aborted": True,
                          "reason": f"fail-closed abort (feed/CDP unreadable): {exc}"}, indent=2))
        return 2

    if write:
        snap = guard.snapshot()
        ledger.record(task_id=run_id, blocked=bool(snap.get("blocked")),
                      rule=snap.get("blocked_rule"), reason=snap.get("blocked_reason"))

    result["data_entry_mode"] = args.mode
    result["limit"] = limit
    result["excluded"] = plan_doc["excluded"]
    (run_dir / "move_plan.json").write_text(json.dumps(result, indent=2, ensure_ascii=False),
                                            encoding="utf-8")

    batch = "full plan" if limit is None else f"canary {limit}" if limit == CANARY_LIMIT else f"limit {limit}"
    print(f"\n{'MOVE' if write else 'DRY-RUN'} — mode={args.mode} ({batch}) — "
          f"moved={result.get('moved')}, attempts={result.get('move_attempts')}, "
          f"plan={len(result['plan'])}, aborted={result.get('aborted')}, stopped={result.get('stopped')}")
    for entry in result["plan"]:
        print(f"  [{_status(entry, write)}] {entry.get('name', '')[:50]} → "
              f"{entry.get('target_list_label')}")
    print(json.dumps({"moved": result.get("moved"), "attempts": result.get("move_attempts"),
                      "aborted": result.get("aborted"), "stopped": result.get("stopped"),
                      "excluded": len(plan_doc["excluded"]), "artifact": str(run_dir / "move_plan.json")},
                     indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

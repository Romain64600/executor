#!/usr/bin/env python3
"""Read-only "list sorting" scan (Stage 8, plan side).

Scans the all-stores Pending list (list 9, NO ``store=`` filter — every store at
once) read-only and writes a Move-to-List sorting *plan*: each offer grouped
under the target list that ``suggest_target_list`` derives from its deterministic
skip reason (Softwares, Gift cards, account, regionals, Blacklist…).

This stage NEVER moves anything. It is the review artifact Romain validates in
bulk, per target list, before Stage 6 executes any move (which stays behind the
canary/authorization gate). Refuses to run unless the invariants are green AND
authoritative (on the VPS), and takes the shared browser lock.

Example (on the VPS):
    python3 scripts/08_sort_plan.py                 # full all-stores pass
    python3 scripts/08_sort_plan.py --pages 1-10    # a slice, to sample
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.aks_env import OFFICIAL_CDP_ENDPOINT  # noqa: E402
from src.browser_lock import BrowserBusyError, browser_lock  # noqa: E402
from src.cdp_session import ReadOnlyCdpSession  # noqa: E402
from src.extractor import (  # noqa: E402
    EmptyPageAnomaly,
    FeedExtractor,
    FeedUnstableError,
    NotLoggedInError,
    parse_page_range,
)
from src.invariants import build_report  # noqa: E402
from src.pacing import Pacer  # noqa: E402
from src.run_log import RunLogger  # noqa: E402
from src.sort_plan import build_sort_plan, render_report  # noqa: E402
from src.step_guard import StepGuard, StepGuardError  # noqa: E402

ALL_STORES_LABEL = "all-stores"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Read-only all-stores Pending list-sorting scan (no mutation)."
    )
    parser.add_argument("--endpoint", default=OFFICIAL_CDP_ENDPOINT)
    parser.add_argument(
        "--max-pages",
        type=int,
        default=60,
        help="Upper bound on pages fetched in a full pass (the feed self-reports "
        "its page count; the scan stops early past the end). If the feed "
        "advertises MORE pages than this, the plan is flagged truncated.",
    )
    parser.add_argument(
        "--pages",
        default=None,
        help="Sample only this page range ('3' or '3-10') instead of a full pass.",
    )
    parser.add_argument(
        "--pace",
        default="2-5",
        help="Seconds between page fetches, 'N' or 'MIN-MAX'. 0 disables.",
    )
    parser.add_argument("--out-dir", default=None)
    parser.add_argument("--run-id", default=None)
    args = parser.parse_args()

    try:
        pacer = Pacer.from_spec(args.pace)
        page_range = parse_page_range(args.pages) if args.pages else None
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    # Fail-closed gate: never touch the feed unless invariants are green on the target.
    report = build_report(endpoint=args.endpoint)
    if not (report["ok"] and report["authoritative"]):
        print(
            json.dumps(
                {
                    "aborted": True,
                    "reason": "invariants not green/authoritative — refusing to scan",
                    "ok": report["ok"],
                    "authoritative": report["authoritative"],
                },
                indent=2,
            )
        )
        return 2

    run_id = args.run_id or f"{datetime.now(timezone.utc):%Y%m%d-%H%M%S}-sort"
    out_dir = Path(args.out_dir) if args.out_dir else ROOT / "runs" / run_id
    out_dir.mkdir(parents=True, exist_ok=True)

    logger = RunLogger(run_id, log_dir=str(ROOT / "logs"))
    guard = StepGuard(max_attempts_per_signature=2)

    first_page, last_page = page_range if page_range else (1, args.max_pages)

    try:
        # OP1: one tab, one driver — refuse to start while another stage holds
        # the browser. store_id=None → the all-stores view (no store filter).
        with browser_lock(ROOT, label="08_sort_plan all-stores"), \
                ReadOnlyCdpSession(args.endpoint) as session:
            extractor = FeedExtractor(session, guard=guard, logger=logger, pacer=pacer)
            snapshot, feed = extractor.extract_pages(
                run_id=run_id,
                merchant=ALL_STORES_LABEL,
                store_id=None,
                first_page=first_page,
                last_page=last_page,
            )
    except BrowserBusyError as exc:
        print(json.dumps({"aborted": True, "reason": str(exc), "run_id": run_id}, indent=2))
        return 2
    except (NotLoggedInError, EmptyPageAnomaly, FeedUnstableError, StepGuardError) as exc:
        print(
            json.dumps(
                {
                    "aborted": True,
                    "abort_type": type(exc).__name__,
                    "reason": str(exc),
                    "run_id": run_id,
                },
                indent=2,
            )
        )
        return 2

    (out_dir / "raw.json").write_text(json.dumps(snapshot.to_dict(), indent=2), encoding="utf-8")
    (out_dir / "offers.json").write_text(json.dumps(feed.to_dict(), indent=2), encoding="utf-8")

    plan = build_sort_plan(feed.offers, run_id=run_id)
    # No silent caps: if the feed advertises more pages than we fetched, the plan
    # covers only part of the list — say so loudly.
    stats = extractor.last_stats
    covered_pages = stats.get("pages_fetched", 0)
    feed_pages = stats.get("feed_last_page", 0)
    truncated = bool(page_range) or (feed_pages > first_page - 1 + covered_pages)
    plan["coverage"] = {
        "partial": True,
        "pages_fetched": covered_pages,
        "feed_last_page": feed_pages,
        "truncated": truncated,
    }

    (out_dir / "sort_plan.json").write_text(json.dumps(plan, indent=2, ensure_ascii=False),
                                            encoding="utf-8")
    (out_dir / "report.txt").write_text(render_report(plan), encoding="utf-8")

    print(
        json.dumps(
            {
                "run_id": run_id,
                "source": "list 9 (all stores, no store filter)",
                "offers": plan["counts"]["total"],
                "coverage": plan["coverage"],
                "counts": plan["counts"],
                "by_list": {
                    lid: {"label": g["label"], "count": g["count"]}
                    for lid, g in plan["by_list"].items()
                },
                "pacing": pacer.snapshot(),
                "out_dir": str(out_dir),
                "guard_blocked": guard.blocked,
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

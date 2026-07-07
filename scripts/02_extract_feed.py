#!/usr/bin/env python3
"""Read-only merchant-feed extractor CLI (Sprint 2).

Refuses to run unless the invariants are green AND authoritative (i.e. on the
Debian VPS target). Navigates the merchant feed read-only and writes
``runs/<run_id>/raw.json`` + ``offers.json``. It never opens the submit modal,
submits, edits, or logs in.

Example (on the VPS):
    python3 scripts/02_extract_feed.py --merchant Driffle --store-id 127
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
from src.cdp_session import ReadOnlyCdpSession  # noqa: E402
from src.extractor import FeedExtractor, NotLoggedInError  # noqa: E402
from src.invariants import build_report  # noqa: E402
from src.run_log import RunLogger  # noqa: E402
from src.step_guard import StepGuard  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract a merchant feed (read-only).")
    parser.add_argument("--merchant", required=True, help="Merchant name, e.g. Driffle.")
    parser.add_argument("--store-id", required=True, help="AKS store id, e.g. 127.")
    parser.add_argument("--endpoint", default=OFFICIAL_CDP_ENDPOINT)
    parser.add_argument("--available", default="all", choices=["all", "pending"])
    parser.add_argument("--max-pages", type=int, default=40)
    parser.add_argument("--out-dir", default=None)
    parser.add_argument("--run-id", default=None)
    args = parser.parse_args()

    # Fail-closed gate: never extract unless invariants are green on the target.
    report = build_report(endpoint=args.endpoint)
    if not (report["ok"] and report["authoritative"]):
        print(
            json.dumps(
                {
                    "aborted": True,
                    "reason": "invariants not green/authoritative — refusing to extract",
                    "ok": report["ok"],
                    "authoritative": report["authoritative"],
                },
                indent=2,
            )
        )
        return 2

    run_id = args.run_id or f"{datetime.now(timezone.utc):%Y%m%d-%H%M%S}-{args.merchant.lower()}"
    out_dir = Path(args.out_dir) if args.out_dir else ROOT / "runs" / run_id
    out_dir.mkdir(parents=True, exist_ok=True)

    logger = RunLogger(run_id, log_dir=str(ROOT / "logs"))
    guard = StepGuard(max_attempts_per_signature=2)

    try:
        with ReadOnlyCdpSession(args.endpoint) as session:
            extractor = FeedExtractor(session, guard=guard, logger=logger)
            snapshot, feed = extractor.extract(
                run_id=run_id,
                merchant=args.merchant,
                store_id=args.store_id,
                available=args.available,
                max_pages=args.max_pages,
            )
    except NotLoggedInError as exc:
        print(json.dumps({"aborted": True, "reason": str(exc), "run_id": run_id}, indent=2))
        return 2

    (out_dir / "raw.json").write_text(json.dumps(snapshot.to_dict(), indent=2), encoding="utf-8")
    (out_dir / "offers.json").write_text(json.dumps(feed.to_dict(), indent=2), encoding="utf-8")

    print(
        json.dumps(
            {
                "run_id": run_id,
                "merchant": args.merchant,
                "pages_scanned": snapshot.pages_scanned,
                "raw_offers": len(snapshot.raw_offers),
                "normalized_offers": len(feed.offers),
                "out_dir": str(out_dir),
                "guard_blocked": guard.blocked,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

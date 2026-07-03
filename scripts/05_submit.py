#!/usr/bin/env python3
"""Stage 4 — submitter CLI.

Modes:
  (default)  DRY-RUN — rehearse the flow, no writes.
  --submit   REAL — fill region/edition + click "Create offer" + verify post-save
             (offer gone from pending). Defaults to a **canary of 1 offer**; pass
             --all for the full batch, or --limit N.

Gates (fail-closed): invariants green + authoritative, `approved.json` present,
pre-flight WP login check. Reads the approved offers (Stage 3), writes
`submit_plan.json` + `submit_report.txt`.

Examples (on the VPS):
  python3 scripts/05_submit.py runs/<id>/approved.json --merchant Driffle --store-id 127
  python3 scripts/05_submit.py runs/<id>/approved.json --merchant Driffle --store-id 127 --submit          # canary (1)
  python3 scripts/05_submit.py runs/<id>/approved.json --merchant Driffle --store-id 127 --submit --all     # full batch
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.aks_env import OFFICIAL_CDP_ENDPOINT  # noqa: E402
from src.invariants import build_report  # noqa: E402
from src.run_log import RunLogger  # noqa: E402
from src.submit_session import SubmitSession, WriteSubmitSession  # noqa: E402
from src.submitter import DryRunSubmitter, Submitter  # noqa: E402


def _status(entry, write):
    if not entry.get("ready"):
        return f"SKIP ({entry.get('blocker')})"
    if not write:
        return "READY"
    return "CREATED (gone from pending)" if entry.get("submitted") else f"FAILED ({entry.get('post_save')})"


def main() -> int:
    parser = argparse.ArgumentParser(description="AKS submitter.")
    parser.add_argument("approved", help="Path to approved.json (from Stage 3 validation).")
    parser.add_argument("--merchant", required=True)
    parser.add_argument("--store-id", required=True)
    parser.add_argument("--endpoint", default=OFFICIAL_CDP_ENDPOINT)
    parser.add_argument("--available", default="all", choices=["all", "pending"])
    parser.add_argument("--max-pages", type=int, default=40)
    parser.add_argument("--submit", action="store_true", help="REAL write (default: dry-run).")
    parser.add_argument("--all", action="store_true", help="With --submit: full batch (default: canary of 1).")
    parser.add_argument("--limit", type=int, default=None, help="With --submit: max offers to create.")
    args = parser.parse_args()

    # Fail-closed gate: invariants must be green AND authoritative.
    report = build_report(endpoint=args.endpoint)
    if not (report["ok"] and report["authoritative"]):
        print(json.dumps({"aborted": True, "reason": "invariants not green/authoritative",
                          "ok": report["ok"], "authoritative": report["authoritative"]}, indent=2))
        return 2

    approved = json.loads(Path(args.approved).read_text(encoding="utf-8"))
    out_dir = Path(args.approved).resolve().parent
    run_id = out_dir.name
    logger = RunLogger(run_id, log_dir=str(ROOT / "logs"))

    write = args.submit
    limit = args.limit if args.limit is not None else (None if args.all else 1)
    if write:
        print(f"REAL SUBMISSION — will create up to {limit if limit is not None else 'ALL'} offer(s).", file=sys.stderr)

    session_cls = WriteSubmitSession if write else SubmitSession
    submitter_cls = Submitter if write else DryRunSubmitter
    with session_cls(args.endpoint) as session:
        result = submitter_cls(session, logger=logger).run(
            run_id=run_id, merchant=args.merchant, store_id=args.store_id,
            approved=approved, available=args.available, max_pages=args.max_pages, limit=limit,
        )

    (out_dir / "submit_plan.json").write_text(json.dumps(result, indent=2), encoding="utf-8")

    done = [p for p in result["plan"] if (p.get("submitted") if write else p.get("ready"))]
    header = (
        f"{'SUBMIT' if write else 'DRY-RUN'} — {args.merchant} — "
        f"{len(done)}/{len(result['plan'])} {'created' if write else 'ready'}, "
        f"{result.get('feed_offers')} offers in current feed, "
        f"aborted={result['aborted']}, stopped={result['stopped']}"
    )
    lines = [header, ""]
    for entry in result["plan"]:
        lines.append(f"[{_status(entry, write)}] {entry['offer_id']} — {entry['merchant_title']}")
        if entry.get("ready") and not write:
            lines.append(f"    {entry['would_submit']}")
    (out_dir / "submit_report.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(json.dumps({
        "mode": "submit" if write else "dry_run",
        "aborted": result["aborted"],
        "stopped": result["stopped"],
        "feed_offers": result.get("feed_offers"),
        "created" if write else "ready": len(done),
        "total": len(result["plan"]),
        "out_dir": str(out_dir),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

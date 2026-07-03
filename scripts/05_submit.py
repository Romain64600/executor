#!/usr/bin/env python3
"""Stage 4 — submitter CLI. DRY-RUN only in this build (no writes).

Rehearses the submit flow for the approved offers (`approved.json` from Stage 3)
against the live feed, read-only: pre-flight login, locate row, open modal, verify
context + select names, and report what it *would* submit. It never fills a form or
clicks "Create offer".

Gates (fail-closed): invariants green + authoritative, `approved.json` present, and
`--dry-run` is the only supported mode — `--submit` is refused (the write path is a
separate, explicitly-authorized build).

Example (on the VPS):
    python3 scripts/05_submit.py runs/<run_id>/approved.json --merchant Driffle --store-id 127
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
from src.submit_session import SubmitSession  # noqa: E402
from src.submitter import DryRunSubmitter  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="AKS submitter (dry-run only).")
    parser.add_argument("approved", help="Path to approved.json (from Stage 3 validation).")
    parser.add_argument("--merchant", required=True)
    parser.add_argument("--store-id", required=True)
    parser.add_argument("--endpoint", default=OFFICIAL_CDP_ENDPOINT)
    parser.add_argument("--available", default="all", choices=["all", "pending"])
    parser.add_argument("--max-pages", type=int, default=40)
    parser.add_argument("--dry-run", action="store_true", default=True)
    parser.add_argument("--submit", action="store_true", help="Refused in this build.")
    args = parser.parse_args()

    if args.submit:
        print(json.dumps({
            "refused": True,
            "reason": "the write path is not built in this version — dry-run only. "
                      "Real submission requires a separate, explicitly-authorized build.",
        }, indent=2))
        return 2

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

    with SubmitSession(args.endpoint) as session:
        result = DryRunSubmitter(session, logger=logger).run(
            run_id=run_id,
            merchant=args.merchant,
            store_id=args.store_id,
            approved=approved,
            available=args.available,
            max_pages=args.max_pages,
        )

    (out_dir / "submit_plan.json").write_text(json.dumps(result, indent=2), encoding="utf-8")

    ready = [p for p in result["plan"] if p.get("ready")]
    lines = [
        f"DRY-RUN submit plan — {args.merchant} — "
        f"{len(ready)}/{len(result['plan'])} ready, aborted={result['aborted']}, stopped={result['stopped']}",
        "",
    ]
    for entry in result["plan"]:
        status = "READY" if entry.get("ready") else f"SKIP ({entry.get('blocker')})"
        lines.append(f"[{status}] {entry['offer_id']} — {entry['merchant_title']}")
        if entry.get("ready"):
            lines.append(f"    {entry['would_submit']}")
    (out_dir / "submit_report.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(json.dumps({
        "dry_run": True,
        "aborted": result["aborted"],
        "stopped": result["stopped"],
        "ready": len(ready),
        "total": len(result["plan"]),
        "out_dir": str(out_dir),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

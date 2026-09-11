#!/usr/bin/env python3
"""Per-merchant feed status document (Markdown, French) — read-only over ``runs/``.

    python3 scripts/14_feed_status.py --merchant MMOGA --store-id 12
    python3 scripts/14_feed_status.py --merchant MMOGA --store-id 12 --out docs/feeds/MMOGA.md

Sections: dernier passage (run, pages, créées, non créées), offres ajoutées (cumul par jour /
édition / région, historique des passages, liste du dernier passage), ce qui reste dans le
feed et pourquoi (familles de motifs, exemples, levier). No network, no secrets.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.feed_status import build_report  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="État du feed d'un marchand (Markdown).")
    ap.add_argument("--merchant", required=True)
    ap.add_argument("--store-id", required=True)
    ap.add_argument("--runs-dir", default="runs")
    ap.add_argument("--out", default=None, help="write the Markdown here (default: stdout)")
    args = ap.parse_args()
    runs_dir = Path(args.runs_dir)
    if not runs_dir.is_dir():
        print(f"runs dir not found: {runs_dir}", file=sys.stderr)
        return 2
    md = build_report(runs_dir, args.merchant, str(args.store_id))
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(md, encoding="utf-8")
        print(f"written {args.out} ({len(md.splitlines())} lines)")
    else:
        sys.stdout.write(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

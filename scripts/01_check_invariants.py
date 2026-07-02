#!/usr/bin/env python3
"""Read-only Sprint 1 invariant checker (CLI).

Thin wrapper around ``src.invariants.build_report``. Performs no browser actions:
it only checks AKS reachability and CDP /json/version metadata, prints a JSON
report, and exits non-zero when any invariant fails (fail-closed).
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


def main() -> int:
    parser = argparse.ArgumentParser(description="Check AKS executor invariants read-only.")
    parser.add_argument(
        "--endpoint",
        default=OFFICIAL_CDP_ENDPOINT,
        help="CDP /json/version endpoint. Defaults to the official Docker bridge proxy.",
    )
    parser.add_argument("--timeout", type=int, default=10, help="HTTP timeout in seconds.")
    args = parser.parse_args()

    report = build_report(endpoint=args.endpoint, timeout=args.timeout)
    print(json.dumps(report, indent=2, sort_keys=True))

    if not report["authoritative"]:
        print(
            "NOTE: authoritative=false — not the Debian VPS target. A failure "
            "here is NOT a production failure. Run on the VPS to gate write stages.",
            file=sys.stderr,
        )

    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

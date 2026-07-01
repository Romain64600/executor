#!/usr/bin/env python3
"""Read-only Sprint 1 invariant checker.

This script performs no browser actions. It only checks AKS reachability and
CDP /json/version metadata, then emits a JSON report and exits non-zero when
any invariant fails.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.aks_env import (  # noqa: E402
    AKS_DIRECT_URL,
    OFFICIAL_CDP_ENDPOINT,
    checks_to_dict,
    http_head_status,
    validate_aks_direct_status,
)
from src.cdp_client import ReadOnlyCdpClient  # noqa: E402


def build_report(endpoint: str, timeout: int) -> dict[str, object]:
    aks_probe = http_head_status(AKS_DIRECT_URL, timeout=timeout)
    aks_check = validate_aks_direct_status(aks_probe.status if aks_probe.ok else None)

    cdp_result = ReadOnlyCdpClient(endpoint=endpoint, timeout=timeout).get_version()
    checks = [aks_check, *cdp_result.checks]
    aggregate = checks_to_dict(checks)

    return {
        "ok": aggregate["ok"],
        "mode": "read-only",
        "dry_run": True,
        "aks_direct": {
            "url": AKS_DIRECT_URL,
            "ok": aks_probe.ok,
            "status": aks_probe.status,
            "error": aks_probe.error,
        },
        "cdp": {
            "endpoint": endpoint,
            "ok": cdp_result.ok,
            "http_status": cdp_result.probe.status,
            "error": cdp_result.error,
            "payload": cdp_result.payload,
        },
        "checks": aggregate["checks"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Check AKS executor invariants read-only.")
    parser.add_argument(
        "--endpoint",
        default=OFFICIAL_CDP_ENDPOINT,
        help="CDP /json/version endpoint. Defaults to the official Docker bridge proxy.",
    )
    parser.add_argument("--timeout", type=int, default=5, help="HTTP timeout in seconds.")
    args = parser.parse_args()

    report = build_report(endpoint=args.endpoint, timeout=args.timeout)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

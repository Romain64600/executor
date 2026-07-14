#!/usr/bin/env python3
"""Stage 0b — login/2FA CLI (LOGIN_SPEC.md, Option A — Romain 2026-07-14).

Authenticates the WP-admin session in the official CDP Chrome tab. Runs ONLY
on explicit request — never self-triggered by another stage's
``NotLoggedInError`` (that stays a fail-closed STOP + error report, unchanged).

Credentials come from the environment ONLY — ``AKS_WP_USER`` /
``AKS_WP_PASSWORD`` — never a CLI arg (leaks into shell history / `ps`), never
stored, never logged. The 2FA code is requested interactively, and ONLY once
the 2FA field is confirmed visible and ready to submit — never pre-requested.
One attempt each for the password and the 2FA code; any failure is a hard
STOP, no retry loop (repeated failed logins can lock/flag the account).

Example (on the VPS):
  set -a; source .env; set +a; python3 scripts/00b_login.py
"""

from __future__ import annotations

import getpass
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.aks_env import OFFICIAL_CDP_ENDPOINT  # noqa: E402
from src.invariants import build_report  # noqa: E402
from src.login_session import LoginSession, run_login  # noqa: E402
from src.run_log import RunLogger  # noqa: E402
from src.step_guard import StepGuard  # noqa: E402


def main() -> int:
    # Gate 1 — invariants green AND authoritative, same gate as every
    # write-capable stage. Retry a couple times for a transient red.
    report = build_report(endpoint=OFFICIAL_CDP_ENDPOINT)
    for _ in range(2):
        if report["ok"] and report["authoritative"]:
            break
        time.sleep(5)
        report = build_report(endpoint=OFFICIAL_CDP_ENDPOINT)
    if not (report["ok"] and report["authoritative"]):
        print(json.dumps({
            "aborted": True,
            "reason": "invariants not green/authoritative after retries",
            "ok": report["ok"],
            "authoritative": report["authoritative"],
            "failing_checks": [c for c in report.get("checks", []) if not c["ok"]],
        }, indent=2))
        return 2

    # Gate 2 — credentials present in the environment only (never a CLI arg).
    username = os.environ.get("AKS_WP_USER", "").strip()
    password = os.environ.get("AKS_WP_PASSWORD", "")
    if not username or not password:
        print(json.dumps({
            "aborted": True,
            "reason": "AKS_WP_USER and AKS_WP_PASSWORD must both be set in the environment",
        }, indent=2))
        return 2

    run_id = f"login-{int(time.time())}"
    logger = RunLogger(run_id, log_dir=str(ROOT / "logs"))
    guard = StepGuard(max_attempts_per_signature=1, max_failures_per_signature=1,
                       max_consecutive_failures=1)

    def get_2fa_code() -> str:
        print("2FA field visible and ready.", file=sys.stderr)
        return getpass.getpass("Enter the 2FA code: ").strip()

    with LoginSession(OFFICIAL_CDP_ENDPOINT) as session:
        result = run_login(
            session,
            username=username,
            password=password,
            get_2fa_code=get_2fa_code,
            guard=guard,
            run_id=run_id,
            logger=logger,
        )

    print(json.dumps(result, indent=2))
    return 0 if result.get("status") in ("already_logged_in", "logged_in") else 2


if __name__ == "__main__":
    raise SystemExit(main())

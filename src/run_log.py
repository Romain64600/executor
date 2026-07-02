"""Append-only JSONL run logger — fail-closed and redacting.

Writes one JSON object per line to ``<log_dir>/<run_id>.jsonl`` (default under the
gitignored ``logs/``). Used to persist an immutable run log: stage events and the
:class:`~src.step_guard.StepGuard` snapshot per task.

Secrets are redacted by key name *before* serialization, so a control token
(``webSocketDebuggerUrl``), a cookie, or a 2FA code can never land in a log even
if a caller passes it in. Standard library only.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

# Keys whose values are always replaced, matched case-insensitively and exactly
# (so e.g. "token" is redacted but "token_count" is not).
REDACT_KEYS = frozenset(
    {
        "websocketdebuggerurl",
        "cookie",
        "cookies",
        "set-cookie",
        "authorization",
        "password",
        "passwd",
        "otp",
        "googleotp",
        "2fa",
        "token",
        "secret",
        "api_key",
        "apikey",
    }
)
REDACTED = "***REDACTED***"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def redact(obj: Any) -> Any:
    """Recursively replace values of secret-named keys. Returns JSON-safe data."""

    if isinstance(obj, dict):
        return {
            key: (REDACTED if str(key).lower() in REDACT_KEYS else redact(value))
            for key, value in obj.items()
        }
    if isinstance(obj, (list, tuple)):
        return [redact(value) for value in obj]
    return obj


class RunLogger:
    """Append-only JSONL logger for one run."""

    def __init__(
        self,
        run_id: str,
        log_dir: str | Path = "logs",
        clock: Callable[[], str] = _utc_now_iso,
    ) -> None:
        if not run_id:
            raise ValueError("run_id must be a non-empty string")
        self.run_id = run_id
        self.dir = Path(log_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.path = self.dir / f"{run_id}.jsonl"
        self._clock = clock

    def log(self, event: str, **fields: Any) -> dict[str, Any]:
        """Append one redacted event record and return it."""

        record = {
            "ts": self._clock(),
            "run_id": self.run_id,
            "event": event,
            **redact(fields),
        }
        line = json.dumps(record, sort_keys=True)
        with open(self.path, "a", encoding="utf-8") as handle:
            handle.write(line + "\n")
        return record

    def log_guard(self, guard_snapshot: dict[str, Any]) -> dict[str, Any]:
        """Persist a StepGuard snapshot (redacted defensively)."""

        return self.log("guard_snapshot", guard=guard_snapshot)

    def read(self) -> list[dict[str, Any]]:
        """Read the run log back as a list of records."""

        if not self.path.exists():
            return []
        return [
            json.loads(line)
            for line in self.path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

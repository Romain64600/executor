"""Minimal read-only CDP helper skeleton for Sprint 1.

No browser actions are implemented here. The only supported operation is
fetching and validating the HTTP /json/version metadata endpoint.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .aks_env import (
    CheckResult,
    HttpProbeResult,
    http_get,
    parse_cdp_version_payload,
    validate_cdp_version_shape,
    validate_official_cdp_endpoint,
    validate_required_user_agent,
)


@dataclass(frozen=True)
class CdpVersionResult:
    """Result of a read-only CDP /json/version check."""

    endpoint: str
    ok: bool
    payload: dict[str, Any] | None
    checks: list[CheckResult]
    probe: HttpProbeResult
    error: str | None = None


class ReadOnlyCdpClient:
    """Tiny CDP HTTP client limited to metadata checks."""

    def __init__(self, endpoint: str, timeout: int = 5) -> None:
        self.endpoint = endpoint
        self.timeout = timeout

    def get_version(self) -> CdpVersionResult:
        """Fetch /json/version and validate endpoint, shape, and User-Agent."""

        checks = [validate_official_cdp_endpoint(self.endpoint)]
        probe = http_get(self.endpoint, timeout=self.timeout)
        if not probe.ok:
            checks.append(
                CheckResult(
                    name="cdp_http_get",
                    ok=False,
                    detail="CDP /json/version is not reachable",
                    data={"status": probe.status, "error": probe.error},
                )
            )
            return CdpVersionResult(
                endpoint=self.endpoint,
                ok=False,
                payload=None,
                checks=checks,
                probe=probe,
                error=probe.error or "CDP /json/version failed",
            )

        try:
            payload = parse_cdp_version_payload(probe.body)
        except (ValueError, TypeError) as exc:
            checks.append(
                CheckResult(
                    name="cdp_json_parse",
                    ok=False,
                    detail="CDP /json/version did not return a JSON object",
                    data={"error": str(exc)},
                )
            )
            return CdpVersionResult(
                endpoint=self.endpoint,
                ok=False,
                payload=None,
                checks=checks,
                probe=probe,
                error=str(exc),
            )

        checks.append(validate_cdp_version_shape(payload))
        checks.append(validate_required_user_agent(payload))
        return CdpVersionResult(
            endpoint=self.endpoint,
            ok=all(check.ok for check in checks),
            payload=payload,
            checks=checks,
            probe=probe,
        )

    def websocket_url(self) -> str:
        """Intentionally unavailable in Sprint 1 to prevent browser actions."""

        raise RuntimeError("Sprint 1 is read-only: WebSocket CDP actions are disabled")

"""Read-only invariant report builder for the AKS controlled executor.

Extracted from the CLI so it is unit-testable, and so the read-only probes run
through the deterministic :class:`~src.step_guard.StepGuard` — the template every
later (write) stage must follow. No browser actions are performed here.
"""

from __future__ import annotations

from typing import Any

from src.aks_env import (
    AKS_DIRECT_URL,
    OFFICIAL_CDP_ENDPOINT,
    checks_to_dict,
    current_environment,
    http_get,
    validate_aks_direct_status,
)
from src.cdp_client import CdpVersionResult, ReadOnlyCdpClient
from src.step_guard import StepGuard


def redact_cdp_payload(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    """Return a safe subset of ``/json/version``.

    Never expose ``webSocketDebuggerUrl`` — it is a live browser-control channel.
    """

    if not payload:
        return None
    return {
        "Browser": payload.get("Browser"),
        "User-Agent": payload.get("User-Agent"),
        "webSocketDebuggerUrl_present": bool(payload.get("webSocketDebuggerUrl")),
    }


def build_report(
    endpoint: str = OFFICIAL_CDP_ENDPOINT, timeout: int = 10
) -> dict[str, Any]:
    """Run the read-only invariant probes through a StepGuard and build a report.

    The probes are wrapped in ``guard.run_step`` with deterministic success
    predicates. A read-only check runs each probe exactly once, so the guard is
    exercised (and its snapshot logged) but cannot trip its own anti-loop block.
    """

    guard = StepGuard(max_attempts_per_signature=2)
    guard.start_task("invariant-check")

    aks_probe = guard.run_step(
        "probe",
        "aks_direct",
        action=lambda: http_get(AKS_DIRECT_URL, timeout=timeout, follow_redirects=False),
        success_predicate=lambda p: validate_aks_direct_status(p.status).ok,
    )
    cdp_result: CdpVersionResult = guard.run_step(
        "probe",
        "cdp_version",
        action=lambda: ReadOnlyCdpClient(endpoint=endpoint, timeout=timeout).get_version(),
        success_predicate=lambda r: r.ok,
    )

    aks_check = validate_aks_direct_status(aks_probe.status)
    aggregate = checks_to_dict([aks_check, *cdp_result.checks])
    environment = current_environment()

    return {
        "ok": aggregate["ok"],
        # authoritative is true only on the Debian VPS target; a red result with
        # authoritative=false (macOS/sandbox) is NOT a production failure.
        "authoritative": environment["authoritative"],
        "mode": "read-only",
        "dry_run": True,
        "environment": environment,
        "aks_direct": {
            "url": AKS_DIRECT_URL,
            "ok": aks_check.ok,
            "status": aks_probe.status,
            "error": aks_probe.error,
        },
        "cdp": {
            "endpoint": endpoint,
            "ok": cdp_result.ok,
            "http_status": cdp_result.probe.status,
            "error": cdp_result.error,
            "payload": redact_cdp_payload(cdp_result.payload),
        },
        "checks": aggregate["checks"],
        "guard": guard.snapshot(),
    }

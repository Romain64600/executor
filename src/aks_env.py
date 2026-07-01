"""Invariant checks for the AKS controlled executor.

This module is intentionally small and dependency-free. It contains pure
validation helpers plus read-only HTTP probes used by Sprint 1 tooling.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from http.client import HTTPResponse
import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

OFFICIAL_CDP_ENDPOINT = "http://172.17.0.1:9223/json/version"
HOST_CDP_ENDPOINT = "http://127.0.0.1:9222/json/version"
REQUIRED_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36"
)
AKS_DIRECT_URL = "https://www.allkeyshop.com/blog/"


@dataclass(frozen=True)
class CheckResult:
    """Single invariant check result."""

    name: str
    ok: bool
    detail: str
    data: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class HttpProbeResult:
    """Read-only HTTP probe result."""

    url: str
    ok: bool
    status: int | None
    body: str
    error: str | None = None
    headers: dict[str, str] = field(default_factory=dict)


def validate_official_cdp_endpoint(endpoint: str) -> CheckResult:
    """Require the Docker bridge CDP proxy endpoint, fail closed otherwise."""

    ok = endpoint == OFFICIAL_CDP_ENDPOINT
    return CheckResult(
        name="official_cdp_endpoint",
        ok=ok,
        detail="endpoint matches official Docker bridge CDP proxy"
        if ok
        else "endpoint is not the official Docker bridge CDP proxy",
        data={"expected": OFFICIAL_CDP_ENDPOINT, "actual": endpoint},
    )


def parse_cdp_version_payload(payload: str | bytes | dict[str, Any]) -> dict[str, Any]:
    """Parse a CDP /json/version payload into a dict."""

    if isinstance(payload, dict):
        return payload
    if isinstance(payload, bytes):
        payload = payload.decode("utf-8")
    parsed = json.loads(payload)
    if not isinstance(parsed, dict):
        raise ValueError("CDP version payload must be a JSON object")
    return parsed


def extract_user_agent(cdp_version: dict[str, Any]) -> str | None:
    """Return the CDP User-Agent value when present."""

    value = cdp_version.get("User-Agent")
    return value if isinstance(value, str) else None


def validate_required_user_agent(cdp_version: dict[str, Any]) -> CheckResult:
    """Require the exact configured Chrome User-Agent."""

    actual = extract_user_agent(cdp_version)
    ok = actual == REQUIRED_USER_AGENT
    return CheckResult(
        name="required_user_agent",
        ok=ok,
        detail="User-Agent matches required invariant"
        if ok
        else "User-Agent does not match required invariant",
        data={"expected": REQUIRED_USER_AGENT, "actual": actual},
    )


def validate_cdp_version_shape(cdp_version: dict[str, Any]) -> CheckResult:
    """Check the minimum read-only fields expected from /json/version."""

    missing = [
        key
        for key in ("Browser", "User-Agent", "webSocketDebuggerUrl")
        if not isinstance(cdp_version.get(key), str) or not cdp_version.get(key)
    ]
    ok = not missing
    return CheckResult(
        name="cdp_version_shape",
        ok=ok,
        detail="CDP version payload contains required fields"
        if ok
        else "CDP version payload is missing required fields",
        data={"missing": missing},
    )


def validate_aks_direct_status(status: int | None) -> CheckResult:
    """Require AKS direct HTTP reachability."""

    ok = status is not None and 200 <= status < 400
    return CheckResult(
        name="aks_direct_status",
        ok=ok,
        detail="AKS direct URL is reachable" if ok else "AKS direct URL is not reachable",
        data={"url": AKS_DIRECT_URL, "status": status},
    )


def checks_to_dict(checks: list[CheckResult]) -> dict[str, Any]:
    """Serialize checks with a fail-closed aggregate status."""

    return {
        "ok": all(check.ok for check in checks),
        "checks": [
            {
                "name": check.name,
                "ok": check.ok,
                "detail": check.detail,
                "data": check.data,
            }
            for check in checks
        ],
    }


def _response_to_probe(url: str, response: HTTPResponse) -> HttpProbeResult:
    body = response.read().decode("utf-8", errors="replace")
    return HttpProbeResult(
        url=url,
        ok=200 <= response.status < 400,
        status=response.status,
        body=body,
        headers=dict(response.headers.items()),
    )


def http_get(url: str, timeout: int = 5) -> HttpProbeResult:
    """Perform a read-only GET request."""

    request = Request(url, method="GET", headers={"User-Agent": REQUIRED_USER_AGENT})
    try:
        with urlopen(request, timeout=timeout) as response:
            return _response_to_probe(url, response)
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return HttpProbeResult(
            url=url,
            ok=False,
            status=exc.code,
            body=body,
            error=str(exc),
            headers=dict(exc.headers.items()) if exc.headers else {},
        )
    except URLError as exc:
        return HttpProbeResult(url=url, ok=False, status=None, body="", error=str(exc))
    except TimeoutError as exc:
        return HttpProbeResult(url=url, ok=False, status=None, body="", error=str(exc))


def http_head_status(url: str, timeout: int = 10) -> HttpProbeResult:
    """Perform a read-only HEAD request for reachability checks."""

    request = Request(url, method="HEAD", headers={"User-Agent": REQUIRED_USER_AGENT})
    try:
        with urlopen(request, timeout=timeout) as response:
            return HttpProbeResult(
                url=url,
                ok=200 <= response.status < 400,
                status=response.status,
                body="",
                headers=dict(response.headers.items()),
            )
    except HTTPError as exc:
        return HttpProbeResult(
            url=url,
            ok=False,
            status=exc.code,
            body="",
            error=str(exc),
            headers=dict(exc.headers.items()) if exc.headers else {},
        )
    except URLError as exc:
        return HttpProbeResult(url=url, ok=False, status=None, body="", error=str(exc))
    except TimeoutError as exc:
        return HttpProbeResult(url=url, ok=False, status=None, body="", error=str(exc))

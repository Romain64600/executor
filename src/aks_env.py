"""Invariant checks for the AKS controlled executor.

This module is intentionally small and dependency-free. It contains pure
validation helpers plus read-only HTTP probes used by Sprint 1 tooling.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from http.client import HTTPException, HTTPResponse
import json
import os
import platform
import socket
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen

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


# The skill/invariants define the acceptable set narrowly and deliberately.
ACCEPTED_AKS_STATUSES = (200, 301, 302)


def validate_aks_direct_status(status: int | None) -> CheckResult:
    """Require AKS direct HTTP reachability with a documented status (200/301/302)."""

    ok = status in ACCEPTED_AKS_STATUSES
    return CheckResult(
        name="aks_direct_status",
        ok=ok,
        detail="AKS direct URL is reachable" if ok else "AKS direct URL is not reachable",
        data={"url": AKS_DIRECT_URL, "status": status, "accepted": list(ACCEPTED_AKS_STATUSES)},
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


# A runtime marker that only exists on the real Debian VPS target. We do NOT
# use /etc/debian_version because Debian-derived sandboxes (e.g. Ubuntu CI)
# also carry it and would be misclassified as the production target.
TARGET_MARKER_PATH = "/home/debian/.hermes/config.yaml"


def classify_environment(
    system: str, target_marker_present: bool, hostname: str
) -> dict[str, Any]:
    """Classify where the checker runs. Pure, so it is unit-testable.

    Only the real Debian VPS target (Linux + a runtime marker) is treated as
    authoritative. Anywhere else (macOS dev, a Debian-derived CI sandbox) an
    invariant failure is NOT a production failure and must never unlock write
    stages.
    """

    is_target = system == "Linux" and target_marker_present
    return {
        "hostname": hostname,
        "platform": system,
        "is_target": is_target,
        "authoritative": is_target,
        "note": (
            "Debian VPS target: invariant result is authoritative"
            if is_target
            else "not the Debian VPS target: invariant failures here are NOT "
            "production failures"
        ),
    }


def current_environment() -> dict[str, Any]:
    """Classify the current runtime using stdlib probes only.

    ``AKS_TARGET=vps`` forces the target marker on; ``AKS_TARGET=dev`` (or
    ``sandbox``/``local``) forces it off; otherwise the runtime marker file is
    probed.
    """

    override = os.environ.get("AKS_TARGET", "").strip().lower()
    if override == "vps":
        marker = True
    elif override in {"dev", "sandbox", "local"}:
        marker = False
    else:
        marker = os.path.exists(TARGET_MARKER_PATH)

    return classify_environment(
        system=platform.system(),
        target_marker_present=marker,
        hostname=socket.gethostname(),
    )


def _response_to_probe(url: str, response: HTTPResponse) -> HttpProbeResult:
    body = response.read().decode("utf-8", errors="replace")
    return HttpProbeResult(
        url=url,
        ok=response.status in ACCEPTED_AKS_STATUSES or 200 <= response.status < 300,
        status=response.status,
        body=body,
        headers=dict(response.headers.items()),
    )


class _NoRedirectHandler(HTTPRedirectHandler):
    """Refuse to follow redirects so callers see the true first hop.

    Returning None makes urllib raise ``HTTPError`` for a 3xx instead of
    transparently following it (e.g. a redirect to a login or geo wall). The
    caller then sees the real 3xx status and validates it deliberately.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D401
        return None


def _http_open(request: Request, timeout: int, follow_redirects: bool = True):
    """Single, patchable IO seam for all read-only HTTP in this module."""

    if follow_redirects:
        return urlopen(request, timeout=timeout)
    return build_opener(_NoRedirectHandler()).open(request, timeout=timeout)


def http_get(url: str, timeout: int = 5, follow_redirects: bool = True) -> HttpProbeResult:
    """Perform a read-only GET request.

    With ``follow_redirects=False`` a 3xx is reported with its real status code
    (surfaced via ``HTTPError``) rather than being followed, so reachability
    checks see the true first hop.
    """

    request = Request(url, method="GET", headers={"User-Agent": REQUIRED_USER_AGENT})
    try:
        with _http_open(request, timeout=timeout, follow_redirects=follow_redirects) as response:
            return _response_to_probe(url, response)
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return HttpProbeResult(
            url=url,
            ok=exc.code in ACCEPTED_AKS_STATUSES,
            status=exc.code,
            body=body,
            error=str(exc),
            headers=dict(exc.headers.items()) if exc.headers else {},
        )
    except URLError as exc:
        return HttpProbeResult(url=url, ok=False, status=None, body="", error=str(exc))
    except (HTTPException, TimeoutError, OSError) as exc:
        # urllib does NOT wrap errors raised while reading the response (e.g.
        # http.client.RemoteDisconnected from a dead proxy upstream) in URLError.
        return HttpProbeResult(
            url=url, ok=False, status=None, body="", error=f"{type(exc).__name__}: {exc}"
        )


def http_head_status(url: str, timeout: int = 10, follow_redirects: bool = True) -> HttpProbeResult:
    """Perform a read-only HEAD request for reachability checks."""

    request = Request(url, method="HEAD", headers={"User-Agent": REQUIRED_USER_AGENT})
    try:
        with _http_open(request, timeout=timeout, follow_redirects=follow_redirects) as response:
            return HttpProbeResult(
                url=url,
                ok=response.status in ACCEPTED_AKS_STATUSES or 200 <= response.status < 300,
                status=response.status,
                body="",
                headers=dict(response.headers.items()),
            )
    except HTTPError as exc:
        return HttpProbeResult(
            url=url,
            ok=exc.code in ACCEPTED_AKS_STATUSES,
            status=exc.code,
            body="",
            error=str(exc),
            headers=dict(exc.headers.items()) if exc.headers else {},
        )
    except URLError as exc:
        return HttpProbeResult(url=url, ok=False, status=None, body="", error=str(exc))
    except (HTTPException, TimeoutError, OSError) as exc:
        return HttpProbeResult(
            url=url, ok=False, status=None, body="", error=f"{type(exc).__name__}: {exc}"
        )

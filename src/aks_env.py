"""Invariant checks for the AKS controlled executor.

This module is intentionally small and stdlib-only at its core. It contains pure
validation helpers plus read-only HTTP probes used by Sprint 1 tooling. The only
optional dependency is ``requests`` — when installed it backs the probes with a
keep-alive Session (see ``_http_open``); when absent the module falls back to
urllib with the same probe contract (status / ok / body — see ``_http_open_keepalive``
for the known, fail-closed divergences), so the invariant gate still runs
dependency-free.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from http.client import HTTPException, HTTPResponse
import io
import json
import os
import platform
import re
import socket
import string
import subprocess
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urljoin, urlsplit
from urllib.request import (HTTPRedirectHandler, Request, build_opener, getproxies,
                            proxy_bypass, urlopen)

OFFICIAL_CDP_ENDPOINT = "http://172.17.0.1:9223/json/version"
HOST_CDP_ENDPOINT = "http://127.0.0.1:9222/json/version"
REQUIRED_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36"
)
AKS_DIRECT_URL = "https://www.allkeyshop.com/blog/"
# Staff anti-bot bypass UA for AKS HTTP probes — allkeyshop.com ONLY (Romain,
# audit #4, 2026-07-08): CDP browsing keeps REQUIRED_USER_AGENT, and no other
# host may ever see a staff/crawler UA. http_get enforces this fail-closed.
AKS_STAFF_UA = "AKS/Staff"


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


def validate_no_openvpn(pids: list[str] | None) -> CheckResult:
    """Forbid a running OpenVPN process (VPN is forbidden while AKS direct works).

    ``pids=None`` means the probe could not determine the process state; per the
    fail-closed policy that is a failure, not a pass.
    """

    if pids is None:
        return CheckResult(
            name="no_openvpn_process",
            ok=False,
            detail="could not determine OpenVPN process state — fail closed",
            data={"pids": None},
        )
    ok = not pids
    return CheckResult(
        name="no_openvpn_process",
        ok=ok,
        detail="no OpenVPN process running"
        if ok
        else "openvpn is running — stop it (VPN forbidden while AKS direct works)",
        data={"pids": list(pids)},
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


# The runtime marker that only exists on the real Debian VPS target. We do NOT
# use /etc/debian_version because Debian-derived sandboxes (e.g. Ubuntu CI)
# also carry it and would be misclassified as the production target.
#
# FC2 (audit 2026-07-17): the marker moved from the user-writable
# ~/.hermes/config.yaml to a ROOT-installed /etc file whose CONTENT must equal
# this machine's hostname, and the ``AKS_TARGET=vps`` force was removed —
# "read-only until green on the VPS" must not be unlockable by one env var or
# a user-level file. Installed once on the VPS (2026-07-17):
#   sudo sh -c 'hostname > /etc/aks-executor.target'; chmod 644.
TARGET_MARKER_PATH = "/etc/aks-executor.target"


def marker_authorizes(
    path: str = TARGET_MARKER_PATH, hostname: str | None = None
) -> bool:
    """True iff the root-installed target marker vouches for THIS machine.

    Three independent requirements, all fail-closed: the file exists AND is
    root-owned with no group/world write (a user or container escapee cannot
    just drop it) AND its content equals the current hostname (a copied
    marker on another box does not transfer authority)."""

    try:
        stat_result = os.stat(path)
        with open(path, "r", encoding="utf-8") as handle:
            content = handle.read().strip()
    except OSError:
        return False
    if stat_result.st_uid != 0 or (stat_result.st_mode & 0o022):
        return False
    host = hostname if hostname is not None else socket.gethostname()
    return bool(content) and content == host


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

    ``AKS_TARGET=dev`` (or ``sandbox``/``local``) forces NON-authoritative —
    forcing OFF is always safe. There is deliberately NO force in the other
    direction (FC2, audit 2026-07-17): ``AKS_TARGET=vps`` used to flip
    ``authoritative`` on from any Linux box, making the whole
    read-only-until-green gate spoofable by one env var. Authority now comes
    only from :func:`marker_authorizes` (root-installed /etc marker pinned to
    this hostname).
    """

    override = os.environ.get("AKS_TARGET", "").strip().lower()
    if override in {"dev", "sandbox", "local"}:
        marker = False
    else:
        marker = marker_authorizes()

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


class StaffUaRedirectRefused(HTTPError):
    """A staff-UA probe was 3xx-redirected off allkeyshop.com and refused (P2-15). [40]
    Fable re-audit 2026-09-06: a DISTINCT type so :func:`http_get` reports ok=False — a
    refused redirect is a fail-closed MISS, never a success, even though its 3xx code is
    in ACCEPTED_AKS_STATUSES (200/301/302) which would otherwise wave it through."""


class _StaffUaHostGuardRedirectHandler(HTTPRedirectHandler):
    """Follow same-domain (allkeyshop.com) redirects, but REFUSE a redirect to any
    other host (P2-15, audit 2026-09-02).

    urllib's ``HTTPRedirectHandler`` preserves the ``User-Agent`` header across a
    cross-host redirect (it strips only content-length/-type), so a staff-UA probe
    that AKS 3xx-redirects off-domain would leak the ``AKS/Staff`` UA off
    allkeyshop.com — the first-hop check in :func:`http_get` only guards the URL the
    caller passed in. Refusing surfaces as an ``HTTPError`` the caller treats as a
    non-200 (fail-closed: over-abort a resolve, never a wrong entry). Same-domain
    canonicalization redirects (301/302) are still followed, so no resolve regresses.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not _allkeyshop_host(newurl):
            raise StaffUaRedirectRefused(
                req.full_url, code,
                f"AKS/Staff redirect off allkeyshop.com refused: {newurl}", headers, fp
            )
        return super().redirect_request(req, fp, code, msg, headers, newurl)


# HTTP keep-alive (Romain 2026-09-08). This module's core stays stdlib-only; ``requests``
# is an OPTIONAL accelerator: when present, a persistent Session reuses ONE TLS connection
# across a page's hundreds of resolve probes (measured 134ms → ~32ms per request, no change
# to the request COUNT — the request RATE rise of the same change comes from the separate
# AKS_PROBE_DELAY_S 0.3→0.15 s pacing in src/matcher.py, still strictly serial). When
# absent, ``_http_open`` falls back to the unchanged urllib path, so the dependency-free
# invariant gate still runs anywhere.
try:  # requests is optional — ANY import/setup failure means "use the stdlib backend"
    import requests as _requests
    from http.cookiejar import DefaultCookiePolicy

    _SESSION = _requests.Session()
    # Never STORE cookies — match urllib's per-call statelessness so a Set-Cookie from one
    # probe cannot change another probe's response (resolution must stay deterministic).
    _SESSION.cookies.set_policy(DefaultCookiePolicy(allowed_domains=[]))
    # Match urllib's redirect ceiling (max_redirections=10) instead of requests' default 30
    # (re-verify 2026-09-08): otherwise the two interchangeable _http_open backends diverge on
    # an 11-30 hop chain — requests would follow it to a 200 (ok=True) where urllib caps at 10
    # and raises HTTPError(3xx) (ok=False for 303/307/308). Pathological on AKS, but capping to
    # 10 keeps the backends provably fail-closed-equivalent.
    _SESSION.max_redirects = 10
    # Stay ENV-BLIND like urllib (audit 2026-09-09): with trust_env, requests reads
    # ~/.netrc / $NETRC (a `default` entry injects `Authorization: Basic …` into EVERY
    # probe — staff-UA ones to AKS included) and REQUESTS_CA_BUNDLE/CURL_CA_BUNDLE; urllib
    # honours neither. The ONE env feature urllib does honour (http(s)_proxy / no_proxy,
    # ProxyHandler) is mirrored per request by _urllib_proxies() instead.
    _SESSION.trust_env = False
except Exception:  # requests missing / broken → stdlib fallback
    _requests = None
    _SESSION = None


class _KeepAliveResponse:
    """Adapt a ``requests.Response`` to the ``http.client.HTTPResponse``-ish interface that
    :func:`_response_to_probe` and :func:`http_head_status` read — ``.read()`` (bytes),
    ``.status``, ``.headers`` — plus the context-manager protocol the callers use."""

    def __init__(self, resp: "Any") -> None:
        self._resp = resp
        self.status = resp.status_code
        self.headers = resp.headers

    def read(self) -> bytes:
        return self._resp.content

    def __enter__(self) -> "_KeepAliveResponse":
        return self

    def __exit__(self, *exc: Any) -> bool:
        self._resp.close()
        return False


def _urllib_proxies(url: str) -> dict[str, str]:
    """The proxy mapping urllib's default ``ProxyHandler`` would apply to ``url``: the
    ``http(s)_proxy`` env vars unless ``no_proxy``/``proxy_bypass`` exempts the host. The
    Session is ``trust_env=False`` (see above), so this keeps the env behaviour the stdlib
    fallback has (urllib's ``req.host`` is ``host[:port]`` with the userinfo stripped, so a
    ``no_proxy=host:port`` entry matches here too)."""

    parts = urlsplit(url)
    if not parts.hostname:
        return {}
    authority = parts.netloc.rpartition("@")[2]
    if proxy_bypass(authority):
        return {}
    return dict(getproxies())


def _http_open_keepalive(request: Request, timeout: int, follow_redirects: bool,
                         host_locked: bool):
    """Keep-alive backend for :func:`_http_open` — SAME contract as the urllib path:
    returns an HTTPResponse-like object on 2xx, raises ``HTTPError`` for any non-2xx (incl.
    a no-redirect 3xx), :class:`StaffUaRedirectRefused` for an off-domain staff hop, and
    ``URLError`` for a transport failure — so ``http_get``/``http_head_status`` are unchanged.

    Known, deliberate divergences from urllib (audit + review 2026-09-09) — every one fails
    CLOSED on this side (ok=False), never less closed than urllib: a chain exhausting the
    redirect ceiling raises ``URLError`` (status None) where urllib raises ``HTTPError(3xx)``;
    in the plain (non-locked) follow branch requests forwards a hop-1 ``Set-Cookie`` to hop 2
    within ONE call (never across calls — the jar rejects everything); a ``Location`` holding
    a lone non-UTF-8 byte makes requests raise while pre-computing ``Response.next`` — in
    EVERY mode, the no-redirect gate included — so it surfaces as ``URLError`` (status None,
    gate red) where urllib reports the 3xx itself (gate green on 301/302); the obsolete
    ``URI:`` redirect header is ignored here (urllib still honours it).
    """

    url = request.full_url
    method = request.get_method()
    headers = dict(request.header_items())
    exhausted = False
    try:
        if not follow_redirects:
            # No-redirect mode (reachability gate): do NOT follow — a 3xx first hop surfaces
            # as HTTPError below, EXACTLY like urllib's _NoRedirectHandler. This MUST take
            # priority over host_locked (adversarial verify 2026-09-08): the urllib fallback
            # checks `if not follow_redirects` first, so a staff-UA + no-redirect probe that
            # met a same-domain 3xx→200 would otherwise be FOLLOWED to 200 here (ok=True)
            # while urllib raised HTTPError(3xx) (ok=False) — flipping the invariant gate to a
            # spurious green. No redirect is followed here, so there is nothing to host-lock.
            resp = _SESSION.request(method, url, headers=headers, allow_redirects=False,
                                    timeout=timeout, proxies=_urllib_proxies(url))
        elif host_locked:
            current = url
            # Initial fetch + at most 10 FOLLOWED redirects — the same ceiling as urllib's
            # HTTPRedirectHandler.max_redirections (audit 2026-09-09: `range(10)` counted
            # requests, so an exactly-10-hop chain resolved on urllib but failed here).
            for _ in range(11):
                resp = _SESSION.request(method, current, headers=headers,
                                        allow_redirects=False, timeout=timeout,
                                        proxies=_urllib_proxies(current))
                location = resp.headers.get("Location")
                if resp.status_code in (301, 302, 303, 307, 308) and location:
                    code, hdrs = resp.status_code, dict(resp.headers)
                    resp.close()
                    # http.client decoded the header value as latin-1; re-quote it exactly
                    # like urllib's HTTPRedirectHandler.http_error_302 so a UTF-8 permalink
                    # ("é" → %C3%A9) is requested as-is instead of double-encoded mojibake.
                    nxt = urljoin(current, quote(location, encoding="iso-8859-1",
                                                 safe=string.punctuation))
                    if not _allkeyshop_host(nxt):
                        raise StaffUaRedirectRefused(
                            url, code,
                            f"AKS/Staff redirect off allkeyshop.com refused: {nxt}",
                            hdrs, io.BytesIO(b""))
                    current = nxt
                    continue
                break
            else:
                exhausted = True   # raised below, OUTSIDE the blanket except (no double wrap)
        else:
            resp = _SESSION.request(method, url, headers=headers, allow_redirects=True,
                                    timeout=timeout, proxies=_urllib_proxies(url))
    except StaffUaRedirectRefused:
        raise  # our own fail-closed refusal — never mask it as a transport error
    except Exception as exc:
        # ANY other failure (requests transport errors, or requests broken at runtime with a
        # non-RequestException) → URLError, so http_get/http_head_status keep their "never
        # raises, fails closed" contract (adversarial verify 2026-09-08, minor #4).
        raise URLError(str(exc)) from exc
    if exhausted:
        raise URLError("too many redirects (host-locked)")
    if not 200 <= resp.status_code < 300:
        code, reason, hdrs, body = (resp.status_code, resp.reason or "",
                                    dict(resp.headers), resp.content)
        resp.close()
        raise HTTPError(url, code, reason, hdrs, io.BytesIO(body))
    return _KeepAliveResponse(resp)


def _http_open_urllib(request: Request, timeout: int, follow_redirects: bool,
                      host_locked: bool):
    """Stdlib fallback (unchanged behavior): opens with the redirect handler the mode needs."""

    if not follow_redirects:
        return build_opener(_NoRedirectHandler()).open(request, timeout=timeout)
    if host_locked:
        return build_opener(_StaffUaHostGuardRedirectHandler()).open(request, timeout=timeout)
    return urlopen(request, timeout=timeout)


def _http_open(request: Request, timeout: int, follow_redirects: bool = True,
               host_locked: bool = False):
    """Single, patchable IO seam for all read-only HTTP in this module.

    Uses the keep-alive backend when ``requests`` is available, else the stdlib fallback —
    both honor the same contract. ``host_locked`` (staff-UA callers) follows only
    same-domain redirects and refuses an off-allkeyshop.com hop, so the staff UA never
    leaks past a cross-host 3xx (P2-15).
    """

    backend = _http_open_keepalive if _SESSION is not None else _http_open_urllib
    return backend(request, timeout, follow_redirects, host_locked)


# An UNAMBIGUOUS authority: host chars + optional :port. No userinfo (`@`), no backslash, no
# whitespace, no IPv6 literal — see _allkeyshop_host.
_STRICT_NETLOC_RE = re.compile(r"^[A-Za-z0-9.-]+(?::\d{1,5})?$")


def _allkeyshop_host(url: str) -> bool:
    """True only for an http(s) URL on allkeyshop.com whose authority is UNAMBIGUOUS.

    Parser-differential guard (audit 2026-09-09, major): ``urlsplit`` ends the netloc at
    ``/?#`` only, but urllib3 (the keep-alive connection) also ends it at a backslash — so
    ``https://evil.tld\\@www.allkeyshop.com/x`` has hostname ``www.allkeyshop.com`` for a
    naive check and host ``evil.tld`` for the actual connection: the staff UA would be sent
    off-domain with the guard green (the urllib fallback fails closed on the same input).
    Refusing any netloc with userinfo, a backslash, whitespace or anything outside
    ``[A-Za-z0-9.-]`` + an optional ``:port`` makes EVERY parser agree on the host before a
    request is made. Non-http(s) schemes (``javascript:``/``data:`` Locations) are refused too.
    """

    parts = urlsplit(url)
    if parts.scheme.lower() not in ("http", "https"):
        return False
    if not _STRICT_NETLOC_RE.match(parts.netloc or ""):
        return False
    host = (parts.hostname or "").lower()
    return host == "allkeyshop.com" or host.endswith(".allkeyshop.com")


def http_get(
    url: str,
    timeout: int = 5,
    follow_redirects: bool = True,
    user_agent: str | None = None,
) -> HttpProbeResult:
    """Perform a read-only GET request.

    With ``follow_redirects=False`` a 3xx is reported with its real status code
    (surfaced via ``HTTPError``) rather than being followed, so reachability
    checks see the true first hop.
    """

    if user_agent == AKS_STAFF_UA and not _allkeyshop_host(url):
        raise ValueError(
            f"{AKS_STAFF_UA!r} User-Agent is restricted to allkeyshop.com hosts"
            f" (audit #4, 2026-07-08): {url}"
        )
    request = Request(url, method="GET", headers={"User-Agent": user_agent or REQUIRED_USER_AGENT})
    try:
        with _http_open(request, timeout=timeout, follow_redirects=follow_redirects,
                        host_locked=(user_agent == AKS_STAFF_UA)) as response:
            return _response_to_probe(url, response)
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        # [40] a guard-refused off-domain staff-UA redirect is a fail-closed MISS, never a
        # success — force ok=False even though its 3xx code is an accepted status.
        refused = isinstance(exc, StaffUaRedirectRefused)
        return HttpProbeResult(
            url=url,
            ok=(not refused) and exc.code in ACCEPTED_AKS_STATUSES,
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


def list_openvpn_pids() -> list[str] | None:
    """Return the PIDs of running ``openvpn`` processes (read-only probe).

    Uses ``pgrep -x openvpn`` (exact process-name match, same as the shell
    audit). Returns ``None`` when the state cannot be determined (pgrep missing,
    timeout, usage/fatal error) so the caller fails closed instead of assuming
    "no VPN".
    """

    try:
        proc = subprocess.run(
            ["pgrep", "-x", "openvpn"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode == 0:
        return [line.strip() for line in proc.stdout.splitlines() if line.strip()]
    if proc.returncode == 1:  # pgrep contract: 1 = no process matched
        return []
    return None  # 2/3 = usage or fatal error — state unknown


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

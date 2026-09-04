"""Session re-auth from the admin page, by COOKIE TRANSFER (Romain 2026-07-29).

AKS disabled password login (social/OAuth only), so the password+2FA flow can
never authenticate. Instead the operator completes the social login in their OWN
browser, exports the AKS session cookies (a Cookie-Editor JSON export), and
pastes them here; this injects them into the VPS CDP tab and PROVES the session
with the same deterministic ``verify_dashboard`` the password path used.

Security: the cookie VALUES are session secrets — they are passed straight to
CDP and NEVER logged, echoed back, or stored; only names/counts and boolean
verify flags are ever surfaced. Runs ONLY on the operator's explicit submit
(never self-triggered), one at a time, behind the browser lock and the same
invariants gate as every browser-touching stage. Injection is restricted to the
allkeyshop.com domain — a pasted cookie for any other domain is dropped.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any, Callable

from src.aks_env import OFFICIAL_CDP_ENDPOINT
from src.browser_lock import BrowserBusyError, browser_lock
from src.invariants import build_report
from src.login_session import LoginSession

_AKS_DOMAIN = "allkeyshop.com"
_SAMESITE = {"no_restriction": "None", "none": "None", "lax": "Lax", "strict": "Strict"}
# Never surface these (defensive scrub on top of never constructing them).
_SECRET_KEYS = ("value", "cookies", "cookie", "password", "otp", "2fa")


class LoginError(RuntimeError):
    """A refusal the route turns into an HTTP error (mirrors SubmitStartError)."""

    def __init__(self, code: str, message: str, http_status: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status


def _scrub(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _scrub(v) for k, v in obj.items() if k.lower() not in _SECRET_KEYS}
    if isinstance(obj, list):
        return [_scrub(v) for v in obj]
    return obj


def _parse_cookie_table(raw: str) -> list[dict[str, Any]]:
    """Best-effort parse of a DevTools 'Application → Cookies' table copy: TAB-
    separated rows ``name  value  domain  path  expires  size … httpOnly …``.
    name/value/domain/path come from the first columns (reliable); ``secure``
    defaults True (AKS is HTTPS); httpOnly is inferred from a ✓ in the flag
    columns. Rows with fewer than 3 tab-separated columns are skipped."""

    rows: list[dict[str, Any]] = []
    for line in raw.splitlines():
        if not line.strip():
            continue
        cols = line.split("\t")
        if len(cols) < 3:
            continue
        path = cols[3].strip() if len(cols) > 3 and cols[3].strip() else "/"
        httponly = "✓" in "\t".join(cols[6:]) if len(cols) > 6 else False
        rows.append({"name": cols[0].strip(), "value": cols[1], "domain": cols[2].strip(),
                     "path": path, "secure": True, "httpOnly": httponly})
    return rows


def normalize_cookies(raw: Any) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Parse cookies into CDP ``Network.setCookies`` params, keeping ONLY
    allkeyshop.com cookies. Accepts a Cookie-Editor JSON export OR a DevTools
    cookie-table copy (TAB-separated). Pure (no CDP) — the tested surface.
    Raises LoginError on unparseable input; returns (cdp_cookies, stats) where
    stats carries counts + skipped NAMES (never values)."""

    if isinstance(raw, str):
        raw = raw.strip()
        if not raw:
            raise LoginError("no_cookies", "colle tes cookies AKS (JSON Cookie-Editor ou tableau DevTools)")
        if raw[:1] in "[{":
            try:
                data = json.loads(raw)
            except (json.JSONDecodeError, ValueError):
                raise LoginError("bad_cookies_json",
                                 "JSON illisible — attendu un tableau (Cookie-Editor → Export)")
            if isinstance(data, dict):
                data = [data]
        else:
            data = _parse_cookie_table(raw)
    else:
        data = raw
    if not isinstance(data, list):
        raise LoginError("bad_cookies_json", "attendu un tableau JSON de cookies ou un tableau DevTools")

    out: list[dict[str, Any]] = []
    skipped: list[str] = []
    for c in data:
        if not isinstance(c, dict):
            skipped.append("entrée non-objet")
            continue
        name = str(c.get("name") or "").strip()
        value = c.get("value")
        domain = str(c.get("domain") or "").strip()
        if not name or value is None:
            skipped.append("cookie sans name/value")
            continue
        host = domain.lstrip(".").lower()
        # EXACT host or a true subdomain — NOT a substring (a substring test
        # would let 'allkeyshop.com.evil.com' / 'evilallkeyshop.com' through and
        # inject a cookie for an attacker domain — security review 2026-07-29).
        if not (host == _AKS_DOMAIN or host.endswith("." + _AKS_DOMAIN)):
            skipped.append(f"{name}: domaine {domain or '?'} hors AKS")
            continue
        cdp: dict[str, Any] = {
            "name": name,
            "value": str(value),
            "domain": domain,
            "path": str(c.get("path") or "/"),
            "secure": bool(c.get("secure", True)),
            "httpOnly": bool(c.get("httpOnly", False)),
        }
        same = _SAMESITE.get(str(c.get("sameSite") or "").strip().lower())
        if same:
            cdp["sameSite"] = same
        exp = c.get("expirationDate", c.get("expires"))
        if isinstance(exp, (int, float)) and exp > 0:
            cdp["expires"] = float(exp)
        out.append(cdp)
    return out, {"accepted": len(out), "skipped": len(skipped), "skipped_detail": skipped[:8]}


class LoginManager:
    """Supervises ONE cookie-transfer re-auth at a time (synchronous)."""

    def __init__(
        self,
        repo_root: Path,
        *,
        endpoint: str = OFFICIAL_CDP_ENDPOINT,
        session_factory: Callable[[str], Any] = LoginSession,
        report_fn: Callable[..., dict[str, Any]] = build_report,
        admin_url: str = LoginSession.ADMIN_URL,
        clock: Callable[[], float] | None = None,
    ) -> None:
        import time
        self.repo_root = Path(repo_root)
        self.endpoint = endpoint
        self._session_factory = session_factory
        self._report_fn = report_fn
        self._admin_url = admin_url
        self._clock = clock or time.time
        self._mutex = threading.Lock()
        self._busy = False
        self._result: dict[str, Any] | None = None
        self._by: str | None = None
        self._at: float | None = None

    def status(self) -> dict[str, Any]:
        with self._mutex:
            return {"busy": self._busy, "by": self._by, "at": self._at,
                    "result": _scrub(self._result) if self._result is not None else None}

    def apply_cookies(self, raw: Any, *, by: str) -> dict[str, Any]:
        with self._mutex:
            if self._busy:
                raise LoginError("login_busy", "une reconnexion est déjà en cours", http_status=409)
            self._busy = True
            self._by = by
            self._at = self._clock()
        try:
            cookies, stats = normalize_cookies(raw)   # raises LoginError → 400
            if not cookies:
                result = {"status": "aborted", "stats": stats, "reason": (
                    "aucun cookie AKS valide — attendu un export JSON Cookie-Editor du "
                    "domaine allkeyshop.com (dont les cookies wordpress_logged_in_*)")}
            else:
                report = self._report_fn(endpoint=self.endpoint)
                if not (report.get("ok") and report.get("authoritative")):
                    result = {"status": "aborted",
                              "reason": "invariants pas au vert/authoritative — injection refusée"}
                else:
                    result = self._inject_and_verify(cookies, stats)
        except LoginError:
            with self._mutex:
                self._busy = False
            raise
        except Exception as exc:  # fail-closed: any error → clean aborted result
            # P3-8 (audit 2026-09-02): build the reason from the exception TYPE + a
            # FIXED message only — never interpolate `{exc}`. This catch-all wraps the
            # cookie-injection chain, whose exception string could carry a cookie VALUE;
            # the reason is returned by /api/login/cookies and re-served by
            # /api/login/status, and `_scrub` is key-name based (it can't redact a
            # free-text field). The type is enough to categorize; details stay off the wire.
            result = {"status": "aborted",
                      "reason": f"erreur interne ({type(exc).__name__}) — voir les logs serveur"}
        with self._mutex:
            self._result = _scrub(result)
            self._busy = False
        return self._result

    def _inject_and_verify(self, cookies: list[dict[str, Any]], stats: dict[str, Any]) -> dict[str, Any]:
        try:
            with browser_lock(self.repo_root, label="admin_cookie_login"), \
                    self._session_factory(self.endpoint) as session:
                session.set_cookies(cookies)          # secrets → CDP, never logged
                session.navigate(self._admin_url)
                verdict = session.verify_dashboard()
        except BrowserBusyError as exc:
            return {"status": "aborted", "reason": f"navigateur occupé (submit/sort en cours ?): {exc}",
                    "stats": stats}
        ok = bool(verdict.get("ok"))
        return {
            "status": "logged_in" if ok else "not_logged_in",
            "verified": {"url_ok": bool(verdict.get("url_ok")), "dom_ok": bool(verdict.get("dom_ok"))},
            "cookies_injected": stats.get("accepted"),
            "stats": stats,
        }

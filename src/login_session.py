"""Stage 0b — login/2FA (LOGIN_SPEC.md), Option A (2026-07-14, Romain).

``LoginSession`` extends ``WriteSubmitSession`` purely to reuse its
already-audited trusted-input primitives (``click_trusted_at_element``,
``_type_text_trusted``) — the exact same ``isTrusted:true`` mouse/keyboard
synthesis already proven on the submit path, pointed at the WP login form
instead of the offer modal. No new CDP mechanism is introduced. Its methods
are thin state-query/action primitives only (mirrors ``SubmitSession``'s own
style: ``is_login_page()``, ``modal_context()``, ...) — the sequencing and
every stop/continue decision lives in ``run_login`` below, so it is testable
against a duck-typed fake session with no CDP, no network (mirrors
``src/submitter.py`` / ``tests/test_submitter.py``'s ``FakeSubmitSession``).

Credentials and the 2FA code are held as local values only, passed straight
into a trusted-type call, and never written to a log line — ``RunLogger``
also redacts by key name (``password``, ``otp``, ``googleotp``, ``2fa``, ...)
as a second layer, but this module additionally never *constructs* a record
containing one in the first place.
"""

from __future__ import annotations

import json
import time
from typing import Any, Callable

from src.step_guard import StepGuard
from src.submit_session import WriteSubmitSession

_DASHBOARD_MARKER_JS = "!!document.querySelector('#wpadminbar')"

_LOGIN_FORM_FIELDS_JS = (
    "JSON.stringify({"
    "user: !!document.querySelector('#user_login'),"
    "pass: !!document.querySelector('#user_pass'),"
    "submit: !!document.querySelector('#wp-submit')"
    "})"
)

# WP 2FA plugins vary the field name (`authcode` is WP's own Google
# Authenticator plugin's convention; `googleotp` is the skill's historical
# name for the same field on this install) — check both, read-only.
_TWOFA_FIELD_JS = (
    "!!document.querySelector("
    "'input[name=\"authcode\"], #authcode, input[name=\"googleotp\"]'"
    ")"
)
_TWOFA_SELECTOR = 'input[name="authcode"], #authcode, input[name="googleotp"]'

_LOGIN_ERROR_JS = "!!document.querySelector('#login_error')"


class LoginSession(WriteSubmitSession):
    """WP-admin login form primitives. No sequencing logic — see ``run_login``."""

    LOGIN_URL = "https://www.allkeyshop.com/blog/wp-login.php"

    def already_logged_in(self) -> bool:
        """Read-only: current page already a dashboard, not a login form."""

        return not self.is_login_page() and bool(self.evaluate_readonly(_DASHBOARD_MARKER_JS))

    def open_login_page(self) -> None:
        self.navigate(self.LOGIN_URL)

    def login_form_ready(self) -> dict[str, bool]:
        raw = self.evaluate_readonly(_LOGIN_FORM_FIELDS_JS)
        return json.loads(raw) if raw else {"user": False, "pass": False, "submit": False}

    def fill_username(self, username: str) -> dict[str, Any]:
        focus = self.click_trusted_at_element("#user_login")
        if focus.get("status") != "CLICKED":
            return {"status": "NO_USERNAME_FIELD"}
        self._type_text_trusted(username)
        return {"status": "FILLED"}

    def fill_password(self, password: str) -> dict[str, Any]:
        focus = self.click_trusted_at_element("#user_pass")
        if focus.get("status") != "CLICKED":
            return {"status": "NO_PASSWORD_FIELD"}
        self._type_text_trusted(password)
        return {"status": "FILLED"}

    def submit_login(self) -> dict[str, Any]:
        return self.click_trusted_at_element("#wp-submit")

    def has_login_error(self) -> bool:
        return bool(self.evaluate_readonly(_LOGIN_ERROR_JS))

    def has_2fa_field(self) -> bool:
        return bool(self.evaluate_readonly(_TWOFA_FIELD_JS))

    def has_dashboard_marker(self) -> bool:
        return bool(self.evaluate_readonly(_DASHBOARD_MARKER_JS))

    def fill_2fa_code(self, code: str) -> dict[str, Any]:
        focus = self.click_trusted_at_element(_TWOFA_SELECTOR)
        if focus.get("status") != "CLICKED":
            return {"status": "NO_2FA_FIELD"}
        self._type_text_trusted(code)
        return {"status": "FILLED"}

    def submit_2fa(self) -> dict[str, Any]:
        return self.click_trusted_at_element('#wp-submit, button[type="submit"]')

    def verify_dashboard(self) -> dict[str, Any]:
        """Deterministic success proof (LOGIN_SPEC.md §5): URL under
        ``/wp-admin/`` with no login/reauth marker, AND the admin toolbar DOM
        node present. Both, not one — a URL check alone can be fooled by a
        redirect loop; a DOM check alone can be fooled by a cached partial
        page."""

        url = str(self.evaluate_readonly("location.href") or "")
        url_ok = (
            "/wp-admin/" in url
            and "wp-login.php" not in url
            and "action=login" not in url
            and "reauth=1" not in url
        )
        dom_ok = self.has_dashboard_marker()
        return {"ok": url_ok and dom_ok, "url_ok": url_ok, "dom_ok": dom_ok, "url": url}


def _poll(session: Any, *, timeout: float, interval: float, sleep: Callable[[float], None]) -> str:
    """Bounded poll for one of: 'error' | '2fa' | 'dashboard' | 'timeout'.

    Checked in this order every tick — an error banner and a lingering 2FA
    field can coexist on a re-rendered form; error takes priority since it is
    the more specific, actionable signal.
    """

    deadline = time.monotonic() + timeout
    while True:
        if session.has_login_error():
            return "error"
        if session.has_2fa_field():
            return "2fa"
        if session.has_dashboard_marker():
            return "dashboard"
        if time.monotonic() >= deadline:
            return "timeout"
        sleep(interval)


def run_login(
    session: Any,
    *,
    username: str,
    password: str,
    get_2fa_code: Callable[[], str],
    guard: StepGuard,
    run_id: str,
    logger: Any = None,
    poll_timeout: float = 15.0,
    poll_interval: float = 1.0,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """Orchestrate one login attempt. Pure control flow over ``session`` — no
    CDP/network here, so this is the fully unit-tested surface (a duck-typed
    fake session covers every branch; the real CDP mechanics it calls are
    already proven by ``tests/test_submitter.py``'s trusted click/type tests).

    One attempt, no retry, ever (LOGIN_SPEC.md §1/§4): a wrong password or a
    wrong 2FA code is a hard STOP, never a second try in the same run —
    repeated failed logins can lock or flag the account, and this is not a
    place to loop. ``get_2fa_code`` is called exactly once, and only after
    the 2FA field is confirmed visible and ready — never pre-requested.
    """

    def _log(event: str, **fields: Any) -> None:
        if logger is not None:
            logger.log(event, **fields)

    guard.start_task(run_id)
    signature = "login:attempt"
    if not guard.check("login", signature).allowed:
        _log("login_aborted", reason="guard_blocked")
        return {"status": "aborted", "reason": "guard_blocked", "run_id": run_id}

    def _finish(success: bool, status: str, **extra: Any) -> dict[str, Any]:
        guard.record_result("login", signature, success, detail=status)
        if logger is not None:
            logger.log_guard(guard.snapshot())
        _log("login_result", status=status, success=success)
        result = {"status": status, "run_id": run_id, **extra}
        if not success:
            result["aborted"] = status
        return result

    if session.already_logged_in():
        return _finish(True, "already_logged_in")

    session.open_login_page()
    _log("login_page_opened")

    ready = session.login_form_ready()
    if not (ready.get("user") and ready.get("pass") and ready.get("submit")):
        return _finish(False, "LOGIN_FORM_UNREADABLE", ready=ready)

    session.fill_username(username)
    session.fill_password(password)
    _log("credentials_filled")  # never the values, by construction
    session.submit_login()

    state = _poll(session, timeout=poll_timeout, interval=poll_interval, sleep=sleep)
    _log("post_submit_state", state=state)

    if state == "error":
        return _finish(False, "LOGIN_REJECTED")
    if state == "timeout":
        return _finish(False, "LOGIN_TIMEOUT")

    if state == "2fa":
        _log("2fa_field_visible")
        code = get_2fa_code()
        if not code:
            return _finish(False, "2FA_EMPTY_CODE")
        session.fill_2fa_code(code)
        _log("2fa_submitted")  # never the code
        session.submit_2fa()
        state2 = _poll(session, timeout=poll_timeout, interval=poll_interval, sleep=sleep)
        _log("post_2fa_state", state=state2)
        if state2 != "dashboard":
            return _finish(False, "2FA_REJECTED")

    verdict = session.verify_dashboard()
    if not verdict.get("ok"):
        return _finish(False, "LOGIN_UNVERIFIED", verdict=verdict)
    return _finish(True, "logged_in")

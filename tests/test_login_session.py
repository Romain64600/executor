"""Tests for src/login_session.py (LOGIN_SPEC.md, Stage 0b).

``run_login`` is the fully unit-tested surface — pure control flow over a
duck-typed fake session, no CDP/network (mirrors test_submitter.py's
FakeSubmitSession style). The CDP mechanics ``LoginSession`` reuses
(trusted click/type) are already proven by test_submitter.py's trusted
click/type tests, so they are not re-tested here.
"""

import json
import unittest

from src.login_session import run_login
from src.step_guard import StepGuard


class FakeLoginSession:
    """Scripted fake implementing LoginSession's public surface.

    ``states`` are poll-ROUND outcomes, not per-check values: round 0 is what
    every ``has_*`` read reflects after ``submit_login()``, round 1 after
    ``submit_2fa()`` (only ``submit_2fa`` advances the round — a poll tick
    calls up to three ``has_*`` methods and must see a consistent state
    across all of them, not one that shifts mid-tick).
    """

    def __init__(self, *, already_logged_in=False, form_ready=None, states=("dashboard",),
                 verify_ok=True):
        self.already_logged_in_value = already_logged_in
        self.form_ready_value = form_ready if form_ready is not None else {
            "user": True, "pass": True, "submit": True,
        }
        self._states = list(states)
        self._round = 0
        self.verify_ok = verify_ok
        self.calls: list[str] = []

    def already_logged_in(self):
        self.calls.append("already_logged_in")
        return self.already_logged_in_value

    def open_login_page(self):
        self.calls.append("open_login_page")

    def login_form_ready(self):
        self.calls.append("login_form_ready")
        return self.form_ready_value

    def fill_username(self, username):
        self.calls.append(f"fill_username:{username}")
        return {"status": "FILLED"}

    def fill_password(self, password):
        self.calls.append("fill_password")  # never log/assert the value itself
        return {"status": "FILLED"}

    def submit_login(self):
        self.calls.append("submit_login")
        return {"status": "CLICKED"}

    def _state(self):
        idx = min(self._round, len(self._states) - 1)
        return self._states[idx]

    def has_login_error(self):
        return self._state() == "error"

    def has_2fa_field(self):
        return self._state() == "2fa"

    def has_dashboard_marker(self):
        return self._state() == "dashboard"

    def fill_2fa_code(self, code):
        self.calls.append(f"fill_2fa_code:{code}")
        return {"status": "FILLED"}

    def submit_2fa(self):
        self.calls.append("submit_2fa")
        self._round += 1
        return {"status": "CLICKED"}

    def verify_dashboard(self):
        self.calls.append("verify_dashboard")
        return {"ok": self.verify_ok, "url_ok": self.verify_ok, "dom_ok": self.verify_ok,
                 "url": "https://x/wp-admin/"}


def _guard():
    return StepGuard(max_attempts_per_signature=1, max_failures_per_signature=1,
                      max_consecutive_failures=1)


def _run(session, *, code="123456", guard=None, run_id="login-test", **kwargs):
    calls = {"n": 0}

    def get_2fa_code():
        calls["n"] += 1
        return code

    result = run_login(
        session, username="romain", password="hunter2", get_2fa_code=get_2fa_code,
        guard=guard or _guard(), run_id=run_id, sleep=lambda s: None, **kwargs,
    )
    return result, calls["n"]


class RunLoginTests(unittest.TestCase):
    def test_already_logged_in_is_a_noop_success(self):
        session = FakeLoginSession(already_logged_in=True)
        result, code_calls = _run(session)
        self.assertEqual(result["status"], "already_logged_in")
        self.assertEqual(code_calls, 0)
        self.assertNotIn("open_login_page", session.calls)

    def test_happy_path_no_2fa_required(self):
        session = FakeLoginSession(states=["dashboard"])
        result, code_calls = _run(session)
        self.assertEqual(result["status"], "logged_in")
        self.assertEqual(code_calls, 0)
        self.assertIn("verify_dashboard", session.calls)

    def test_happy_path_with_2fa(self):
        session = FakeLoginSession(states=["2fa", "dashboard"])
        result, code_calls = _run(session, code="654321")
        self.assertEqual(result["status"], "logged_in")
        self.assertEqual(code_calls, 1)
        self.assertIn("fill_2fa_code:654321", session.calls)

    def test_2fa_code_never_requested_before_field_visible(self):
        # Bad password path: state resolves straight to "error", never "2fa".
        session = FakeLoginSession(states=["error"])
        result, code_calls = _run(session)
        self.assertEqual(result["status"], "LOGIN_REJECTED")
        self.assertEqual(code_calls, 0, "must never request a 2FA code before the field is visible")

    def test_login_form_unreadable_stops_before_typing_credentials(self):
        session = FakeLoginSession(form_ready={"user": True, "pass": False, "submit": True})
        result, code_calls = _run(session)
        self.assertEqual(result["status"], "LOGIN_FORM_UNREADABLE")
        self.assertEqual(code_calls, 0)
        self.assertNotIn("fill_password", session.calls)

    def test_bad_password_is_rejected_no_retry(self):
        session = FakeLoginSession(states=["error"])
        result, _ = _run(session)
        self.assertEqual(result["status"], "LOGIN_REJECTED")
        self.assertEqual(session.calls.count("submit_login"), 1)

    def test_timeout_waiting_for_post_submit_state(self):
        # "timeout" matches none of error/2fa/dashboard, so the real deadline
        # in _poll fires — keep it tiny so the test doesn't actually wait 15s.
        session = FakeLoginSession(states=["timeout"])
        result, code_calls = _run(session, poll_timeout=0.02, poll_interval=0.005)
        self.assertEqual(result["status"], "LOGIN_TIMEOUT")
        self.assertEqual(code_calls, 0)

    def test_wrong_2fa_code_is_rejected_no_second_attempt(self):
        # 2FA field visible, code entered, but the second poll never reaches
        # dashboard (re-rendered 2FA form, no explicit #login_error).
        session = FakeLoginSession(states=["2fa", "2fa"])
        result, code_calls = _run(session)
        self.assertEqual(result["status"], "2FA_REJECTED")
        self.assertEqual(code_calls, 1, "a wrong code must never trigger a second prompt")

    def test_empty_2fa_code_aborts_without_filling_it(self):
        session = FakeLoginSession(states=["2fa"])
        result, code_calls = _run(session, code="")
        self.assertEqual(result["status"], "2FA_EMPTY_CODE")
        self.assertEqual(code_calls, 1)
        self.assertNotIn("fill_2fa_code:", "".join(session.calls))

    def test_verify_dashboard_false_after_apparent_success_is_unverified(self):
        session = FakeLoginSession(states=["dashboard"], verify_ok=False)
        result, _ = _run(session)
        self.assertEqual(result["status"], "LOGIN_UNVERIFIED")

    def test_same_run_id_second_call_is_guard_blocked(self):
        # One attempt, no retry, ever — even a second orchestrated call with
        # the same task/signature must not re-attempt.
        guard = _guard()
        session1 = FakeLoginSession(states=["error"])
        result1, _ = _run(session1, guard=guard, run_id="login-fixed")
        self.assertEqual(result1["status"], "LOGIN_REJECTED")

        session2 = FakeLoginSession(states=["dashboard"])
        result2, code_calls2 = _run(session2, guard=guard, run_id="login-fixed")
        self.assertEqual(result2["status"], "aborted")
        self.assertEqual(result2["reason"], "guard_blocked")
        self.assertEqual(code_calls2, 0)
        self.assertEqual(session2.calls, [], "a blocked attempt must not touch the session at all")

    def test_credentials_never_appear_in_logged_events(self):
        class _RecordingLogger:
            def __init__(self):
                self.events = []

            def log(self, event, **fields):
                self.events.append((event, fields))

            def log_guard(self, snapshot):
                pass

        logger = _RecordingLogger()
        session = FakeLoginSession(states=["2fa", "dashboard"])
        run_login(
            session, username="romain", password="hunter2-super-secret",
            get_2fa_code=lambda: "999999", guard=_guard(), run_id="login-log-test",
            logger=logger, sleep=lambda s: None,
        )
        blob = repr(logger.events)
        self.assertNotIn("hunter2-super-secret", blob)
        self.assertNotIn("999999", blob)


if __name__ == "__main__":
    unittest.main()


class LoginPrimitivesTests(unittest.TestCase):
    """TE4 (audit 2026-07-17): the REAL LoginSession primitives — previously
    only the run_login sequencing was tested, against a duck-typed fake; the
    primitives themselves (JS payloads, statuses, the verify_dashboard proof)
    were never executed."""

    def _session(self, eval_results=None, click_status="CLICKED"):
        from src.login_session import LoginSession

        session = LoginSession.__new__(LoginSession)
        results = dict(eval_results or {})
        session._eval_calls = []
        session._typed = []
        session._clicked = []

        def evaluate(js):
            session._eval_calls.append(js)
            for needle, value in results.items():
                if needle in js:
                    return value
            return None

        session._evaluate = evaluate
        session.click_trusted_at_element = lambda selector=None: (
            session._clicked.append(selector) or {"status": click_status}
        )
        session._type_text_trusted = lambda text: (
            session._typed.append(text) or {"chars": len(text)}
        )
        return session

    def test_login_form_ready_parses_field_presence(self):
        session = self._session({"user_login": json.dumps(
            {"user": True, "pass": True, "submit": False})})
        self.assertEqual(session.login_form_ready(),
                         {"user": True, "pass": True, "submit": False})

    def test_login_form_ready_unreadable_is_all_false(self):
        session = self._session({})
        self.assertEqual(session.login_form_ready(),
                         {"user": False, "pass": False, "submit": False})

    def test_fill_username_types_only_after_focus_click(self):
        session = self._session()
        result = session.fill_username("romain")
        self.assertEqual(result, {"status": "FILLED"})
        self.assertEqual(session._clicked, ["#user_login"])
        self.assertEqual(session._typed, ["romain"])

    def test_fill_password_no_field_types_nothing(self):
        # The credential must NEVER be typed into whatever holds focus when
        # the field's own focus click failed.
        session = self._session(click_status="NO_ELEMENT")
        result = session.fill_password("secret")
        self.assertEqual(result, {"status": "NO_PASSWORD_FIELD"})
        self.assertEqual(session._typed, [])

    def test_fill_2fa_no_field_types_nothing(self):
        session = self._session(click_status="NO_ELEMENT")
        result = session.fill_2fa_code("123456")
        self.assertEqual(result, {"status": "NO_2FA_FIELD"})
        self.assertEqual(session._typed, [])

    def test_verify_dashboard_needs_url_and_dom(self):
        # Both proofs, not one (LOGIN_SPEC §5).
        session = self._session({
            "location.href": "https://www.allkeyshop.com/blog/wp-admin/index.php",
            "wpadminbar": True,
        })
        self.assertTrue(session.verify_dashboard()["ok"])

    def test_verify_dashboard_reauth_url_fails_despite_dom(self):
        session = self._session({
            "location.href": "https://www.allkeyshop.com/blog/wp-login.php?reauth=1",
            "wpadminbar": True,
        })
        result = session.verify_dashboard()
        self.assertFalse(result["ok"])
        self.assertFalse(result["url_ok"])
        self.assertTrue(result["dom_ok"])

    def test_verify_dashboard_dom_missing_fails_despite_url(self):
        session = self._session({
            "location.href": "https://www.allkeyshop.com/blog/wp-admin/",
            "wpadminbar": False,
        })
        result = session.verify_dashboard()
        self.assertFalse(result["ok"])
        self.assertTrue(result["url_ok"])
        self.assertFalse(result["dom_ok"])

    def test_2fa_probe_covers_both_plugin_field_names(self):
        from src.login_session import _TWOFA_FIELD_JS

        self.assertIn("authcode", _TWOFA_FIELD_JS)
        self.assertIn("googleotp", _TWOFA_FIELD_JS)

    def test_primitive_js_payloads_are_readonly(self):
        from src.cdp_session import is_readonly_expression
        from src.login_session import (
            _DASHBOARD_MARKER_JS,
            _LOGIN_ERROR_JS,
            _LOGIN_FORM_FIELDS_JS,
            _TWOFA_FIELD_JS,
        )

        for js in (_DASHBOARD_MARKER_JS, _LOGIN_ERROR_JS,
                   _LOGIN_FORM_FIELDS_JS, _TWOFA_FIELD_JS):
            self.assertTrue(is_readonly_expression(js), js)

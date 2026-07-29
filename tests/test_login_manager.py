"""Admin-driven Stage 0b login (LoginManager). Drives the SAME audited
``run_login`` in a background thread with the 2FA code supplied via the web UI.
These tests inject fakes for every side effect (no CDP, no browser, no network)
and lock the security-critical properties:

  * the password comes from the environment, and NEITHER the password NOR the
    2FA code ever appears in the operator-facing status/result;
  * ``get_2fa_code`` is invoked only by the runner (i.e. only after the 2FA
    field is ready) and blocks until the UI posts the code;
  * ONE attempt — a 2FA-wait timeout returns "" (→ the runner's hard STOP), not
    a re-prompt;
  * missing creds / a busy login / a 2FA submit out of turn all fail closed.
"""

import contextlib
import time
import unittest
from unittest import mock

from src.admin.login_manager import LoginError, LoginManager, _scrub


@contextlib.contextmanager
def _noop_lock(*a, **k):
    yield None


class _FakeSession:
    def __init__(self, *a, **k):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


GREEN = {"ok": True, "authoritative": True}
# Distinctive multi-char values so a leak into status/logs is detectable as a raw
# substring (a 1-char secret like "p" is undetectable — review 2026-07-29).
CREDS = {"AKS_WP_USER": "aks-user-xyz", "AKS_WP_PASSWORD": "hunter2-super-secret"}


def _mgr(tmp, runner, *, report=GREEN):
    return LoginManager(tmp, login_runner=runner, session_factory=_FakeSession,
                        report_fn=lambda **k: report)


def _wait(mgr, state, timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if mgr.status()["state"] == state:
            return True
        time.sleep(0.01)
    return False


class LoginManagerTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        from pathlib import Path
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        # browser_lock + RunLogger are the two real side effects in _run — stub them.
        p1 = mock.patch("src.admin.login_manager.browser_lock", _noop_lock)
        p2 = mock.patch("src.admin.login_manager.RunLogger", lambda *a, **k: mock.Mock())
        p1.start(); p2.start()
        self.addCleanup(p1.stop); self.addCleanup(p2.stop)

    def _runner_2fa(self, capture):
        def runner(session, *, username, password, get_2fa_code, guard, run_id, logger, **kw):
            capture["user"] = username
            capture["pass"] = password
            code = get_2fa_code()               # sets awaiting_2fa, blocks for the UI
            capture["code"] = code
            if code == "GOOD":
                return {"status": "logged_in", "run_id": run_id}
            if not code:
                return {"status": "2FA_EMPTY_CODE", "run_id": run_id, "aborted": "2FA_EMPTY_CODE"}
            return {"status": "2FA_REJECTED", "run_id": run_id, "aborted": "2FA_REJECTED"}
        return runner

    def test_full_success_with_2fa_from_ui(self):
        cap = {}
        mgr = _mgr(self.root, self._runner_2fa(cap))
        with mock.patch.dict("os.environ", CREDS):
            mgr.start(by="Romain")
        self.assertTrue(_wait(mgr, "awaiting_2fa"))
        self.assertTrue(mgr.status()["awaiting_2fa"])
        mgr.submit_2fa("GOOD")
        self.assertTrue(_wait(mgr, "done"))
        self.assertEqual(mgr.status()["result"]["status"], "logged_in")
        self.assertEqual(cap["user"], "aks-user-xyz")   # runner got the env creds
        self.assertEqual(cap["code"], "GOOD")

    def test_password_and_code_never_in_status(self):
        cap = {}
        mgr = _mgr(self.root, self._runner_2fa(cap))
        with mock.patch.dict("os.environ", CREDS):
            mgr.start(by="Romain")
        self.assertTrue(_wait(mgr, "awaiting_2fa"))
        mgr.submit_2fa("SECRET-CODE-123")
        self.assertTrue(_wait(mgr, "done"))
        blob = repr(mgr.status())
        self.assertNotIn("SECRET-CODE-123", blob)       # the 2FA code never surfaces
        self.assertNotIn("hunter2-super-secret", blob)  # nor the password value (raw substring)

    def test_missing_creds_fails_closed_before_any_browser_action(self):
        called = {"ran": False}

        def runner(*a, **k):
            called["ran"] = True
            return {"status": "logged_in"}

        mgr = _mgr(self.root, runner)
        with mock.patch.dict("os.environ", {"AKS_WP_USER": "", "AKS_WP_PASSWORD": ""}):
            with self.assertRaises(LoginError) as ctx:
                mgr.start(by="Romain")
        self.assertEqual(ctx.exception.code, "no_creds")
        self.assertFalse(called["ran"])             # the runner (browser) never started
        self.assertEqual(mgr.status()["state"], "done")

    def test_invariants_red_aborts_before_any_browser_action(self):
        # LOGIN_SPEC §5: invariants not green/authoritative → login refused BEFORE
        # the browser is touched (the runner never runs).
        called = {"ran": False}

        def runner(*a, **k):
            called["ran"] = True
            return {"status": "logged_in"}

        mgr = _mgr(self.root, runner, report={"ok": False, "authoritative": False})
        with mock.patch.dict("os.environ", CREDS):
            mgr.start(by="Romain")
        self.assertTrue(_wait(mgr, "done"))
        self.assertEqual(mgr.status()["result"]["status"], "aborted")
        self.assertIn("invariants", mgr.status()["result"]["reason"])
        self.assertFalse(called["ran"])                 # browser/login never started

    def test_already_logged_in_skips_2fa(self):
        def runner(session, *, get_2fa_code, run_id, **kw):
            return {"status": "already_logged_in", "run_id": run_id}   # never asks for 2FA

        mgr = _mgr(self.root, runner)
        with mock.patch.dict("os.environ", CREDS):
            mgr.start(by="Romain")
        self.assertTrue(_wait(mgr, "done"))
        self.assertEqual(mgr.status()["result"]["status"], "already_logged_in")

    def test_2fa_timeout_is_one_attempt_stop(self):
        cap = {}
        mgr = _mgr(self.root, self._runner_2fa(cap))
        mgr.TWOFA_WAIT_S = 0.2                       # don't wait 3 min in a test
        with mock.patch.dict("os.environ", CREDS):
            mgr.start(by="Romain")
        self.assertTrue(_wait(mgr, "awaiting_2fa"))
        # never submit a code → the wait times out → "" → runner hard-STOPs
        self.assertTrue(_wait(mgr, "done", timeout=3.0))
        self.assertEqual(cap["code"], "")
        self.assertEqual(mgr.status()["result"]["status"], "2FA_EMPTY_CODE")

    def test_submit_2fa_out_of_turn_refused(self):
        mgr = _mgr(self.root, self._runner_2fa({}))
        with self.assertRaises(LoginError) as ctx:
            mgr.submit_2fa("123456")                # nothing running
        self.assertEqual(ctx.exception.code, "no_2fa_wait")

    def test_start_while_running_refused(self):
        cap = {}
        mgr = _mgr(self.root, self._runner_2fa(cap))
        with mock.patch.dict("os.environ", CREDS):
            mgr.start(by="Romain")
            self.assertTrue(_wait(mgr, "awaiting_2fa"))
            with self.assertRaises(LoginError) as ctx:
                mgr.start(by="Romain")
            self.assertEqual(ctx.exception.code, "login_busy")
        mgr.submit_2fa("GOOD")                       # let the thread finish cleanly
        _wait(mgr, "done")

    def test_browser_busy_aborts_cleanly(self):
        from src.browser_lock import BrowserBusyError

        def runner(*a, **k):
            return {"status": "logged_in"}

        mgr = _mgr(self.root, runner)
        with mock.patch("src.admin.login_manager.browser_lock",
                        side_effect=BrowserBusyError("submit en cours")):
            with mock.patch.dict("os.environ", CREDS):
                mgr.start(by="Romain")
            self.assertTrue(_wait(mgr, "done"))
        self.assertEqual(mgr.status()["result"]["status"], "aborted")
        self.assertIn("occupé", mgr.status()["result"]["reason"])


class ScrubTests(unittest.TestCase):
    def test_scrub_drops_secret_keys(self):
        out = _scrub({"status": "logged_in", "password": "x", "code": "123",
                      "otp": "y", "nested": {"authcode": "z", "ok": True}})
        self.assertEqual(out, {"status": "logged_in", "nested": {"ok": True}})


if __name__ == "__main__":
    unittest.main()

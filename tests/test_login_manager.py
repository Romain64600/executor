"""Cookie-transfer re-auth (LoginManager) — AKS is social-login only, so the
authenticated session is injected as cookies exported from the operator's
browser. These tests inject fakes for every side effect (no CDP, no browser) and
lock the security-critical properties:

  * cookie VALUES are never surfaced in status/result (only names/counts/flags);
  * only allkeyshop.com cookies are injected (a foreign-domain cookie dropped);
  * both a Cookie-Editor JSON export and a DevTools tab-table copy parse;
  * fail-closed: no valid cookies / red invariants / browser busy → clean abort
    (nothing injected), and a concurrent re-auth is refused.
"""

import contextlib
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from src.admin.login_manager import LoginError, LoginManager, normalize_cookies, _scrub


@contextlib.contextmanager
def _noop_lock(*a, **k):
    yield None


class _FakeSession:
    def __init__(self, verdict, captured=None):
        self._verdict = verdict
        self._captured = captured

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def set_cookies(self, cookies):
        if self._captured is not None:
            self._captured.append(cookies)
        return {"ack": True}

    def navigate(self, url, settle=None):
        pass

    def verify_dashboard(self):
        return self._verdict


GREEN = {"ok": True, "authoritative": True}
JSON_COOKIES = (
    '[{"name":"wordpress_logged_in_abc","value":"SECRET-COOKIE-VALUE-XYZ",'
    '"domain":".allkeyshop.com","path":"/","secure":true,"httpOnly":true,'
    '"sameSite":"no_restriction","expirationDate":1900000000},'
    '{"name":"_ga","value":"analytics","domain":".google.com","path":"/"}]'
)
TABLE_COOKIES = (
    "wordpress_logged_in_abc\tSECRET-COOKIE-VALUE-XYZ\t.allkeyshop.com\t/\tSession\t80\t\t\t✓\tNone\tMedium\n"
    "_ga\tGA1.1\t.google.com\t/\t2027-01-01\t20\tMedium"
)


def _mgr(root, *, verdict=None, report=GREEN, captured=None):
    factory = lambda endpoint: _FakeSession(verdict or {"ok": True, "url_ok": True, "dom_ok": True}, captured)
    return LoginManager(root, session_factory=factory, report_fn=lambda **k: report,
                        clock=lambda: 1.0)


class NormalizeCookiesTests(unittest.TestCase):
    def test_json_export_maps_to_cdp_and_filters_domain(self):
        cookies, stats = normalize_cookies(JSON_COOKIES)
        self.assertEqual(len(cookies), 1)                      # google cookie dropped
        c = cookies[0]
        self.assertEqual(c["name"], "wordpress_logged_in_abc")
        self.assertEqual(c["value"], "SECRET-COOKIE-VALUE-XYZ")
        self.assertEqual(c["domain"], ".allkeyshop.com")
        self.assertTrue(c["httpOnly"] and c["secure"])
        self.assertEqual(c["sameSite"], "None")               # no_restriction → None
        self.assertEqual(c["expires"], 1900000000.0)
        self.assertEqual(stats["accepted"], 1)
        self.assertEqual(stats["skipped"], 1)

    def test_devtools_table_copy_parses(self):
        cookies, stats = normalize_cookies(TABLE_COOKIES)
        self.assertEqual([c["name"] for c in cookies], ["wordpress_logged_in_abc"])
        c = cookies[0]
        self.assertEqual(c["value"], "SECRET-COOKIE-VALUE-XYZ")
        self.assertEqual(c["domain"], ".allkeyshop.com")
        self.assertTrue(c["httpOnly"])                        # ✓ detected

    def test_empty_and_bad_json_raise(self):
        with self.assertRaises(LoginError) as e1:
            normalize_cookies("   ")
        self.assertEqual(e1.exception.code, "no_cookies")
        with self.assertRaises(LoginError) as e2:
            normalize_cookies("[ not json ")
        self.assertEqual(e2.exception.code, "bad_cookies_json")

    def test_no_aks_cookies_returns_empty(self):
        cookies, stats = normalize_cookies('[{"name":"x","value":"y","domain":".google.com"}]')
        self.assertEqual(cookies, [])
        self.assertEqual(stats["accepted"], 0)

    def test_lookalike_domains_are_dropped(self):
        # A substring filter would let these through and inject a cookie for an
        # attacker domain (security review 2026-07-29) — must be host/suffix match.
        for bad in ("allkeyshop.com.evil.com", "evilallkeyshop.com", "myallkeyshop.com",
                    "notallkeyshop.com.attacker.net", ".allkeyshop.com.evil.com"):
            cookies, _ = normalize_cookies(
                [{"name": "wordpress_logged_in_x", "value": "ATTACKER", "domain": bad}])
            self.assertEqual(cookies, [], f"lookalike {bad!r} must be dropped")

    def test_real_aks_domains_accepted(self):
        for good in ("allkeyshop.com", ".allkeyshop.com", "www.allkeyshop.com"):
            cookies, _ = normalize_cookies(
                [{"name": "wordpress_sec_x", "value": "v", "domain": good}])
            self.assertEqual(len(cookies), 1, f"{good!r} must be accepted")

    def test_accepts_list_of_dicts_from_form_fields(self):
        # The field-based UI sends a LIST directly (name+value+domain per row).
        cookies, stats = normalize_cookies([
            {"name": "wordpress_sec_x", "value": "v1", "domain": ".allkeyshop.com",
             "path": "/", "secure": True, "httpOnly": True},
            {"name": "junk", "value": "v2", "domain": ".google.com"},
        ])
        self.assertEqual([c["name"] for c in cookies], ["wordpress_sec_x"])
        self.assertEqual(cookies[0]["value"], "v1")
        self.assertEqual(stats["accepted"], 1)


class ApplyCookiesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        p = mock.patch("src.admin.login_manager.browser_lock", _noop_lock)
        p.start(); self.addCleanup(p.stop)

    def test_success_injects_and_verifies(self):
        captured = []
        mgr = _mgr(self.root, verdict={"ok": True, "url_ok": True, "dom_ok": True}, captured=captured)
        res = mgr.apply_cookies(JSON_COOKIES, by="Romain")
        self.assertEqual(res["status"], "logged_in")
        self.assertEqual(res["cookies_injected"], 1)
        self.assertEqual(captured[0][0]["name"], "wordpress_logged_in_abc")   # actually injected

    def test_cookie_values_never_in_status(self):
        mgr = _mgr(self.root, captured=[])
        mgr.apply_cookies(JSON_COOKIES, by="Romain")
        blob = repr(mgr.status())
        self.assertNotIn("SECRET-COOKIE-VALUE-XYZ", blob)     # the cookie value never surfaces

    def test_not_logged_in_when_dashboard_unverified(self):
        mgr = _mgr(self.root, verdict={"ok": False, "url_ok": True, "dom_ok": False})
        res = mgr.apply_cookies(JSON_COOKIES, by="Romain")
        self.assertEqual(res["status"], "not_logged_in")

    def test_no_valid_cookies_aborts_without_browser(self):
        captured = []
        mgr = _mgr(self.root, captured=captured)
        res = mgr.apply_cookies('[{"name":"_ga","value":"z","domain":".google.com"}]', by="Romain")
        self.assertEqual(res["status"], "aborted")
        self.assertEqual(captured, [])                        # nothing injected
        self.assertIn("aucun cookie", res["reason"])

    def test_invariants_red_aborts_without_injection(self):
        captured = []
        mgr = _mgr(self.root, report={"ok": False, "authoritative": False}, captured=captured)
        res = mgr.apply_cookies(JSON_COOKIES, by="Romain")
        self.assertEqual(res["status"], "aborted")
        self.assertIn("invariants", res["reason"])
        self.assertEqual(captured, [])

    def test_browser_busy_aborts_cleanly(self):
        from src.browser_lock import BrowserBusyError
        mgr = _mgr(self.root)
        with mock.patch("src.admin.login_manager.browser_lock",
                        side_effect=BrowserBusyError("submit en cours")):
            res = mgr.apply_cookies(JSON_COOKIES, by="Romain")
        self.assertEqual(res["status"], "aborted")
        self.assertIn("occupé", res["reason"])

    def test_bad_json_raises_login_error(self):
        mgr = _mgr(self.root)
        with self.assertRaises(LoginError) as ctx:
            mgr.apply_cookies("[ not json", by="Romain")
        self.assertEqual(ctx.exception.code, "bad_cookies_json")
        self.assertFalse(mgr.status()["busy"])                # busy released on the raise

    def test_concurrent_reauth_refused(self):
        mgr = _mgr(self.root)
        mgr._busy = True
        with self.assertRaises(LoginError) as ctx:
            mgr.apply_cookies(JSON_COOKIES, by="Romain")
        self.assertEqual(ctx.exception.code, "login_busy")

    def test_p3_8_injection_error_reason_never_leaks_exception_message(self):
        # P3-8 (audit 2026-09-02): a cookie-injection exception must NOT put its
        # message (which could echo a cookie value) into the aborted reason returned
        # to /api/login/cookies and re-served by /api/login/status. Only the type.
        SECRET = "SECRET-COOKIE-VALUE-XYZ"

        class _BoomSession(_FakeSession):
            def set_cookies(self, cookies):
                raise RuntimeError(f"CDP Network.setCookies rejected value={SECRET}")

        mgr = LoginManager(self.root, session_factory=lambda endpoint: _BoomSession({"ok": True}),
                           report_fn=lambda **k: GREEN, clock=lambda: 1.0)
        res = mgr.apply_cookies(JSON_COOKIES, by="Romain")
        self.assertEqual(res["status"], "aborted")
        self.assertNotIn(SECRET, res["reason"])           # the value never reaches the wire
        self.assertNotIn("value=", res["reason"])
        self.assertIn("RuntimeError", res["reason"])      # the type is kept to categorize


class VerifyDashboardTests(unittest.TestCase):
    """The kept LoginSession.verify_dashboard — session proof needs BOTH the
    wp-admin URL and the admin toolbar node (post-cookie-injection check)."""

    def _session(self, href, has_bar):
        from src.login_session import LoginSession
        s = LoginSession.__new__(LoginSession)   # no CDP __init__
        s.evaluate_readonly = lambda js: (href if "location.href" in js else has_bar)
        return s

    def test_logged_in_needs_url_and_dom(self):
        v = self._session("https://www.allkeyshop.com/blog/wp-admin/index.php", "1").verify_dashboard()
        self.assertTrue(v["ok"] and v["url_ok"] and v["dom_ok"])

    def test_login_page_url_not_ok(self):
        self.assertFalse(self._session("https://www.allkeyshop.com/blog/wp-login.php", "1").verify_dashboard()["ok"])

    def test_no_toolbar_not_ok(self):
        v = self._session("https://www.allkeyshop.com/blog/wp-admin/", "").verify_dashboard()
        self.assertFalse(v["ok"])
        self.assertTrue(v["url_ok"])
        self.assertFalse(v["dom_ok"])


class ScrubTests(unittest.TestCase):
    def test_scrub_drops_secret_keys(self):
        out = _scrub({"status": "logged_in", "value": "x", "cookies": [1],
                      "nested": {"value": "y", "ok": True}})
        self.assertEqual(out, {"status": "logged_in", "nested": {"ok": True}})


if __name__ == "__main__":
    unittest.main()

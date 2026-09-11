import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from urllib.error import HTTPError, URLError

from src.aks_env import (
    AKS_STAFF_UA,
    OFFICIAL_CDP_ENDPOINT,
    REQUIRED_USER_AGENT,
    checks_to_dict,
    classify_environment,
    current_environment,
    http_get,
    http_head_status,
    list_openvpn_pids,
    parse_cdp_version_payload,
    validate_aks_direct_status,
    validate_cdp_version_shape,
    validate_no_openvpn,
    validate_official_cdp_endpoint,
    validate_required_user_agent,
)


class _FakeResp:
    """Minimal context-manager stand-in for an HTTP response."""

    def __init__(self, status, body=b"", headers=None):
        self.status = status
        self._body = body
        self.headers = headers or {}

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def valid_cdp_payload():
    return {
        "Browser": "Chrome/149.0.0.0",
        "Protocol-Version": "1.3",
        "User-Agent": REQUIRED_USER_AGENT,
        "V8-Version": "14.9.0",
        "WebKit-Version": "537.36",
        "webSocketDebuggerUrl": "ws://172.17.0.1:9223/devtools/browser/example",
    }


class AksEnvTests(unittest.TestCase):
    def test_parse_cdp_version_payload_accepts_json_string(self):
        payload = valid_cdp_payload()

        parsed = parse_cdp_version_payload(json.dumps(payload))

        self.assertEqual(parsed, payload)

    def test_parse_cdp_version_payload_rejects_non_object_json(self):
        with self.assertRaisesRegex(ValueError, "JSON object"):
            parse_cdp_version_payload("[]")

    def test_validate_official_cdp_endpoint_accepts_only_docker_bridge_proxy(self):
        self.assertTrue(validate_official_cdp_endpoint(OFFICIAL_CDP_ENDPOINT).ok)

        result = validate_official_cdp_endpoint("http://127.0.0.1:9222/json/version")

        self.assertFalse(result.ok)
        self.assertEqual(result.data["expected"], OFFICIAL_CDP_ENDPOINT)

    def test_validate_required_user_agent_requires_exact_value(self):
        self.assertTrue(validate_required_user_agent(valid_cdp_payload()).ok)

        payload = valid_cdp_payload()
        payload["User-Agent"] = "Mozilla/5.0 Different"

        result = validate_required_user_agent(payload)

        self.assertFalse(result.ok)
        self.assertEqual(result.data["actual"], "Mozilla/5.0 Different")

    def test_validate_cdp_version_shape_requires_metadata_fields(self):
        self.assertTrue(validate_cdp_version_shape(valid_cdp_payload()).ok)

        payload = valid_cdp_payload()
        del payload["webSocketDebuggerUrl"]

        result = validate_cdp_version_shape(payload)

        self.assertFalse(result.ok)
        self.assertEqual(result.data["missing"], ["webSocketDebuggerUrl"])

    def test_validate_aks_direct_status_accepts_only_200_301_302(self):
        for good in (200, 301, 302):
            self.assertTrue(validate_aks_direct_status(good).ok, good)
        for bad in (204, 307, 308, 400, 404, 500, None):
            self.assertFalse(validate_aks_direct_status(bad).ok, bad)

    def test_checks_to_dict_fails_closed_when_any_check_fails(self):
        checks = [validate_aks_direct_status(200), validate_official_cdp_endpoint("bad")]

        result = checks_to_dict(checks)

        self.assertFalse(result["ok"])
        self.assertEqual(len(result["checks"]), 2)


class _FakeCompleted:
    def __init__(self, returncode, stdout=""):
        self.returncode = returncode
        self.stdout = stdout


class OpenVpnCheckTests(unittest.TestCase):
    def test_no_pids_passes(self):
        result = validate_no_openvpn([])

        self.assertTrue(result.ok)
        self.assertEqual(result.name, "no_openvpn_process")
        self.assertEqual(result.data["pids"], [])

    def test_running_openvpn_fails(self):
        result = validate_no_openvpn(["1819"])

        self.assertFalse(result.ok)
        self.assertIn("VPN forbidden", result.detail)
        self.assertEqual(result.data["pids"], ["1819"])

    def test_unknown_state_fails_closed(self):
        result = validate_no_openvpn(None)

        self.assertFalse(result.ok)
        self.assertIn("fail closed", result.detail)

    def test_list_pids_parses_pgrep_matches(self):
        with mock.patch(
            "src.aks_env.subprocess.run",
            return_value=_FakeCompleted(0, "1819\n2001\n"),
        ):
            self.assertEqual(list_openvpn_pids(), ["1819", "2001"])

    def test_list_pids_empty_on_pgrep_no_match(self):
        with mock.patch("src.aks_env.subprocess.run", return_value=_FakeCompleted(1)):
            self.assertEqual(list_openvpn_pids(), [])

    def test_list_pids_none_on_pgrep_error(self):
        with mock.patch("src.aks_env.subprocess.run", return_value=_FakeCompleted(2)):
            self.assertIsNone(list_openvpn_pids())

    def test_list_pids_none_when_pgrep_missing(self):
        with mock.patch(
            "src.aks_env.subprocess.run", side_effect=FileNotFoundError("pgrep")
        ):
            self.assertIsNone(list_openvpn_pids())


class ClassifyEnvironmentTests(unittest.TestCase):
    def test_linux_with_target_marker_is_authoritative(self):
        env = classify_environment(
            system="Linux", target_marker_present=True, hostname="vps-debian"
        )

        self.assertTrue(env["is_target"])
        self.assertTrue(env["authoritative"])
        self.assertEqual(env["hostname"], "vps-debian")

    def test_macos_is_not_authoritative(self):
        env = classify_environment(
            system="Darwin", target_marker_present=False, hostname="MacBook-Air"
        )

        self.assertFalse(env["is_target"])
        self.assertFalse(env["authoritative"])
        self.assertIn("NOT", env["note"])

    def test_linux_without_marker_is_not_authoritative(self):
        # Debian-derived sandbox (Ubuntu CI) must NOT be treated as the VPS.
        env = classify_environment(
            system="Linux", target_marker_present=False, hostname="ubuntu-sandbox"
        )

        self.assertFalse(env["authoritative"])


class StaffUaPolicyTests(unittest.TestCase):
    """Audit #4 (Romain, 2026-07-08): AKS/Staff is allkeyshop.com-only — every
    other host keeps the required Chrome UA. The guard sits BEFORE any network
    IO, so the refusal path needs no mocking."""

    def test_staff_ua_refused_on_non_aks_hosts(self):
        for url in (
            "https://www.g2a.com/x",
            "https://k4g.com/y",
            "https://allkeyshop.com.evil.tld/z",  # suffix spoof
        ):
            with self.assertRaises(ValueError, msg=url):
                http_get(url, user_agent=AKS_STAFF_UA)

    def test_staff_ua_allowed_on_aks_hosts(self):
        for url in ("https://www.allkeyshop.com/blog/x", "https://allkeyshop.com/y"):
            opener = mock.Mock(return_value=_FakeResp(200, b"ok"))
            with mock.patch("src.aks_env._http_open", opener):
                probe = http_get(url, user_agent=AKS_STAFF_UA)
            self.assertTrue(probe.ok, url)
            request = opener.call_args[0][0]
            self.assertEqual(request.get_header("User-agent"), AKS_STAFF_UA)

    def test_default_ua_unaffected_on_any_host(self):
        opener = mock.Mock(return_value=_FakeResp(200, b"ok"))
        with mock.patch("src.aks_env._http_open", opener):
            probe = http_get("https://www.g2a.com/x")
        self.assertTrue(probe.ok)
        request = opener.call_args[0][0]
        self.assertEqual(request.get_header("User-agent"), REQUIRED_USER_AGENT)

    def test_default_ua_towards_allkeyshop_is_the_staff_ua(self):
        # 2026-09-11: the browser UA over HTTP got the VPS IP banned by the AKS anti-bot;
        # every request to an allkeyshop.com host defaults to AKS/Staff (host-locked).
        opener = mock.Mock(return_value=_FakeResp(200, b"ok"))
        with mock.patch("src.aks_env._http_open", opener):
            http_get("https://www.allkeyshop.com/blog/buy-x-cd-key-compare-prices/")
            http_get("https://allkeyshop.com/blog/")
        for call in opener.call_args_list:
            self.assertEqual(call[0][0].get_header("User-agent"), AKS_STAFF_UA)
            self.assertTrue(call[1].get("host_locked"))
        # an explicit browser UA is still honoured when a caller asks for it
        with mock.patch("src.aks_env._http_open", opener):
            http_get("https://www.allkeyshop.com/blog/", user_agent=REQUIRED_USER_AGENT)
        self.assertEqual(opener.call_args[0][0].get_header("User-agent"), REQUIRED_USER_AGENT)

    def test_refused_off_domain_redirect_is_not_ok(self):
        # [40] (Fable re-audit 2026-09-06): a staff-UA probe 3xx-redirected off
        # allkeyshop.com is refused — a fail-closed MISS (ok=False), NEVER a success,
        # even though its 3xx code (302) is in ACCEPTED_AKS_STATUSES (200/301/302).
        import io
        from src.aks_env import StaffUaRedirectRefused
        exc = StaffUaRedirectRefused("https://allkeyshop.com/x", 302,
                                     "off-domain redirect refused", {}, io.BytesIO(b""))
        with mock.patch("src.aks_env._http_open", side_effect=exc):
            probe = http_get("https://www.allkeyshop.com/blog/x", user_agent=AKS_STAFF_UA)
        self.assertFalse(probe.ok)          # refused → fail-closed, not a success
        self.assertEqual(probe.status, 302)


class HttpProbeTests(unittest.TestCase):
    def test_http_get_success_2xx(self):
        with mock.patch("src.aks_env._http_open", return_value=_FakeResp(200, b'{"a":1}')):
            probe = http_get("http://example.test")
        self.assertTrue(probe.ok)
        self.assertEqual(probe.status, 200)
        self.assertIn('"a"', probe.body)

    def test_http_get_uses_get_method(self):
        opener = mock.MagicMock(return_value=_FakeResp(200, b"{}"))
        with mock.patch("src.aks_env._http_open", opener):
            http_get("http://example.test")
        self.assertEqual(opener.call_args.args[0].get_method(), "GET")

    def test_http_head_uses_head_method(self):
        opener = mock.MagicMock(return_value=_FakeResp(200, b""))
        with mock.patch("src.aks_env._http_open", opener):
            probe = http_head_status("http://example.test")
        self.assertEqual(opener.call_args.args[0].get_method(), "HEAD")
        self.assertTrue(probe.ok)

    def test_http_get_http_error_maps_status(self):
        err = HTTPError("http://example.test", 404, "Not Found", {}, io.BytesIO(b"nope"))
        with mock.patch("src.aks_env._http_open", side_effect=err):
            probe = http_get("http://example.test")
        self.assertFalse(probe.ok)
        self.assertEqual(probe.status, 404)
        self.assertIsNotNone(probe.error)

    def test_http_get_no_follow_reports_302_which_validator_accepts(self):
        err = HTTPError("http://example.test", 302, "Found", {}, io.BytesIO(b""))
        with mock.patch("src.aks_env._http_open", side_effect=err):
            probe = http_get("http://example.test", follow_redirects=False)
        self.assertEqual(probe.status, 302)
        self.assertTrue(validate_aks_direct_status(probe.status).ok)

    def test_http_get_url_error_status_none(self):
        with mock.patch("src.aks_env._http_open", side_effect=URLError("down")):
            probe = http_get("http://example.test")
        self.assertFalse(probe.ok)
        self.assertIsNone(probe.status)

    def test_http_get_timeout_status_none(self):
        with mock.patch("src.aks_env._http_open", side_effect=TimeoutError("slow")):
            probe = http_get("http://example.test")
        self.assertFalse(probe.ok)
        self.assertIsNone(probe.status)

    def test_http_get_remote_disconnected_fails_closed(self):
        # urllib does not wrap getresponse() errors in URLError; seen live
        # 2026-07-07 when the 9223 proxy was up but host Chrome 9222 was down.
        from http.client import RemoteDisconnected

        exc = RemoteDisconnected("Remote end closed connection without response")
        with mock.patch("src.aks_env._http_open", side_effect=exc):
            probe = http_get("http://example.test")
        self.assertFalse(probe.ok)
        self.assertIsNone(probe.status)
        self.assertIn("RemoteDisconnected", probe.error)

    def test_http_get_connection_reset_fails_closed(self):
        with mock.patch("src.aks_env._http_open", side_effect=ConnectionResetError(104, "reset")):
            probe = http_get("http://example.test")
        self.assertFalse(probe.ok)
        self.assertIsNone(probe.status)


import src.aks_env as _aks_env_mod

_REAL_SESSION = _aks_env_mod._SESSION   # None on a stdlib-only box


class _FakeReqResp:
    """Minimal stand-in for a ``requests.Response`` (keep-alive backend)."""

    def __init__(self, status_code, content=b"", headers=None, reason="OK"):
        self.status_code = status_code
        self.content = content
        self.headers = headers or {}
        self.reason = reason
        self.closed = False

    def close(self):
        self.closed = True


class KeepAliveBackendTests(unittest.TestCase):
    """The optional requests keep-alive backend honors the SAME `_http_open` contract as
    the urllib fallback: HTTPResponse-like on 2xx, HTTPError on non-2xx, StaffUaRedirect-
    Refused off-domain (staff), URLError on transport failure (Romain 2026-09-08)."""

    def _open(self, request, *, follow_redirects=True, host_locked=False, side_effect=None,
              return_value=None):
        from urllib.request import Request
        from src.aks_env import _http_open_keepalive
        sess = mock.Mock()
        if side_effect is not None:
            sess.request.side_effect = side_effect
        else:
            sess.request.return_value = return_value
        req = request if isinstance(request, Request) else Request(
            request, method="GET", headers={"User-Agent": AKS_STAFF_UA})
        # Hermetic: the backend mirrors the process proxy env (like urllib); neutralise it.
        with mock.patch("src.aks_env._SESSION", sess), \
                mock.patch.dict("os.environ", {"no_proxy": "*"}):
            return _http_open_keepalive(req, 8, follow_redirects, host_locked), sess

    def test_2xx_returns_readable_response(self):
        resp, _ = self._open("https://www.allkeyshop.com/blog/x",
                             return_value=_FakeReqResp(200, b'{"a":1}', {"X": "y"}))
        with resp as r:
            self.assertEqual(r.status, 200)
            self.assertEqual(r.read(), b'{"a":1}')
            self.assertEqual(dict(r.headers.items()), {"X": "y"})

    def test_non_2xx_raises_httperror_with_status_and_body(self):
        with self.assertRaises(HTTPError) as ctx:
            self._open("https://www.allkeyshop.com/blog/x",
                       return_value=_FakeReqResp(404, b"nope", reason="Not Found"))
        self.assertEqual(ctx.exception.code, 404)
        self.assertEqual(ctx.exception.read(), b"nope")

    def test_no_follow_surfaces_302_as_httperror(self):
        with self.assertRaises(HTTPError) as ctx:
            self._open("https://www.allkeyshop.com/blog/x", follow_redirects=False,
                       return_value=_FakeReqResp(302, b"", {"Location": "/elsewhere"}))
        self.assertEqual(ctx.exception.code, 302)

    def test_host_locked_refuses_off_domain_redirect(self):
        from src.aks_env import StaffUaRedirectRefused
        with self.assertRaises(StaffUaRedirectRefused) as ctx:
            self._open("https://www.allkeyshop.com/blog/x", host_locked=True,
                       return_value=_FakeReqResp(302, b"", {"Location": "https://evil.tld/x"}))
        self.assertEqual(ctx.exception.code, 302)

    def test_host_locked_follows_same_domain_redirect(self):
        resps = [_FakeReqResp(302, b"", {"Location": "https://www.allkeyshop.com/blog/y"}),
                 _FakeReqResp(200, b"ok")]
        resp, sess = self._open("https://www.allkeyshop.com/blog/x", host_locked=True,
                                side_effect=resps)
        with resp as r:
            self.assertEqual(r.status, 200)
        self.assertEqual(sess.request.call_count, 2)
        # Audit 2026-09-09: assert the hop actually PROGRESSED to the Location and the
        # request shape (method, UA header, no auto-follow, timeout, env-blind proxies).
        first, second = sess.request.call_args_list
        self.assertEqual(first.args, ("GET", "https://www.allkeyshop.com/blog/x"))
        self.assertEqual(second.args, ("GET", "https://www.allkeyshop.com/blog/y"))
        for call in (first, second):
            self.assertEqual(call.kwargs["headers"]["User-agent"], AKS_STAFF_UA)
            self.assertFalse(call.kwargs["allow_redirects"])
            self.assertEqual(call.kwargs["timeout"], 8)
            self.assertEqual(call.kwargs["proxies"], {})
        self.assertTrue(resps[0].closed)   # the 3xx hop is closed before moving on
        self.assertTrue(resps[1].closed)   # __exit__ closes the final response

    def test_host_locked_resolves_relative_location_against_current_hop(self):
        resps = [_FakeReqResp(301, b"", {"Location": "/blog/a/"}),
                 _FakeReqResp(302, b"", {"Location": "b/"}),
                 _FakeReqResp(200, b"ok")]
        resp, sess = self._open("https://www.allkeyshop.com/blog/x", host_locked=True,
                                side_effect=resps)
        with resp as r:
            self.assertEqual(r.status, 200)
        urls = [c.args[1] for c in sess.request.call_args_list]
        self.assertEqual(urls, ["https://www.allkeyshop.com/blog/x",
                                "https://www.allkeyshop.com/blog/a/",
                                "https://www.allkeyshop.com/blog/a/b/"])

    @unittest.skipUnless(_REAL_SESSION is not None, "requests not installed (stdlib-only box)")
    def test_host_locked_lowercase_location_header_is_followed(self):
        # The property production relies on is requests' CaseInsensitiveDict — use the
        # real class, not a stand-in (review 2026-09-09).
        from requests.structures import CaseInsensitiveDict
        resps = [_FakeReqResp(302, b"", CaseInsensitiveDict({"location": "https://www.allkeyshop.com/blog/y"})),
                 _FakeReqResp(200, b"ok")]
        resp, sess = self._open("https://www.allkeyshop.com/blog/x", host_locked=True,
                                side_effect=resps)
        with resp as r:
            self.assertEqual(r.status, 200)
        self.assertEqual(sess.request.call_args_list[1].args[1], "https://www.allkeyshop.com/blog/y")

    def test_host_locked_3xx_without_location_is_not_followed(self):
        with self.assertRaises(HTTPError) as ctx:
            self._open("https://www.allkeyshop.com/blog/x", host_locked=True,
                       return_value=_FakeReqResp(302, b"", {}))
        self.assertEqual(ctx.exception.code, 302)

    def test_host_locked_follows_exactly_ten_redirects_like_urllib(self):
        # Audit 2026-09-09: urllib's HTTPRedirectHandler follows 10 redirects (fetching the
        # 11th URL); the loop used to follow only 9. 10 hops → 200 on both backends now.
        chain = [_FakeReqResp(302, b"", {"Location": f"https://www.allkeyshop.com/blog/h{i}"})
                 for i in range(10)] + [_FakeReqResp(200, b"end")]
        resp, sess = self._open("https://www.allkeyshop.com/blog/x", host_locked=True,
                                side_effect=chain)
        with resp as r:
            self.assertEqual(r.read(), b"end")
        self.assertEqual(sess.request.call_count, 11)

    def test_host_locked_eleventh_redirect_is_refused_single_wrapped(self):
        chain = [_FakeReqResp(302, b"", {"Location": f"https://www.allkeyshop.com/blog/h{i}"})
                 for i in range(12)]
        with self.assertRaises(URLError) as ctx:
            self._open("https://www.allkeyshop.com/blog/x", host_locked=True, side_effect=chain)
        self.assertEqual(str(ctx.exception), "<urlopen error too many redirects (host-locked)>")
        self.assertNotIn("<urlopen error <urlopen error", str(ctx.exception))  # no double wrap

    def test_host_locked_refuses_backslash_authority_location(self):
        # Audit 2026-09-09 (MAJOR): urlsplit reads the host as www.allkeyshop.com but
        # urllib3 would CONNECT to evil.tld — the staff UA must never be sent there.
        from src.aks_env import StaffUaRedirectRefused
        evil = "https://evil.tld\\@www.allkeyshop.com/blog/x"
        with self.assertRaises(StaffUaRedirectRefused):
            self._open("https://www.allkeyshop.com/blog/x", host_locked=True,
                       return_value=_FakeReqResp(302, b"", {"Location": evil}))
        # userinfo form, same class of ambiguity
        with self.assertRaises(StaffUaRedirectRefused):
            self._open("https://www.allkeyshop.com/blog/x", host_locked=True,
                       return_value=_FakeReqResp(302, b"", {"Location": "https://evil.tld@www.allkeyshop.com/x"}))
        with self.assertRaises(StaffUaRedirectRefused):
            self._open("https://www.allkeyshop.com/blog/x", host_locked=True,
                       return_value=_FakeReqResp(302, b"", {"Location": "javascript:alert(1)"}))

    def test_host_locked_never_requests_a_refused_location(self):
        from src.aks_env import StaffUaRedirectRefused
        evil = "https://evil.tld\\@www.allkeyshop.com/blog/x"
        # only the original URL is ever requested — the refused hop never reaches the wire
        sess = mock.Mock()
        sess.request.return_value = _FakeReqResp(302, b"", {"Location": evil})
        from urllib.request import Request
        from src.aks_env import _http_open_keepalive
        req = Request("https://www.allkeyshop.com/blog/x", headers={"User-Agent": AKS_STAFF_UA})
        with mock.patch("src.aks_env._SESSION", sess):
            with self.assertRaises(StaffUaRedirectRefused):
                _http_open_keepalive(req, 8, True, True)
        self.assertEqual([c.args[1] for c in sess.request.call_args_list],
                         ["https://www.allkeyshop.com/blog/x"])

    def test_host_locked_requotes_latin1_decoded_utf8_location_like_urllib(self):
        # Audit 2026-09-09 (critic): http.client decodes header bytes as latin-1, so a UTF-8
        # permalink "é" (C3 A9) arrives as "Ã©"; urllib re-quotes it to %C3%A9. Mirror that
        # instead of letting urllib3 double-encode it to %C3%83%C2%A9 (a 404 on any site).
        mojibake = "/blog/buy-pok\u00c3\u00a9mon-cd-key-compare-prices/"
        resps = [_FakeReqResp(301, b"", {"Location": mojibake}), _FakeReqResp(200, b"ok")]
        _, sess = self._open("https://www.allkeyshop.com/blog/x", host_locked=True,
                             side_effect=resps)
        self.assertEqual(sess.request.call_args_list[1].args[1],
                         "https://www.allkeyshop.com/blog/buy-pok%C3%A9mon-cd-key-compare-prices/")

    def test_transport_error_becomes_urlerror(self):
        # A transport failure (requests raises a RequestException subclass of OSError) maps
        # to URLError. Uses the stdlib ConnectionError so the test runs without requests.
        with self.assertRaises(URLError):
            self._open("https://www.allkeyshop.com/blog/x",
                       side_effect=ConnectionError("down"))

    def test_no_follow_under_host_lock_surfaces_3xx_not_followed(self):
        # Adversarial verify 2026-09-08 (CRITICAL fail-open): a staff-UA + follow_redirects=
        # False probe (the invariant reachability gate + 03_match) must NOT follow even a
        # SAME-domain 3xx — it surfaces as HTTPError, exactly like urllib's _NoRedirectHandler.
        # Before the fix the host_locked branch was checked first and followed the 3xx to 200,
        # flipping the gate ok=True where urllib fail-closed.
        with self.assertRaises(HTTPError) as ctx:
            self._open("https://www.allkeyshop.com/blog/", host_locked=True,
                       follow_redirects=False,
                       return_value=_FakeReqResp(307, b"", {"Location": "https://www.allkeyshop.com/blog/x"}))
        self.assertEqual(ctx.exception.code, 307)

    def test_runtime_non_request_exception_becomes_urlerror(self):
        # minor #4: requests broken at RUNTIME (not import) with a non-RequestException must
        # still fail closed as URLError, keeping http_get's "never raises" contract.
        with self.assertRaises(URLError):
            self._open("https://www.allkeyshop.com/blog/x", side_effect=RuntimeError("boom"))

    def test_too_many_redirects_fails_closed(self):
        # re-verify 2026-09-08: the Session caps at max_redirects=10 (like urllib), so a
        # >10-hop chain raises TooManyRedirects → URLError → ok=False, never a spurious 200.
        class TooManyRedirects(Exception):   # shape of requests.exceptions.TooManyRedirects
            pass
        with self.assertRaises(URLError):
            self._open("https://www.allkeyshop.com/blog/x", side_effect=TooManyRedirects("loop"))

    @unittest.skipUnless(_REAL_SESSION is not None, "requests not installed (stdlib-only box)")
    def test_real_session_is_capped_stateless_and_env_blind(self):
        # The three properties the keep-alive Session relies on, asserted on the REAL
        # object (audit 2026-09-09: only max_redirects was covered before).
        import src.aks_env as env
        self.assertEqual(env._SESSION.max_redirects, 10)
        self.assertFalse(env._SESSION.trust_env)            # no ~/.netrc, no CA env vars
        policy = env._SESSION.cookies.get_policy()
        self.assertEqual(policy.allowed_domains(), ())
        self.assertTrue(policy.is_not_allowed("www.allkeyshop.com"))
        self.assertTrue(policy.is_not_allowed("difmark.com"))


class CurrentEnvironmentTests(unittest.TestCase):
    def _env(self, *, system="Linux", marker=False, aks_target=None):
        environ = {} if aks_target is None else {"AKS_TARGET": aks_target}
        with mock.patch.dict("src.aks_env.os.environ", environ, clear=True), mock.patch(
            "src.aks_env.platform.system", return_value=system
        ), mock.patch("src.aks_env.marker_authorizes", return_value=marker), mock.patch(
            "src.aks_env.socket.gethostname", return_value="host"
        ):
            return current_environment()

    def test_aks_target_vps_no_longer_forces_authoritative(self):
        # FC2 (audit 2026-07-17): one env var must never unlock write stages.
        self.assertFalse(self._env(aks_target="vps")["authoritative"])
        self.assertFalse(self._env(aks_target="vps", marker=False)["authoritative"])

    def test_aks_target_dev_overrides_even_if_marker_present(self):
        self.assertFalse(self._env(aks_target="dev", marker=True)["authoritative"])

    def test_root_marker_is_the_only_authority(self):
        self.assertTrue(self._env(marker=True)["authoritative"])
        self.assertFalse(self._env(marker=False)["authoritative"])

    def test_marker_still_requires_linux(self):
        self.assertFalse(self._env(system="Darwin", marker=True)["authoritative"])


class MarkerAuthorizesTests(unittest.TestCase):
    """FC2: the marker vouches only when root-owned, unwritable by others,
    and pinned to THIS hostname."""

    def _marker(self, tmp, content="host-a", uid=0, mode=0o644):
        import os as real_os

        path = Path(tmp) / "aks-executor.target"
        path.write_text(content + "\n", encoding="utf-8")
        real_stat = real_os.stat(path)

        class FakeStat:
            st_uid = uid
            st_mode = (real_stat.st_mode & ~0o777) | mode

        return str(path), FakeStat()

    def test_valid_marker_authorizes(self):
        from src.aks_env import marker_authorizes

        with tempfile.TemporaryDirectory() as tmp:
            path, fake_stat = self._marker(tmp)
            with mock.patch("src.aks_env.os.stat", return_value=fake_stat):
                self.assertTrue(marker_authorizes(path, hostname="host-a"))

    def test_wrong_hostname_refused(self):
        from src.aks_env import marker_authorizes

        with tempfile.TemporaryDirectory() as tmp:
            path, fake_stat = self._marker(tmp, content="host-a")
            with mock.patch("src.aks_env.os.stat", return_value=fake_stat):
                self.assertFalse(marker_authorizes(path, hostname="host-b"))

    def test_non_root_owner_refused(self):
        from src.aks_env import marker_authorizes

        with tempfile.TemporaryDirectory() as tmp:
            path, fake_stat = self._marker(tmp, uid=1000)
            with mock.patch("src.aks_env.os.stat", return_value=fake_stat):
                self.assertFalse(marker_authorizes(path, hostname="host-a"))

    def test_world_writable_refused(self):
        from src.aks_env import marker_authorizes

        with tempfile.TemporaryDirectory() as tmp:
            path, fake_stat = self._marker(tmp, mode=0o666)
            with mock.patch("src.aks_env.os.stat", return_value=fake_stat):
                self.assertFalse(marker_authorizes(path, hostname="host-a"))

    def test_missing_file_refused(self):
        from src.aks_env import marker_authorizes

        self.assertFalse(marker_authorizes("/nonexistent/marker", hostname="host-a"))

    def test_empty_marker_refused(self):
        from src.aks_env import marker_authorizes

        with tempfile.TemporaryDirectory() as tmp:
            path, fake_stat = self._marker(tmp, content="")
            with mock.patch("src.aks_env.os.stat", return_value=fake_stat):
                self.assertFalse(marker_authorizes(path, hostname="host-a"))


class StaffUaRedirectGuardTests(unittest.TestCase):
    """P2-15: the AKS/Staff UA must never leak off allkeyshop.com via a followed 3xx."""

    def _handler(self):
        from src.aks_env import _StaffUaHostGuardRedirectHandler
        return _StaffUaHostGuardRedirectHandler()

    def _req(self):
        from urllib.request import Request
        return Request("https://www.allkeyshop.com/blog/buy-x-cd-key-compare-prices/",
                       headers={"User-agent": AKS_STAFF_UA})

    class _FP:
        def read(self):  return b""
        def close(self): pass

    def test_off_domain_redirect_is_refused(self):
        with self.assertRaises(HTTPError):
            self._handler().redirect_request(
                self._req(), self._FP(), 302, "Found", {}, "https://cdn.evil.tld/x")

    def test_same_domain_redirect_is_followed_ua_preserved(self):
        r = self._handler().redirect_request(
            self._req(), self._FP(), 301, "Moved", {}, "https://www.allkeyshop.com/canonical/")
        self.assertIsNotNone(r)                                  # followed, not refused
        self.assertEqual(r.get_header("User-agent"), AKS_STAFF_UA)  # UA preserved across the hop

    def test_http_get_staff_ua_uses_host_locked_opener(self):
        # a staff-UA follow-redirect GET opens through the host-locked opener; an
        # explicit browser UA on AKS and any other host do NOT. Since 2026-09-11 the
        # DEFAULT towards an allkeyshop.com host IS the staff UA (→ host-locked too).
        captured = {}

        def fake_open(request, timeout, follow_redirects=True, host_locked=False):
            captured["host_locked"] = host_locked
            return _FakeResp(200, b"ok")

        with mock.patch("src.aks_env._http_open", side_effect=fake_open):
            http_get("https://www.allkeyshop.com/x", user_agent=AKS_STAFF_UA)
            self.assertTrue(captured["host_locked"])
            http_get("https://www.allkeyshop.com/x")            # default towards AKS = staff UA
            self.assertTrue(captured["host_locked"])
            http_get("https://www.allkeyshop.com/x", user_agent=REQUIRED_USER_AGENT)
            self.assertFalse(captured["host_locked"])           # explicit browser UA: as before
            http_get("https://www.g2a.com/x")                   # other host: default browser UA
            self.assertFalse(captured["host_locked"])
            http_get("https://www.allkeyshop.com/x", user_agent=AKS_STAFF_UA, follow_redirects=False)
            self.assertTrue(captured["host_locked"])            # passed, but _http_open uses the no-redirect handler



class ProxyMirrorTests(unittest.TestCase):
    """`_urllib_proxies` mirrors urllib's ProxyHandler env handling (review 2026-09-09)."""

    ENV = {"http_proxy": "http://p:1", "https_proxy": "http://p:1",
           "no_proxy": ".allkeyshop.com,172.17.0.1:9223"}

    def test_env_proxies_forwarded_unless_bypassed(self):
        from src.aks_env import _urllib_proxies
        with mock.patch.dict("os.environ", self.ENV, clear=False):
            self.assertEqual(_urllib_proxies("https://www.allkeyshop.com/blog/"), {})
            self.assertEqual(_urllib_proxies("http://172.17.0.1:9223/json/version"), {})  # host:port form
            self.assertEqual(_urllib_proxies("https://difmark.com/x").get("https"), "http://p:1")
            self.assertEqual(_urllib_proxies("not a url"), {})

    def test_every_keepalive_branch_passes_the_mirrored_proxies(self):
        from urllib.request import Request
        from src.aks_env import _http_open_keepalive
        env = {"http_proxy": "http://p:1", "https_proxy": "http://p:1", "no_proxy": ""}
        for follow, locked in ((False, True), (True, True), (True, False)):
            sess = mock.Mock()
            sess.request.return_value = _FakeReqResp(200, b"ok")
            req = Request("https://www.allkeyshop.com/blog/x", headers={"User-Agent": AKS_STAFF_UA})
            with mock.patch("src.aks_env._SESSION", sess), mock.patch.dict("os.environ", env):
                _http_open_keepalive(req, 8, follow, locked)
            self.assertEqual(sess.request.call_args.kwargs["proxies"].get("https"), "http://p:1",
                             (follow, locked))


class HostGuardTests(unittest.TestCase):
    """`_allkeyshop_host` must be UNAMBIGUOUS across URL parsers (audit 2026-09-09)."""

    def test_accepts_plain_allkeyshop_hosts(self):
        from src.aks_env import _allkeyshop_host
        for url in ("https://www.allkeyshop.com/blog/x", "http://allkeyshop.com",
                    "https://WWW.AllKeyShop.com:443/blog/?s=q#f", "https://cdn.allkeyshop.com/a"):
            self.assertTrue(_allkeyshop_host(url), url)

    def test_refuses_ambiguous_or_foreign_authorities(self):
        from src.aks_env import _allkeyshop_host
        for url in ("https://evil.tld\\@www.allkeyshop.com/x",     # backslash: urllib3 → evil.tld
                    "https://evil.tld@www.allkeyshop.com/x",       # userinfo
                    "https://www.allkeyshop.com evil.tld/x",       # whitespace
                    "https://www.allkeyshop.com.evil.tld/x",       # suffix trick
                    "https://notallkeyshop.com/x", "https://allkeyshop.com.evil/x",
                    "javascript:alert(1)", "data:text/html,x", "//www.allkeyshop.com/x",
                    "https://[::1]/x", ""):
            self.assertFalse(_allkeyshop_host(url), url)


class _LocalHandler(__import__("http.server").server.BaseHTTPRequestHandler):
    """Tiny 127.0.0.1 server for REAL-backend tests: records every request it sees."""
    seen: list = []

    def log_message(self, *a):  # silence
        pass

    def do_HEAD(self):
        type(self).seen.append((self.path, dict(self.headers)))
        self.send_response(200 if self.path == "/ok" else 404)
        self.send_header("Content-Length", "0"); self.end_headers()

    def do_GET(self):
        type(self).seen.append((self.path, dict(self.headers)))
        if self.path == "/ok":
            body = b"ok"
            self.send_response(200); self.send_header("Content-Length", str(len(body)))
            self.end_headers(); self.wfile.write(body)
        elif self.path == "/r302":
            self.send_response(302); self.send_header("Location", "/ok"); self.end_headers()
        elif self.path == "/off":                                  # off-domain hop
            self.send_response(302)
            self.send_header("Location", f"http://localhost:{self.server.server_port}/ok")
            self.end_headers()
        elif self.path == "/backslash":   # parser-differential authority (audit major)
            self.send_response(302)
            self.send_header("Location",
                             f"http://localhost:{self.server.server_port}\\@127.0.0.1:{self.server.server_port}/ok")
            self.end_headers()
        elif self.path == "/setcookie":
            self.send_response(200); self.send_header("Set-Cookie", "sid=42; Path=/")
            self.send_header("Content-Length", "0"); self.end_headers()
        elif self.path == "/echo":
            body = json.dumps({"cookie": self.headers.get("Cookie"),
                               "auth": self.headers.get("Authorization"),
                               "ua": self.headers.get("User-Agent")}).encode()
            self.send_response(200); self.send_header("Content-Length", str(len(body)))
            self.end_headers(); self.wfile.write(body)
        else:
            self.send_response(404); self.send_header("Content-Length", "0"); self.end_headers()


class RealBackendsLocalServerTests(unittest.TestCase):
    """Drive the REAL `_http_open` dispatcher and BOTH backends end to end through http_get
    against a throwaway 127.0.0.1 server (audit 2026-09-09: the dispatcher and the stdlib
    fallback executed 0 times in the suite; a swapped positional in the dispatcher — the
    exact 54f1f88 fail-open shape — went unnoticed). No network leaves the box."""

    @classmethod
    def setUpClass(cls):
        import threading
        from http.server import ThreadingHTTPServer
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), _LocalHandler)
        cls.port = cls.server.server_port
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown(); cls.server.server_close()

    def setUp(self):
        _LocalHandler.seen = []
        # The staff host-lock is keyed on allkeyshop.com; point it at the local box so the
        # host-locked branches run for real (localhost ≠ 127.0.0.1 → "off-domain"), keeping
        # the REAL strictness (scheme + netloc regex) so the guard runs against a socket.
        from urllib.parse import urlsplit
        from src.aks_env import _STRICT_NETLOC_RE

        def local_guard(u):
            parts = urlsplit(u)
            return (parts.scheme == "http" and bool(_STRICT_NETLOC_RE.match(parts.netloc or ""))
                    and parts.hostname == "127.0.0.1")
        patcher = mock.patch("src.aks_env._allkeyshop_host", local_guard)
        patcher.start(); self.addCleanup(patcher.stop)
        env = mock.patch.dict("os.environ", {"no_proxy": "*"})   # hermetic to the shell's proxies
        env.start(); self.addCleanup(env.stop)

    def _backends(self):
        yield "urllib", mock.patch("src.aks_env._SESSION", None)
        if _REAL_SESSION is not None:
            yield "keep-alive", mock.patch("src.aks_env._SESSION", _REAL_SESSION)

    def test_no_redirect_mode_never_follows_on_either_backend(self):
        for name, patch in self._backends():
            with self.subTest(backend=name), patch:
                _LocalHandler.seen = []
                p = http_get(self.base + "/r302", follow_redirects=False, user_agent=AKS_STAFF_UA)
                self.assertEqual(p.status, 302, name)
                self.assertEqual([s[0] for s in _LocalHandler.seen], ["/r302"], name)

    def test_staff_follow_same_host_and_refuses_off_host_on_either_backend(self):
        for name, patch in self._backends():
            with self.subTest(backend=name), patch:
                _LocalHandler.seen = []
                p = http_get(self.base + "/r302", user_agent=AKS_STAFF_UA)
                self.assertEqual((p.ok, p.status, p.body), (True, 200, "ok"), name)
                self.assertEqual([s[0] for s in _LocalHandler.seen], ["/r302", "/ok"], name)
                _LocalHandler.seen = []
                p = http_get(self.base + "/off", user_agent=AKS_STAFF_UA)
                self.assertEqual((p.ok, p.status), (False, 302), name)
                # the refused hop was NEVER requested — the staff UA stayed on-host
                self.assertEqual([s[0] for s in _LocalHandler.seen], ["/off"], name)
                _LocalHandler.seen = []
                # backslash-authority Location (urlsplit says 127.0.0.1, urllib3 would connect
                # to localhost): refused BEFORE any socket is opened, on both backends
                p = http_get(self.base + "/backslash", user_agent=AKS_STAFF_UA)
                self.assertEqual((p.ok, p.status), (False, 302), name)
                self.assertEqual([s[0] for s in _LocalHandler.seen], ["/backslash"], name)

    def test_plain_ua_follow_and_status_mapping_on_either_backend(self):
        for name, patch in self._backends():
            with self.subTest(backend=name), patch:
                p = http_get(self.base + "/r302")
                self.assertEqual((p.ok, p.status, p.body), (True, 200, "ok"), name)
                p = http_get(self.base + "/missing")
                self.assertEqual((p.ok, p.status), (False, 404), name)
                self.assertEqual(http_head_status(self.base + "/ok").status, 200, name)
                self.assertIn("Content-Length", http_get(self.base + "/echo").headers, name)

    def test_keepalive_is_stateless_across_calls_and_netrc_blind(self):
        if _REAL_SESSION is None:
            self.skipTest("requests not installed")
        with tempfile.TemporaryDirectory() as tmp:
            netrc = Path(tmp) / "netrc"
            netrc.write_text("default login leakuser password leakpass\n")
            netrc.chmod(0o600)
            with mock.patch.dict("os.environ", {"NETRC": str(netrc)}), \
                    mock.patch("src.aks_env._SESSION", _REAL_SESSION):
                http_get(self.base + "/setcookie")
                echo = json.loads(http_get(self.base + "/echo").body)
        self.assertIsNone(echo["cookie"])       # Set-Cookie from call N never replayed
        self.assertIsNone(echo["auth"])         # no ~/.netrc Authorization injection
        # this server is patched to count as an allkeyshop host (setUpClass) → the
        # 2026-09-11 default applies: the staff UA, never the browser UA, towards AKS
        self.assertEqual(echo["ua"], AKS_STAFF_UA)
        self.assertEqual(len(_REAL_SESSION.cookies), 0)


if __name__ == "__main__":
    unittest.main()

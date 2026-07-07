import io
import json
import unittest
from unittest import mock
from urllib.error import HTTPError, URLError

from src.aks_env import (
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


class CurrentEnvironmentTests(unittest.TestCase):
    def _env(self, *, system="Linux", marker=False, aks_target=None):
        environ = {} if aks_target is None else {"AKS_TARGET": aks_target}
        with mock.patch.dict("src.aks_env.os.environ", environ, clear=True), mock.patch(
            "src.aks_env.platform.system", return_value=system
        ), mock.patch("src.aks_env.os.path.exists", return_value=marker), mock.patch(
            "src.aks_env.socket.gethostname", return_value="host"
        ):
            return current_environment()

    def test_aks_target_vps_forces_authoritative(self):
        self.assertTrue(self._env(aks_target="vps")["authoritative"])

    def test_aks_target_dev_overrides_even_if_marker_present(self):
        self.assertFalse(self._env(aks_target="dev", marker=True)["authoritative"])

    def test_marker_file_fallback_when_no_override(self):
        self.assertTrue(self._env(marker=True)["authoritative"])
        self.assertFalse(self._env(marker=False)["authoritative"])

    def test_vps_override_still_requires_linux(self):
        self.assertFalse(self._env(system="Darwin", aks_target="vps")["authoritative"])


if __name__ == "__main__":
    unittest.main()

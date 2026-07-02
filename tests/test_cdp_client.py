import json
import unittest
from unittest import mock

from src.aks_env import HOST_CDP_ENDPOINT, OFFICIAL_CDP_ENDPOINT, REQUIRED_USER_AGENT, HttpProbeResult
from src.cdp_client import ReadOnlyCdpClient


def _valid_payload():
    return {
        "Browser": "Chrome/149.0.0.0",
        "Protocol-Version": "1.3",
        "User-Agent": REQUIRED_USER_AGENT,
        "webSocketDebuggerUrl": "ws://172.17.0.1:9223/devtools/browser/xyz",
    }


def _probe(ok=True, status=200, body="", error=None):
    return HttpProbeResult(url=OFFICIAL_CDP_ENDPOINT, ok=ok, status=status, body=body, error=error)


def _check_names(result):
    return [c.name for c in result.checks]


class ReadOnlyCdpClientTests(unittest.TestCase):
    def test_websocket_url_is_disabled_for_sprint_1(self):
        client = ReadOnlyCdpClient(OFFICIAL_CDP_ENDPOINT)

        with self.assertRaisesRegex(RuntimeError, "read-only"):
            client.websocket_url()


class GetVersionTests(unittest.TestCase):
    def test_wrong_endpoint_fails_closed_without_probing(self):
        client = ReadOnlyCdpClient(HOST_CDP_ENDPOINT)
        with mock.patch("src.cdp_client.http_get") as get:
            result = client.get_version()
        self.assertFalse(result.ok)
        get.assert_not_called()  # never probe a non-official endpoint
        endpoint_check = next(c for c in result.checks if c.name == "official_cdp_endpoint")
        self.assertFalse(endpoint_check.ok)

    def test_unreachable_probe_fails_closed(self):
        client = ReadOnlyCdpClient(OFFICIAL_CDP_ENDPOINT)
        with mock.patch("src.cdp_client.http_get", return_value=_probe(ok=False, status=None, error="down")):
            result = client.get_version()
        self.assertFalse(result.ok)
        self.assertIn("cdp_http_get", _check_names(result))
        self.assertIsNone(result.payload)

    def test_non_json_body_fails_closed(self):
        client = ReadOnlyCdpClient(OFFICIAL_CDP_ENDPOINT)
        with mock.patch("src.cdp_client.http_get", return_value=_probe(body="not json")):
            result = client.get_version()
        self.assertFalse(result.ok)
        self.assertIn("cdp_json_parse", _check_names(result))

    def test_bad_user_agent_fails_closed(self):
        payload = _valid_payload()
        payload["User-Agent"] = "Mozilla/5.0 HeadlessChrome"
        client = ReadOnlyCdpClient(OFFICIAL_CDP_ENDPOINT)
        with mock.patch("src.cdp_client.http_get", return_value=_probe(body=json.dumps(payload))):
            result = client.get_version()
        self.assertFalse(result.ok)
        ua_check = next(c for c in result.checks if c.name == "required_user_agent")
        self.assertFalse(ua_check.ok)

    def test_full_pass(self):
        client = ReadOnlyCdpClient(OFFICIAL_CDP_ENDPOINT)
        with mock.patch("src.cdp_client.http_get", return_value=_probe(body=json.dumps(_valid_payload()))):
            result = client.get_version()
        self.assertTrue(result.ok)
        self.assertEqual(result.payload["Browser"], "Chrome/149.0.0.0")


if __name__ == "__main__":
    unittest.main()

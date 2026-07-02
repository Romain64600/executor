import json
import unittest

from src.aks_env import (
    OFFICIAL_CDP_ENDPOINT,
    REQUIRED_USER_AGENT,
    checks_to_dict,
    classify_environment,
    parse_cdp_version_payload,
    validate_aks_direct_status,
    validate_cdp_version_shape,
    validate_official_cdp_endpoint,
    validate_required_user_agent,
)


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

    def test_validate_aks_direct_status_accepts_2xx_and_3xx_only(self):
        self.assertTrue(validate_aks_direct_status(200).ok)
        self.assertTrue(validate_aks_direct_status(302).ok)
        self.assertFalse(validate_aks_direct_status(404).ok)
        self.assertFalse(validate_aks_direct_status(None).ok)

    def test_checks_to_dict_fails_closed_when_any_check_fails(self):
        checks = [validate_aks_direct_status(200), validate_official_cdp_endpoint("bad")]

        result = checks_to_dict(checks)

        self.assertFalse(result["ok"])
        self.assertEqual(len(result["checks"]), 2)


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


if __name__ == "__main__":
    unittest.main()

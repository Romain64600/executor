import json
import unittest
from unittest import mock

from src.aks_env import (
    AKS_DIRECT_URL,
    OFFICIAL_CDP_ENDPOINT,
    REQUIRED_USER_AGENT,
    CheckResult,
    HttpProbeResult,
)
from src.cdp_client import CdpVersionResult
from src import invariants


def _ok_cdp():
    payload = {
        "Browser": "Chrome/149.0.0.0",
        "User-Agent": REQUIRED_USER_AGENT,
        "webSocketDebuggerUrl": "ws://172.17.0.1:9223/devtools/browser/SECRET",
    }
    return CdpVersionResult(
        endpoint=OFFICIAL_CDP_ENDPOINT,
        ok=True,
        payload=payload,
        checks=[
            CheckResult("official_cdp_endpoint", True, "", {}),
            CheckResult("cdp_version_shape", True, "", {}),
            CheckResult("required_user_agent", True, "", {}),
        ],
        probe=HttpProbeResult(url=OFFICIAL_CDP_ENDPOINT, ok=True, status=200, body=""),
    )


def _bad_cdp():
    return CdpVersionResult(
        endpoint=OFFICIAL_CDP_ENDPOINT,
        ok=False,
        payload=None,
        checks=[CheckResult("cdp_version_shape", False, "unreachable", {})],
        probe=HttpProbeResult(
            url=OFFICIAL_CDP_ENDPOINT, ok=False, status=None, body="", error="down"
        ),
        error="down",
    )


def _env(authoritative):
    return {
        "hostname": "h",
        "platform": "Linux",
        "is_target": authoritative,
        "authoritative": authoritative,
        "note": "n",
    }


class BuildReportTests(unittest.TestCase):
    def _run(self, aks_probe, env_authoritative=True, openvpn_pids=None, cdp=None):
        openvpn_pids = [] if openvpn_pids is None else openvpn_pids
        with mock.patch("src.invariants.http_get", return_value=aks_probe), mock.patch(
            "src.invariants.ReadOnlyCdpClient"
        ) as cdp_cls, mock.patch(
            "src.invariants.list_openvpn_pids", return_value=openvpn_pids
        ), mock.patch(
            "src.invariants.current_environment", return_value=_env(env_authoritative)
        ):
            cdp_cls.return_value.get_version.return_value = cdp or _ok_cdp()
            return invariants.build_report()

    def test_all_pass_and_guard_is_exercised(self):
        report = self._run(HttpProbeResult(url=AKS_DIRECT_URL, ok=True, status=200, body=""))
        self.assertTrue(report["ok"])
        self.assertTrue(report["authoritative"])
        self.assertFalse(report["guard"]["blocked"])
        self.assertEqual(report["guard"]["counters"]["total_failures"], 0)
        self.assertEqual(report["guard"]["counters"]["attempts_by_signature"],
                         {"aks_direct": 1, "openvpn_process": 1, "cdp_version": 1})

    def test_cdp_payload_is_redacted(self):
        report = self._run(HttpProbeResult(url=AKS_DIRECT_URL, ok=True, status=200, body=""))
        payload = report["cdp"]["payload"]
        self.assertTrue(payload["webSocketDebuggerUrl_present"])
        self.assertNotIn("webSocketDebuggerUrl", payload)
        # the raw control-channel URL must not appear anywhere in the report
        self.assertNotIn("SECRET", json.dumps(report))

    def test_aks_failure_fails_closed_and_records_guard_failure(self):
        report = self._run(
            HttpProbeResult(url=AKS_DIRECT_URL, ok=False, status=None, body="", error="down"),
            env_authoritative=False,
        )
        self.assertFalse(report["ok"])
        self.assertFalse(report["authoritative"])
        self.assertGreaterEqual(report["guard"]["counters"]["total_failures"], 1)

    def test_302_is_accepted_as_reachable(self):
        report = self._run(HttpProbeResult(url=AKS_DIRECT_URL, ok=False, status=302, body=""))
        self.assertTrue(report["aks_direct"]["ok"])

    def test_openvpn_running_fails_the_gate(self):
        report = self._run(
            HttpProbeResult(url=AKS_DIRECT_URL, ok=True, status=200, body=""),
            openvpn_pids=["1819"],
        )
        self.assertFalse(report["ok"])
        self.assertTrue(report["aks_direct"]["ok"])
        self.assertFalse(report["openvpn"]["ok"])
        self.assertEqual(report["openvpn"]["pids"], ["1819"])
        by_name = {check["name"]: check for check in report["checks"]}
        self.assertFalse(by_name["no_openvpn_process"]["ok"])

    def test_all_probes_failing_still_yields_report(self):
        # A fully-red environment must produce the fail-closed JSON report,
        # not trip the guard's consecutive-failure block mid-report.
        report = self._run(
            HttpProbeResult(url=AKS_DIRECT_URL, ok=False, status=None, body="", error="down"),
            env_authoritative=False,
            openvpn_pids=["1819"],
            cdp=_bad_cdp(),
        )
        self.assertFalse(report["ok"])
        self.assertFalse(report["guard"]["blocked"])
        self.assertEqual(report["guard"]["counters"]["total_failures"], 3)


if __name__ == "__main__":
    unittest.main()

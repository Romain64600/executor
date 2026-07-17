"""CDP transport fail-closed semantics (audit 2026-07-17, SC1/SC6/TE1).

A command timeout or a Chrome protocol error must RAISE — the old sentinel
dict flowed through ``_evaluate`` as a silent ``None``, which feed scans read
as "0 rows": the exact shape of a false post-save disappearance proof. These
tests drive ``_cmd``/``navigate`` over a stubbed WebSocket, no real I/O.
"""

import json
import unittest

from src.cdp_session import CdpCommandError, ReadOnlyCdpSession


class _StubbedSession(ReadOnlyCdpSession):
    """ReadOnlyCdpSession whose WebSocket is a scripted queue of frames."""

    def __init__(self, frames=(), cmd_timeout=1):
        super().__init__("http://127.0.0.1:9999/json/version", cmd_timeout=cmd_timeout)
        self.sent = []
        self.frames = list(frames)

    def _ws_send(self, msg):
        self.sent.append(json.loads(msg))

    def _ws_recv(self, timeout=5.0):
        if self.frames:
            return self.frames.pop(0)
        return None


class CmdFailClosedTests(unittest.TestCase):
    def test_timeout_raises_instead_of_sentinel(self):
        session = _StubbedSession(frames=[], cmd_timeout=0)
        with self.assertRaises(CdpCommandError) as ctx:
            session._cmd("Runtime.evaluate", {"expression": "1"})
        self.assertIn("no response", str(ctx.exception))

    def test_protocol_error_raises(self):
        session = _StubbedSession(
            frames=[json.dumps({"id": 1, "error": {"code": -32000, "message": "Target closed"}})]
        )
        with self.assertRaises(CdpCommandError) as ctx:
            session._cmd("Runtime.evaluate", {"expression": "1"})
        self.assertIn("Target closed", str(ctx.exception))

    def test_clean_response_returned(self):
        session = _StubbedSession(
            frames=[json.dumps({"id": 1, "result": {"result": {"value": 42}}})]
        )
        response = session._cmd("Runtime.evaluate", {"expression": "6*7"})
        self.assertEqual(response["result"]["result"]["value"], 42)

    def test_evaluate_propagates_timeout(self):
        session = _StubbedSession(frames=[], cmd_timeout=0)
        with self.assertRaises(CdpCommandError):
            session._evaluate("document.title")

    def test_unrelated_ids_are_skipped_until_match(self):
        session = _StubbedSession(
            frames=[
                json.dumps({"method": "Page.frameNavigated", "params": {}}),
                json.dumps({"id": 1, "result": {"ok": True}}),
            ]
        )
        response = session._cmd("Page.enable")
        self.assertEqual(response["result"], {"ok": True})


class NavigateFailClosedTests(unittest.TestCase):
    def test_net_error_raises(self):
        session = _StubbedSession(
            frames=[json.dumps({"id": 1, "result": {"frameId": "F", "errorText": "net::ERR_CONNECTION_REFUSED"}})]
        )
        with self.assertRaises(CdpCommandError) as ctx:
            session.navigate("https://example.test/feed", settle=0)
        self.assertIn("net::ERR_CONNECTION_REFUSED", str(ctx.exception))

    def test_clean_navigation_passes(self):
        session = _StubbedSession(
            frames=[json.dumps({"id": 1, "result": {"frameId": "F"}})]
        )
        session.navigate("https://example.test/feed", settle=0)  # no raise
        self.assertEqual(session.sent[0]["method"], "Page.navigate")


if __name__ == "__main__":
    unittest.main()

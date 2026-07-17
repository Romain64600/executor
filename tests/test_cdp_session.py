"""CDP transport fail-closed semantics (audit 2026-07-17, SC1/SC6/TE1).

A command timeout or a Chrome protocol error must RAISE — the old sentinel
dict flowed through ``_evaluate`` as a silent ``None``, which feed scans read
as "0 rows": the exact shape of a false post-save disappearance proof. These
tests drive ``_cmd``/``navigate`` over a stubbed WebSocket, no real I/O.
"""

import json
import socket
import unittest
from unittest import mock

from src.cdp_session import CdpCommandError, ReadOnlyCdpSession


def _server_frame(opcode: int, payload: bytes = b"", fin: bool = True) -> bytes:
    """A server→client frame (unmasked, RFC 6455 §5.1)."""

    first = (0x80 if fin else 0x00) | opcode
    length = len(payload)
    if length < 126:
        header = bytes([first, length])
    elif length < 65536:
        header = bytes([first, 126]) + length.to_bytes(2, "big")
    else:
        header = bytes([first, 127]) + length.to_bytes(8, "big")
    return header + payload


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


class WsFramingTests(unittest.TestCase):
    """SC8 (audit 2026-07-17): opcode handling, fragmentation, and
    desync-proof reads over a real socketpair."""

    def setUp(self):
        self.session = ReadOnlyCdpSession("http://127.0.0.1:9999/json/version")
        self.client, self.server = socket.socketpair()
        self.addCleanup(self.client.close)
        self.addCleanup(self.server.close)
        self.session._sock = self.client

    def test_text_frame_round_trip(self):
        self.server.sendall(_server_frame(0x1, b'{"id": 1}'))
        self.assertEqual(self.session._ws_recv(timeout=1), '{"id": 1}')

    def test_fragmented_message_is_assembled(self):
        self.server.sendall(_server_frame(0x1, b'{"id"', fin=False))
        self.server.sendall(_server_frame(0x0, b": 42}", fin=True))
        self.assertEqual(self.session._ws_recv(timeout=1), '{"id": 42}')

    def test_close_frame_raises_instead_of_parsing_as_text(self):
        self.server.sendall(_server_frame(0x8, b"\x03\xe8"))
        with self.assertRaises(CdpCommandError) as ctx:
            self.session._ws_recv(timeout=1)
        self.assertIn("close frame", str(ctx.exception))

    def test_ping_is_answered_with_pong_and_data_still_returned(self):
        self.server.sendall(_server_frame(0x9, b"hb") + _server_frame(0x1, b"ok"))
        self.assertEqual(self.session._ws_recv(timeout=1), "ok")
        pong = self.server.recv(64)
        self.assertEqual(pong[0], 0x80 | 0xA)  # FIN + pong opcode
        self.assertTrue(pong[1] & 0x80)        # client frames are masked

    def test_benign_timeout_returns_none(self):
        self.assertIsNone(self.session._ws_recv(timeout=0.05))

    def test_eof_before_any_byte_raises(self):
        self.server.close()
        with self.assertRaises(CdpCommandError) as ctx:
            self.session._ws_recv(timeout=1)
        self.assertIn("EOF", str(ctx.exception))

    def test_mid_frame_eof_raises_never_desyncs(self):
        self.server.sendall(b"\x81")  # half a header, then the peer dies
        self.server.close()
        with self.assertRaises(CdpCommandError) as ctx:
            self.session._ws_recv(timeout=1)
        self.assertIn("mid-frame", str(ctx.exception))

    def test_mid_frame_stall_raises_never_desyncs(self):
        self.server.sendall(b"\x81")  # half a header, then silence
        with self.assertRaises(CdpCommandError) as ctx:
            self.session._ws_recv(timeout=0.05)
        self.assertIn("stalled", str(ctx.exception))


class PageTargetSelectionTests(unittest.TestCase):
    """SC7 (audit 2026-07-17): only real http(s) tabs qualify, AKS preferred."""

    def _pick(self, targets):
        session = ReadOnlyCdpSession("http://127.0.0.1:9999/json/version")
        payload = json.dumps(targets).encode("utf-8")
        fake_response = mock.Mock()
        fake_response.read.return_value = payload
        with mock.patch("src.cdp_session.urlopen", return_value=fake_response):
            return session._page_ws_path()

    def test_chrome_error_tab_is_filtered(self):
        path = self._pick([
            {"type": "page", "url": "chrome-error://chromewebdata/",
             "webSocketDebuggerUrl": "ws://h/devtools/page/BAD"},
            {"type": "page", "url": "https://example.test/x",
             "webSocketDebuggerUrl": "ws://h/devtools/page/GOOD"},
        ])
        self.assertEqual(path, "/devtools/page/GOOD")

    def test_aks_tab_preferred_over_first_listed(self):
        path = self._pick([
            {"type": "page", "url": "https://example.test/other",
             "webSocketDebuggerUrl": "ws://h/devtools/page/OTHER"},
            {"type": "page", "url": "https://www.allkeyshop.com/blog/wp-admin/",
             "webSocketDebuggerUrl": "ws://h/devtools/page/AKS"},
        ])
        self.assertEqual(path, "/devtools/page/AKS")

    def test_devtools_and_chrome_tabs_filtered(self):
        path = self._pick([
            {"type": "page", "url": "devtools://devtools/bundled/inspector.html",
             "webSocketDebuggerUrl": "ws://h/devtools/page/DT"},
            {"type": "page", "url": "chrome://newtab/",
             "webSocketDebuggerUrl": "ws://h/devtools/page/NT"},
            {"type": "page", "url": "http://plain.test/",
             "webSocketDebuggerUrl": "ws://h/devtools/page/PLAIN"},
        ])
        self.assertEqual(path, "/devtools/page/PLAIN")

    def test_suffix_spoof_host_not_treated_as_aks(self):
        # "evilallkeyshop.com" (listed FIRST) must not steal the AKS
        # preference from the real allkeyshop.com tab (dot-safe suffix check).
        path = self._pick([
            {"type": "page", "url": "https://evilallkeyshop.com/x",
             "webSocketDebuggerUrl": "ws://h/devtools/page/EVIL"},
            {"type": "page", "url": "https://www.allkeyshop.com/blog/",
             "webSocketDebuggerUrl": "ws://h/devtools/page/AKS"},
        ])
        self.assertEqual(path, "/devtools/page/AKS")


if __name__ == "__main__":
    unittest.main()

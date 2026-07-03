"""Read-only CDP session over a raw WebSocket — stdlib only, zero new deps.

Adapted from the skill's proven ``cdp-raw-socket`` transport. Two hard-won
details are preserved: the handshake sends **no Origin header** (which is what
avoids Chrome's 403 from the Docker terminal), and the server frames are read
unmasked (RFC 6455 §5.1). It drives the EXISTING desktop Chrome on the VPS
through the official proxy endpoint.

It exposes ONLY read-only operations — ``navigate`` and ``evaluate_readonly`` —
and refuses to evaluate anything that looks like a mutation (click / submit /
XHR / selectize). It never clicks, fills, or submits. This is not a security
boundary (JS can obfuscate) but a deliberate footgun-preventer for the read-only
extractor stage.

The live socket path cannot be exercised from a sandbox; the pure extractor
logic that uses this session is tested with a fake session
(see ``tests/test_extractor.py``). The read-only refusal IS unit-tested here-free
(it triggers before any I/O).
"""

from __future__ import annotations

import base64
import json
import os
import socket
import time
from urllib.parse import urlparse
from urllib.request import Request, urlopen

# Expressions containing any of these (whitespace-insensitive) tokens are refused.
_FORBIDDEN_EVAL = (
    ".click(",
    ".submit(",
    "dispatchevent",
    "setvalue",
    ".value=",
    "admin-ajax",
    "data-create-offer",
    "xmlhttprequest",
    "fetch(",
    "createelement",
    "appendchild",
    "removechild",
    "document.write",
)


class ReadOnlyEvalError(RuntimeError):
    """Raised when an expression is not obviously read-only."""


def _derive_base(endpoint: str) -> tuple[str, int, str]:
    """From ``http://host:port/json/version`` → ``(host, port, 'http://host:port')``."""

    parsed = urlparse(endpoint)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 80
    return host, port, f"{parsed.scheme}://{host}:{port}"


def is_readonly_expression(expression: str) -> bool:
    """True when ``expression`` contains no known mutation token."""

    collapsed = "".join(expression.split()).lower()
    return not any(tok.replace(" ", "") in collapsed for tok in _FORBIDDEN_EVAL)


class ReadOnlyCdpSession:
    """A minimal, read-only CDP page session."""

    def __init__(self, endpoint: str, *, connect_timeout: int = 10, cmd_timeout: int = 20) -> None:
        self.endpoint = endpoint
        self._host, self._port, self._base = _derive_base(endpoint)
        self._connect_timeout = connect_timeout
        self._cmd_timeout = cmd_timeout
        self._sock: socket.socket | None = None
        self._mid = 0

    # -- lifecycle -------------------------------------------------------
    def open(self) -> "ReadOnlyCdpSession":
        self._sock = self._ws_connect(self._page_ws_path())
        self._cmd("Page.enable")
        self._cmd("Runtime.enable")
        return self

    def close(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            finally:
                self._sock = None

    def __enter__(self) -> "ReadOnlyCdpSession":
        return self.open()

    def __exit__(self, *exc: object) -> bool:
        self.close()
        return False

    # -- read-only operations -------------------------------------------
    def navigate(self, url: str, settle: float = 3.0) -> None:
        self._cmd("Page.navigate", {"url": url})
        if settle:
            time.sleep(settle)

    def _evaluate(self, expression: str) -> object:
        """Raw Runtime.evaluate (no read-only guard). Subclasses use this for their
        own, explicitly-named safe interactions; callers should prefer
        ``evaluate_readonly``."""

        response = self._cmd(
            "Runtime.evaluate",
            {"expression": expression, "returnByValue": True, "awaitPromise": True},
        )
        result = response.get("result", {})
        if "exceptionDetails" in result:
            raise RuntimeError(f"CDP evaluate raised: {result['exceptionDetails']}")
        return result.get("result", {}).get("value")

    def evaluate_readonly(self, expression: str) -> object:
        if not is_readonly_expression(expression):
            raise ReadOnlyEvalError("refusing to evaluate a non-read-only expression")
        return self._evaluate(expression)

    # -- internals (adapted from the skill's proven raw-socket client) ---
    def _page_ws_path(self) -> str:
        targets = json.loads(urlopen(f"{self._base}/json", timeout=self._connect_timeout).read())
        pages = [
            t for t in targets
            if t.get("type") == "page" and "chrome://" not in t.get("url", "")
        ]
        if pages:
            ws_url = pages[0]["webSocketDebuggerUrl"]
        else:
            request = Request(f"{self._base}/json/new", method="PUT")
            ws_url = json.loads(urlopen(request, timeout=self._connect_timeout).read())[
                "webSocketDebuggerUrl"
            ]
        # Keep only the devtools path; connect to the proxy host:port ourselves.
        return urlparse(ws_url).path

    def _ws_connect(self, path: str) -> socket.socket:
        key = base64.b64encode(os.urandom(16)).decode()
        request = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {self._host}:{self._port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            f"Sec-WebSocket-Key: {key}\r\n\r\n"
        )
        sock = socket.socket()
        sock.settimeout(self._connect_timeout)
        sock.connect((self._host, self._port))
        sock.send(request.encode())
        resp = sock.recv(4096)
        if b"101" not in resp:
            raise RuntimeError(f"WS handshake failed: {resp[:200]!r}")
        return sock

    def _ws_send(self, msg: str) -> None:
        assert self._sock is not None
        data = msg.encode()
        mask = os.urandom(4)
        frame = bytearray([0x81])  # FIN + text
        n = len(data)
        if n < 126:
            frame.append(0x80 | n)
        elif n < 65536:
            frame.append(0x80 | 126)
            frame.extend(n.to_bytes(2, "big"))
        else:
            frame.append(0x80 | 127)
            frame.extend(n.to_bytes(8, "big"))
        frame.extend(mask)
        frame.extend(byte ^ mask[i % 4] for i, byte in enumerate(data))
        self._sock.send(bytes(frame))

    def _ws_recv(self, timeout: float = 5.0) -> str | None:
        assert self._sock is not None
        self._sock.settimeout(timeout)
        header = self._sock.recv(2)
        if len(header) < 2:
            return None
        length = header[1] & 0x7F
        if length == 126:
            length = int.from_bytes(self._sock.recv(2), "big")
        elif length == 127:
            length = int.from_bytes(self._sock.recv(8), "big")
        buffer = bytearray()
        while len(buffer) < length:
            chunk = self._sock.recv(length - len(buffer))
            if not chunk:
                break
            buffer.extend(chunk)
        return buffer.decode("utf-8", errors="replace")

    def _cmd(self, method: str, params: dict | None = None) -> dict:
        self._mid += 1
        mid = self._mid
        self._ws_send(json.dumps({"id": mid, "method": method, "params": params or {}}))
        deadline = time.time() + self._cmd_timeout
        while time.time() < deadline:
            try:
                raw = self._ws_recv(3)
            except socket.timeout:
                continue
            if not raw:
                continue
            try:
                data = json.loads(raw)
            except ValueError:
                continue
            if data.get("id") == mid:
                return data
        return {"error": "timeout", "method": method}

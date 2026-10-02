"""One CDP session, several commands.

own_chrome.cdp.evaluate()/navigate() each re-resolve the target tab from a
fresh pages() list on every call (by url_contains/host substring/hostname
match) and open a fresh WebSocket per call. Two gaps that leaves for a
multi-step operation (fill, attach, send, verify) that must stay pinned to
the exact tab it started on (see messaging.linkedin_tab/send_message):

1. DOM.setFileInputFiles needs an objectId minted by a Runtime.evaluate on
   the *same* connection -- own-chrome's public API has no way to do that.
2. Re-resolving by URL on every call means a tab that opens or navigates to
   an attacker URL between steps (e.g. mid-operation, during a sleep) could
   be picked up by a later re-resolution instead of the tab actually chosen
   at the start.

This module covers both: CdpSession for the shared-connection case, and
evaluate_pinned/set_file_input_pinned for routing every step of one
operation through the SAME CDP target (via own_chrome.cdp's public
cdp_call(ws_url, ...), given the target's webSocketDebuggerUrl once) instead
of re-resolving by URL each time. It does not reimplement own-chrome's CLI or
queries.
"""

from __future__ import annotations

import base64
import json
import os
import socket
import urllib.parse
from typing import Any

from own_chrome.cdp import ChromeError, cdp_call, pick_page

JSON = dict[str, Any]  # JSON/CDP boundary: payload shapes are page-defined


class CdpSession:
    """A single WebSocket connection to one Chrome tab, for a short sequence
    of CDP commands that must share objectIds/domain state.

    Pass either (port, url_contains/host) to resolve the tab via
    own_chrome.cdp.pick_page, or an already-known `ws_url` to connect
    directly to that exact CDP target, skipping tab resolution entirely."""

    def __init__(self, port: int = 0, url_contains: str = "", host: str = "", *, ws_url: str = ""):
        if not ws_url:
            page = pick_page(port, url_contains, host)
            ws_url = page.get("webSocketDebuggerUrl") or ""
        if not ws_url:
            raise ChromeError("Tab has no CDP websocket")
        self._sock = self._connect(ws_url)
        self._next_id = 1

    @staticmethod
    def _connect(ws_url: str) -> socket.socket:
        parsed = urllib.parse.urlparse(ws_url)
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or 80
        path = parsed.path or "/"
        if parsed.query:
            path = f"{path}?{parsed.query}"
        sock = socket.create_connection((host, port), timeout=5)
        key = base64.b64encode(os.urandom(16)).decode()
        request = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            "\r\n"
        )
        sock.sendall(request.encode())
        data = b""
        while b"\r\n\r\n" not in data:
            chunk = sock.recv(4096)
            if not chunk:
                break
            data += chunk
        if b" 101 " not in data.split(b"\r\n", 1)[0]:
            raise ChromeError(f"WebSocket upgrade failed: {data[:200]!r}")
        return sock

    def _send_frame(self, text: str) -> None:
        payload = text.encode()
        header = bytearray([0x81])
        length = len(payload)
        if length < 126:
            header.append(0x80 | length)
        elif length < 65536:
            header.append(0x80 | 126)
            header.extend(length.to_bytes(2, "big"))
        else:
            header.append(0x80 | 127)
            header.extend(length.to_bytes(8, "big"))
        mask = os.urandom(4)
        header.extend(mask)
        masked = bytes(byte ^ mask[i % 4] for i, byte in enumerate(payload))
        self._sock.sendall(bytes(header) + masked)

    def _recv_frame(self) -> str:
        def read_exact(n: int) -> bytes:
            buf = b""
            while len(buf) < n:
                chunk = self._sock.recv(n - len(buf))
                if not chunk:
                    raise ChromeError("Chrome closed the CDP socket")
                buf += chunk
            return buf

        first, second = read_exact(2)
        opcode = first & 0x0F
        length = second & 0x7F
        if length == 126:
            length = int.from_bytes(read_exact(2), "big")
        elif length == 127:
            length = int.from_bytes(read_exact(8), "big")
        if second & 0x80:
            mask = read_exact(4)
            payload = bytes(byte ^ mask[i % 4] for i, byte in enumerate(read_exact(length)))
        else:
            payload = read_exact(length)
        if opcode == 0x8:
            raise ChromeError("Chrome closed the CDP session")
        if opcode != 0x1:
            return ""
        return payload.decode()

    def call(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        call_id = self._next_id
        self._next_id += 1
        self._send_frame(json.dumps({"id": call_id, "method": method, "params": params or {}}))
        while True:
            raw = self._recv_frame()
            if not raw:
                continue
            message = json.loads(raw)
            if message.get("id") == call_id:
                if "error" in message:
                    raise ChromeError(json.dumps(message["error"]))
                result: JSON = message.get("result", {})
                return result

    def close(self) -> None:
        try:
            self._sock.close()
        except OSError:
            pass

    def __enter__(self) -> "CdpSession":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()


def _set_file_input_via_session(session: CdpSession, selector: str, file_path: str) -> bool:
    result = session.call(
        "Runtime.evaluate",
        {"expression": f"document.querySelector({json.dumps(selector)})", "returnByValue": False},
    )
    remote = result.get("result", {})
    object_id = remote.get("objectId")
    if not object_id:
        return False
    session.call("DOM.setFileInputFiles", {"files": [file_path], "objectId": object_id})
    return True


def set_file_input(
    port: int, selector: str, file_path: str, url_contains: str = "", host: str = "", ws_url: str = ""
) -> bool:
    """Set a hidden <input type="file"> to file_path via CDP, no clicking the
    real file picker. Returns True if the element was found and set.

    Pass `ws_url` (the exact CDP target captured earlier by the caller, see
    messaging.linkedin_tab/send_message) to connect directly to that target
    instead of re-resolving the tab from `port`/url_contains/host."""
    with CdpSession(port, url_contains, host, ws_url=ws_url) as session:
        return _set_file_input_via_session(session, selector, file_path)


def evaluate_pinned(ws_url: str, expression: str) -> Any:
    """Runtime.evaluate on the exact CDP target at `ws_url`, bypassing
    own_chrome.cdp.evaluate's per-call pages()/pick_page re-resolution.
    Same semantics as own_chrome.cdp.evaluate (returnByValue, awaitPromise,
    exceptionDetails raised as ChromeError), routed through its public
    cdp_call(ws_url, ...) instead of evaluate(port, ..., url_contains/host)."""
    result = cdp_call(ws_url, "Runtime.evaluate", {"expression": expression, "returnByValue": True, "awaitPromise": True})
    if "exceptionDetails" in result:
        raise ChromeError(json.dumps(result["exceptionDetails"])[:500])
    return result.get("result", {}).get("value")

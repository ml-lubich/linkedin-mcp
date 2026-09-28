from __future__ import annotations

import json

import pytest

from linkedin_mcp import cdp_session as cdp_session_mod
from linkedin_mcp.cdp_session import CdpSession, ChromeError, set_file_input


class FakeSocket:
    """A socket-shaped buffer: sendall appends, recv slices off the front."""

    def __init__(self, data: bytes = b""):
        self.buf = bytearray(data)
        self.sent: list[bytes] = []
        self.closed = False

    def sendall(self, data: bytes) -> None:
        self.sent.append(bytes(data))

    def recv(self, n: int) -> bytes:
        chunk = bytes(self.buf[:n])
        del self.buf[:n]
        return chunk

    def close(self) -> None:
        self.closed = True


class RaisingCloseSocket(FakeSocket):
    def close(self) -> None:
        raise OSError("already closed")


def _http_101(extra: bytes = b"") -> bytes:
    return b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n\r\n" + extra


def _http_404() -> bytes:
    return b"HTTP/1.1 404 Not Found\r\n\r\n"


def _server_frame(payload: bytes, opcode: int = 0x1) -> bytes:
    header = bytearray([0x80 | opcode])
    length = len(payload)
    if length < 126:
        header.append(length)
    elif length < 65536:
        header.append(126)
        header.extend(length.to_bytes(2, "big"))
    else:
        header.append(127)
        header.extend(length.to_bytes(8, "big"))
    return bytes(header) + payload


def _bare_session(sock) -> CdpSession:
    session = CdpSession.__new__(CdpSession)
    session._sock = sock
    session._next_id = 1
    return session


def _result_frame(call_id: int, result: dict) -> bytes:
    return _server_frame(json.dumps({"id": call_id, "result": result}).encode())


def _error_frame(call_id: int, message: str) -> bytes:
    return _server_frame(json.dumps({"id": call_id, "error": {"message": message}}).encode())


# ------------------------------------------------------------- handshake ----


def test_connect_success(monkeypatch):
    fake = FakeSocket(_http_101())
    monkeypatch.setattr(cdp_session_mod.socket, "create_connection", lambda *a, **k: fake)
    sock = CdpSession._connect("ws://127.0.0.1:9222/devtools/page/ABC")
    assert sock is fake
    assert fake.sent  # the upgrade request was written


def test_connect_failure_raises(monkeypatch):
    fake = FakeSocket(_http_404())
    monkeypatch.setattr(cdp_session_mod.socket, "create_connection", lambda *a, **k: fake)
    with pytest.raises(ChromeError, match="WebSocket upgrade failed"):
        CdpSession._connect("ws://127.0.0.1:9222/devtools/page/ABC")


def test_connect_handles_url_without_query(monkeypatch):
    fake = FakeSocket(_http_101())
    monkeypatch.setattr(cdp_session_mod.socket, "create_connection", lambda *a, **k: fake)
    CdpSession._connect("ws://localhost:1234/devtools/browser/xyz?foo=bar")


def test_connect_default_host_and_port(monkeypatch):
    fake = FakeSocket(_http_101())
    captured = {}
    monkeypatch.setattr(
        cdp_session_mod.socket,
        "create_connection",
        lambda addr, timeout=None: (captured.setdefault("addr", addr), fake)[1],
    )
    CdpSession._connect("ws:///devtools/page/ABC")
    assert captured["addr"][0] == "127.0.0.1"


def test_connect_closes_on_empty_read(monkeypatch):
    fake = FakeSocket(b"")  # connection closes before any response
    monkeypatch.setattr(cdp_session_mod.socket, "create_connection", lambda *a, **k: fake)
    with pytest.raises(ChromeError):
        CdpSession._connect("ws://127.0.0.1:9222/devtools/page/ABC")


# ----------------------------------------------------------------- init ----


def test_init_uses_pick_page_and_connects(monkeypatch):
    monkeypatch.setattr(
        cdp_session_mod, "pick_page", lambda port, url_contains="", host="": {"webSocketDebuggerUrl": "ws://x/y"}
    )
    fake = FakeSocket()
    monkeypatch.setattr(CdpSession, "_connect", staticmethod(lambda ws_url: fake))
    session = CdpSession(9222, "linkedin.com")
    assert session._sock is fake
    assert session._next_id == 1


def test_init_raises_without_websocket_url(monkeypatch):
    monkeypatch.setattr(cdp_session_mod, "pick_page", lambda port, url_contains="", host="": {})
    with pytest.raises(ChromeError, match="no CDP websocket"):
        CdpSession(9222, "linkedin.com")


# ----------------------------------------------------------------- call ----


def test_call_round_trip():
    sock = FakeSocket(_result_frame(1, {"ok": True}))
    session = _bare_session(sock)
    result = session.call("Runtime.evaluate", {"expression": "1+1"})
    assert result == {"ok": True}
    assert len(sock.sent) == 1  # exactly one frame written for one call


def test_call_raises_on_error_response():
    sock = FakeSocket(_error_frame(1, "boom"))
    session = _bare_session(sock)
    with pytest.raises(ChromeError, match="boom"):
        session.call("DOM.enable")


def test_call_skips_frames_for_other_ids_then_matches():
    # A stray response for id=99 (e.g. a slow earlier call) must not be
    # mistaken for the answer to id=1.
    sock = FakeSocket(_result_frame(99, {"ignored": True}) + _result_frame(1, {"real": True}))
    session = _bare_session(sock)
    result = session.call("Page.navigate", {"url": "https://example.com"})
    assert result == {"real": True}


def test_call_ignores_empty_frames():
    # A continuation/ping-like frame decodes to "" and must be skipped, not
    # returned or crashed on.
    sock = FakeSocket(_server_frame(b"", opcode=0x0) + _result_frame(1, {"ok": True}))
    session = _bare_session(sock)
    assert session.call("Target.ping") == {"ok": True}


def test_call_increments_id_each_time():
    sock = FakeSocket(_result_frame(1, {}) + _result_frame(2, {}))
    session = _bare_session(sock)
    session.call("A")
    session.call("B")
    assert session._next_id == 3


def test_call_unmasks_a_masked_server_frame():
    # Real servers never mask, but the decoder must still handle a masked
    # frame correctly rather than assuming the mask bit is always clear.
    payload = json.dumps({"id": 1, "result": {"ok": True}}).encode()
    mask = bytes([0x12, 0x34, 0x56, 0x78])
    masked_payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
    header = bytearray([0x81, 0x80 | len(masked_payload)])  # mask bit set
    frame = bytes(header) + mask + masked_payload
    sock = FakeSocket(frame)
    session = _bare_session(sock)
    assert session.call("X") == {"ok": True}


@pytest.mark.parametrize("payload_len", [200, 70000])
def test_call_decodes_extended_length_response_frames(payload_len):
    # 200 bytes triggers the 16-bit extended length (0x7E/126); 70000 bytes
    # triggers the 64-bit extended length (0x7F/127) receive-side branch.
    big_result = {"data": "y" * payload_len}
    sock = FakeSocket(_result_frame(1, big_result))
    session = _bare_session(sock)
    assert session.call("X") == big_result


def test_recv_frame_raises_on_close_opcode():
    sock = FakeSocket(_server_frame(b"bye", opcode=0x8))
    session = _bare_session(sock)
    with pytest.raises(ChromeError, match="closed the CDP session"):
        session.call("X")


def test_recv_frame_raises_when_socket_dies_mid_read():
    # Header says a payload is coming, but the socket returns EOF.
    sock = FakeSocket(bytes([0x81, 0x05]))  # text frame, length 5, then nothing
    session = _bare_session(sock)
    with pytest.raises(ChromeError, match="closed the CDP socket"):
        session.call("X")


@pytest.mark.parametrize("payload_len", [10, 200, 70000])
def test_send_frame_length_encoding_branches(payload_len):
    sock = FakeSocket(_result_frame(1, {}))
    session = _bare_session(sock)
    session.call("X", {"big": "y" * payload_len})
    assert sock.sent, "frame should have been written"
    header_first_byte = sock.sent[0][0]
    assert header_first_byte == 0x81  # FIN + text opcode


def test_close_swallows_oserror():
    session = _bare_session(RaisingCloseSocket())
    session.close()  # must not raise


def test_context_manager_closes_on_exit():
    sock = FakeSocket()
    with _bare_session(sock) as session:
        assert session is not None
    assert sock.closed is True


# ----------------------------------------------------------- set_file_input ----


def test_set_file_input_success(monkeypatch):
    monkeypatch.setattr(
        cdp_session_mod, "pick_page", lambda port, url_contains="", host="": {"webSocketDebuggerUrl": "ws://x/y"}
    )
    frames = _result_frame(1, {"result": {"objectId": "obj-1"}}) + _result_frame(2, {})
    fake = FakeSocket(frames)
    monkeypatch.setattr(CdpSession, "_connect", staticmethod(lambda ws_url: fake))
    assert set_file_input(9222, "input[type='file']", "/tmp/x.pdf", "linkedin.com") is True
    assert fake.closed is True


def test_set_file_input_missing_element_returns_false(monkeypatch):
    monkeypatch.setattr(
        cdp_session_mod, "pick_page", lambda port, url_contains="", host="": {"webSocketDebuggerUrl": "ws://x/y"}
    )
    frames = _result_frame(1, {"result": {}})  # no objectId: querySelector found nothing
    fake = FakeSocket(frames)
    monkeypatch.setattr(CdpSession, "_connect", staticmethod(lambda ws_url: fake))
    assert set_file_input(9222, "input[type='file']", "/tmp/x.pdf") is False
    assert fake.closed is True


def test_set_file_input_closes_session_even_on_error(monkeypatch):
    monkeypatch.setattr(
        cdp_session_mod, "pick_page", lambda port, url_contains="", host="": {"webSocketDebuggerUrl": "ws://x/y"}
    )
    fake = FakeSocket(_error_frame(1, "no such frame"))
    monkeypatch.setattr(CdpSession, "_connect", staticmethod(lambda ws_url: fake))
    with pytest.raises(ChromeError):
        set_file_input(9222, "input[type='file']", "/tmp/x.pdf")
    assert fake.closed is True

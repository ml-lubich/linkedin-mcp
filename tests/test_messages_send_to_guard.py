"""Correctness fix (review B1): messages_send(to=NAME) ignored
select_thread's result entirely -- a no-match or ambiguous `to` still typed
and (with confirm=True) sent into whatever thread happened to already be
open. Now it must refuse with a clear error unless select_thread reports
exactly one match, and send_message must never be called in that case."""

from __future__ import annotations

import pytest

import linkedin_mcp.core as core


@pytest.fixture(autouse=True)
def _wire_config(monkeypatch):
    monkeypatch.setattr(core, "load_agent_config", lambda path=None: type("C", (), {"cdp_port": 9222})())


def test_messages_send_refuses_when_to_matches_nothing(monkeypatch):
    monkeypatch.setattr(core.messaging_mod, "select_thread", lambda port, name: {"ok": False, "ambiguous": False, "matches": []})
    called = {"send": False}
    monkeypatch.setattr(core.messaging_mod, "send_message", lambda **kw: called.__setitem__("send", True))

    with pytest.raises(ValueError, match="no thread matched"):
        core.messages_send("hi", to="Nobody", confirm=True)

    assert called["send"] is False


def test_messages_send_refuses_when_to_is_ambiguous(monkeypatch):
    monkeypatch.setattr(
        core.messaging_mod,
        "select_thread",
        lambda port, name: {"ok": False, "ambiguous": True, "matches": ["Ada Lovelace", "Ada Wong"]},
    )
    called = {"send": False}
    monkeypatch.setattr(core.messaging_mod, "send_message", lambda **kw: called.__setitem__("send", True))

    with pytest.raises(ValueError, match="ambiguous"):
        core.messages_send("hi", to="Ada", confirm=True)

    assert called["send"] is False


def test_messages_send_proceeds_when_to_matches_exactly_one(monkeypatch):
    monkeypatch.setattr(core.messaging_mod, "select_thread", lambda port, name: {"ok": True, "ambiguous": False, "matched": "Ada"})
    monkeypatch.setattr(core.messaging_mod, "send_message", lambda **kw: {"sent": True})

    result = core.messages_send("hi", to="Ada", confirm=True)

    assert result == {"sent": True}


def test_messages_send_without_to_never_calls_select_thread(monkeypatch):
    calls = []
    monkeypatch.setattr(core.messaging_mod, "select_thread", lambda *a, **k: calls.append(1))
    monkeypatch.setattr(core.messaging_mod, "send_message", lambda **kw: {"sent": True})

    core.messages_send("hi", confirm=True)

    assert calls == []

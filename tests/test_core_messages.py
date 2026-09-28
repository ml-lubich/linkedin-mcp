"""core.py wrappers for the messaging capabilities absorbed from `li`:
threads listing, select, open, popups, workflow, commands discovery, and
the restored `scan`. Same rule as the rest of core.py: one function per
behavior, called identically by the CLI and by mcp_server.py."""

from __future__ import annotations

import linkedin_mcp.core as core


def test_messages_threads_delegates(monkeypatch) -> None:
    captured = {}
    monkeypatch.setattr(core, "load_agent_config", lambda path=None: type("C", (), {"cdp_port": 9222})())
    monkeypatch.setattr(
        core.messaging_mod,
        "list_threads",
        lambda port, **kw: captured.update(port=port, **kw) or {"threads": [], "url": "u", "title": "t"},
    )
    result = core.messages_threads(needle="acme", limit=5, unread=True)
    assert result == {"threads": [], "url": "u", "title": "t"}
    assert captured["kind"] == "unread"
    assert captured["needle"] == "acme"
    assert captured["limit"] == 5


def test_messages_select_delegates(monkeypatch) -> None:
    monkeypatch.setattr(core, "load_agent_config", lambda path=None: type("C", (), {"cdp_port": 9222})())
    monkeypatch.setattr(core.messaging_mod, "select_thread", lambda port, name: {"ok": True, "matched": name})
    assert core.messages_select("Jordan") == {"ok": True, "matched": "Jordan"}


def test_messages_send_with_to_selects_the_thread_by_name_first(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(core, "load_agent_config", lambda path=None: type("C", (), {"cdp_port": 9222})())
    monkeypatch.setattr(core.messaging_mod, "select_thread", lambda port, name: calls.append(("select", name)) or {"ok": True})
    monkeypatch.setattr(core.messaging_mod, "send_message", lambda **kw: calls.append(("send", kw.get("text"))) or {"sent": True})
    result = core.messages_send("hi", to="Jordan", confirm=True)
    assert result == {"sent": True}
    assert calls == [("select", "Jordan"), ("send", "hi")]


def test_messages_send_without_to_does_not_select(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(core, "load_agent_config", lambda path=None: type("C", (), {"cdp_port": 9222})())
    monkeypatch.setattr(core.messaging_mod, "select_thread", lambda port, name: calls.append("select"))
    monkeypatch.setattr(core.messaging_mod, "send_message", lambda **kw: {"sent": True})
    core.messages_send("hi", confirm=True)
    assert calls == []


def test_messages_open_delegates(monkeypatch) -> None:
    monkeypatch.setattr(core, "load_agent_config", lambda path=None: type("C", (), {"cdp_port": 9222})())
    monkeypatch.setattr(core.messaging_mod, "ensure_messaging", lambda port: {"opened": "already"})
    assert core.messages_open() == {"opened": "already"}


def test_messages_popups_delegates(monkeypatch) -> None:
    captured = {}
    monkeypatch.setattr(core, "load_agent_config", lambda path=None: type("C", (), {"cdp_port": 9222})())
    monkeypatch.setattr(core.messaging_mod, "popups", lambda port, apply, policy: captured.update(apply=apply) or {"action": None})
    assert core.messages_popups(apply=True) == {"action": None}
    assert captured["apply"] is True


def test_messages_workflow_delegates(monkeypatch) -> None:
    monkeypatch.setattr(core.messaging_mod, "workflow_run", lambda spec_path, text, port: {"go": False})
    assert core.messages_workflow("spec.json", text="hi") == {"go": False}


def test_messages_commands_lists_the_catalog() -> None:
    result = core.messages_commands()
    names = [row["name"] for row in result["commands"]]
    assert "select" in names
    assert "send" in names


def test_scan_delegates(monkeypatch) -> None:
    monkeypatch.setattr(core, "load_agent_config", lambda path=None: "cfg")
    monkeypatch.setattr(core.scan_mod, "find_referral_candidates", lambda cfg, port=None: {"Jordan": "candidate"})
    assert core.scan() == {"Jordan": "candidate"}

"""core.py wrappers for the messaging capabilities absorbed from `li`:
threads listing, select, open, popups, workflow, commands discovery, and
the restored `scan`. Same rule as the rest of core.py: one function per
behavior, called identically by the CLI and by mcp_server.py."""

from __future__ import annotations

from pathlib import Path

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


def test_messages_threads_passes_every_kwarg_exactly_with_explicit_port(monkeypatch) -> None:
    captured = {}
    monkeypatch.setattr(core, "load_agent_config", lambda path=None: type("C", (), {"cdp_port": 9222})())
    monkeypatch.setattr(
        core.messaging_mod,
        "list_threads",
        lambda port, **kw: captured.update(port=port, **kw) or {"threads": [], "url": "u", "title": "t"},
    )
    core.messages_threads(needle="acme", limit=5, unread=True, no_navigate=True, port=1234)
    assert captured == {
        "port": 1234,
        "kind": "unread",
        "needle": "acme",
        "limit": 5,
        "no_navigate": True,
    }


def test_messages_threads_default_kind_is_threads_not_unread(monkeypatch) -> None:
    captured = {}
    monkeypatch.setattr(core, "load_agent_config", lambda path=None: type("C", (), {"cdp_port": 9222})())
    monkeypatch.setattr(
        core.messaging_mod,
        "list_threads",
        lambda port, **kw: captured.update(port=port, **kw) or {"threads": []},
    )
    core.messages_threads()
    assert captured == {
        "port": 9222,
        "kind": "threads",
        "needle": "",
        "limit": 20,
        "no_navigate": False,
    }


def test_messages_select_delegates(monkeypatch) -> None:
    monkeypatch.setattr(core, "load_agent_config", lambda path=None: type("C", (), {"cdp_port": 9222})())
    monkeypatch.setattr(core.messaging_mod, "select_thread", lambda port, name: {"ok": True, "matched": name})
    assert core.messages_select("Jordan") == {"ok": True, "matched": "Jordan"}


def test_messages_select_uses_configured_port_by_default(monkeypatch) -> None:
    captured = {}
    monkeypatch.setattr(core, "load_agent_config", lambda path=None: type("C", (), {"cdp_port": 9222})())
    monkeypatch.setattr(
        core.messaging_mod,
        "select_thread",
        lambda port, name: captured.update(port=port, name=name) or {"ok": True},
    )
    core.messages_select("Jordan")
    assert captured == {"port": 9222, "name": "Jordan"}


def test_messages_select_uses_explicit_port_override(monkeypatch) -> None:
    captured = {}
    monkeypatch.setattr(core, "load_agent_config", lambda path=None: type("C", (), {"cdp_port": 9222})())
    monkeypatch.setattr(
        core.messaging_mod,
        "select_thread",
        lambda port, name: captured.update(port=port, name=name) or {"ok": True},
    )
    core.messages_select("Jordan", port=4321)
    assert captured == {"port": 4321, "name": "Jordan"}


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


def test_messages_open_uses_configured_port_by_default(monkeypatch) -> None:
    captured = {}
    monkeypatch.setattr(core, "load_agent_config", lambda path=None: type("C", (), {"cdp_port": 9222})())
    monkeypatch.setattr(core.messaging_mod, "ensure_messaging", lambda port: captured.update(port=port) or {"opened": "already"})
    core.messages_open()
    assert captured["port"] == 9222


def test_messages_open_uses_explicit_port_override(monkeypatch) -> None:
    captured = {}
    monkeypatch.setattr(core, "load_agent_config", lambda path=None: type("C", (), {"cdp_port": 9222})())
    monkeypatch.setattr(core.messaging_mod, "ensure_messaging", lambda port: captured.update(port=port) or {"opened": "already"})
    core.messages_open(port=7777)
    assert captured["port"] == 7777


def test_messages_popups_delegates(monkeypatch) -> None:
    captured = {}
    monkeypatch.setattr(core, "load_agent_config", lambda path=None: type("C", (), {"cdp_port": 9222})())
    monkeypatch.setattr(core.messaging_mod, "popups", lambda port, apply, policy: captured.update(apply=apply) or {"action": None})
    assert core.messages_popups(apply=True) == {"action": None}
    assert captured["apply"] is True


def test_messages_popups_passes_port_and_none_policy_exactly(monkeypatch) -> None:
    captured = {}
    monkeypatch.setattr(core, "load_agent_config", lambda path=None: type("C", (), {"cdp_port": 9222})())
    monkeypatch.setattr(
        core.messaging_mod,
        "popups",
        lambda port, apply, policy: captured.update(port=port, apply=apply, policy=policy) or {"action": None},
    )
    core.messages_popups(apply=False, port=555)
    assert captured == {"port": 555, "apply": False, "policy": None}


def test_messages_popups_uses_configured_port_by_default(monkeypatch) -> None:
    captured = {}
    monkeypatch.setattr(core, "load_agent_config", lambda path=None: type("C", (), {"cdp_port": 9222})())
    monkeypatch.setattr(
        core.messaging_mod,
        "popups",
        lambda port, apply, policy: captured.update(port=port) or {"action": None},
    )
    core.messages_popups()
    assert captured["port"] == 9222


def test_messages_workflow_delegates(monkeypatch) -> None:
    monkeypatch.setattr(core.messaging_mod, "workflow_run", lambda spec_path, text, port: {"go": False})
    assert core.messages_workflow("spec.json", text="hi") == {"go": False}


def test_messages_workflow_passes_every_arg_exactly_including_defaults(monkeypatch) -> None:
    # Updated for review B4: port=None used to reach workflow_run verbatim
    # (which then silently skipped reading the open thread, since its own
    # `port is not None` guard was never true by default) -- it must fall
    # back to config.cdp_port here instead. See
    # test_messages_workflow_port_fallback.py for the focused regression test.
    captured = {}
    monkeypatch.setattr(core, "load_agent_config", lambda path=None: type("C", (), {"cdp_port": 9999})())
    monkeypatch.setattr(
        core.messaging_mod,
        "workflow_run",
        lambda spec_path, text, port: captured.update(spec_path=spec_path, text=text, port=port) or {"go": False},
    )
    core.messages_workflow("spec.json")
    assert captured == {"spec_path": "spec.json", "text": "", "port": 9999}

    core.messages_workflow("other.json", text="hello", port=42)
    assert captured == {"spec_path": "other.json", "text": "hello", "port": 42}


def test_messages_commands_lists_the_catalog() -> None:
    result = core.messages_commands()
    names = [row["name"] for row in result["commands"]]
    assert "select" in names
    assert "send" in names


def test_scan_delegates(monkeypatch) -> None:
    monkeypatch.setattr(core, "load_agent_config", lambda path=None: "cfg")
    monkeypatch.setattr(core.scan_mod, "find_referral_candidates", lambda cfg, port=None: {"Jordan": "candidate"})
    assert core.scan() == {"Jordan": "candidate"}


def test_scan_passes_config_path_and_port_through(monkeypatch) -> None:
    load_calls = {}
    scan_calls = {}

    def fake_load_agent_config(path=None):
        load_calls["path"] = path
        return "cfg-from-path"

    monkeypatch.setattr(core, "load_agent_config", fake_load_agent_config)
    monkeypatch.setattr(
        core.scan_mod,
        "find_referral_candidates",
        lambda cfg, port=None: scan_calls.update(cfg=cfg, port=port) or {},
    )
    core.scan(port=9999, config_path="scan.yaml")
    assert load_calls["path"] == Path("scan.yaml")
    assert scan_calls == {"cfg": "cfg-from-path", "port": 9999}

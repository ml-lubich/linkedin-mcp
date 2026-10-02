"""CLI commands for the messaging capabilities absorbed from `li`."""

from __future__ import annotations

from typer.testing import CliRunner

import linkedin_mcp.core as core
from linkedin_mcp.cli import app

runner = CliRunner()


def test_messages_threads_json(monkeypatch) -> None:
    monkeypatch.setattr(core, "messages_threads", lambda **k: {"threads": [{"name": "Jordan"}], "url": "u", "title": "t"})
    result = runner.invoke(app, ["messages", "threads", "--json"])
    assert result.exit_code == 0
    assert "Jordan" in result.output


def test_messages_threads_unread_flag(monkeypatch) -> None:
    captured = {}
    monkeypatch.setattr(core, "messages_threads", lambda **k: captured.update(k) or {"threads": [], "url": "", "title": ""})
    runner.invoke(app, ["messages", "threads", "--unread", "--json"])
    assert captured["unread"] is True


def test_messages_select_json(monkeypatch) -> None:
    monkeypatch.setattr(core, "messages_select", lambda name, **k: {"ok": True, "matched": name})
    result = runner.invoke(app, ["messages", "select", "Jordan", "--json"])
    assert result.exit_code == 0
    assert "Jordan" in result.output


def test_messages_select_ambiguous_exits_3(monkeypatch) -> None:
    monkeypatch.setattr(core, "messages_select", lambda name, **k: {"ok": False, "ambiguous": True, "matches": ["A", "B"]})
    result = runner.invoke(app, ["messages", "select", "A"])
    assert result.exit_code == 3


def test_messages_select_missing_exits_2(monkeypatch) -> None:
    monkeypatch.setattr(core, "messages_select", lambda name, **k: {"ok": False, "ambiguous": False, "matches": []})
    result = runner.invoke(app, ["messages", "select", "Nobody"])
    assert result.exit_code == 2


def test_messages_open_json(monkeypatch) -> None:
    monkeypatch.setattr(core, "messages_open", lambda **k: {"opened": "already", "ok": True})
    result = runner.invoke(app, ["messages", "open", "--json"])
    assert result.exit_code == 0


def test_messages_popups_apply_flag(monkeypatch) -> None:
    captured = {}
    monkeypatch.setattr(core, "messages_popups", lambda **k: captured.update(k) or {"action": None, "applied": False})
    runner.invoke(app, ["messages", "popups", "--apply", "--json"])
    assert captured["apply"] is True


def test_messages_workflow_json(monkeypatch, tmp_path) -> None:
    spec = tmp_path / "spec.json"
    spec.write_text("{}")
    monkeypatch.setattr(core, "messages_workflow", lambda spec_path, **k: {"go": False, "reason": "regex miss", "sent": False})
    result = runner.invoke(app, ["messages", "workflow", str(spec), "--text", "hi", "--json"])
    assert result.exit_code == 0
    assert '"sent":false' in result.output


def test_messages_commands_json(monkeypatch) -> None:
    monkeypatch.setattr(core, "messages_commands", lambda: {"commands": [{"name": "select", "sends": False, "summary": "s"}]})
    result = runner.invoke(app, ["messages", "commands", "--json"])
    assert result.exit_code == 0
    assert "select" in result.output


def test_messages_send_to_flag(monkeypatch) -> None:
    captured = {}
    monkeypatch.setattr(core, "messages_send", lambda text, **k: captured.update(text=text, **k) or {"sent": True})
    result = runner.invoke(app, ["messages", "send", "hi", "--to", "Jordan", "--confirm", "--json"])
    assert result.exit_code == 0
    assert captured["to"] == "Jordan"


def test_scan_json(monkeypatch) -> None:
    monkeypatch.setattr(core, "scan", lambda **k: {"Jordan": {"name": "Jordan", "url": "u", "unread": True, "text": "hi"}})
    result = runner.invoke(app, ["scan", "--json"])
    assert result.exit_code == 0
    assert "Jordan" in result.output

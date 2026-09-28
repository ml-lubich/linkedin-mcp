"""Correctness fix (review B4): core.messages_workflow ignored
config.cdp_port when port=None, so it never read the open thread's text
(workflow_run's own port-is-not-None guard was never satisfied) -- both the
CLI (`linkedin messages workflow spec.json`, no --port) and the MCP tool
(no port argument) hit this by default."""

from __future__ import annotations

import linkedin_mcp.core as core


def test_messages_workflow_falls_back_to_config_cdp_port(monkeypatch):
    captured = {}
    monkeypatch.setattr(core, "load_agent_config", lambda path=None: type("C", (), {"cdp_port": 9222})())
    monkeypatch.setattr(core.messaging_mod, "workflow_run", lambda spec_path, text, port: captured.update(port=port) or {"go": False})

    core.messages_workflow("spec.json")

    assert captured["port"] == 9222


def test_messages_workflow_explicit_port_overrides_config(monkeypatch):
    captured = {}
    monkeypatch.setattr(core, "load_agent_config", lambda path=None: type("C", (), {"cdp_port": 9222})())
    monkeypatch.setattr(core.messaging_mod, "workflow_run", lambda spec_path, text, port: captured.update(port=port) or {"go": False})

    core.messages_workflow("spec.json", port=7777)

    assert captured["port"] == 7777

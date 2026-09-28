"""MCP server smoke tests: tool discovery, a read tool round-tripping through
core.py, and the confirm guard surfacing as a tool error."""

from __future__ import annotations

import asyncio

import pytest

import linkedin_mcp.core as core
from linkedin_mcp.mcp_server import mcp
from mcp.server.mcpserver.exceptions import UnexpectedToolError


def _run(coro):
    return asyncio.run(coro)


def test_list_tools_includes_expected_names() -> None:
    tools = _run(mcp.list_tools())
    names = {t.name for t in tools}
    for expected in ("feed", "search", "profile", "post", "react", "doctor", "messages_send", "referral_send"):
        assert expected in names
    assert "auth_env" not in names  # never exposed as a remote tool


def test_read_tool_round_trips_a_dataclass_to_a_dict(monkeypatch) -> None:
    from linkedin_mcp.models import Actor, Post

    monkeypatch.setattr(
        core,
        "feed",
        lambda limit=None, config_path=None: [Post(urn="urn:li:activity:1", author=Actor(name="Jane"), text="hi")],
    )
    result = _run(mcp.call_tool("feed", {}))
    assert result.is_error is False
    import json as _json

    payload = _json.loads(result.content[0].text)
    assert payload["untrusted"] is True
    posts = payload["result"]
    assert posts[0]["text"] == "hi"
    assert posts[0]["author"]["name"] == "Jane"


def test_write_tool_without_confirm_raises_tool_error(monkeypatch) -> None:
    called = {"post": False}
    monkeypatch.setattr(core, "_voyager_client", lambda config_path=None: called)  # never used if guarded

    with pytest.raises(UnexpectedToolError) as excinfo:
        _run(mcp.call_tool("react", {"identifier": "urn:li:activity:1"}))
    assert "confirm=True" in str(excinfo.value.__cause__)
    assert called["post"] is False


def test_write_tool_with_confirm_reaches_core(monkeypatch) -> None:
    captured = {}

    def fake_react(identifier, reaction_type="like", confirm=False, config_path=None):
        captured.update(identifier=identifier, reaction_type=reaction_type, confirm=confirm)
        return "reacted"

    monkeypatch.setattr(core, "react", fake_react)
    result = _run(mcp.call_tool("react", {"identifier": "urn:li:activity:1", "confirm": True}))
    assert result.is_error is False
    assert captured == {"identifier": "urn:li:activity:1", "reaction_type": "like", "confirm": True}


# ---- coverage: remaining tool wrappers just prove passthrough -----------


@pytest.mark.parametrize(
    "tool_name,core_name,args,expected_positional,expected_kwargs",
    [
        ("unreact", "unreact", {"identifier": "u1", "confirm": True}, ("u1",), {"confirm": True, "config_path": None}),
        ("save", "save_activity", {"identifier": "u1", "confirm": True}, ("u1",), {"confirm": True, "config_path": None}),
        ("unsave", "unsave_activity", {"identifier": "u1", "confirm": True}, ("u1",), {"confirm": True, "config_path": None}),
        (
            "comment",
            "comment",
            {"identifier": "u1", "text": "nice", "confirm": True},
            ("u1", "nice"),
            {"confirm": True, "config_path": None},
        ),
        ("doctor", "doctor", {}, (), {"config_path": None}),
        (
            "classify",
            "classify_message",
            {"text": "hiring"},
            ("hiring",),
            {"name": "", "headline": "", "config_path": None},
        ),
        ("post_cdp_draft", "post_cdp_draft", {"text": "hi"}, ("hi",), {}),
        ("messages_read", "messages_read", {}, (), {"url": "", "limit": 40, "port": None, "config_path": None}),
        (
            "referral_draft",
            "referral_draft",
            {"name": "Jordan", "text": "hiring"},
            ("Jordan", "hiring"),
            {"headline": "", "reengage": False, "stale_days": 0, "config_path": None},
        ),
        ("auth_capture", "auth_capture", {}, (), {"port": 9333, "timeout": 600.0}),
    ],
)
def test_tool_delegates_to_core(monkeypatch, tool_name, core_name, args, expected_positional, expected_kwargs):
    captured = {}

    str_returning_tools = {"unreact", "save", "unsave", "comment"}

    def fake(*a, **kwargs):
        captured["positional"] = a
        captured.update(kwargs)
        if tool_name == "post_cdp_draft":
            return {"text": "hi", "problems": []}
        if tool_name in str_returning_tools:
            return "ok"
        return {}

    monkeypatch.setattr(core, core_name, fake)
    result = _run(mcp.call_tool(tool_name, args))
    assert result.is_error is False
    assert captured["positional"] == expected_positional
    for key, value in expected_kwargs.items():
        assert captured.get(key) == value


def test_referral_send_tool_delegates(monkeypatch):
    captured = {}

    def fake_referral_send(*a, **kwargs):
        captured.update(kwargs)
        return {"name": "Jordan", "skipped": "", "draft": "hi", "proof": {"sent": True}}

    monkeypatch.setattr(core, "referral_send", fake_referral_send)
    result = _run(mcp.call_tool("referral_send", {"name": "Jordan", "url": "https://x", "confirm": True}))
    assert result.is_error is False
    assert captured["confirm"] is True


# ---- messaging tools absorbed from `li` (Phase 2) -------------------------


def test_messages_select_tool_delegates(monkeypatch) -> None:
    monkeypatch.setattr(core, "messages_select", lambda name, **k: {"ok": True, "matched": name})
    result = _run(mcp.call_tool("messages_select", {"name": "Jordan"}))
    assert result.is_error is False
    import json as _json
    assert _json.loads(result.content[0].text)["matched"] == "Jordan"


def test_messages_threads_tool_delegates(monkeypatch) -> None:
    captured = {}
    monkeypatch.setattr(core, "messages_threads", lambda **k: captured.update(k) or {"threads": []})
    result = _run(mcp.call_tool("messages_threads", {"filter": "acme", "unread": True}))
    assert result.is_error is False
    assert captured["needle"] == "acme"
    assert captured["unread"] is True


def test_scan_tool_converts_dataclasses(monkeypatch) -> None:
    from linkedin_mcp.scan import Candidate

    monkeypatch.setattr(core, "scan", lambda **k: {"Jordan": Candidate(name="Jordan", url="u", unread=True, text="hi")})
    result = _run(mcp.call_tool("scan", {}))
    assert result.is_error is False
    import json as _json
    payload = _json.loads(result.content[0].text)
    assert payload["untrusted"] is True
    assert payload["result"]["Jordan"]["unread"] is True


def test_messages_workflow_tool_never_sends(monkeypatch, tmp_path) -> None:
    spec = tmp_path / "spec.json"
    spec.write_text("{}")
    monkeypatch.setattr(core, "messages_workflow", lambda spec_path, **k: {"go": False, "sent": False})
    result = _run(mcp.call_tool("messages_workflow", {"spec_path": str(spec)}))
    assert result.is_error is False
    import json as _json
    payload = _json.loads(result.content[0].text)
    assert payload["untrusted"] is True
    assert payload["result"]["sent"] is False


def test_main_runs_the_stdio_server(monkeypatch) -> None:
    from linkedin_mcp import mcp_server

    captured = {}
    monkeypatch.setattr(mcp_server.mcp, "run", lambda **kwargs: captured.update(kwargs))
    mcp_server.main()
    assert captured == {"transport": "stdio"}

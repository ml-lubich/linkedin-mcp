"""Hardened parity (review B7): for every CLI command and its paired MCP
tool, invoking both must hit the exact same core.py function with the same
config_path -- not just "a tool with a matching name exists" (that's
test_mcp_parity.py's job). This is what actually catches a B6-class bug
(--config silently dropped by one surface but not the other, or the two
surfaces quietly calling different core functions)."""

from __future__ import annotations

import asyncio

from typer.testing import CliRunner

import linkedin_mcp.core as core
from linkedin_mcp.cli import app
from linkedin_mcp.mcp_server import mcp

runner = CliRunner()


def _run(coro):
    return asyncio.run(coro)


# (cli_argv_after_config, mcp_tool_name, mcp_tool_args, core_fn_name, stub_result)
CASES = [
    (["feed"], "feed", {}, "feed", []),
    (["search", "x"], "search", {"query": "x"}, "search", []),
    (["profile", "jane"], "profile", {"identifier": "jane"}, "get_profile", None),
    (["profile-posts", "jane"], "profile_posts", {"identifier": "jane"}, "get_profile_posts", []),
    (["activity", "u1"], "activity", {"identifier": "u1"}, "get_activity", None),
    (["auth-status"], "auth_status", {}, "auth_diagnostics", {"ok": True}),
    (["doctor"], "doctor", {}, "doctor", {"ok": True, "checks": []}),
    (["classify", "hi"], "classify", {"text": "hi"}, "classify_message", {"hiring": False, "excluded": False, "exclude_reason": "", "already_referred": False}),
    # post_cdp_draft is pure text linting -- core.post_cdp_draft(text) takes no
    # config_path at all, correctly, so it's not in the config-passthrough check.
    (["post-cdp", "publish", "hi", "--confirm"], "post_cdp_publish", {"text": "hi", "confirm": True}, "post_cdp_publish", {"clicked_post": True}),
    (["messages", "open"], "messages_open", {}, "messages_open", {"opened": "already", "ok": True}),
    (["messages", "threads"], "messages_threads", {}, "messages_threads", {"threads": []}),
    (["messages", "select", "Jordan"], "messages_select", {"name": "Jordan"}, "messages_select", {"ok": True, "matched": "Jordan"}),
    (["messages", "read"], "messages_read", {}, "messages_read", {"bodies": []}),
    (["messages", "send", "hi", "--confirm"], "messages_send", {"text": "hi", "confirm": True}, "messages_send", {"sent": True}),
    (["messages", "popups"], "messages_popups", {}, "messages_popups", {"action": None, "applied": False}),
    (["messages", "workflow", "spec.json"], "messages_workflow", {"spec_path": "spec.json"}, "messages_workflow", {"go": False, "reason": "regex miss", "sent": False}),
    (["referral", "draft", "Jordan", "hi"], "referral_draft", {"name": "Jordan", "text": "hi"}, "referral_draft", {"draft": "hi", "problems": []}),
    (["referral", "send", "Jordan", "https://x", "--confirm"], "referral_send", {"name": "Jordan", "url": "https://x", "confirm": True}, "referral_send", {"name": "Jordan", "skipped": "", "draft": "hi", "proof": {"sent": True}}),
    (["scan"], "scan", {}, "scan", {}),
]


def test_cli_and_mcp_tool_hit_the_same_core_function_with_the_same_config_path(monkeypatch) -> None:
    from linkedin_mcp.models import Actor, Post, Profile

    for argv, tool_name, tool_args, core_fn_name, stub_result in CASES:
        if core_fn_name == "get_profile":
            stub_result = Profile(public_id="jane")
        elif core_fn_name == "get_activity":
            stub_result = Post(urn="u1", author=Actor(name="A"), text="hi")

        cli_captured = {}
        mcp_captured = {}

        def make_recorder(sink):
            def recorder(*a, **kw):
                sink["config_path"] = kw.get("config_path")
                sink["called"] = True
                return stub_result

            return recorder

        # CLI call
        monkeypatch.setattr(core, core_fn_name, make_recorder(cli_captured))
        cli_result = runner.invoke(app, ["--config", "cfg.toml", *argv])
        assert cli_captured.get("called"), f"CLI {argv} never called core.{core_fn_name} (exit={cli_result.exit_code}, out={cli_result.output})"
        assert cli_captured.get("config_path") == "cfg.toml", f"CLI {argv} did not pass --config to core.{core_fn_name}"

        # MCP tool call, same underlying core function, same config_path
        monkeypatch.setattr(core, core_fn_name, make_recorder(mcp_captured))
        mcp_result = _run(mcp.call_tool(tool_name, {**tool_args, "config_path": "cfg.toml"}))
        assert mcp_result.is_error is False, f"MCP {tool_name} errored: {mcp_result}"
        assert mcp_captured.get("called"), f"MCP tool {tool_name} never called core.{core_fn_name}"
        assert mcp_captured.get("config_path") == "cfg.toml", f"MCP tool {tool_name} did not pass config_path to core.{core_fn_name}"

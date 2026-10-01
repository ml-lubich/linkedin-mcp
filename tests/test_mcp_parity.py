"""CLI <-> MCP parity: every CLI command must have a matching MCP tool, and
vice versa, except the explicit allowlist below. This is what keeps the two
surfaces (cli.py, mcp_server.py) from drifting apart as commands are added.
"""

from __future__ import annotations

import asyncio

import typer

from linkedin_mcp.cli import app
from linkedin_mcp.mcp_server import mcp

# CLI commands with intentionally no MCP tool, and why:
#  - serve: starts the MCP server itself; a tool of itself makes no sense.
#  - auth_env: the one command that reads a raw cookie value back out. Never
#    exposed as an MCP tool -- an MCP client/LLM should not receive it.
#  - prompt: prompt template inspection & emission subcommand (reflected via prompt_manager / helper).
CLI_ONLY = {"serve", "auth_env", "prompt"}


# MCP tools with intentionally no matching CLI command (none yet).
MCP_ONLY: set[str] = set()


def _cli_command_names() -> set[str]:
    group = typer.main.get_command(app)
    names: set[str] = set()

    def walk(cmd, prefix: str) -> None:
        # Typer vendors its own click internally (typer._click), so a plain
        # `isinstance(cmd, click.Group)` never matches -- duck-type instead.
        sub_commands = getattr(cmd, "commands", None)
        if sub_commands:
            for sub_name, sub_cmd in sub_commands.items():
                walk(sub_cmd, f"{prefix}_{sub_name}" if prefix else sub_name)
        else:
            names.add(prefix.replace("-", "_"))

    walk(group, "")
    names.discard("")
    return names


def _mcp_tool_names() -> set[str]:
    async def _list() -> set[str]:
        tools = await mcp.list_tools()
        return {t.name for t in tools}

    return asyncio.run(_list())


def test_every_cli_command_has_an_mcp_tool_or_is_allowlisted() -> None:
    cli_names = _cli_command_names()
    tool_names = _mcp_tool_names()
    missing = (cli_names - tool_names) - CLI_ONLY
    assert not missing, f"CLI commands with no MCP tool and not allowlisted: {sorted(missing)}"


def test_every_mcp_tool_has_a_cli_command_or_is_allowlisted() -> None:
    cli_names = _cli_command_names()
    tool_names = _mcp_tool_names()
    missing = (tool_names - cli_names) - MCP_ONLY
    assert not missing, f"MCP tools with no CLI command and not allowlisted: {sorted(missing)}"


def test_allowlisted_cli_only_commands_actually_exist() -> None:
    """Guards against the allowlist going stale (e.g. a command renamed)."""
    cli_names = _cli_command_names()
    assert CLI_ONLY <= cli_names

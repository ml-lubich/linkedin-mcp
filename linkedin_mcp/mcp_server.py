"""MCP server: every tool here is a one-line wrapper around a function in
core.py, so an MCP client and the `linkedin`/`linkedin-mcp` CLI always do the
exact same thing (see tests/test_mcp_parity.py, which fails if a tool and its
CLI command drift apart).

Write/send/publish tools take an explicit `confirm: bool` argument mirroring
the CLI's `--confirm` flag; without it, core.py refuses to act.

Run as `linkedin-mcp serve`, or configure a client with:
    {"command": "linkedin-mcp", "args": ["serve"]}
"""

from __future__ import annotations

from typing import Optional

from mcp.server.mcpserver import MCPServer

from . import core
from .serialization import post_to_dict, profile_to_dict, search_result_to_dict

mcp = MCPServer("linkedin-mcp")


# ---- read-only Voyager tools --------------------------------------------


@mcp.tool()
def auth_status(config_path: Optional[str] = None) -> dict:
    """Validate the current LinkedIn session and return identity metadata."""
    return core.auth_status(config_path)


@mcp.tool()
def feed(max: Optional[int] = None, config_path: Optional[str] = None) -> list[dict]:
    """Fetch the authenticated home feed."""
    return [post_to_dict(p) for p in core.feed(limit=max, config_path=config_path)]


@mcp.tool()
def search(query: str, max: Optional[int] = None, config_path: Optional[str] = None) -> list[dict]:
    """Search LinkedIn entities and posts."""
    return [search_result_to_dict(r) for r in core.search(query, limit=max, config_path=config_path)]


@mcp.tool()
def profile(identifier: str, config_path: Optional[str] = None) -> dict:
    """Fetch a LinkedIn profile by public id or URL."""
    return profile_to_dict(core.get_profile(identifier, config_path=config_path))


@mcp.tool()
def profile_posts(identifier: str, max: Optional[int] = None, config_path: Optional[str] = None) -> list[dict]:
    """Fetch posts for a LinkedIn profile."""
    return [post_to_dict(p) for p in core.get_profile_posts(identifier, limit=max, config_path=config_path)]


@mcp.tool()
def activity(identifier: str, config_path: Optional[str] = None) -> dict:
    """Fetch a LinkedIn activity (post) detail, with comments and reactions."""
    return post_to_dict(core.get_activity(identifier, config_path=config_path))


# ---- Voyager/browser write tools (confirm-gated) ------------------------


@mcp.tool()
def post(text: str, visibility: str = "connections", confirm: bool = False, config_path: Optional[str] = None) -> str:
    """Publish a new LinkedIn post through the Playwright browser fallback. Requires confirm=True."""
    return core.publish_post(text, visibility=visibility, confirm=confirm, config_path=config_path)


@mcp.tool()
def react(identifier: str, reaction_type: str = "like", confirm: bool = False, config_path: Optional[str] = None) -> str:
    """React to a LinkedIn activity. Requires confirm=True."""
    return core.react(identifier, reaction_type=reaction_type, confirm=confirm, config_path=config_path)


@mcp.tool()
def unreact(identifier: str, confirm: bool = False, config_path: Optional[str] = None) -> str:
    """Remove the current reaction from a LinkedIn activity. Requires confirm=True."""
    return core.unreact(identifier, confirm=confirm, config_path=config_path)


@mcp.tool()
def save(identifier: str, confirm: bool = False, config_path: Optional[str] = None) -> str:
    """Save a LinkedIn activity. Requires confirm=True."""
    return core.save_activity(identifier, confirm=confirm, config_path=config_path)


@mcp.tool()
def unsave(identifier: str, confirm: bool = False, config_path: Optional[str] = None) -> str:
    """Remove a saved LinkedIn activity. Requires confirm=True."""
    return core.unsave_activity(identifier, confirm=confirm, config_path=config_path)


@mcp.tool()
def comment(identifier: str, text: str, confirm: bool = False, config_path: Optional[str] = None) -> str:
    """Comment on a LinkedIn activity. Requires confirm=True."""
    return core.comment(identifier, text, confirm=confirm, config_path=config_path)


# ---- CDP agent tools: drive the user's own logged-in Chrome -------------


@mcp.tool()
def doctor(config_path: Optional[str] = None) -> dict:
    """Check own-chrome, Chrome's CDP port, LinkedIn login, and referral config."""
    return core.doctor(config_path=config_path)


@mcp.tool()
def classify(text: str, name: str = "", headline: str = "", config_path: Optional[str] = None) -> dict:
    """Classify a message: hiring? excluded? already referred?"""
    return core.classify_message(text, name=name, headline=headline, config_path=config_path)


@mcp.tool()
def post_cdp_draft(text: str) -> dict:
    """Lint post text against the anti-cringe rules. Never touches the browser."""
    return core.post_cdp_draft(text)


@mcp.tool()
def post_cdp_publish(
    text: str,
    image: Optional[str] = None,
    confirm: bool = False,
    port: Optional[int] = None,
    config_path: Optional[str] = None,
) -> dict:
    """Fill the feed composer and, only with confirm=True, publish (own logged-in Chrome via CDP)."""
    return core.post_cdp_publish(text, image=image, confirm=confirm, port=port, config_path=config_path)


@mcp.tool()
def messages_read(url: str = "", max: int = 40, port: Optional[int] = None, config_path: Optional[str] = None) -> dict:
    """Read the open LinkedIn message thread (or one named by url)."""
    return core.messages_read(url=url, limit=max, port=port, config_path=config_path)


@mcp.tool()
def messages_send(
    text: str,
    attach: Optional[str] = None,
    attach_name: Optional[str] = None,
    target: str = "",
    confirm: bool = False,
    port: Optional[int] = None,
    config_path: Optional[str] = None,
) -> dict:
    """Fill the compose box and, only with confirm=True, send. Requires confirm=True."""
    return core.messages_send(
        text, attach=attach, attach_name=attach_name, target=target, confirm=confirm, port=port, config_path=config_path
    )


@mcp.tool()
def referral_draft(
    name: str,
    text: str,
    headline: str = "",
    reengage: bool = False,
    stale_days: int = 0,
    config_path: Optional[str] = None,
) -> dict:
    """Draft a referral message. Never touches the browser."""
    return core.referral_draft(
        name, text, headline=headline, reengage=reengage, stale_days=stale_days, config_path=config_path
    )


@mcp.tool()
def referral_send(
    name: str,
    url: str,
    text: str = "",
    stamp: str = "",
    confirm: bool = False,
    port: Optional[int] = None,
    config_path: Optional[str] = None,
) -> dict:
    """Draft and, only with confirm=True, send a referral (text + resume). Requires confirm=True."""
    return core.referral_send(name, url, text=text, stamp=stamp, confirm=confirm, port=port, config_path=config_path)


# ---- session cookie capture ----------------------------------------------


@mcp.tool()
def auth_capture(port: int = 9333, timeout: float = 600.0) -> dict:
    """Poll a CDP-attached Chrome until logged in to LinkedIn, then save the session cookie."""
    return core.auth_capture(port=port, timeout=timeout)


def main() -> None:
    """Entry point for `linkedin-mcp serve`: run the stdio MCP server."""
    mcp.run(transport="stdio")


if __name__ == "__main__":  # pragma: no cover
    main()

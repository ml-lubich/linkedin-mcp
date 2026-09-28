"""CLI entrypoint for linkedin-mcp. Every command is a thin wrapper around
core.py -- the same functions the MCP server calls (see mcp_server.py and
tests/test_mcp_parity.py, which fails if a command and its tool drift apart).
"""

from __future__ import annotations

import logging
import sys
from typing import Optional

import typer
from rich.console import Console

from . import __version__, core
from .formatter import (
    build_search_table,
    build_status_panel,
    print_post_detail,
    print_post_table,
    print_profile,
)
from .serialization import posts_to_json, profile_to_dict, search_results_to_json, to_json

console = Console(stderr=True)
REACTION_CHOICES = ["like", "celebrate", "support", "love", "insightful", "curious"]

app = typer.Typer(name="linkedin", help="linkedin - LinkedIn CLI + MCP server.", add_completion=False)
auth_app = typer.Typer(help="Manage the LinkedIn session cookie.", no_args_is_help=True)
post_cdp_app = typer.Typer(help="Draft or publish a feed post over your own logged-in Chrome (CDP).", no_args_is_help=True)
messages_app = typer.Typer(help="Read or send a LinkedIn message in the open thread (CDP).", no_args_is_help=True)
referral_app = typer.Typer(help="Draft or send a referral message (CDP).", no_args_is_help=True)
app.add_typer(auth_app, name="auth")
app.add_typer(post_cdp_app, name="post-cdp")
app.add_typer(messages_app, name="messages")
app.add_typer(referral_app, name="referral")


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(__version__)
        raise typer.Exit()


@app.callback()
def main_callback(
    ctx: typer.Context,
    config_path: Optional[str] = typer.Option(None, "--config", help="Path to a config YAML/TOML file."),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable debug logging."),
    version: Optional[bool] = typer.Option(
        None, "--version", callback=_version_callback, is_eager=True, help="Show version and exit."
    ),
) -> None:
    """linkedin - LinkedIn CLI."""
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )
    ctx.ensure_object(dict)
    ctx.obj["config_path"] = config_path


def _config_path(ctx: typer.Context) -> Optional[str]:
    return (ctx.obj or {}).get("config_path")


def _write_output(output_file: Optional[str], payload: str) -> None:
    if output_file:
        from pathlib import Path

        Path(output_file).write_text(payload + "\n", encoding="utf-8")


def _handle_error(exc: Exception) -> None:
    console.print(build_status_panel("linkedin", False, str(exc)))
    raise typer.Exit(1)


# ---- read-only Voyager commands -----------------------------------------


@app.command("auth-status")
def auth_status_cmd(ctx: typer.Context) -> None:
    """Verify the current LinkedIn session."""
    try:
        payload = core.auth_diagnostics(config_path=_config_path(ctx))
    except Exception as exc:
        _handle_error(exc)
        return
    success = bool(payload.get("ok"))
    detail_lines = []
    identity = payload.get("public_id") or payload.get("full_name")
    summary_parts = [f"source={payload.get('source', 'unknown')}"]
    if payload.get("browser"):
        summary_parts.append(f"browser={payload['browser']}")
    if identity:
        summary_parts.append(f"identity={identity}")
    summary_parts.append(f"cookies={payload.get('cookie_count', 0)}")
    detail_lines.append(" | ".join(summary_parts))

    validation = payload.get("validation") or {}
    if validation.get("ok"):
        detail_lines.append("basic-probe=ok")
    else:
        probe_line = f"basic-probe={validation.get('kind') or 'error'}"
        if validation.get("status_code") is not None:
            probe_line += f":{validation['status_code']}"
        if validation.get("location"):
            probe_line += f" -> {validation['location']}"
        elif validation.get("error"):
            probe_line += f" ({validation['error']})"
        detail_lines.append(probe_line)

    for name, result in (payload.get("probes") or {}).items():
        if result.get("ok"):
            probe_line = f"{name}=ok"
            if result.get("status_code") is not None:
                probe_line += f":{result['status_code']}"
            detail_lines.append(probe_line)
            continue
        probe_line = f"{name}={result.get('reason') or result.get('kind') or 'error'}"
        if result.get("status_code") is not None:
            probe_line += f":{result['status_code']}"
        if result.get("location"):
            probe_line += f" -> {result['location']}"
        elif result.get("error"):
            probe_line += f" ({result['error']})"
        detail_lines.append(probe_line)

    if payload.get("hint"):
        detail_lines.append(f"hint={payload['hint']}")

    title = "Authentication OK" if success else "Authentication degraded"
    console.print(build_status_panel(title, success, "\n".join(detail_lines)))
    if not success:
        raise typer.Exit(1)


@auth_app.command("capture")
def auth_capture_cmd(
    port: int = typer.Option(9333, "--port", help="Chrome CDP port to poll."),
    timeout: float = typer.Option(600.0, "--timeout", help="Seconds to wait for a login."),
    as_json: bool = typer.Option(False, "--json", help="Emit JSON to stdout."),
) -> None:
    """Poll a CDP-attached Chrome until logged in, then save the session cookie. Never prints cookie values."""
    result = core.auth_capture(port=port, timeout=timeout)
    if as_json:
        typer.echo(to_json(result))
    else:
        console.print(build_status_panel("Session capture", bool(result.get("captured")), str(result)))
    if not result.get("captured"):
        raise typer.Exit(1)


@auth_app.command("env")
def auth_env_cmd() -> None:
    """Print `export LINKEDIN_COOKIE_HEADER=...` for the saved session."""
    try:
        typer.echo(core.auth_env())
    except Exception as exc:
        _handle_error(exc)


@app.command()
def feed(
    ctx: typer.Context,
    max_count: Optional[int] = typer.Option(None, "--max", help="Maximum number of feed items to fetch."),
    as_json: bool = typer.Option(False, "--json", help="Emit JSON to stdout."),
    output_file: Optional[str] = typer.Option(None, "--output", "-o", help="Write JSON output to a file."),
) -> None:
    """Fetch the authenticated home feed."""
    try:
        posts = core.feed(limit=max_count, config_path=_config_path(ctx))
    except Exception as exc:
        _handle_error(exc)
        return
    payload = posts_to_json(posts)
    _write_output(output_file, payload)
    if as_json:
        typer.echo(payload)
        return
    print_post_table(posts, console=console, title="LinkedIn feed")


@app.command()
def search(
    ctx: typer.Context,
    query: str,
    max_count: Optional[int] = typer.Option(None, "--max", help="Maximum number of search results to fetch."),
    as_json: bool = typer.Option(False, "--json", help="Emit JSON to stdout."),
    output_file: Optional[str] = typer.Option(None, "--output", "-o", help="Write JSON output to a file."),
) -> None:
    """Search LinkedIn entities and posts."""
    try:
        results = core.search(query, limit=max_count, config_path=_config_path(ctx))
    except Exception as exc:
        _handle_error(exc)
        return
    payload = search_results_to_json(results)
    _write_output(output_file, payload)
    if as_json:
        typer.echo(payload)
        return
    console.print(build_search_table(results, title=f"Search: {query}"))


@app.command()
def profile(
    ctx: typer.Context,
    identifier: str,
    as_json: bool = typer.Option(False, "--json", help="Emit JSON to stdout."),
) -> None:
    """Fetch a LinkedIn profile by public id or URL."""
    try:
        result = core.get_profile(identifier, config_path=_config_path(ctx))
    except Exception as exc:
        _handle_error(exc)
        return
    if as_json:
        typer.echo(to_json(profile_to_dict(result)))
        return
    print_profile(result, console=console)


@app.command("profile-posts")
def profile_posts(
    ctx: typer.Context,
    identifier: str,
    max_count: Optional[int] = typer.Option(None, "--max", help="Maximum number of posts to fetch."),
    as_json: bool = typer.Option(False, "--json", help="Emit JSON to stdout."),
    output_file: Optional[str] = typer.Option(None, "--output", "-o", help="Write JSON output to a file."),
) -> None:
    """Fetch posts for a LinkedIn profile."""
    try:
        posts = core.get_profile_posts(identifier, limit=max_count, config_path=_config_path(ctx))
    except Exception as exc:
        _handle_error(exc)
        return
    payload = posts_to_json(posts)
    _write_output(output_file, payload)
    if as_json:
        typer.echo(payload)
        return
    print_post_table(posts, console=console, title=f"Posts by {identifier}")


@app.command()
def activity(
    ctx: typer.Context,
    identifier: str,
    as_json: bool = typer.Option(False, "--json", help="Emit JSON to stdout."),
) -> None:
    """Fetch a LinkedIn activity detail."""
    try:
        post = core.get_activity(identifier, config_path=_config_path(ctx))
    except Exception as exc:
        _handle_error(exc)
        return
    if as_json:
        typer.echo(to_json(post))
        return
    print_post_detail(post, console=console)


# ---- Voyager/browser write commands (confirm-gated) ---------------------


@app.command()
def post(
    ctx: typer.Context,
    text: str,
    visibility: str = typer.Option("connections", "--visibility"),
    confirm: bool = typer.Option(False, "--confirm", help="Actually publish. Without this, nothing is posted."),
) -> None:
    """Publish a new LinkedIn post through the Playwright browser fallback."""
    try:
        detail = core.publish_post(text, visibility=visibility, confirm=confirm, config_path=_config_path(ctx))
    except Exception as exc:
        _handle_error(exc)
        return
    console.print(build_status_panel("Post created", True, detail))


@app.command()
def react(
    ctx: typer.Context,
    identifier: str,
    reaction_type: str = typer.Option("like", "--type"),
    confirm: bool = typer.Option(False, "--confirm", help="Actually react. Without this, nothing is sent."),
) -> None:
    """React to a LinkedIn activity."""
    if reaction_type not in REACTION_CHOICES:
        _handle_error(ValueError(f"--type must be one of: {', '.join(REACTION_CHOICES)}"))
        return
    try:
        detail = core.react(identifier, reaction_type=reaction_type, confirm=confirm, config_path=_config_path(ctx))
    except Exception as exc:
        _handle_error(exc)
        return
    console.print(build_status_panel("Reaction applied", True, detail))


@app.command()
def unreact(
    ctx: typer.Context,
    identifier: str,
    confirm: bool = typer.Option(False, "--confirm", help="Actually remove the reaction. Without this, nothing is sent."),
) -> None:
    """Remove the current reaction from a LinkedIn activity."""
    try:
        detail = core.unreact(identifier, confirm=confirm, config_path=_config_path(ctx))
    except Exception as exc:
        _handle_error(exc)
        return
    console.print(build_status_panel("Reaction removed", True, detail))


@app.command()
def save(
    ctx: typer.Context,
    identifier: str,
    confirm: bool = typer.Option(False, "--confirm", help="Actually save. Without this, nothing is sent."),
) -> None:
    """Save a LinkedIn activity."""
    try:
        detail = core.save_activity(identifier, confirm=confirm, config_path=_config_path(ctx))
    except Exception as exc:
        _handle_error(exc)
        return
    console.print(build_status_panel("Post saved", True, detail))


@app.command()
def unsave(
    ctx: typer.Context,
    identifier: str,
    confirm: bool = typer.Option(False, "--confirm", help="Actually unsave. Without this, nothing is sent."),
) -> None:
    """Remove a saved LinkedIn activity."""
    try:
        detail = core.unsave_activity(identifier, confirm=confirm, config_path=_config_path(ctx))
    except Exception as exc:
        _handle_error(exc)
        return
    console.print(build_status_panel("Post unsaved", True, detail))


@app.command()
def comment(
    ctx: typer.Context,
    identifier: str,
    text: str,
    confirm: bool = typer.Option(False, "--confirm", help="Actually comment. Without this, nothing is sent."),
) -> None:
    """Comment on a LinkedIn activity."""
    try:
        detail = core.comment(identifier, text, confirm=confirm, config_path=_config_path(ctx))
    except Exception as exc:
        _handle_error(exc)
        return
    console.print(build_status_panel("Comment posted", True, detail))


# ---- CDP agent commands: drive the user's own logged-in Chrome ----------


@app.command()
def doctor(
    ctx: typer.Context,
    as_json: bool = typer.Option(False, "--json", help="Emit JSON to stdout."),
) -> None:
    """Check own-chrome, Chrome's CDP port, LinkedIn login, and referral config."""
    report = core.doctor(config_path=_config_path(ctx))
    if as_json:
        typer.echo(to_json(report))
    else:
        for check in report["checks"]:
            status = "ok" if check["ok"] else "FAIL"
            console.print(f"[{status}] {check['name']}" + (f" -- {check['detail']}" if check.get("detail") else ""))
    raise typer.Exit(0 if report.get("ok") else 1)


@app.command()
def scan(
    ctx: typer.Context,
    as_json: bool = typer.Option(False, "--json", help="Emit JSON to stdout."),
) -> None:
    """Find threads that still need a reply/referral."""
    candidates = core.scan(config_path=_config_path(ctx))
    if as_json:
        typer.echo(to_json(candidates))
        return
    for name, candidate in candidates.items():
        status = "unread" if candidate.get("unread") else "read"
        console.print(f"{name}\t{status}\t{candidate.get('url', '')}")


@app.command()
def classify(
    ctx: typer.Context,
    text: str,
    name: str = typer.Option("", "--name"),
    headline: str = typer.Option("", "--headline"),
    as_json: bool = typer.Option(False, "--json", help="Emit JSON to stdout."),
) -> None:
    """Classify a message: hiring? excluded? already referred?"""
    result = core.classify_message(text, name=name, headline=headline, config_path=_config_path(ctx))
    if as_json:
        typer.echo(to_json(result))
        return
    for key, value in result.items():
        console.print(f"{key}: {value}")


@post_cdp_app.command("draft")
def post_cdp_draft_cmd(text: str, as_json: bool = typer.Option(False, "--json")) -> None:
    """Lint post text against the anti-cringe rules. Never touches the browser."""
    result = core.post_cdp_draft(text)
    if as_json:
        typer.echo(to_json(result))
        raise typer.Exit(0 if not result["problems"] else 2)
    console.print(build_status_panel("Post draft", not result["problems"], str(result["problems"]) or "clean"))
    raise typer.Exit(0 if not result["problems"] else 2)


@post_cdp_app.command("publish")
def post_cdp_publish_cmd(
    ctx: typer.Context,
    text: str,
    image: Optional[str] = typer.Option(None, "--image"),
    confirm: bool = typer.Option(False, "--confirm", help="Actually click Post. Without this, nothing is published."),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Fill the composer and, only with --confirm, publish (own logged-in Chrome via CDP)."""
    try:
        result = core.post_cdp_publish(text, image=image, confirm=confirm, config_path=_config_path(ctx))
    except Exception as exc:
        _handle_error(exc)
        return
    if as_json:
        typer.echo(to_json(result))
        return
    console.print(build_status_panel("Post published", bool(result.get("clicked_post")), str(result)))


@messages_app.command("open")
def messages_open_cmd(ctx: typer.Context, as_json: bool = typer.Option(False, "--json")) -> None:
    """Open LinkedIn messaging in the attached Chrome. Creates a tab if needed."""
    info = core.messages_open(config_path=_config_path(ctx))
    if as_json:
        typer.echo(to_json(info))
        return
    console.print(build_status_panel("Messaging", bool(info.get("ok")), info.get("url", "")))


@messages_app.command("threads")
def messages_threads_cmd(
    ctx: typer.Context,
    filter_: str = typer.Option("", "--filter", help="Case-insensitive match on name or preview."),
    limit: int = typer.Option(20, "--limit"),
    unread: bool = typer.Option(False, "--unread", help="Only unread threads."),
    no_navigate: bool = typer.Option(False, "--no-navigate", help="Read the current tab; do not open messaging."),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """List messaging threads."""
    data = core.messages_threads(needle=filter_, limit=limit, unread=unread, no_navigate=no_navigate, config_path=_config_path(ctx))
    if as_json:
        typer.echo(to_json(data))
        return
    for thread in data.get("threads") or []:
        mark = " *" if thread.get("unread") else ""
        console.print(f"- {thread.get('name', '')}{mark}  {(thread.get('preview') or '')[:80]}")
    if filter_ and not data.get("threads"):
        raise typer.Exit(2)


@messages_app.command("select")
def messages_select_cmd(
    ctx: typer.Context,
    name: str = typer.Argument(help="Thread name, or a unique piece of it."),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Open the one thread whose name contains NAME. Exits 2 if none match, 3 if several match."""
    result = core.messages_select(name, config_path=_config_path(ctx))
    if as_json:
        typer.echo(to_json(result))
    else:
        console.print(build_status_panel("select", bool(result.get("ok")), result.get("matched", "")))
    if result.get("ambiguous"):
        raise typer.Exit(3)
    if not result.get("ok"):
        raise typer.Exit(2)


@messages_app.command("read")
def messages_read_cmd(
    ctx: typer.Context,
    url: str = typer.Option("", "--url"),
    limit: int = typer.Option(40, "--limit"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Read the open thread (or one you name with --url)."""
    data = core.messages_read(url=url, limit=limit, config_path=_config_path(ctx))
    if as_json:
        typer.echo(to_json(data))
        return
    for i, body in enumerate(data.get("bodies") or []):
        console.print(f"{i + 1}. {body}")


@messages_app.command("send")
def messages_send_cmd(
    ctx: typer.Context,
    text: str,
    to: str = typer.Option("", "--to", help="Select this thread by name before typing."),
    attach: Optional[str] = typer.Option(None, "--attach"),
    attach_name: Optional[str] = typer.Option(None, "--attach-name"),
    target: str = typer.Option("", "--target", help="Recipient/thread identity for pacing (governor)."),
    confirm: bool = typer.Option(False, "--confirm", help="Actually click Send. Without this, nothing is sent."),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Select a thread by --to (if given) and type TEXT. Sends only with --confirm."""
    try:
        proof = core.messages_send(text, to=to, attach=attach, attach_name=attach_name, target=target, confirm=confirm, config_path=_config_path(ctx))
    except Exception as exc:
        _handle_error(exc)
        return
    if as_json:
        typer.echo(to_json(proof))
        return
    console.print(build_status_panel("Message sent", bool(proof.get("sent")), str(proof)))


@messages_app.command("popups")
def messages_popups_cmd(
    ctx: typer.Context,
    apply: bool = typer.Option(False, "--apply", help="Click the configured button. Default policy declines."),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Report the open LinkedIn dialog. Without --apply, nothing is clicked."""
    result = core.messages_popups(apply=apply, config_path=_config_path(ctx))
    if as_json:
        typer.echo(to_json(result))
        return
    console.print(build_status_panel("popups", True, str(result)))


@messages_app.command("workflow")
def messages_workflow_cmd(
    ctx: typer.Context,
    spec: str = typer.Argument(help="Path to the workflow JSON."),
    text: str = typer.Option("", "--text", help="Thread text. Default is the open thread."),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Classify the open thread and draft a reply. Never sends -- sent is always false."""
    result = core.messages_workflow(spec, text=text, config_path=_config_path(ctx))
    if as_json:
        typer.echo(to_json(result))
        raise typer.Exit(0 if result.get("go") or result.get("reason") == "regex miss" else 2)
    console.print(build_status_panel("workflow", bool(result.get("go")), str(result)))
    raise typer.Exit(0 if result.get("go") or result.get("reason") == "regex miss" else 2)


@messages_app.command("commands")
def messages_commands_cmd(as_json: bool = typer.Option(False, "--json")) -> None:
    """List the `messages` agent verbs. No browser."""
    result = core.messages_commands()
    if as_json:
        typer.echo(to_json(result))
        return
    for row in result["commands"]:
        console.print(f"{row['name']}\t{row['summary']}")


@referral_app.command("draft")
def referral_draft_cmd(
    ctx: typer.Context,
    name: str,
    text: str,
    headline: str = typer.Option("", "--headline"),
    reengage: bool = typer.Option(False, "--reengage"),
    stale_days: int = typer.Option(0, "--stale-days"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Draft a referral message. Never touches the browser."""
    try:
        result = core.referral_draft(
            name, text, headline=headline, reengage=reengage, stale_days=stale_days, config_path=_config_path(ctx)
        )
    except Exception as exc:
        _handle_error(exc)
        return
    if as_json:
        typer.echo(to_json(result))
        raise typer.Exit(0 if not result["problems"] else 2)
    console.print(build_status_panel("Referral draft", not result["problems"], result["draft"]))
    raise typer.Exit(0 if not result["problems"] else 2)


@referral_app.command("send")
def referral_send_cmd(
    ctx: typer.Context,
    name: str,
    url: str,
    text: str = typer.Option("", "--text"),
    stamp: str = typer.Option("", "--stamp"),
    confirm: bool = typer.Option(False, "--confirm", help="Actually click Send. Without this, nothing is sent."),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Draft and, only with --confirm, send a referral (text + resume)."""
    try:
        result = core.referral_send(name, url, text=text, stamp=stamp, confirm=confirm, config_path=_config_path(ctx))
    except Exception as exc:
        _handle_error(exc)
        return
    if as_json:
        typer.echo(to_json(result))
        raise typer.Exit(0 if not result["skipped"] else 2)
    if result["skipped"]:
        console.print(build_status_panel("Referral skipped", False, result["skipped"]))
        raise typer.Exit(2)
    console.print(build_status_panel("Referral sent", bool((result["proof"] or {}).get("sent")), result["draft"]))


@app.command()
def serve() -> None:
    """Run the MCP server over stdio (for Claude/Cursor: {"command": "linkedin-mcp", "args": ["serve"]})."""
    from . import mcp_server

    mcp_server.main()


def main() -> None:
    """Entry point for `python -m linkedin_mcp.cli`."""
    app()


if __name__ == "__main__":  # pragma: no cover
    main()

"""CLI entrypoint for linkedin-mcp. Every command is a thin wrapper around
core.py -- the same functions the MCP server calls (see mcp_server.py and
tests/test_mcp_parity.py, which fails if a command and its tool drift apart).
"""

from __future__ import annotations

import json
import logging
import sys
from typing import Optional

import typer
from rich.console import Console
from typer.core import TyperGroup

from . import __version__, compact, core
from . import scan as scan_mod
from .serialization import profile_to_dict

console = Console(stderr=True)
REACTION_CHOICES = ["like", "celebrate", "support", "love", "insightful", "curious"]

_HELP = {"help_option_names": ["-h", "--help"]}

_HOISTED = ("--fields", "--max-chars")


class _RootGroup(TyperGroup):
    """Accept --fields/--max-chars anywhere on the line (`li scan --fields name`),
    not only before the subcommand: hoist them to the root before parsing."""

    def parse_args(self, ctx, args):
        hoisted: list[str] = []
        rest: list[str] = []
        it = iter(args)
        for arg in it:
            if arg in _HOISTED:
                hoisted += [arg, next(it, "")]
            elif arg.startswith(tuple(h + "=" for h in _HOISTED)):
                hoisted.append(arg)
            else:
                rest.append(arg)
        return super().parse_args(ctx, hoisted + rest)


app = typer.Typer(
    cls=_RootGroup,
    name="linkedin",
    help="linkedin - LinkedIn CLI + MCP server.",
    add_completion=False,
    context_settings=_HELP,
)
auth_app = typer.Typer(help="Manage the LinkedIn session cookie.", no_args_is_help=True, context_settings=_HELP)
post_cdp_app = typer.Typer(
    help="Draft or publish a feed post over your own logged-in Chrome (CDP).",
    no_args_is_help=True,
    context_settings=_HELP,
)
messages_app = typer.Typer(
    help="Read or send a LinkedIn message in the open thread (CDP).",
    no_args_is_help=True,
    context_settings=_HELP,
)
referral_app = typer.Typer(help="Draft or send a referral message (CDP).", no_args_is_help=True, context_settings=_HELP)
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
    fields: Optional[str] = typer.Option(None, "--fields", "-F", help="Comma list of keys to keep per row (e.g. name,url)."),
    limit: Optional[int] = typer.Option(None, "--limit", "-l", help="Max rows to print (a final {\"more\":k} row says k were cut)."),
    max_chars: int = typer.Option(300, "--max-chars", help="Truncate every string to N chars (0 = no cut)."),
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
    ctx.obj["shape"] = {"fields": compact.parse_fields(fields), "limit": limit, "max_chars": max_chars}


def _config_path(ctx: typer.Context) -> Optional[str]:
    return (ctx.obj or {}).get("config_path")


def _write_output(output_file: Optional[str], payload: str) -> None:
    if output_file:
        from pathlib import Path

        Path(output_file).write_text(payload + "\n", encoding="utf-8")


def _emit(ctx: typer.Context, data, output_file: Optional[str] = None, **override) -> None:
    """Print a read result as one line of compact JSON (the default for every
    read command; --json is accepted and changes nothing)."""
    opts = {**((ctx.obj or {}).get("shape") or {}), **{k: v for k, v in override.items() if v is not None}}
    payload = compact.dumps(compact.shape(data, **opts))
    _write_output(output_file, payload)
    typer.echo(payload)


def _status(title: str, ok: bool, detail: str = "") -> None:
    """One-line result for write commands: `ok: title: detail`."""
    typer.echo(f"{'ok' if ok else 'FAIL'}: {title}" + (f": {' '.join(str(detail).split())}" if detail else ""))


def _handle_error(exc: Exception) -> None:
    typer.echo(compact.error_line(exc), err=True)
    raise typer.Exit(1)


def _call(fn):
    """Run a core call. typer.Exit is a control-flow signal (filter miss,
    ambiguous select) and must not be rewritten as a generic failure."""
    try:
        return fn()
    except typer.Exit:
        raise
    except Exception as exc:
        _handle_error(exc)


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
    _status(title, success, "\n".join(detail_lines))
    if not success:
        raise typer.Exit(1)


@auth_app.command("capture")
def auth_capture_cmd(
    port: int = typer.Option(9333, "--port", help="Chrome CDP port to poll."),
    timeout: float = typer.Option(600.0, "--timeout", help="Seconds to wait for a login."),
    as_json: bool = typer.Option(False, "--json", "-j", help="Emit JSON to stdout."),
) -> None:
    """Poll a CDP-attached Chrome until logged in, then save the session cookie. Never prints cookie values."""
    result = core.auth_capture(port=port, timeout=timeout)
    if as_json:
        typer.echo(compact.dumps(result))
    else:
        _status("Session capture", bool(result.get("captured")), str(result))
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
    as_json: bool = typer.Option(False, "--json", "-j", help="Emit JSON to stdout."),
    output_file: Optional[str] = typer.Option(None, "--output", "-o", help="Write JSON output to a file."),
) -> None:
    """Fetch the authenticated home feed."""
    try:
        posts = core.feed(limit=max_count, config_path=_config_path(ctx))
    except Exception as exc:
        _handle_error(exc)
        return
    _emit(ctx, list(posts), output_file)


@app.command()
def search(
    ctx: typer.Context,
    query: str,
    max_count: Optional[int] = typer.Option(None, "--max", help="Maximum number of search results to fetch."),
    as_json: bool = typer.Option(False, "--json", "-j", help="Emit JSON to stdout."),
    output_file: Optional[str] = typer.Option(None, "--output", "-o", help="Write JSON output to a file."),
) -> None:
    """Search LinkedIn entities and posts."""
    try:
        results = core.search(query, limit=max_count, config_path=_config_path(ctx))
    except Exception as exc:
        _handle_error(exc)
        return
    _emit(ctx, list(results), output_file)


@app.command()
def profile(
    ctx: typer.Context,
    identifier: str,
    as_json: bool = typer.Option(False, "--json", "-j", help="Emit JSON to stdout."),
) -> None:
    """Fetch a LinkedIn profile by public id or URL."""
    try:
        result = core.get_profile(identifier, config_path=_config_path(ctx))
    except Exception as exc:
        _handle_error(exc)
        return
    _emit(ctx, profile_to_dict(result))


@app.command("profile-posts")
def profile_posts(
    ctx: typer.Context,
    identifier: str,
    max_count: Optional[int] = typer.Option(None, "--max", help="Maximum number of posts to fetch."),
    as_json: bool = typer.Option(False, "--json", "-j", help="Emit JSON to stdout."),
    output_file: Optional[str] = typer.Option(None, "--output", "-o", help="Write JSON output to a file."),
) -> None:
    """Fetch posts for a LinkedIn profile."""
    try:
        posts = core.get_profile_posts(identifier, limit=max_count, config_path=_config_path(ctx))
    except Exception as exc:
        _handle_error(exc)
        return
    _emit(ctx, list(posts), output_file)


@app.command()
def activity(
    ctx: typer.Context,
    identifier: str,
    as_json: bool = typer.Option(False, "--json", "-j", help="Emit JSON to stdout."),
) -> None:
    """Fetch a LinkedIn activity detail."""
    try:
        post = core.get_activity(identifier, config_path=_config_path(ctx))
    except Exception as exc:
        _handle_error(exc)
        return
    _emit(ctx, post)


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
    _status("Post created", True, detail)


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
    _status("Reaction applied", True, detail)


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
    _status("Reaction removed", True, detail)


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
    _status("Post saved", True, detail)


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
    _status("Post unsaved", True, detail)


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
    _status("Comment posted", True, detail)


# ---- CDP agent commands: drive the user's own logged-in Chrome ----------


@app.command()
def doctor(
    ctx: typer.Context,
    as_json: bool = typer.Option(False, "--json", "-j", help="Emit JSON to stdout."),
) -> None:
    """Check own-chrome, Chrome's CDP port, LinkedIn login, and referral config."""
    report = core.doctor(config_path=_config_path(ctx))
    if as_json:
        typer.echo(compact.dumps(report))
    else:
        for check in report["checks"]:
            status = "ok" if check["ok"] else "FAIL"
            console.print(f"[{status}] {check['name']}" + (f" -- {check['detail']}" if check.get("detail") else ""))
    raise typer.Exit(0 if report.get("ok") else 1)


@app.command()
def scan(
    ctx: typer.Context,
    as_json: bool = typer.Option(False, "--json", "-j", hidden=True, help="Accepted; output is always compact JSON."),
) -> None:
    """Find threads that still need a referral: [{name,url,unread,text,fit}]. text is the newest --max-chars."""
    candidates = _call(lambda: core.scan(config_path=_config_path(ctx)))
    rows = json.loads(scan_mod.to_json(candidates))
    max_chars = ((ctx.obj or {}).get("shape") or {}).get("max_chars", 300)
    for row in rows:
        if max_chars > 0:
            row["text"] = row.get("text", "")[-max_chars:]  # newest message is last
    _emit(ctx, rows, max_chars=0)


@app.command()
def classify(
    ctx: typer.Context,
    text: str,
    name: str = typer.Option("", "--name"),
    headline: str = typer.Option("", "--headline"),
    as_json: bool = typer.Option(False, "--json", "-j", help="Emit JSON to stdout."),
) -> None:
    """Classify a message: hiring? excluded? already referred?"""
    result = core.classify_message(text, name=name, headline=headline, config_path=_config_path(ctx))
    if as_json:
        typer.echo(compact.dumps(result))
        return
    for key, value in result.items():
        console.print(f"{key}: {value}")


@post_cdp_app.command("draft")
def post_cdp_draft_cmd(text: str, as_json: bool = typer.Option(False, "--json", "-j")) -> None:
    """Lint post text against the anti-cringe rules. Never touches the browser."""
    result = core.post_cdp_draft(text)
    if as_json:
        typer.echo(compact.dumps(result))
        raise typer.Exit(0 if not result["problems"] else 2)
    _status("Post draft", not result["problems"], str(result["problems"]) or "clean")
    raise typer.Exit(0 if not result["problems"] else 2)


@post_cdp_app.command("publish")
def post_cdp_publish_cmd(
    ctx: typer.Context,
    text: str,
    image: Optional[str] = typer.Option(None, "--image"),
    confirm: bool = typer.Option(False, "--confirm", help="Actually click Post. Without this, nothing is published."),
    as_json: bool = typer.Option(False, "--json", "-j"),
) -> None:
    """Fill the composer and, only with --confirm, publish (own logged-in Chrome via CDP)."""
    try:
        result = core.post_cdp_publish(text, image=image, confirm=confirm, config_path=_config_path(ctx))
    except Exception as exc:
        _handle_error(exc)
        return
    if as_json:
        typer.echo(compact.dumps(result))
        return
    _status("Post published", bool(result.get("clicked_post")), str(result))


@messages_app.command("open")
def messages_open_cmd(ctx: typer.Context, as_json: bool = typer.Option(False, "--json", "-j")) -> None:
    """Open LinkedIn messaging in the attached Chrome. Creates a tab if needed."""
    info = _call(lambda: core.messages_open(config_path=_config_path(ctx)))
    if as_json:
        typer.echo(compact.dumps(info))
        return
    _status("Messaging", bool(info.get("ok")), info.get("url", ""))


@messages_app.command("threads")
def messages_threads_cmd(
    ctx: typer.Context,
    filter_: str = typer.Option("", "--filter", help="Case-insensitive match on name or preview."),
    limit: int = typer.Option(20, "--limit"),
    unread: bool = typer.Option(False, "--unread", help="Only unread threads."),
    no_navigate: bool = typer.Option(False, "--no-navigate", help="Read the current tab; do not open messaging."),
    as_json: bool = typer.Option(False, "--json", "-j"),
) -> None:
    """List messaging threads."""
    data = _call(lambda: core.messages_threads(needle=filter_, limit=limit, unread=unread, no_navigate=no_navigate, config_path=_config_path(ctx)))
    _emit(ctx, data)
    if filter_ and not data.get("threads"):
        raise typer.Exit(2)


@messages_app.command("select")
def messages_select_cmd(
    ctx: typer.Context,
    name: str = typer.Argument(help="Thread name, or a unique piece of it."),
    as_json: bool = typer.Option(False, "--json", "-j"),
) -> None:
    """Open the one thread whose name contains NAME. Exits 2 if none match, 3 if several match."""
    result = _call(lambda: core.messages_select(name, config_path=_config_path(ctx)))
    if as_json:
        typer.echo(compact.dumps(result))
    else:
        _status("select", bool(result.get("ok")), result.get("matched", ""))
    if result.get("ambiguous"):
        raise typer.Exit(3)
    if not result.get("ok"):
        raise typer.Exit(2)


@messages_app.command("read")
def messages_read_cmd(
    ctx: typer.Context,
    url: str = typer.Option("", "--url"),
    limit: int = typer.Option(40, "--limit"),
    as_json: bool = typer.Option(False, "--json", "-j"),
) -> None:
    """Read the open thread (or one you name with --url)."""
    data = _call(lambda: core.messages_read(url=url, limit=limit, config_path=_config_path(ctx)))
    _emit(ctx, data)


@messages_app.command("send")
def messages_send_cmd(
    ctx: typer.Context,
    text: str,
    to: str = typer.Option("", "--to", help="Select this thread by name before typing."),
    attach: Optional[str] = typer.Option(None, "--attach"),
    attach_name: Optional[str] = typer.Option(None, "--attach-name"),
    target: str = typer.Option("", "--target", help="Recipient/thread identity for pacing (governor)."),
    confirm: bool = typer.Option(False, "--confirm", help="Actually click Send. Without this, nothing is sent."),
    as_json: bool = typer.Option(False, "--json", "-j"),
) -> None:
    """Select a thread by --to (if given) and type TEXT. Sends only with --confirm."""
    try:
        proof = core.messages_send(text, to=to, attach=attach, attach_name=attach_name, target=target, confirm=confirm, config_path=_config_path(ctx))
    except Exception as exc:
        _handle_error(exc)
        return
    if as_json:
        typer.echo(compact.dumps(proof))
        return
    _status("Message sent", bool(proof.get("sent")), str(proof))


@messages_app.command("popups")
def messages_popups_cmd(
    ctx: typer.Context,
    apply: bool = typer.Option(False, "--apply", help="Click the configured button. Default policy declines."),
    as_json: bool = typer.Option(False, "--json", "-j"),
) -> None:
    """Report the open LinkedIn dialog. Without --apply, nothing is clicked."""
    result = _call(lambda: core.messages_popups(apply=apply, config_path=_config_path(ctx)))
    if as_json:
        typer.echo(compact.dumps(result))
        return
    _status("popups", True, str(result))


@messages_app.command("workflow")
def messages_workflow_cmd(
    ctx: typer.Context,
    spec: str = typer.Argument(help="Path to the workflow JSON."),
    text: str = typer.Option("", "--text", help="Thread text. Default is the open thread."),
    as_json: bool = typer.Option(False, "--json", "-j"),
) -> None:
    """Classify the open thread and draft a reply. Never sends -- sent is always false."""
    result = _call(lambda: core.messages_workflow(spec, text=text, config_path=_config_path(ctx)))
    if as_json:
        typer.echo(compact.dumps(result))
        raise typer.Exit(0 if result.get("go") or result.get("reason") == "regex miss" else 2)
    _status("workflow", bool(result.get("go")), str(result))
    raise typer.Exit(0 if result.get("go") or result.get("reason") == "regex miss" else 2)


@messages_app.command("commands")
def messages_commands_cmd(as_json: bool = typer.Option(False, "--json", "-j")) -> None:
    """List the `messages` agent verbs. No browser."""
    result = core.messages_commands()
    if as_json:
        typer.echo(compact.dumps(result))
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
    as_json: bool = typer.Option(False, "--json", "-j"),
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
        typer.echo(compact.dumps(result))
        raise typer.Exit(0 if not result["problems"] else 2)
    _status("Referral draft", not result["problems"], result["draft"])
    raise typer.Exit(0 if not result["problems"] else 2)


@referral_app.command("send")
def referral_send_cmd(
    ctx: typer.Context,
    name: str,
    url: str,
    text: str = typer.Option("", "--text"),
    stamp: str = typer.Option("", "--stamp"),
    confirm: bool = typer.Option(False, "--confirm", help="Actually click Send. Without this, nothing is sent."),
    as_json: bool = typer.Option(False, "--json", "-j"),
) -> None:
    """Draft and, only with --confirm, send a referral (text + resume)."""
    try:
        result = core.referral_send(name, url, text=text, stamp=stamp, confirm=confirm, config_path=_config_path(ctx))
    except Exception as exc:
        _handle_error(exc)
        return
    if as_json:
        typer.echo(compact.dumps(result))
        raise typer.Exit(0 if not result["skipped"] else 2)
    if result["skipped"]:
        _status("Referral skipped", False, result["skipped"])
        raise typer.Exit(2)
    _status("Referral sent", bool((result["proof"] or {}).get("sent")), result["draft"])


@app.command("login")
def login_cmd(
    ctx: typer.Context,
    account: Optional[str] = typer.Option(None, "--account", "-a", help="Sign-in email (Keychain account). Default michaelle.lubich@gmail.com."),
    port: Optional[int] = typer.Option(None, "--port", "-p", help="CDP port (default from config, 9222)."),
    as_json: bool = typer.Option(False, "--json", "-j"),
) -> None:
    """Sign the LinkedIn Chrome in using the Keychain password. One attempt; stops on captcha/2FA/checkpoint."""
    result = _call(lambda: core.login(account=account, port=port, config_path=_config_path(ctx)))
    if as_json:
        typer.echo(compact.dumps(result))
        return
    _status("LinkedIn login", True, f"{result['status']} ({result['account']})")


@referral_app.command("queue")
def referral_queue_cmd(
    ctx: typer.Context,
    queue_file: str = typer.Argument(..., help="JSON list of {name, profile_url|thread_url, company, role, body}."),
    confirm: bool = typer.Option(False, "--confirm", help="Actually send. Without this, only a dry-run plan is printed."),
    limit: Optional[int] = typer.Option(None, "--limit", "-l", help="Stop after N sends (or N planned, in a dry run)."),
    port: Optional[int] = typer.Option(None, "--port", "-p", help="CDP port (default from config, 9222)."),
    as_json: bool = typer.Option(False, "--json", "-j"),
) -> None:
    """Ledger-guarded bulk referrals: body then resume per person, verified, logged. Dry run unless --confirm."""
    result = _call(
        lambda: core.referral_queue(queue_file, confirm=confirm, limit=limit, port=port, config_path=_config_path(ctx))
    )
    if as_json:
        typer.echo(compact.dumps(result))
    else:
        typer.echo("DRY RUN (nothing sent; pass --confirm)" if result["dry_run"] else "SENT RUN")
        for row in result["results"]:
            typer.echo(f"{row['status']}\t{row['name']}\t{row['reason']}")
        if result["aborted"]:
            typer.echo(f"ABORTED: {result['aborted']}")
    raise typer.Exit(2 if result["aborted"] else 0)


@app.command("prompt")
def prompt_cmd(
    name: Optional[str] = typer.Argument(None, help="Name of prompt template (e.g. cold-outreach, triage-inbox, connection-invite)."),
    list_prompts: bool = typer.Option(False, "--list", "-l", help="List all available prompt templates."),
    as_json: bool = typer.Option(False, "--json", "-j", help="Output instructions, schemas, few-shots, and template as JSON."),
) -> None:
    """Inspect or output AI-native prompt templates, schemas, and few-shots."""
    try:
        if list_prompts or not name:
            prompts = core.prompt_list()
            if as_json:
                typer.echo(compact.dumps({"prompts": prompts}))
            else:
                for p in prompts:
                    typer.echo(p)
            raise typer.Exit(0)

        prompt_data = core.prompt_get(name)
        if as_json:
            typer.echo(compact.dumps(prompt_data))
        else:
            console.print(f"[bold green]Prompt:[/bold green] {prompt_data['name']}")
            console.print(f"[bold cyan]Description:[/bold cyan] {prompt_data['description']}")
            if prompt_data.get("instructions"):
                console.print(f"\n[bold yellow]Instructions:[/bold yellow]\n{prompt_data['instructions']}")
            if prompt_data.get("template"):
                console.print(f"\n[bold magenta]Template:[/bold magenta]\n{prompt_data['template']}")
    except typer.Exit:
        raise
    except FileNotFoundError as exc:
        _handle_error(exc)
    except Exception as exc:
        _handle_error(exc)



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

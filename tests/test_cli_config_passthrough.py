"""Correctness fix (review B6, M2): `linkedin --config path.toml <command>`
was silently ignored for classify, post-cdp publish, every messages_*
command, and referral draft/send -- their CLI functions never accepted
`ctx` at all, so the global --config flag never reached core.py.

M2: that fix's own test only covered the commands review B6 named --
post/react/unreact/save/unsave/comment were never in CASES at all, so an
architect could revert core.react's config_path in cli.py and the suite
stayed green. CASES is now cross-checked against the live CLI command tree
(the same walk test_mcp_parity.py uses): any command that's neither in
CASES nor in NO_CONFIG_NEEDED fails test_every_cli_command_is_classified,
so a newly added command can't silently go uncovered.
"""

from __future__ import annotations

from typer.testing import CliRunner

import linkedin_mcp.core as core
import typer
from linkedin_mcp.cli import app
from linkedin_mcp.models import Actor, Post, Profile

runner = CliRunner()

# Commands that genuinely take no config_path -- auth capture/env are pure
# CDP/file operations, post-cdp draft is pure text linting, messages commands
# is a static catalog, serve starts the server itself.
NO_CONFIG_NEEDED = {"auth_capture", "auth_env", "post_cdp_draft", "messages_commands", "serve", "prompt"}

CASES = [
    (["--config", "cfg.toml", "auth-status"], "auth_diagnostics"),
    (["--config", "cfg.toml", "feed", "--json"], "feed"),
    (["--config", "cfg.toml", "search", "x", "--json"], "search"),
    (["--config", "cfg.toml", "profile", "jane", "--json"], "get_profile"),
    (["--config", "cfg.toml", "profile-posts", "jane", "--json"], "get_profile_posts"),
    (["--config", "cfg.toml", "activity", "u1", "--json"], "get_activity"),
    (["--config", "cfg.toml", "post", "hi", "--confirm"], "publish_post"),
    (["--config", "cfg.toml", "react", "u1", "--confirm"], "react"),
    (["--config", "cfg.toml", "unreact", "u1", "--confirm"], "unreact"),
    (["--config", "cfg.toml", "save", "u1", "--confirm"], "save_activity"),
    (["--config", "cfg.toml", "unsave", "u1", "--confirm"], "unsave_activity"),
    (["--config", "cfg.toml", "comment", "u1", "hi", "--confirm"], "comment"),
    (["--config", "cfg.toml", "doctor"], "doctor"),
    (["--config", "cfg.toml", "scan"], "scan"),
    (["--config", "cfg.toml", "classify", "hi"], "classify_message"),
    (["--config", "cfg.toml", "post-cdp", "publish", "hi", "--confirm"], "post_cdp_publish"),
    (["--config", "cfg.toml", "messages", "open"], "messages_open"),
    (["--config", "cfg.toml", "messages", "threads"], "messages_threads"),
    (["--config", "cfg.toml", "messages", "select", "Jordan"], "messages_select"),
    (["--config", "cfg.toml", "messages", "read"], "messages_read"),
    (["--config", "cfg.toml", "messages", "send", "hi", "--confirm"], "messages_send"),
    (["--config", "cfg.toml", "messages", "popups"], "messages_popups"),
    (["--config", "cfg.toml", "messages", "workflow", "spec.json"], "messages_workflow"),
    (["--config", "cfg.toml", "referral", "draft", "Jordan", "hi"], "referral_draft"),
    (["--config", "cfg.toml", "referral", "send", "Jordan", "https://x", "--confirm"], "referral_send"),
    (["--config", "cfg.toml", "login"], "login"),
    (["--config", "cfg.toml", "referral", "queue", "q.json", "--confirm"], "referral_queue"),
]

STUB_RESULTS = {
    "auth_diagnostics": {"ok": True},
    "feed": [Post(urn="u1", author=Actor(name="A"), text="hi")],
    "search": [],
    "get_profile": Profile(public_id="jane"),
    "get_profile_posts": [Post(urn="u1", author=Actor(name="A"), text="hi")],
    "get_activity": Post(urn="u1", author=Actor(name="A"), text="hi"),
    "publish_post": "posted",
    "react": "reacted",
    "unreact": "unreacted",
    "save_activity": "saved",
    "unsave_activity": "unsaved",
    "comment": "commented",
    "doctor": {"ok": True, "checks": []},
    "scan": {},
    "classify_message": {"hiring": False, "excluded": False, "exclude_reason": "", "already_referred": False},
    "post_cdp_publish": {"clicked_post": True},
    "messages_open": {"opened": "already", "ok": True},
    "messages_threads": {"threads": []},
    "messages_select": {"ok": True, "matched": "Jordan"},
    "messages_read": {"bodies": []},
    "messages_send": {"sent": True},
    "messages_popups": {"action": None, "applied": False},
    "messages_workflow": {"go": False, "reason": "regex miss", "sent": False},
    "referral_draft": {"draft": "hi", "problems": []},
    "login": {"status": "signed_in", "account": "a"},
    "referral_queue": {"dry_run": False, "results": [], "aborted": ""},
    "referral_send": {"name": "Jordan", "skipped": "", "draft": "hi", "proof": {"sent": True}},
}


def _cli_command_names() -> set[str]:
    """Same tree walk as test_mcp_parity.py's _cli_command_names()."""
    group = typer.main.get_command(app)
    names: set[str] = set()

    def walk(cmd, prefix: str) -> None:
        sub_commands = getattr(cmd, "commands", None)
        if sub_commands:
            for sub_name, sub_cmd in sub_commands.items():
                walk(sub_cmd, f"{prefix}_{sub_name}" if prefix else sub_name)
        else:
            names.add(prefix.replace("-", "_"))

    walk(group, "")
    names.discard("")
    return names


def _cli_case_command_names() -> set[str]:
    """Recover the dotted command name each CASES entry exercises, e.g.
    ["messages", "send", ...] -> "messages_send", ["scan"] -> "scan"."""
    names = set()
    for argv, _core_fn_name in CASES:
        # Drop the leading --config/value pair, then take leading tokens
        # that aren't option flags or positional arguments.
        tokens = argv[2:]
        parts = []
        for token in tokens:
            if token.startswith("-"):
                break
            parts.append(token)
            if len(parts) == 2 and parts[0] in {"messages", "referral", "post-cdp", "auth"}:
                break
            if len(parts) == 1 and parts[0] not in {"messages", "referral", "post-cdp", "auth"}:
                break
        names.add("_".join(p.replace("-", "_") for p in parts))
    return names


def test_every_cli_command_is_classified() -> None:
    """Fails if a command is neither exercised by CASES nor declared exempt
    in NO_CONFIG_NEEDED -- this is what catches a new command (or a
    reverted config_path passthrough elsewhere) going uncovered."""
    all_commands = _cli_command_names()
    classified = _cli_case_command_names() | NO_CONFIG_NEEDED
    missing = all_commands - classified
    assert not missing, f"CLI commands not classified in test_cli_config_passthrough.py: {sorted(missing)}"


def test_every_config_dependent_command_passes_config_path_through(monkeypatch) -> None:
    for argv, core_fn_name in CASES:
        captured = {}

        def fake(*a, _name=core_fn_name, **kw):
            captured["config_path"] = kw.get("config_path")
            return STUB_RESULTS[_name]

        monkeypatch.setattr(core, core_fn_name, fake)
        result = runner.invoke(app, argv)
        assert result.exit_code in (0, 2), f"{argv}: {result.output}"
        assert captured.get("config_path") == "cfg.toml", f"{argv} did not pass --config through: {captured}"

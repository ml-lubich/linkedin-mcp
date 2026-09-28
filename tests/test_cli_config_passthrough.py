"""Correctness fix (review B6): `linkedin --config path.toml <command>` was
silently ignored for classify, post-cdp publish, every messages_* command,
and referral draft/send -- their CLI functions never accepted `ctx` at all,
so the global --config flag never reached core.py."""

from __future__ import annotations

from typer.testing import CliRunner

import linkedin_mcp.core as core
from linkedin_mcp.cli import app

runner = CliRunner()

CASES = [
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
]

STUB_RESULTS = {
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
    "referral_send": {"name": "Jordan", "skipped": "", "draft": "hi", "proof": {"sent": True}},
}


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

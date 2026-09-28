from __future__ import annotations

from dataclasses import dataclass

from typer.testing import CliRunner

import linkedin_mcp.core as core
from linkedin_mcp.cli import app
from linkedin_mcp.models import Actor, Post, Profile, SearchResult

runner = CliRunner()


@dataclass
class FakeClient:
    def auth_status(self):
        return {"source": "env", "browser": None, "public_id": "john-doe", "full_name": "John Doe"}

    def feed(self, limit=None):
        return [
            Post(
                urn="urn:li:activity:123456",
                author=Actor(name="Jane Doe", public_id="jane-doe"),
                text="Hello feed",
                url="https://www.linkedin.com/feed/update/urn:li:activity:123456/",
            )
        ]

    def search(self, query, limit=None):
        return [
            SearchResult(
                kind="profile",
                title="Jane Doe",
                subtitle="Builder",
                snippet=f"query={query}",
                url="https://www.linkedin.com/in/jane-doe/",
                profile=Profile(
                    public_id="jane-doe",
                    full_name="Jane Doe",
                    headline="Builder",
                    profile_url="https://www.linkedin.com/in/jane-doe/",
                ),
            )
        ]

    def get_profile(self, identifier):
        return Profile(
            public_id=identifier,
            full_name="Jane Doe",
            headline="Builder",
            profile_url=f"https://www.linkedin.com/in/{identifier}/",
        )

    def get_profile_posts(self, identifier, limit=None):
        return self.feed(limit=limit)

    def get_activity(self, identifier):
        return self.feed()[0]

    def post(self, text, visibility="connections"):
        return f"posted {visibility}: {text}"

    def react(self, identifier, reaction_type):
        return f"reacted {reaction_type} -> {identifier}"

    def unreact(self, identifier):
        return f"unreacted -> {identifier}"

    def save(self, identifier):
        return f"saved -> {identifier}"

    def unsave(self, identifier):
        return f"unsaved -> {identifier}"

    def comment(self, identifier, text):
        return f"commented -> {identifier}: {text}"


def _wire(monkeypatch) -> FakeClient:
    client = FakeClient()
    monkeypatch.setattr(core, "_voyager_client", lambda config_path=None: client)
    return client


def test_cli_help_renders() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "LinkedIn CLI" in result.output or "linkedin" in result.output


def test_feed_json_output(monkeypatch) -> None:
    _wire(monkeypatch)
    result = runner.invoke(app, ["feed", "--json"])
    assert result.exit_code == 0
    assert '"text": "Hello feed"' in result.output


def test_auth_status_includes_probe_summary(monkeypatch) -> None:
    monkeypatch.setattr(
        core,
        "auth_diagnostics",
        lambda config_path=None: {
            "ok": False,
            "source": "env",
            "public_id": "jane-doe",
            "cookie_count": 7,
            "validation": {
                "ok": False,
                "kind": "self-redirect-loop",
                "status_code": 302,
                "location": "https://www.linkedin.com/voyager/api/me",
            },
            "probes": {
                "voyager_me": {"ok": False, "reason": "self-redirect-loop", "status_code": 302},
                "voyager_feed": {"ok": False, "reason": "redirect", "status_code": 302},
            },
            "hint": "Need a fuller cookie jar.",
        },
    )
    result = runner.invoke(app, ["auth-status"])
    assert result.exit_code == 1
    assert "cookies=7" in result.output
    assert "basic-probe=self-redirect-loop:302" in result.output
    assert "voyager_feed=redirect:302" in result.output
    assert "Need a fuller cookie jar." in result.output


def test_auth_status_success(monkeypatch) -> None:
    monkeypatch.setattr(
        core,
        "auth_diagnostics",
        lambda config_path=None: {
            "ok": True,
            "source": "browser",
            "browser": "chrome",
            "public_id": "jane-doe",
            "cookie_count": 9,
            "validation": {"ok": True, "kind": "profile-read"},
            "probes": {
                "voyager_me": {"ok": True, "status_code": 200},
                "voyager_feed": {"ok": True, "status_code": 200},
            },
            "hint": "",
        },
    )
    result = runner.invoke(app, ["auth-status"])
    assert result.exit_code == 0
    assert "source=browser" in result.output
    assert "basic-probe=ok" in result.output
    assert "voyager_feed=ok:200" in result.output


def test_profile_json_output(monkeypatch) -> None:
    _wire(monkeypatch)
    result = runner.invoke(app, ["profile", "jane-doe", "--json"])
    assert result.exit_code == 0
    assert '"public_id": "jane-doe"' in result.output


def test_search_json_output(monkeypatch) -> None:
    _wire(monkeypatch)
    result = runner.invoke(app, ["search", "builder", "--json"])
    assert result.exit_code == 0
    assert '"title": "Jane Doe"' in result.output


# ---- Voyager write commands: new confirm guard ---------------------------


def test_post_without_confirm_fails_and_never_calls_client(monkeypatch) -> None:
    client = _wire(monkeypatch)
    result = runner.invoke(app, ["post", "hello world"])
    assert result.exit_code == 1
    assert "confirm=True" in result.output


def test_post_with_confirm_calls_client(monkeypatch) -> None:
    client = _wire(monkeypatch)
    result = runner.invoke(app, ["post", "hello world", "--confirm"])
    assert result.exit_code == 0
    assert "posted connections: hello world" in result.output


def test_react_without_confirm_fails(monkeypatch) -> None:
    _wire(monkeypatch)
    result = runner.invoke(app, ["react", "urn:li:activity:1"])
    assert result.exit_code == 1
    assert "confirm=True" in result.output


def test_react_with_confirm_succeeds(monkeypatch) -> None:
    _wire(monkeypatch)
    result = runner.invoke(app, ["react", "urn:li:activity:1", "--confirm"])
    assert result.exit_code == 0
    assert "reacted like -> urn:li:activity:1" in result.output


def test_comment_without_confirm_fails(monkeypatch) -> None:
    _wire(monkeypatch)
    result = runner.invoke(app, ["comment", "urn:li:activity:1", "nice"])
    assert result.exit_code == 1


def test_save_and_unsave_require_confirm(monkeypatch) -> None:
    _wire(monkeypatch)
    assert runner.invoke(app, ["save", "urn:li:activity:1"]).exit_code == 1
    assert runner.invoke(app, ["unsave", "urn:li:activity:1"]).exit_code == 1
    assert runner.invoke(app, ["save", "urn:li:activity:1", "--confirm"]).exit_code == 0
    assert runner.invoke(app, ["unsave", "urn:li:activity:1", "--confirm"]).exit_code == 0


def test_unreact_requires_confirm(monkeypatch) -> None:
    _wire(monkeypatch)
    assert runner.invoke(app, ["unreact", "urn:li:activity:1"]).exit_code == 1
    assert runner.invoke(app, ["unreact", "urn:li:activity:1", "--confirm"]).exit_code == 0


# ---- agent (CDP) commands: thin wiring ------------------------------------


def test_classify_json_output(monkeypatch) -> None:
    monkeypatch.setattr(
        core,
        "classify_message",
        lambda text, name="", headline="", config_path=None: {
            "hiring": True,
            "excluded": False,
            "exclude_reason": "",
            "already_referred": False,
        },
    )
    result = runner.invoke(app, ["classify", "we are hiring", "--json"])
    assert result.exit_code == 0
    assert '"hiring": true' in result.output


def test_doctor_reports_failure_exit_code(monkeypatch) -> None:
    monkeypatch.setattr(
        core,
        "doctor",
        lambda config_path=None: {"ok": False, "checks": [{"name": "chrome cdp reachable", "ok": False, "detail": "nope"}]},
    )
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 1
    assert "chrome cdp reachable" in result.output


def test_serve_command_starts_the_mcp_server(monkeypatch) -> None:
    called = {"served": False}
    monkeypatch.setattr("linkedin_mcp.mcp_server.main", lambda: called.__setitem__("served", True))
    result = runner.invoke(app, ["serve"])
    assert result.exit_code == 0
    assert called["served"] is True


# ---- coverage: table rendering, --version, --output, error paths --------


def test_version_flag_prints_version_and_exits() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert result.output.strip()


def test_feed_table_rendering_and_output_file(monkeypatch, tmp_path) -> None:
    _wire(monkeypatch)
    out = tmp_path / "feed.json"
    result = runner.invoke(app, ["feed", "--output", str(out)])
    assert result.exit_code == 0
    assert "Jane Doe" in result.output
    assert '"text": "Hello feed"' in out.read_text()


def test_feed_error_path(monkeypatch) -> None:
    monkeypatch.setattr(core, "feed", lambda limit=None, config_path=None: (_ for _ in ()).throw(RuntimeError("boom")))
    result = runner.invoke(app, ["feed"])
    assert result.exit_code == 1
    assert "boom" in result.output


def test_search_table_rendering(monkeypatch) -> None:
    _wire(monkeypatch)
    result = runner.invoke(app, ["search", "builder"])
    assert result.exit_code == 0
    assert "Jane Doe" in result.output


def test_profile_table_rendering(monkeypatch) -> None:
    _wire(monkeypatch)
    result = runner.invoke(app, ["profile", "jane-doe"])
    assert result.exit_code == 0
    assert "Jane Doe" in result.output


def test_profile_posts_json_and_error(monkeypatch) -> None:
    _wire(monkeypatch)
    result = runner.invoke(app, ["profile-posts", "jane-doe", "--json"])
    assert result.exit_code == 0
    assert "Hello feed" in result.output

    monkeypatch.setattr(
        core, "get_profile_posts", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("nope"))
    )
    assert runner.invoke(app, ["profile-posts", "jane-doe"]).exit_code == 1


def test_activity_table_and_json(monkeypatch) -> None:
    _wire(monkeypatch)
    assert runner.invoke(app, ["activity", "urn:li:activity:1"]).exit_code == 0
    assert runner.invoke(app, ["activity", "urn:li:activity:1", "--json"]).exit_code == 0

    monkeypatch.setattr(core, "get_activity", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("nope")))
    assert runner.invoke(app, ["activity", "urn:li:activity:1"]).exit_code == 1


def test_react_rejects_unknown_reaction_type(monkeypatch) -> None:
    _wire(monkeypatch)
    result = runner.invoke(app, ["react", "urn:li:activity:1", "--type", "nope", "--confirm"])
    assert result.exit_code == 1
    assert "must be one of" in result.output


# ---- post-cdp / messages / referral command groups -----------------------


def test_post_cdp_draft_clean_and_dirty(monkeypatch) -> None:
    monkeypatch.setattr(core, "post_cdp_draft", lambda text: {"text": text, "problems": []})
    result = runner.invoke(app, ["post-cdp", "draft", "a clean post"])
    assert result.exit_code == 0

    monkeypatch.setattr(core, "post_cdp_draft", lambda text: {"text": text, "problems": ["ai-tell"]})
    result = runner.invoke(app, ["post-cdp", "draft", "leveraging synergies", "--json"])
    assert result.exit_code == 2
    assert "ai-tell" in result.output


def test_post_cdp_publish_confirm_and_error(monkeypatch) -> None:
    monkeypatch.setattr(core, "post_cdp_publish", lambda text, **k: {"clicked_post": True})
    result = runner.invoke(app, ["post-cdp", "publish", "hello", "--confirm", "--json"])
    assert result.exit_code == 0
    assert "clicked_post" in result.output

    monkeypatch.setattr(core, "post_cdp_publish", lambda text, **k: (_ for _ in ()).throw(RuntimeError("nope")))
    result = runner.invoke(app, ["post-cdp", "publish", "hello"])
    assert result.exit_code == 1


def test_messages_read_and_send(monkeypatch) -> None:
    monkeypatch.setattr(core, "messages_read", lambda **k: {"bodies": ["hi there"], "url": "u"})
    result = runner.invoke(app, ["messages", "read"])
    assert result.exit_code == 0
    assert "hi there" in result.output

    monkeypatch.setattr(core, "messages_send", lambda text, **k: {"sent": True})
    result = runner.invoke(app, ["messages", "send", "hello", "--confirm", "--json"])
    assert result.exit_code == 0
    assert "sent" in result.output

    monkeypatch.setattr(core, "messages_send", lambda text, **k: (_ for _ in ()).throw(RuntimeError("nope")))
    result = runner.invoke(app, ["messages", "send", "hello", "--confirm"])
    assert result.exit_code == 1


def test_referral_draft_and_send(monkeypatch) -> None:
    monkeypatch.setattr(core, "referral_draft", lambda *a, **k: {"draft": "hi jordan", "problems": []})
    result = runner.invoke(app, ["referral", "draft", "Jordan", "hiring for a role"])
    assert result.exit_code == 0

    monkeypatch.setattr(core, "referral_draft", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("disabled")))
    result = runner.invoke(app, ["referral", "draft", "Jordan", "hiring", "--json"])
    assert result.exit_code == 1

    monkeypatch.setattr(
        core, "referral_send", lambda *a, **k: {"name": "Jordan", "skipped": "", "draft": "hi", "proof": {"sent": True}}
    )
    result = runner.invoke(app, ["referral", "send", "Jordan", "https://x", "--confirm"])
    assert result.exit_code == 0

    monkeypatch.setattr(
        core, "referral_send", lambda *a, **k: {"name": "Jordan", "skipped": "already referred", "draft": "", "proof": None}
    )
    result = runner.invoke(app, ["referral", "send", "Jordan", "https://x", "--confirm"])
    assert result.exit_code == 2


def test_auth_capture_command_success_and_failure(monkeypatch) -> None:
    monkeypatch.setattr(core, "auth_capture", lambda **k: {"captured": True, "cookie_count": 2})
    assert runner.invoke(app, ["auth", "capture", "--json"]).exit_code == 0

    monkeypatch.setattr(core, "auth_capture", lambda **k: {"captured": False})
    assert runner.invoke(app, ["auth", "capture"]).exit_code == 1


def test_auth_env_command_success_and_failure(monkeypatch) -> None:
    monkeypatch.setattr(core, "auth_env", lambda: 'export LINKEDIN_COOKIE_HEADER="x"')
    result = runner.invoke(app, ["auth", "env"])
    assert result.exit_code == 0
    assert "LINKEDIN_COOKIE_HEADER" in result.output

    monkeypatch.setattr(core, "auth_env", lambda: (_ for _ in ()).throw(RuntimeError("no session")))
    result = runner.invoke(app, ["auth", "env"])
    assert result.exit_code == 1

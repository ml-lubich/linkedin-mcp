"""core.py is the one place shared by the CLI and the MCP server. These
tests exercise it directly: the newly-added confirm guard on the Voyager
write surface, and passthrough for the read surface."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

import linkedin_mcp.core as core
from linkedin_mcp.guard import ConfirmRequiredError
from linkedin_mcp.models import Actor, Post, Profile, SearchResult


@dataclass
class FakeVoyagerClient:
    calls: list = None

    def __post_init__(self):
        self.calls = []

    def auth_status(self):
        return {"source": "env"}

    def feed(self, limit=None):
        self.calls.append(("feed", limit))
        return [Post(urn="urn:li:activity:1", author=Actor(name="A"), text="hi")]

    def search(self, query, limit=None):
        self.calls.append(("search", query, limit))
        return [SearchResult(kind="profile", title="A", profile=Profile(public_id="a"))]

    def get_profile(self, identifier):
        self.calls.append(("get_profile", identifier))
        return Profile(public_id=identifier, full_name="A")

    def get_profile_posts(self, identifier, limit=None):
        self.calls.append(("get_profile_posts", identifier, limit))
        return [Post(urn="urn:li:activity:2", author=Actor(name="A"), text="hi2")]

    def get_activity(self, identifier):
        self.calls.append(("get_activity", identifier))
        return Post(urn=identifier, author=Actor(name="A"), text="hi3")

    def post(self, text, visibility="connections"):
        self.calls.append(("post", text, visibility))
        return f"posted {visibility}: {text}"

    def react(self, identifier, reaction_type):
        self.calls.append(("react", identifier, reaction_type))
        return f"reacted {reaction_type} -> {identifier}"

    def unreact(self, identifier):
        self.calls.append(("unreact", identifier))
        return f"unreacted -> {identifier}"

    def save(self, identifier):
        self.calls.append(("save", identifier))
        return f"saved -> {identifier}"

    def unsave(self, identifier):
        self.calls.append(("unsave", identifier))
        return f"unsaved -> {identifier}"

    def comment(self, identifier, text):
        self.calls.append(("comment", identifier, text))
        return f"commented -> {identifier}: {text}"


@pytest.fixture
def fake_client(monkeypatch) -> FakeVoyagerClient:
    client = FakeVoyagerClient()
    client.config_path_calls = []

    def _build(config_path=None):
        client.config_path_calls.append(config_path)
        return client

    monkeypatch.setattr(core, "_voyager_client", _build)
    return client


# ---- _voyager_config / _voyager_client / _agent_config: the tiny builders --


def test_voyager_config_forwards_a_given_path(monkeypatch) -> None:
    captured = {}

    def fake_load(path):
        captured["path"] = path
        return "cfg"

    monkeypatch.setattr(core, "load_voyager_config", fake_load)
    assert core._voyager_config("custom.yaml") == "cfg"
    assert captured["path"] == Path("custom.yaml")


def test_voyager_config_defaults_to_none_path(monkeypatch) -> None:
    captured = {}

    def fake_load(path):
        captured["path"] = path
        return "cfg"

    monkeypatch.setattr(core, "load_voyager_config", fake_load)
    core._voyager_config()
    assert captured["path"] is None


def test_voyager_client_builds_from_voyager_config(monkeypatch) -> None:
    monkeypatch.setattr(core, "_voyager_config", lambda config_path=None: "cfg-marker")
    monkeypatch.setattr(core, "LinkedInClient", lambda cfg: ("client-for", cfg))
    assert core._voyager_client("x.yaml") == ("client-for", "cfg-marker")


def test_agent_config_forwards_a_given_path(monkeypatch) -> None:
    captured = {}

    def fake_load(path):
        captured["path"] = path
        return "cfg"

    monkeypatch.setattr(core, "load_agent_config", fake_load)
    assert core._agent_config("agent.yaml") == "cfg"
    assert captured["path"] == Path("agent.yaml")


def test_agent_config_defaults_to_none_path(monkeypatch) -> None:
    captured = {}

    def fake_load(path):
        captured["path"] = path
        return "cfg"

    monkeypatch.setattr(core, "load_agent_config", fake_load)
    core._agent_config()
    assert captured["path"] is None


# ---- read surface passes through untouched -------------------------------


def test_feed_passes_through(fake_client) -> None:
    posts = core.feed(limit=5, config_path="cfg.yaml")
    assert posts[0].text == "hi"
    assert fake_client.calls == [("feed", 5)]
    assert fake_client.config_path_calls == ["cfg.yaml"]


def test_search_passes_through(fake_client) -> None:
    results = core.search("builder", limit=3, config_path="cfg.yaml")
    assert results[0].title == "A"
    assert fake_client.calls == [("search", "builder", 3)]
    assert fake_client.config_path_calls == ["cfg.yaml"]


def test_get_profile_passes_through(fake_client) -> None:
    profile = core.get_profile("jane-doe", config_path="cfg.yaml")
    assert profile.public_id == "jane-doe"
    assert fake_client.calls == [("get_profile", "jane-doe")]
    assert fake_client.config_path_calls == ["cfg.yaml"]


def test_get_profile_posts_passes_through(fake_client) -> None:
    posts = core.get_profile_posts("jane-doe", limit=1, config_path="cfg.yaml")
    assert posts[0].text == "hi2"
    assert fake_client.calls == [("get_profile_posts", "jane-doe", 1)]
    assert fake_client.config_path_calls == ["cfg.yaml"]


def test_get_activity_passes_through(fake_client) -> None:
    post = core.get_activity("urn:li:activity:9", config_path="cfg.yaml")
    assert post.text == "hi3"
    assert fake_client.calls == [("get_activity", "urn:li:activity:9")]
    assert fake_client.config_path_calls == ["cfg.yaml"]


# ---- write surface: new confirm guard -------------------------------------


@pytest.mark.parametrize(
    "call,expected_action",
    [
        (lambda: core.publish_post("hello"), "post"),
        (lambda: core.react("urn:li:activity:1"), "react"),
        (lambda: core.unreact("urn:li:activity:1"), "unreact"),
        (lambda: core.save_activity("urn:li:activity:1"), "save"),
        (lambda: core.unsave_activity("urn:li:activity:1"), "unsave"),
        (lambda: core.comment("urn:li:activity:1", "nice"), "comment"),
    ],
)
def test_write_actions_refuse_without_confirm(fake_client, call, expected_action) -> None:
    with pytest.raises(ConfirmRequiredError) as excinfo:
        call()
    assert excinfo.value.action == expected_action
    assert fake_client.calls == []  # the underlying client method was never reached


def test_publish_post_with_confirm_reaches_client(fake_client) -> None:
    result = core.publish_post("hello", visibility="public", confirm=True, config_path="cfg.yaml")
    assert result == "posted public: hello"
    assert fake_client.calls == [("post", "hello", "public")]
    assert fake_client.config_path_calls == ["cfg.yaml"]


def test_publish_post_defaults_to_connections_visibility(fake_client) -> None:
    result = core.publish_post("hello", confirm=True)
    assert result == "posted connections: hello"
    assert fake_client.calls == [("post", "hello", "connections")]


def test_react_with_confirm_reaches_client(fake_client) -> None:
    result = core.react("urn:li:activity:1", reaction_type="celebrate", confirm=True, config_path="cfg.yaml")
    assert result == "reacted celebrate -> urn:li:activity:1"
    assert fake_client.config_path_calls == ["cfg.yaml"]


def test_react_defaults_to_like_reaction(fake_client) -> None:
    result = core.react("urn:li:activity:1", confirm=True)
    assert result == "reacted like -> urn:li:activity:1"


def test_unreact_with_confirm_reaches_client(fake_client) -> None:
    result = core.unreact("urn:li:activity:1", confirm=True, config_path="cfg.yaml")
    assert result == "unreacted -> urn:li:activity:1"
    assert fake_client.calls == [("unreact", "urn:li:activity:1")]
    assert fake_client.config_path_calls == ["cfg.yaml"]


def test_save_activity_with_confirm_reaches_client(fake_client) -> None:
    result = core.save_activity("urn:li:activity:1", confirm=True, config_path="cfg.yaml")
    assert result == "saved -> urn:li:activity:1"
    assert fake_client.calls == [("save", "urn:li:activity:1")]
    assert fake_client.config_path_calls == ["cfg.yaml"]


def test_unsave_activity_with_confirm_reaches_client(fake_client) -> None:
    result = core.unsave_activity("urn:li:activity:1", confirm=True, config_path="cfg.yaml")
    assert result == "unsaved -> urn:li:activity:1"
    assert fake_client.calls == [("unsave", "urn:li:activity:1")]
    assert fake_client.config_path_calls == ["cfg.yaml"]


def test_comment_with_confirm_reaches_client(fake_client) -> None:
    result = core.comment("urn:li:activity:1", "nice", confirm=True, config_path="cfg.yaml")
    assert result == "commented -> urn:li:activity:1: nice"
    assert fake_client.calls == [("comment", "urn:li:activity:1", "nice")]
    assert fake_client.config_path_calls == ["cfg.yaml"]


# ---- agent (CDP) surface: existing SendNotConfirmedError guard passes through --


def test_doctor_delegates_to_doctor_module(monkeypatch) -> None:
    captured = {}

    def fake_load(path=None):
        captured["path"] = path
        return "cfg"

    monkeypatch.setattr(core, "load_agent_config", fake_load)
    monkeypatch.setattr(core.doctor_mod, "check", lambda cfg: {"ok": True, "checks": [], "config": cfg})
    assert core.doctor(config_path="doc.yaml") == {"ok": True, "checks": [], "config": "cfg"}
    assert captured["path"] == Path("doc.yaml")


def test_classify_message_shapes_result_and_forwards_exact_args(monkeypatch) -> None:
    class Cfg:
        pass

    cfg = Cfg()
    captured = {}

    def fake_exclude_reason(name, headline, message, config):
        captured["exclude_reason"] = (name, headline, message, config)
        return "blocked"

    def fake_already_referred(text, config):
        captured["already_referred"] = (text, config)
        return True

    monkeypatch.setattr(core, "load_agent_config", lambda path=None: cfg)
    monkeypatch.setattr(core.classify_mod, "exclude_reason", fake_exclude_reason)
    monkeypatch.setattr(core.classify_mod, "looks_like_hiring", lambda text: text == "hiring for a role")
    monkeypatch.setattr(core.classify_mod, "already_referred", fake_already_referred)
    result = core.classify_message("hiring for a role", name="Jordan", headline="Recruiter")
    assert result == {
        "hiring": True,
        "excluded": True,
        "exclude_reason": "blocked",
        "already_referred": True,
    }
    assert captured["exclude_reason"] == ("Jordan", "Recruiter", "hiring for a role", cfg)
    assert captured["already_referred"] == ("hiring for a role", cfg)


def test_classify_message_defaults_name_and_headline_to_empty_string(monkeypatch) -> None:
    captured = {}

    def fake_exclude_reason(name, headline, message, config):
        captured["args"] = (name, headline)
        return ""

    monkeypatch.setattr(core, "load_agent_config", lambda path=None: "cfg")
    monkeypatch.setattr(core.classify_mod, "exclude_reason", fake_exclude_reason)
    monkeypatch.setattr(core.classify_mod, "looks_like_hiring", lambda text: False)
    monkeypatch.setattr(core.classify_mod, "already_referred", lambda text, config: False)
    core.classify_message("hi")
    assert captured["args"] == ("", "")


# ---- more direct wrapper coverage -----------------------------------------


def test_core_auth_status_and_diagnostics_call_through(fake_client, monkeypatch) -> None:
    fake_client.auth_status = lambda: {"source": "browser"}
    assert core.auth_status(config_path="cfg.yaml") == {"source": "browser"}
    assert fake_client.config_path_calls == ["cfg.yaml"]

    monkeypatch.setattr(core, "collect_auth_diagnostics", lambda cfg: {"ok": True, "cfg": cfg})
    monkeypatch.setattr(core, "_voyager_config", lambda config_path=None: config_path)
    assert core.auth_diagnostics(config_path="diag.yaml") == {"ok": True, "cfg": "diag.yaml"}


def test_post_cdp_draft_lints_and_shapes_result(monkeypatch) -> None:
    captured = {}

    def fake_lint(text):
        captured["text"] = text
        return ["too salesy"]

    monkeypatch.setattr(core.post_cdp_mod, "lint_post", fake_lint)
    result = core.post_cdp_draft("Excited to announce!")
    assert result == {"text": "Excited to announce!", "problems": ["too salesy"]}
    assert captured["text"] == "Excited to announce!"


def test_messages_read_opens_thread_only_when_url_given(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(core, "load_agent_config", lambda path=None: type("C", (), {"cdp_port": 9222})())
    monkeypatch.setattr(core.messaging_mod, "open_thread", lambda url, port: calls.append(("open", url, port)))
    monkeypatch.setattr(core.messaging_mod, "read_thread", lambda port, limit=40: calls.append(("read", port, limit)) or {"bodies": []})

    core.messages_read()
    assert calls == [("read", 9222, 40)]

    calls.clear()
    core.messages_read(url="https://x", port=1234, limit=5)
    assert calls == [("open", "https://x", 1234), ("read", 1234, 5)]


def test_messages_read_forwards_config_path_to_agent_config(monkeypatch) -> None:
    load_calls = {}

    def fake_load_agent_config(path=None):
        load_calls["path"] = path
        return type("C", (), {"cdp_port": 9222})()

    monkeypatch.setattr(core, "load_agent_config", fake_load_agent_config)
    monkeypatch.setattr(core.messaging_mod, "read_thread", lambda port, limit=40: {"bodies": []})
    core.messages_read(config_path="read.yaml")
    assert load_calls["path"] == Path("read.yaml")


def test_messages_send_delegates_with_confirm(monkeypatch) -> None:
    captured = {}
    monkeypatch.setattr(core, "load_agent_config", lambda path=None: "cfg")
    monkeypatch.setattr(core.messaging_mod, "send_message", lambda **kw: captured.update(kw) or {"sent": True})

    result = core.messages_send("hi", confirm=True, target="t1")
    assert result == {"sent": True}
    assert captured["confirm"] is True
    assert captured["target"] == "t1"


def test_messages_send_passes_every_kwarg_exactly(monkeypatch) -> None:
    captured = {}
    monkeypatch.setattr(core, "load_agent_config", lambda path=None: "cfg")
    monkeypatch.setattr(core.messaging_mod, "send_message", lambda **kw: captured.update(kw) or {"sent": True})

    core.messages_send(
        "hello",
        attach="/tmp/resume.pdf",
        attach_name="Resume.pdf",
        target="thread-1",
        confirm=True,
        port=1234,
    )
    assert captured == {
        "text": "hello",
        "config": "cfg",
        "confirm": True,
        "attachment_path": "/tmp/resume.pdf",
        "attachment_name_hint": "Resume.pdf",
        "port": 1234,
        "target": "thread-1",
    }


def test_messages_send_defaults_attach_and_target_to_falsy(monkeypatch) -> None:
    captured = {}
    monkeypatch.setattr(core, "load_agent_config", lambda path=None: "cfg")
    monkeypatch.setattr(core.messaging_mod, "send_message", lambda **kw: captured.update(kw) or {"sent": True})

    core.messages_send("hello", confirm=True)
    assert captured["attachment_path"] is None
    assert captured["attachment_name_hint"] is None
    assert captured["target"] == ""
    assert captured["port"] is None


def test_post_cdp_publish_delegates(monkeypatch) -> None:
    captured = {}
    monkeypatch.setattr(core, "load_agent_config", lambda path=None: "cfg")
    monkeypatch.setattr(core.post_cdp_mod, "publish_post", lambda **kw: captured.update(kw) or {"clicked_post": True})

    result = core.post_cdp_publish("hi", confirm=True)
    assert result == {"clicked_post": True}
    assert captured["confirm"] is True


def test_post_cdp_publish_passes_every_kwarg_exactly(monkeypatch) -> None:
    captured = {}
    monkeypatch.setattr(core, "load_agent_config", lambda path=None: "cfg")
    monkeypatch.setattr(core.post_cdp_mod, "publish_post", lambda **kw: captured.update(kw) or {"clicked_post": True})

    core.post_cdp_publish("hi there", image="/tmp/pic.png", confirm=True, port=9999)
    assert captured == {
        "text": "hi there",
        "config": "cfg",
        "confirm": True,
        "image_path": "/tmp/pic.png",
        "port": 9999,
    }


def test_post_cdp_publish_defaults_image_and_port_to_none(monkeypatch) -> None:
    captured = {}
    monkeypatch.setattr(core, "load_agent_config", lambda path=None: "cfg")
    monkeypatch.setattr(core.post_cdp_mod, "publish_post", lambda **kw: captured.update(kw) or {"clicked_post": True})

    core.post_cdp_publish("hi")
    assert captured["image_path"] is None
    assert captured["port"] is None
    assert captured["confirm"] is False


def test_referral_draft_raises_when_disabled(monkeypatch) -> None:
    cfg = type("C", (), {"referral": type("R", (), {"enabled": False})()})()
    monkeypatch.setattr(core, "load_agent_config", lambda path=None: cfg)
    with pytest.raises(RuntimeError, match="referral is disabled"):
        core.referral_draft("Jordan", "hiring")


def test_referral_draft_delegates_when_enabled(monkeypatch) -> None:
    cfg = type("C", (), {"referral": type("R", (), {"enabled": True})()})()
    monkeypatch.setattr(core, "load_agent_config", lambda path=None: cfg)
    monkeypatch.setattr(core.copywriter_mod, "draft_referral", lambda **kw: "hi jordan")
    monkeypatch.setattr(core.copywriter_mod, "assert_human_copy", lambda draft, cfg: [])
    result = core.referral_draft("Jordan", "hiring")
    assert result == {"draft": "hi jordan", "problems": []}


def test_referral_draft_passes_every_kwarg_exactly(monkeypatch) -> None:
    cfg = type("C", (), {"referral": type("R", (), {"enabled": True})()})()
    captured = {}
    monkeypatch.setattr(core, "load_agent_config", lambda path=None: cfg)
    monkeypatch.setattr(core.copywriter_mod, "draft_referral", lambda **kw: captured.update(kw) or "drafted")
    monkeypatch.setattr(
        core.copywriter_mod,
        "assert_human_copy",
        lambda draft, config: [f"draft={draft}", f"config-is-cfg={config is cfg}"],
    )
    result = core.referral_draft("Jordan", "hiring for a role", headline="Recruiter", reengage=True, stale_days=30)
    assert result == {"draft": "drafted", "problems": ["draft=drafted", "config-is-cfg=True"]}
    assert captured == {
        "name": "Jordan",
        "headline": "Recruiter",
        "message": "hiring for a role",
        "config": cfg,
        "reengage": True,
        "stale_days": 30,
    }


def test_referral_draft_defaults_headline_reengage_stale_days(monkeypatch) -> None:
    cfg = type("C", (), {"referral": type("R", (), {"enabled": True})()})()
    captured = {}
    monkeypatch.setattr(core, "load_agent_config", lambda path=None: cfg)
    monkeypatch.setattr(core.copywriter_mod, "draft_referral", lambda **kw: captured.update(kw) or "drafted")
    monkeypatch.setattr(core.copywriter_mod, "assert_human_copy", lambda draft, config: [])
    core.referral_draft("Jordan", "hiring for a role")
    assert captured["headline"] == ""
    assert captured["reengage"] is False
    assert captured["stale_days"] == 0


def test_referral_send_delegates(monkeypatch) -> None:
    from linkedin_mcp.referral import ReferralResult

    monkeypatch.setattr(core, "load_agent_config", lambda path=None: "cfg")
    monkeypatch.setattr(
        core.referral_mod,
        "send_referral_for_candidate",
        lambda **kw: ReferralResult(name="Jordan", draft="hi", proof={"sent": True}),
    )
    result = core.referral_send("Jordan", "https://x", confirm=True)
    assert result == {"name": "Jordan", "skipped": "", "draft": "hi", "proof": {"sent": True}}


def test_referral_send_passes_every_kwarg_exactly(monkeypatch) -> None:
    from linkedin_mcp.referral import ReferralResult

    captured = {}
    monkeypatch.setattr(core, "load_agent_config", lambda path=None: "cfg")
    monkeypatch.setattr(
        core.referral_mod,
        "send_referral_for_candidate",
        lambda **kw: captured.update(kw)
        or ReferralResult(name="Jordan", skipped="already referred", draft="", proof=None),
    )
    result = core.referral_send(
        "Jordan", "https://x", text="hiring", stamp="2026-01-01", confirm=True, port=4321
    )
    assert result == {"name": "Jordan", "skipped": "already referred", "draft": "", "proof": None}
    assert captured == {
        "name": "Jordan",
        "url": "https://x",
        "thread_text": "hiring",
        "config": "cfg",
        "confirm": True,
        "stamp": "2026-01-01",
        "port": 4321,
    }


def test_referral_send_defaults_text_and_stamp_to_empty_string(monkeypatch) -> None:
    from linkedin_mcp.referral import ReferralResult

    captured = {}
    monkeypatch.setattr(core, "load_agent_config", lambda path=None: "cfg")
    monkeypatch.setattr(
        core.referral_mod,
        "send_referral_for_candidate",
        lambda **kw: captured.update(kw) or ReferralResult(name="Jordan", draft="hi", proof={"sent": True}),
    )
    core.referral_send("Jordan", "https://x")
    assert captured["thread_text"] == ""
    assert captured["stamp"] == ""
    assert captured["confirm"] is False
    assert captured["port"] is None


def test_auth_capture_and_env_delegate(monkeypatch) -> None:
    monkeypatch.setattr(core.auth_capture_mod, "capture", lambda port, timeout_seconds: {"captured": True, "port": port})
    assert core.auth_capture(port=1, timeout=2)["captured"] is True

    monkeypatch.setattr(core.auth_capture_mod, "env_line", lambda: "export X=1")
    assert core.auth_env() == "export X=1"


def test_auth_capture_uses_default_port_and_timeout(monkeypatch) -> None:
    captured = {}
    monkeypatch.setattr(
        core.auth_capture_mod,
        "capture",
        lambda port, timeout_seconds: captured.update(port=port, timeout_seconds=timeout_seconds) or {"captured": True},
    )
    core.auth_capture()
    assert captured == {"port": 9333, "timeout_seconds": 600.0}

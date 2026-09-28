"""core.py is the one place shared by the CLI and the MCP server. These
tests exercise it directly: the newly-added confirm guard on the Voyager
write surface, and passthrough for the read surface."""

from __future__ import annotations

from dataclasses import dataclass

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
    monkeypatch.setattr(core, "_voyager_client", lambda config_path=None: client)
    return client


# ---- read surface passes through untouched -------------------------------


def test_feed_passes_through(fake_client) -> None:
    posts = core.feed(limit=5)
    assert posts[0].text == "hi"
    assert fake_client.calls == [("feed", 5)]


def test_search_passes_through(fake_client) -> None:
    results = core.search("builder", limit=3)
    assert results[0].title == "A"
    assert fake_client.calls == [("search", "builder", 3)]


def test_get_profile_passes_through(fake_client) -> None:
    profile = core.get_profile("jane-doe")
    assert profile.public_id == "jane-doe"


def test_get_profile_posts_passes_through(fake_client) -> None:
    posts = core.get_profile_posts("jane-doe", limit=1)
    assert posts[0].text == "hi2"


def test_get_activity_passes_through(fake_client) -> None:
    post = core.get_activity("urn:li:activity:9")
    assert post.text == "hi3"


# ---- write surface: new confirm guard -------------------------------------


@pytest.mark.parametrize(
    "call",
    [
        lambda: core.publish_post("hello"),
        lambda: core.react("urn:li:activity:1"),
        lambda: core.unreact("urn:li:activity:1"),
        lambda: core.save_activity("urn:li:activity:1"),
        lambda: core.unsave_activity("urn:li:activity:1"),
        lambda: core.comment("urn:li:activity:1", "nice"),
    ],
)
def test_write_actions_refuse_without_confirm(fake_client, call) -> None:
    with pytest.raises(ConfirmRequiredError):
        call()
    assert fake_client.calls == []  # the underlying client method was never reached


def test_publish_post_with_confirm_reaches_client(fake_client) -> None:
    result = core.publish_post("hello", visibility="public", confirm=True)
    assert result == "posted public: hello"
    assert fake_client.calls == [("post", "hello", "public")]


def test_react_with_confirm_reaches_client(fake_client) -> None:
    result = core.react("urn:li:activity:1", reaction_type="celebrate", confirm=True)
    assert result == "reacted celebrate -> urn:li:activity:1"


def test_comment_with_confirm_reaches_client(fake_client) -> None:
    result = core.comment("urn:li:activity:1", "nice", confirm=True)
    assert result == "commented -> urn:li:activity:1: nice"


# ---- agent (CDP) surface: existing SendNotConfirmedError guard passes through --


def test_doctor_delegates_to_doctor_module(monkeypatch) -> None:
    monkeypatch.setattr(core, "load_agent_config", lambda path=None: "cfg")
    monkeypatch.setattr(core.doctor_mod, "check", lambda cfg: {"ok": True, "checks": [], "config": cfg})
    assert core.doctor() == {"ok": True, "checks": [], "config": "cfg"}


def test_classify_message_shapes_result(monkeypatch) -> None:
    class Cfg:
        pass

    monkeypatch.setattr(core, "load_agent_config", lambda path=None: Cfg())
    monkeypatch.setattr(core.classify_mod, "exclude_reason", lambda *a, **k: "")
    monkeypatch.setattr(core.classify_mod, "looks_like_hiring", lambda text: True)
    monkeypatch.setattr(core.classify_mod, "already_referred", lambda *a, **k: False)
    result = core.classify_message("hiring for a role")
    assert result == {"hiring": True, "excluded": False, "exclude_reason": "", "already_referred": False}


# ---- more direct wrapper coverage -----------------------------------------


def test_core_auth_status_and_diagnostics_call_through(fake_client, monkeypatch) -> None:
    fake_client.auth_status = lambda: {"source": "browser"}
    assert core.auth_status() == {"source": "browser"}

    monkeypatch.setattr(core, "collect_auth_diagnostics", lambda cfg: {"ok": True})
    monkeypatch.setattr(core, "_voyager_config", lambda config_path=None: "cfg")
    assert core.auth_diagnostics() == {"ok": True}


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


def test_messages_send_delegates_with_confirm(monkeypatch) -> None:
    captured = {}
    monkeypatch.setattr(core, "load_agent_config", lambda path=None: "cfg")
    monkeypatch.setattr(core.messaging_mod, "send_message", lambda **kw: captured.update(kw) or {"sent": True})

    result = core.messages_send("hi", confirm=True, target="t1")
    assert result == {"sent": True}
    assert captured["confirm"] is True
    assert captured["target"] == "t1"


def test_post_cdp_publish_delegates(monkeypatch) -> None:
    captured = {}
    monkeypatch.setattr(core, "load_agent_config", lambda path=None: "cfg")
    monkeypatch.setattr(core.post_cdp_mod, "publish_post", lambda **kw: captured.update(kw) or {"clicked_post": True})

    result = core.post_cdp_publish("hi", confirm=True)
    assert result == {"clicked_post": True}
    assert captured["confirm"] is True


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


def test_auth_capture_and_env_delegate(monkeypatch) -> None:
    monkeypatch.setattr(core.auth_capture_mod, "capture", lambda port, timeout_seconds: {"captured": True, "port": port})
    assert core.auth_capture(port=1, timeout=2)["captured"] is True

    monkeypatch.setattr(core.auth_capture_mod, "env_line", lambda: "export X=1")
    assert core.auth_env() == "export X=1"

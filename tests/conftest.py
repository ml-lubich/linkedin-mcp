from __future__ import annotations

import socket as _socket_mod

import pytest

from linkedin_mcp.agent_config import Config, PitchRule, ReferralConfig
from linkedin_mcp.models import Actor, Comment, EngagementMetrics, Post, Profile, ReactionSummary, SearchResult


@pytest.fixture(autouse=True)
def _block_real_sockets(monkeypatch):
    """Safety net for the "mock only CDP/network" rule: any test that forgets
    to mock the CDP boundary and tries to open a real socket (own_chrome.cdp,
    linkedin_mcp.cdp_session) fails loudly here instead of silently touching
    a real Chrome. test_cdp_session.py monkeypatches socket.create_connection
    itself, which overrides this for its own scope."""

    def _blocked(*args, **kwargs):
        raise AssertionError(
            "test opened a real socket.create_connection() -- mock the CDP boundary "
            "(own_chrome.cdp.evaluate/navigate/pick_page, or cdp_session.set_file_input) instead"
        )

    monkeypatch.setattr(_socket_mod, "create_connection", _blocked)


@pytest.fixture
def config(tmp_path) -> Config:
    """Agent-side (CDP) config fixture, shared by the ported linkedin-agent tests."""
    return Config(
        cdp_port=9222,
        self_name="Agent Self",
        governor_db_path=str(tmp_path / "governor.db"),
        referral=ReferralConfig(
            enabled=True,
            name="Referee Person",
            email="referee@example.com",
            linkedin_url="https://www.linkedin.com/in/referee-example/",
            resume_path="/tmp/referee_resume.pdf",
            attachment_name="resume.pdf",
            pitch=[
                PitchRule(keywords=["data", "analytics"], text="built data platforms that shipped"),
                PitchRule(keywords=["default"], text="is a strong generalist engineer"),
            ],
        ),
        reserved_for_self=["Reserved Co"],
        never_contact=["Blocked Person"],
        share_contact="decline",
    )


@pytest.fixture
def disabled_config(tmp_path) -> Config:
    return Config(governor_db_path=str(tmp_path / "governor-disabled.db"))


# Reused across many parametrized edge-case tables: empty, whitespace-only,
# unicode, emoji (incl. a ZWJ family sequence), very long, injection-shaped,
# control/newline characters, and a null byte. The point of each case is
# "must not crash and must return a sane type", not a specific value.
EDGE_STRINGS: list[str] = [
    "",
    " ",
    "   \t\n  ",
    "a",
    "héllo wörld café",
    "\U0001f680\U0001f525\U0001f4af",
    "\U0001f468‍\U0001f469‍\U0001f467‍\U0001f466",
    "x" * 5000,
    "'; DROP TABLE actions; --",
    "<script>alert(1)</script>",
    "line1\nline2\r\nline3",
    "\x00null\x00byte",
    "مرحبا",  # Arabic "hello" (RTL)
    "Hello 世界 \U0001f30d",  # mixed scripts + emoji
    "control\x07bell\x1bchars",
    "-----BEGIN PRIVATE KEY-----",
    "{{7*7}}",  # template-injection-shaped
    "a" * 65600,  # forces the 2-byte-length WS frame branch if ever framed
]


@pytest.fixture
def sample_profile() -> Profile:
    return Profile(
        urn="urn:li:fs_profile:123",
        public_id="ada-lovelace",
        full_name="Ada Lovelace",
        headline="Mathematician",
        summary="Built the first algorithm for a machine.",
        location="London",
        followers_count=1200,
        connections_count=500,
        profile_url="https://www.linkedin.com/in/ada-lovelace/",
        skills=["Python", "Math"],
    )


@pytest.fixture
def sample_post(sample_profile: Profile) -> Post:
    return Post(
        urn="urn:li:activity:999",
        author=sample_profile.as_actor(),
        text="Shipping linkedin-cli today #python @team",
        created_at="1h",
        url="https://www.linkedin.com/feed/update/urn:li:activity:999/",
        metrics=EngagementMetrics(reactions=42, comments=4, reposts=2),
        reactions=ReactionSummary(like=30, celebrate=10, insightful=2),
        comments=[
            Comment(
                urn="urn:li:comment:1",
                author=Actor(name="Grace Hopper", public_id="grace-hopper"),
                text="Looks great",
            )
        ],
        hashtags=["#python"],
        mentions=["@team"],
        saved_by_viewer=True,
    )


@pytest.fixture
def sample_search_result(sample_profile: Profile, sample_post: Post) -> SearchResult:
    return SearchResult(
        kind="post",
        title="Ada shared a post",
        subtitle=sample_profile.headline,
        snippet=sample_post.text,
        url=sample_post.url,
        profile=sample_profile,
        post=sample_post,
    )

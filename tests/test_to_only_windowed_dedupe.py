"""Security fix (review F1): core.messages_send(to=..., no target) had NO
dedupe at all (only budget pacing, see review H2) -- a verification false
negative (M1) plus an agent retry could send the identical text to the
same person twice. Fix: `to`-only sends dedupe on
f"{to}:{sha256(normalized text)[:16]}" WITHIN A TIME WINDOW (24h default,
config.to_dedupe_window_seconds) -- the identical text to the same person
is refused inside the window; a different reply, or the same short text
after the window passes, still goes through. An explicit `target` keeps
its existing permanent dedupe (review H2), unaffected.
"""

from __future__ import annotations

import pytest

import linkedin_mcp.core as core
from linkedin_mcp.governor import Governor, RateLimited


@pytest.fixture
def config(tmp_path):
    return type(
        "C",
        (),
        {"cdp_port": 9222, "governor_db_path": str(tmp_path / "g.db"), "to_dedupe_window_seconds": 86400},
    )()


@pytest.fixture(autouse=True)
def _fake_cdp(monkeypatch):
    def fake_evaluate_pinned(ws_url, script):
        if '"query": "threads"' in script:
            return {"threads": [{"name": "John", "href": "/messaging/thread/1/", "preview": "", "unread": False}]}
        if "matches.length" in script:  # the select-click ACT_JS expression
            return {"action": "select", "ok": True, "matched": "John", "ambiguous": False, "matches": ["John"]}
        if "insertText" in script:
            return True
        if "location.href" in script:
            return "https://www.linkedin.com/messaging/"
        if "aria-disabled" in script:
            return True
        if ".click(); return !!b" in script:
            return True
        return "delivered hi bye"

    monkeypatch.setattr(core.messaging_mod, "evaluate_pinned", fake_evaluate_pinned)
    monkeypatch.setattr(core.messaging_mod.time, "sleep", lambda s: None)


def test_identical_text_to_the_same_to_within_the_window_is_rate_limited(config, monkeypatch):
    monkeypatch.setattr(core, "load_agent_config", lambda path=None: config)

    core.messages_send("hi", to="John", confirm=True)
    with pytest.raises(RateLimited):
        core.messages_send("hi", to="John", confirm=True)


def test_different_text_to_the_same_to_is_not_blocked(config, monkeypatch):
    monkeypatch.setattr(core, "load_agent_config", lambda path=None: config)

    core.messages_send("hi", to="John", confirm=True)
    result = core.messages_send("bye", to="John", confirm=True)  # must not raise

    assert result["sent"] is True


def test_identical_text_after_the_window_elapses_is_allowed(config, monkeypatch):
    """Inject the clock via a real Governor pre-seeded at t0, then simulate
    time passing by recording with an overridden `now`."""
    monkeypatch.setattr(core, "load_agent_config", lambda path=None: config)

    real_governor_cls = core.Governor
    created = {}

    class FrozenGovernor(real_governor_cls):
        def __init__(self, db_path):
            super().__init__(db_path, now=created.setdefault("now", 1_000_000.0))

    monkeypatch.setattr(core, "Governor", FrozenGovernor)
    core.messages_send("hi", to="John", confirm=True)

    created["now"] = 1_000_000.0 + config.to_dedupe_window_seconds + 1
    result = core.messages_send("hi", to="John", confirm=True)  # must not raise -- window elapsed

    assert result["sent"] is True


def test_second_identical_to_only_send_never_reaches_send_message_when_verification_never_matched(config, monkeypatch):
    """The exact double-send risk this fixes: verification reports
    sent:false (a false negative), then a retry with the identical text
    must be refused rather than clicking Send again."""

    def fake_evaluate_never_verifies(ws_url, script):
        if '"query": "threads"' in script:
            return {"threads": [{"name": "John", "href": "/messaging/thread/1/", "preview": "", "unread": False}]}
        if "matches.length" in script:
            return {"action": "select", "ok": True, "matched": "John", "ambiguous": False, "matches": ["John"]}
        if "insertText" in script:
            return True
        if "location.href" in script:
            return "https://www.linkedin.com/messaging/"
        if "aria-disabled" in script:
            return True
        if ".click(); return !!b" in script:
            return True
        if "items.length - 1" in script:
            return "unrelated stale message"
        if "trim().length === 0" in script:
            return False
        return ""

    monkeypatch.setattr(core.messaging_mod, "evaluate_pinned", fake_evaluate_never_verifies)
    monkeypatch.setattr(core, "load_agent_config", lambda path=None: config)

    result = core.messages_send("hi", to="John", confirm=True)
    assert result["sent"] is False  # verification genuinely failed

    with pytest.raises(RateLimited):
        core.messages_send("hi", to="John", confirm=True)


def test_explicit_target_still_dedupes_permanently_not_by_window(config, monkeypatch):
    monkeypatch.setattr(core, "load_agent_config", lambda path=None: config)

    core.messages_send("hi", target="thread-1", confirm=True)
    with pytest.raises(RateLimited):
        # Different text, same explicit target -- explicit target dedupe is
        # keyed on the target alone, unaffected by F1's to-only text-hash change.
        core.messages_send("totally different text", target="thread-1", confirm=True)

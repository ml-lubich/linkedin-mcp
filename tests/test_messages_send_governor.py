"""Correctness fix (review B5): messages_send never actually constructed a
Governor, so the `target` parameter's pacing/dedup claim in its docstring
was a no-op -- a script could hammer the same thread every call. Wiring it:
a repeat send to the same target within the window must be refused.

Exercises the real send_message + real Governor end to end; only the CDP
boundary (own_chrome.cdp.evaluate) is mocked, same convention as
test_referral.py's rate-limit test.
"""

from __future__ import annotations

import pytest

import linkedin_mcp.core as core
from linkedin_mcp.governor import Governor, RateLimited


@pytest.fixture
def config(tmp_path):
    return type("C", (), {"cdp_port": 9222, "governor_db_path": str(tmp_path / "g.db")})()


@pytest.fixture(autouse=True)
def _fake_cdp(monkeypatch):
    def fake_evaluate(port, script, **kw):
        if "insertText" in script:
            return True
        if "getAttribute('disabled')" in script:
            return True
        if ".click(); return !!b" in script:
            return True
        return "delivered hello hi"

    monkeypatch.setattr(core.messaging_mod, "evaluate", fake_evaluate)
    monkeypatch.setattr(core.messaging_mod.time, "sleep", lambda s: None)


def test_second_send_to_the_same_target_is_rate_limited(config, monkeypatch):
    monkeypatch.setattr(core, "load_agent_config", lambda path=None: config)

    core.messages_send("hi", target="thread-1", confirm=True)

    with pytest.raises(RateLimited):
        core.messages_send("hi again", target="thread-1", confirm=True)


def test_different_targets_are_not_rate_limited(config, monkeypatch):
    monkeypatch.setattr(core, "load_agent_config", lambda path=None: config)

    core.messages_send("hi", target="thread-1", confirm=True)
    result = core.messages_send("hi", target="thread-2", confirm=True)  # must not raise

    assert result["sent"] is True


def test_messages_send_passes_a_real_governor_when_target_is_set(config, monkeypatch):
    captured = {}
    real_send_message = core.messaging_mod.send_message

    def spy_send_message(**kw):
        captured.update(kw)
        return real_send_message(**kw)

    monkeypatch.setattr(core, "load_agent_config", lambda path=None: config)
    monkeypatch.setattr(core.messaging_mod, "send_message", spy_send_message)

    core.messages_send("hi", target="thread-1", confirm=True)

    assert isinstance(captured.get("governor"), Governor)


def test_no_governor_constructed_without_a_target(config, monkeypatch):
    captured = {}
    real_send_message = core.messaging_mod.send_message

    def spy_send_message(**kw):
        captured.update(kw)
        return real_send_message(**kw)

    monkeypatch.setattr(core, "load_agent_config", lambda path=None: config)
    monkeypatch.setattr(core.messaging_mod, "send_message", spy_send_message)

    core.messages_send("hi", confirm=True)

    assert captured.get("governor") is None


# ---- H2: `to`-only paces without permanent dedupe; `target` still dedupes --


def test_two_confirmed_sends_with_the_same_to_both_reach_send_message(config, monkeypatch):
    monkeypatch.setattr(core, "load_agent_config", lambda path=None: config)
    monkeypatch.setattr(core.messaging_mod, "select_thread", lambda port, name: {"ok": True, "ambiguous": False})

    core.messages_send("hi", to="John", confirm=True)
    result = core.messages_send("hi", to="John", confirm=True)  # must not raise

    assert result["sent"] is True


def test_budget_exhaustion_via_to_still_raises_rate_limited(config, monkeypatch):
    from linkedin_mcp.governor import LIMITS, RateLimited

    monkeypatch.setattr(core, "load_agent_config", lambda path=None: config)
    monkeypatch.setattr(core.messaging_mod, "select_thread", lambda port, name: {"ok": True, "ambiguous": False})

    limit, _window = LIMITS["message"]
    for _ in range(limit):
        core.messages_send("hi", to="John", confirm=True)
    with pytest.raises(RateLimited):
        core.messages_send("hi", to="John", confirm=True)


def test_same_explicit_target_twice_is_rate_limited(config, monkeypatch):
    from linkedin_mcp.governor import RateLimited

    monkeypatch.setattr(core, "load_agent_config", lambda path=None: config)

    core.messages_send("hi", target="thread-1", confirm=True)
    with pytest.raises(RateLimited):
        core.messages_send("hi", target="thread-1", confirm=True)

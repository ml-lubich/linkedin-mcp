"""Correctness fix (review H2): messages_send(to=NAME) keyed the governor's
permanent per-target dedupe on `identity = target or to` -- after one
confirmed `--to "John"` send, every later reply to John was RateLimited
forever, even a week later.

Superseded by review F1: `to`-only sends now dedupe on a windowed key
(Governor.check_windowed) instead of the un-deduped check_budget/record_paced
pair this file originally exercised -- those methods are gone, replaced by
check_windowed. This file now tests check_windowed directly at the Governor
level (budget still enforced, no permanent block) and send_message's
dedupe_window_seconds parameter (None = permanent, a number = windowed,
matching F1's fix in test_to_only_windowed_dedupe.py at the core level)."""

from __future__ import annotations

import pytest

from linkedin_mcp.governor import Governor, RateLimited


def test_check_windowed_does_not_block_a_repeat_target_outside_the_window(tmp_path):
    gov = Governor(tmp_path / "g.db", now=1_000_000.0)
    gov.check_windowed("message", "John", window_seconds=10)
    gov.record("message", "John")
    # 20s later, outside the 10s window -- must not raise.
    gov._now_override = 1_000_020.0
    gov.check_windowed("message", "John", window_seconds=10)  # must not raise
    gov.close()


def test_check_windowed_still_enforces_the_rolling_budget(tmp_path):
    from linkedin_mcp.governor import LIMITS

    gov = Governor(tmp_path / "g.db", now=1_000_000.0)
    limit, _window = LIMITS["message"]
    for i in range(limit):
        gov.check_windowed("message", f"target-{i}", window_seconds=10)
        gov.record("message", f"target-{i}")
    with pytest.raises(RateLimited):
        gov.check_windowed("message", "one-more", window_seconds=10)
    gov.close()


def test_check_with_explicit_target_still_dedupes_permanently(tmp_path):
    gov = Governor(tmp_path / "g.db", now=1_000_000.0)
    gov.check("message", "thread-1")
    gov.record("message", "thread-1")
    with pytest.raises(RateLimited):
        gov.check("message", "thread-1")
    gov.close()


def test_send_message_windowed_dedupe_paces_without_blocking_different_targets(config, monkeypatch):
    from linkedin_mcp import messaging

    def fake_evaluate_pinned(ws_url, script):
        if "insertText" in script:
            return True
        if "location.href" in script:
            return "https://www.linkedin.com/messaging/"
        if "aria-disabled" in script:
            return True
        if ".click(); return !!b" in script:
            return True
        return "delivered hi"

    monkeypatch.setattr(messaging, "evaluate_pinned", fake_evaluate_pinned)
    monkeypatch.setattr(messaging.time, "sleep", lambda s: None)
    gov = Governor(config.governor_db_path, now=1_000_000.0)

    # Different target each time -- a windowed dedupe never blocks distinct
    # targets, only an identical (action, target) repeat within the window.
    for i in range(3):
        proof = messaging.send_message(
            "hi", config, confirm=True, governor=gov, target=f"John-{i}",
            dedupe_window_seconds=86400, verify_attempts=1, verify_wait_seconds=0,
        )
        assert proof["sent"] is True
    gov.close()


def test_send_message_dedupe_window_none_still_blocks_a_repeat_target(config, monkeypatch):
    from linkedin_mcp import messaging

    def fake_evaluate_pinned(ws_url, script):
        if "insertText" in script:
            return True
        if "location.href" in script:
            return "https://www.linkedin.com/messaging/"
        if "aria-disabled" in script:
            return True
        if ".click(); return !!b" in script:
            return True
        return "delivered hi"

    monkeypatch.setattr(messaging, "evaluate_pinned", fake_evaluate_pinned)
    monkeypatch.setattr(messaging.time, "sleep", lambda s: None)
    gov = Governor(config.governor_db_path, now=1_000_000.0)

    messaging.send_message(
        "hi", config, confirm=True, governor=gov, target="John", dedupe_window_seconds=None,
        verify_attempts=1, verify_wait_seconds=0,
    )
    with pytest.raises(RateLimited):
        messaging.send_message(
            "hi", config, confirm=True, governor=gov, target="John", dedupe_window_seconds=None,
            verify_attempts=1, verify_wait_seconds=0,
        )
    gov.close()

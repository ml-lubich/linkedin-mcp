"""Correctness fix (review H2): messages_send(to=NAME) keyed the governor's
permanent per-target dedupe on `identity = target or to` -- after one
confirmed `--to "John"` send, every later reply to John was RateLimited
forever, even a week later. Fix: `to`-only sends count against the rolling
budget but are NOT deduped; permanent dedupe only applies with an explicit
`target`."""

from __future__ import annotations

import pytest

from linkedin_mcp.governor import Governor, RateLimited


def test_check_budget_does_not_dedupe_by_target(tmp_path):
    gov = Governor(tmp_path / "g.db", now=1_000_000.0)
    gov.check_budget("message")
    gov.record_paced("message")
    # A second call for the exact same real-world target must not be
    # blocked by "already done" -- only the rolling budget applies.
    gov.check_budget("message")  # must not raise
    gov.close()


def test_check_budget_still_enforces_the_rolling_budget(tmp_path):
    from linkedin_mcp.governor import LIMITS

    gov = Governor(tmp_path / "g.db", now=1_000_000.0)
    limit, _window = LIMITS["message"]
    for _ in range(limit):
        gov.check_budget("message")
        gov.record_paced("message")
    with pytest.raises(RateLimited):
        gov.check_budget("message")
    gov.close()


def test_check_with_explicit_target_still_dedupes_permanently(tmp_path):
    gov = Governor(tmp_path / "g.db", now=1_000_000.0)
    gov.check("message", "thread-1")
    gov.record("message", "thread-1")
    with pytest.raises(RateLimited):
        gov.check("message", "thread-1")
    gov.close()


def test_send_message_dedupe_false_paces_without_blocking_repeats(config, monkeypatch):
    from linkedin_mcp import messaging

    def fake_evaluate(port, script, **kw):
        if "insertText" in script:
            return True
        if "aria-disabled" in script:
            return True
        if ".click(); return !!b" in script:
            return True
        return "delivered hi"

    monkeypatch.setattr(messaging, "evaluate", fake_evaluate)
    monkeypatch.setattr(messaging.time, "sleep", lambda s: None)
    gov = Governor(config.governor_db_path, now=1_000_000.0)

    for _ in range(3):  # would blow a dedupe-by-target budget of 1 if dedupe=True
        proof = messaging.send_message(
            "hi", config, confirm=True, governor=gov, target="John", dedupe=False,
            verify_attempts=1, verify_wait_seconds=0,
        )
        assert proof["sent"] is True
    gov.close()


def test_send_message_dedupe_true_still_blocks_a_repeat_target(config, monkeypatch):
    from linkedin_mcp import messaging

    def fake_evaluate(port, script, **kw):
        if "insertText" in script:
            return True
        if "aria-disabled" in script:
            return True
        if ".click(); return !!b" in script:
            return True
        return "delivered hi"

    monkeypatch.setattr(messaging, "evaluate", fake_evaluate)
    monkeypatch.setattr(messaging.time, "sleep", lambda s: None)
    gov = Governor(config.governor_db_path, now=1_000_000.0)

    messaging.send_message(
        "hi", config, confirm=True, governor=gov, target="John", dedupe=True, verify_attempts=1, verify_wait_seconds=0
    )
    with pytest.raises(RateLimited):
        messaging.send_message(
            "hi", config, confirm=True, governor=gov, target="John", dedupe=True,
            verify_attempts=1, verify_wait_seconds=0,
        )
    gov.close()

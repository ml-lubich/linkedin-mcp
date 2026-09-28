"""Correctness fix (review M1): proof-of-send compared raw, un-normalized
text, so a multi-line or emoji message rendered slightly differently by
LinkedIn's DOM could report sent:false after a *real* send. Since the
governor only recorded on a verified sent:true, that false negative meant a
retry wasn't blocked -- an actual duplicate send. Fix: normalize whitespace
on both sides of the comparison, and record with the governor right after
the confirmed click (not gated on verification succeeding)."""

from __future__ import annotations

import pytest

from linkedin_mcp import messaging
from linkedin_mcp.governor import Governor, RateLimited


def test_multiline_text_with_different_rendered_whitespace_reports_sent(config, monkeypatch):
    def fake_evaluate(port, script, **kw):
        if "insertText" in script:
            return True
        if "aria-disabled" in script:
            return True
        if ".click(); return !!b" in script:
            return True
        if "items.length - 1" in script:
            # LinkedIn rendered the two lines with a different whitespace
            # run (extra blank line / spaces) than the raw sent text.
            return "line1\n\n   line2  "
        if "trim().length === 0" in script:
            return True
        return ""

    monkeypatch.setattr(messaging, "evaluate", fake_evaluate)
    monkeypatch.setattr(messaging.time, "sleep", lambda s: None)

    proof = messaging.send_message(
        "line1\nline2", config, confirm=True, verify_attempts=1, verify_wait_seconds=0
    )

    assert proof["sent"] is True


def test_governor_records_on_the_confirmed_click_even_if_verification_never_matches(config, monkeypatch, tmp_path):
    def fake_evaluate(port, script, **kw):
        if "insertText" in script:
            return True
        if "aria-disabled" in script:
            return True
        if ".click(); return !!b" in script:
            return True
        if "items.length - 1" in script:
            return "totally unrelated text that never matches"
        if "trim().length === 0" in script:
            return False  # compose never appears to clear either
        return ""

    monkeypatch.setattr(messaging, "evaluate", fake_evaluate)
    monkeypatch.setattr(messaging.time, "sleep", lambda s: None)
    gov = Governor(tmp_path / "g.db", now=1_000_000.0)

    proof = messaging.send_message(
        "hi", config, confirm=True, governor=gov, target="thread-1",
        verify_attempts=1, verify_wait_seconds=0,
    )

    assert proof["sent"] is False  # verification genuinely failed
    # But the click DID happen -- a retry to the same target must still be
    # blocked, because retrying now risks an actual duplicate send.
    with pytest.raises(RateLimited):
        messaging.send_message(
            "hi", config, confirm=True, governor=gov, target="thread-1",
            verify_attempts=1, verify_wait_seconds=0,
        )
    gov.close()

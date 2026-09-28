"""Correctness fix (review B9): a short message (e.g. "ok", 2 chars) could
be falsely reported as sent. Two bugs compounded: (1) `_compose_is_empty`
used `innerText.trim().length < 5`, so a compose box that still had "ok"
sitting in it (send silently failed) read as "empty"; (2) without an
attachment hint, the verify loop accepted *any* non-empty last message as
proof, including a stale older message, instead of checking the sent text
was actually the one that landed. Also: `_send_button_enabled` ignored
aria-disabled, a common a11y way to disable a button without the native
`disabled` attribute."""

from __future__ import annotations

from linkedin_mcp import messaging


def test_compose_is_empty_requires_truly_zero_length_not_under_five(monkeypatch):
    # A leftover 2-char "ok" still sitting in the box must not read as empty.
    calls = []

    def fake_evaluate(ws_url, script):
        calls.append(script)
        if "innerText.trim().length" in script:
            # Simulate: box still contains "ok" (2 chars) -- not truly empty.
            return False
        return True

    monkeypatch.setattr(messaging, "evaluate_pinned", fake_evaluate)
    assert messaging._compose_is_empty("ws://127.0.0.1:9222/devtools/page/msg") is False
    assert any("=== 0" in c for c in calls), "must check for exactly zero length, not a small threshold"


def test_send_message_does_not_report_sent_for_a_stale_unrelated_last_message(config, monkeypatch):
    """No attachment hint, box did NOT clear, but an old unrelated message
    is technically "non-empty" -- must not be mistaken for proof of send."""
    monkeypatch.setattr(messaging.time, "sleep", lambda s: None)

    def fake_evaluate(ws_url, script):
        if "insertText" in script:
            return True
        if "location.href" in script:
            return "https://www.linkedin.com/messaging/"
        if "aria-disabled" in script:
            return True  # enabled
        if ".click(); return !!b" in script:
            return True
        if "items.length - 1" in script:
            return "some unrelated older message"
        if "innerText.trim().length" in script:
            return False  # compose did not clear
        return ""

    monkeypatch.setattr(messaging, "evaluate_pinned", fake_evaluate)
    proof = messaging.send_message("ok", config, confirm=True, verify_attempts=1, verify_wait_seconds=0)
    assert proof["sent"] is False


def test_send_message_reports_sent_when_the_short_text_actually_landed(config, monkeypatch):
    monkeypatch.setattr(messaging.time, "sleep", lambda s: None)

    def fake_evaluate(ws_url, script):
        if "insertText" in script:
            return True
        if "location.href" in script:
            return "https://www.linkedin.com/messaging/"
        if "aria-disabled" in script:
            return True
        if ".click(); return !!b" in script:
            return True
        if "items.length - 1" in script:
            return "ok"
        if "innerText.trim().length" in script:
            return True  # compose cleared
        return ""

    monkeypatch.setattr(messaging, "evaluate_pinned", fake_evaluate)
    proof = messaging.send_message("ok", config, confirm=True, verify_attempts=1, verify_wait_seconds=0)
    assert proof["sent"] is True


def test_send_button_enabled_honors_aria_disabled(monkeypatch):
    calls = []

    def fake_evaluate(ws_url, script):
        calls.append(script)
        return False  # button reports aria-disabled=true -> not enabled

    monkeypatch.setattr(messaging, "evaluate_pinned", fake_evaluate)
    assert messaging._send_button_enabled("ws://127.0.0.1:9222/devtools/page/msg") is False
    assert any("aria-disabled" in c for c in calls)


def test_send_message_disabled_via_aria_only_raises(config, monkeypatch):
    def fake_evaluate(ws_url, script):
        if "insertText" in script:
            return True
        if "location.href" in script:
            return "https://www.linkedin.com/messaging/"
        if "aria-disabled" in script:
            return False  # native disabled attr absent, but aria-disabled=true
        return ""

    monkeypatch.setattr(messaging, "evaluate_pinned", fake_evaluate)
    try:
        messaging.send_message("ok", config, confirm=True)
        raised = False
    except messaging.ChromeError:
        raised = True
    assert raised, "an aria-disabled send button must be treated as disabled"

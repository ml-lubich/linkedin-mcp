from __future__ import annotations

import pytest

import linkedin_mcp.messaging as messaging


def test_open_thread_navigates(config, monkeypatch):
    calls = []
    monkeypatch.setattr(messaging, "navigate", lambda port, url, **kw: calls.append((port, url, kw.get("host"))))
    url = "https://www.linkedin.com/messaging/thread/abc/"
    messaging.open_thread(url, config.cdp_port)
    assert calls == [(config.cdp_port, url, messaging.TAB)]


def test_read_thread_slices_bodies(config, monkeypatch):
    import json as _json

    payload = _json.dumps({"url": "u", "bodies": ["a", "b", "c"], "speakers": ["X"]})
    monkeypatch.setattr(messaging, "evaluate", lambda *a, **k: payload)
    result = messaging.read_thread(config.cdp_port, limit=2)
    assert result["bodies"] == ["b", "c"]
    assert result["url"] == "u"


def test_read_thread_zero_limit_keeps_all(config, monkeypatch):
    import json as _json

    payload = _json.dumps({"url": "u", "bodies": ["a", "b"], "speakers": []})
    monkeypatch.setattr(messaging, "evaluate", lambda *a, **k: payload)
    result = messaging.read_thread(config.cdp_port, limit=0)
    assert result["bodies"] == ["a", "b"]


def test_send_message_requires_confirm(config, monkeypatch):
    monkeypatch.setattr(messaging, "evaluate_pinned", lambda *a, **k: True)
    with pytest.raises(messaging.SendNotConfirmedError):
        messaging.send_message("hello", config, confirm=False)


def test_send_message_raises_when_compose_missing(config, monkeypatch):
    monkeypatch.setattr(messaging, "evaluate_pinned", lambda *a, **k: False)
    with pytest.raises(messaging.ChromeError):
        messaging.send_message("hello", config, confirm=True)


def test_send_message_full_success(config, monkeypatch):
    state = {"sent_clicked": False}

    def fake_evaluate(port, script, **kw):
        if "insertText" in script:
            return True
        if "location.href" in script:
            return "https://www.linkedin.com/messaging/"
        if "getAttribute('disabled')" in script:
            return True  # enabled
        if ".click(); return !!b" in script:
            state["sent_clicked"] = True
            return True
        if "innerText : ''" in script or "innerText;})()" in script:
            return f"delivered to {config.referral.attachment_name}"
        if "innerText.trim().length" in script:
            return True
        return ""

    monkeypatch.setattr(messaging, "evaluate_pinned", fake_evaluate)
    monkeypatch.setattr(messaging, "set_file_input", lambda *a, **k: True)
    proof = messaging.send_message(
        "hello",
        config,
        confirm=True,
        attachment_path=config.referral.resume_path,
        attachment_name_hint=config.referral.attachment_name,
        verify_attempts=1,
        verify_wait_seconds=0,
        attach_wait_seconds=0,
    )
    assert state["sent_clicked"] is True
    assert proof["attached"] is True
    assert proof["sent"] is True


def test_send_message_attachment_not_found_raises(config, monkeypatch):
    monkeypatch.setattr(messaging, "evaluate_pinned", lambda *a, **k: True)
    monkeypatch.setattr(messaging, "set_file_input", lambda *a, **k: False)
    with pytest.raises(messaging.ChromeError, match="no file input"):
        messaging.send_message("hello", config, confirm=True, attachment_path=config.referral.resume_path)


def test_send_message_disabled_button_raises(config, monkeypatch):
    def fake_evaluate(port, script, **kw):
        if "insertText" in script:
            return True
        if "location.href" in script:
            return "https://www.linkedin.com/messaging/"
        if "getAttribute('disabled')" in script:
            return False  # disabled
        return ""

    monkeypatch.setattr(messaging, "evaluate_pinned", fake_evaluate)
    with pytest.raises(messaging.ChromeError, match="disabled"):
        messaging.send_message("hello", config, confirm=True)


def test_send_message_with_governor_checks_before_sending(config, monkeypatch, tmp_path):
    from linkedin_mcp.governor import Governor, RateLimited

    def fake_evaluate(port, script, **kw):
        if "insertText" in script:
            return True
        if "location.href" in script:
            return "https://www.linkedin.com/messaging/"
        if "getAttribute('disabled')" in script:
            return True
        if ".click(); return !!b" in script:
            return True
        return "delivered hello hi"

    monkeypatch.setattr(messaging, "evaluate_pinned", fake_evaluate)
    gov = Governor(tmp_path / "gov.db", now=1_000_000.0)
    proof = messaging.send_message(
        "hello", config, confirm=True, governor=gov, target="alice", action="message",
        verify_attempts=1, verify_wait_seconds=0,
    )
    assert proof["sent"] is True
    assert gov.already_done("message", "alice")  # governor.record() was called

    # A second send to the same target must now be refused by the governor,
    # before ever touching the send button again.
    with pytest.raises(RateLimited):
        messaging.send_message(
            "hello again", config, confirm=True, governor=gov, target="alice", action="message",
            verify_attempts=1, verify_wait_seconds=0,
        )
    gov.close()


def test_send_message_governor_recorded_on_click_even_when_verification_fails(config, monkeypatch, tmp_path):
    # Updated for review M1: the click already happened by this point, so a
    # retry to the same target risks an actual duplicate send even when
    # verification reports a false "not sent" -- the governor now records
    # right after the confirmed click, not gated on verification succeeding.
    # See test_send_message_double_send.py for the full regression coverage.
    from linkedin_mcp.governor import Governor

    def fake_evaluate(port, script, **kw):
        if "insertText" in script:
            return True
        if "location.href" in script:
            return "https://www.linkedin.com/messaging/"
        if "getAttribute('disabled')" in script:
            return True
        if ".click(); return !!b" in script:
            return True
        if "innerText.trim().length" in script:
            return False  # compose never empties -> proof["sent"] stays False
        return ""

    monkeypatch.setattr(messaging, "evaluate_pinned", fake_evaluate)
    gov = Governor(tmp_path / "gov.db", now=1_000_000.0)
    proof = messaging.send_message(
        "hello", config, confirm=True, governor=gov, target="bob", action="message",
        verify_attempts=1, verify_wait_seconds=0,
    )
    assert proof["sent"] is False
    assert gov.already_done("message", "bob")  # recorded on the click, not gated on verification
    gov.close()


def test_send_message_without_target_skips_governor_entirely(config, monkeypatch, tmp_path):
    """No target means no identity to dedupe/budget against -- the governor
    check is skipped rather than crashing on an empty key."""
    from linkedin_mcp.governor import Governor

    def fake_evaluate(port, script, **kw):
        if "insertText" in script:
            return True
        if "location.href" in script:
            return "https://www.linkedin.com/messaging/"
        if "getAttribute('disabled')" in script:
            return True
        if ".click(); return !!b" in script:
            return True
        return "delivered hello hi"

    monkeypatch.setattr(messaging, "evaluate_pinned", fake_evaluate)
    gov = Governor(tmp_path / "gov.db", now=1_000_000.0)
    for _ in range(3):  # would blow a budget of 1 if the governor were consulted
        proof = messaging.send_message(
            "hi", config, confirm=True, governor=gov, target="", verify_attempts=1, verify_wait_seconds=0
        )
        assert proof["sent"] is True
    gov.close()


def test_send_message_incomplete_delivery_reports_not_sent(config, monkeypatch):
    def fake_evaluate(port, script, **kw):
        if "insertText" in script:
            return True
        if "location.href" in script:
            return "https://www.linkedin.com/messaging/"
        if "getAttribute('disabled')" in script:
            return True
        if ".click(); return !!b" in script:
            return True
        if "innerText.trim().length" in script:
            return False  # compose never empties
        return ""

    monkeypatch.setattr(messaging, "evaluate_pinned", fake_evaluate)
    proof = messaging.send_message("hello", config, confirm=True, verify_attempts=2, verify_wait_seconds=0)
    assert proof["sent"] is False

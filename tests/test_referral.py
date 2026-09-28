from __future__ import annotations

import linkedin_mcp.referral as referral_mod
from linkedin_mcp.messaging import SendNotConfirmedError


def test_send_referral_disabled_short_circuits(disabled_config):
    result = referral_mod.send_referral_for_candidate(
        name="Jordan Lee", url="https://example.com", thread_text="hi", config=disabled_config, confirm=False
    )
    assert result.skipped
    assert result.proof is None


def test_send_referral_missing_resume_path_short_circuits(config):
    config.referral.resume_path = ""
    result = referral_mod.send_referral_for_candidate(
        name="Jordan Lee", url="https://example.com", thread_text="hi", config=config, confirm=False
    )
    assert "resume_path" in result.skipped


def test_send_referral_already_referred_short_circuits(config, monkeypatch):
    monkeypatch.setattr(referral_mod, "open_thread", lambda *a, **k: None)
    monkeypatch.setattr(
        referral_mod,
        "read_thread",
        lambda *a, **k: {"bodies": [f"already told them about {config.referral.email}"], "speakers": []},
    )
    result = referral_mod.send_referral_for_candidate(
        name="Jordan Lee", url="https://example.com", thread_text="hi", config=config, confirm=False
    )
    assert result.skipped == "already referred"


def test_send_referral_drafts_and_sends(config, monkeypatch):
    monkeypatch.setattr(referral_mod, "open_thread", lambda *a, **k: None)
    monkeypatch.setattr(
        referral_mod,
        "read_thread",
        lambda *a, **k: {"bodies": ["Exciting AI role at Acme"], "speakers": ["Jordan Lee"]},
    )

    captured = {}

    def fake_send_message(text, config, confirm, attachment_path, attachment_name_hint, port, **kwargs):
        captured["text"] = text
        captured["attachment_path"] = attachment_path
        captured["governor_kwargs"] = kwargs
        return {"sent": confirm}

    monkeypatch.setattr(referral_mod, "send_message", fake_send_message)
    result = referral_mod.send_referral_for_candidate(
        name="Jordan Lee",
        url="https://example.com/thread",
        thread_text="Exciting AI role at Acme",
        config=config,
        confirm=True,
        stamp="Tue",
    )
    assert result.skipped == ""
    assert "jordan" in result.draft.lower()
    assert captured["attachment_path"] == config.referral.resume_path
    assert result.proof == {"sent": True}
    assert captured["governor_kwargs"]["target"] == "https://example.com/thread"
    assert captured["governor_kwargs"]["action"] == "referral"
    assert captured["governor_kwargs"]["governor"] is not None


def test_send_referral_reengage_when_last_speaker_is_self(config, monkeypatch):
    monkeypatch.setattr(referral_mod, "open_thread", lambda *a, **k: None)
    monkeypatch.setattr(
        referral_mod,
        "read_thread",
        lambda *a, **k: {"bodies": ["following up"], "speakers": [config.self_name]},
    )
    monkeypatch.setattr(referral_mod, "send_message", lambda **kwargs: {"sent": False})
    result = referral_mod.send_referral_for_candidate(
        name="Sam", url="https://example.com", thread_text="following up", config=config, confirm=False
    )
    assert "long time no see" in result.draft


def test_send_referral_rate_limited_by_real_governor_on_repeat_url(config, monkeypatch):
    """End-to-end (real send_message + real Governor, only the CDP boundary
    mocked): sending a referral twice to the same thread URL must have the
    second call caught and reported as skipped, not raised past the caller."""
    import linkedin_mcp.messaging as messaging_mod

    monkeypatch.setattr(referral_mod, "open_thread", lambda *a, **k: None)
    monkeypatch.setattr(referral_mod, "read_thread", lambda *a, **k: {"bodies": ["hiring"], "speakers": []})
    monkeypatch.setattr(messaging_mod.time, "sleep", lambda s: None)

    def fake_evaluate(port, script, tab):
        if "insertText" in script:
            return True
        if "getAttribute('disabled')" in script:
            return True
        if ".click(); return !!b" in script:
            return True
        if "innerText : ''" in script:
            return "delivered " + config.referral.attachment_name
        if "innerText.trim().length" in script:
            return True
        return ""

    monkeypatch.setattr(messaging_mod, "evaluate", fake_evaluate)
    monkeypatch.setattr(messaging_mod, "set_file_input", lambda *a, **k: True)

    url = "https://example.com/thread/rate-limit-me"
    first = referral_mod.send_referral_for_candidate(
        name="Jordan", url=url, thread_text="hiring", config=config, confirm=True
    )
    assert first.skipped == ""
    assert first.proof["sent"] is True

    second = referral_mod.send_referral_for_candidate(
        name="Jordan", url=url, thread_text="hiring", config=config, confirm=True
    )
    assert second.skipped.startswith("rate-limited:")


def test_send_referral_propagates_send_not_confirmed(config, monkeypatch):
    monkeypatch.setattr(referral_mod, "open_thread", lambda *a, **k: None)
    monkeypatch.setattr(referral_mod, "read_thread", lambda *a, **k: {"bodies": ["hiring"], "speakers": []})

    def raise_confirm(**kwargs):
        raise SendNotConfirmedError("nope")

    monkeypatch.setattr(referral_mod, "send_message", raise_confirm)
    try:
        referral_mod.send_referral_for_candidate(
            name="Jordan", url="https://example.com", thread_text="hiring", config=config, confirm=False
        )
        assert False, "expected SendNotConfirmedError"
    except SendNotConfirmedError:
        pass

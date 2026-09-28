"""Sending without an explicit confirmation must be impossible. Tested at
every layer that could accidentally bypass it: the plain functions, the CLI
flags, flag ordering, and falsy-but-not-literally-False confirm values.
"""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

import linkedin_mcp.cli as cli_mod
import linkedin_mcp.core as core_mod
import linkedin_mcp.messaging as messaging_mod
import linkedin_mcp.post_cdp as post_mod
import linkedin_mcp.referral as referral_mod
from linkedin_mcp.messaging import SendNotConfirmedError, send_message

runner = CliRunner()


@pytest.fixture(autouse=True)
def _wire_config(config, monkeypatch):
    monkeypatch.setattr(core_mod, "load_agent_config", lambda path=None: config)
    monkeypatch.setattr(messaging_mod.time, "sleep", lambda s: None)
    monkeypatch.setattr(post_mod.time, "sleep", lambda s: None)
    return config


# ---------------------------------------------------- function-level guard --


@pytest.mark.parametrize("falsy_confirm", [False, 0, None, "", [], {}])
def test_send_message_refuses_every_falsy_confirm_value(config, monkeypatch, falsy_confirm):
    monkeypatch.setattr(messaging_mod, "evaluate", lambda *a, **k: True)
    with pytest.raises(SendNotConfirmedError):
        send_message("hello", config, confirm=falsy_confirm)


def test_send_message_never_calls_click_script_without_confirm(config, monkeypatch):
    calls = []

    def fake_evaluate(port, script, tab):
        calls.append(script)
        return True

    monkeypatch.setattr(messaging_mod, "evaluate", fake_evaluate)
    with pytest.raises(SendNotConfirmedError):
        send_message("hello", config, confirm=False)
    assert not any("msg-form__send-button" in c and ".click()" in c for c in calls)


def test_send_message_attachment_alone_does_not_send(config, monkeypatch):
    """Attaching a file without --confirm is "drafting with an attachment",
    not sending -- the send button must still never be clicked."""
    monkeypatch.setattr(messaging_mod, "evaluate", lambda *a, **k: True)
    monkeypatch.setattr(messaging_mod, "set_file_input", lambda *a, **k: True)
    with pytest.raises(SendNotConfirmedError):
        send_message("hello", config, confirm=False, attachment_path="/tmp/x.pdf")


def test_publish_post_refuses_without_confirm(config, monkeypatch):
    monkeypatch.setattr(post_mod, "navigate", lambda *a, **k: None)
    monkeypatch.setattr(post_mod, "evaluate", lambda *a, **k: True)
    with pytest.raises(SendNotConfirmedError):
        post_mod.publish_post("hello", config, confirm=False)


def test_publish_post_never_calls_post_click_script_without_confirm(config, monkeypatch):
    calls = []

    def fake_evaluate(port, script, tab):
        calls.append(script)
        return True

    monkeypatch.setattr(post_mod, "navigate", lambda *a, **k: None)
    monkeypatch.setattr(post_mod, "evaluate", fake_evaluate)
    with pytest.raises(SendNotConfirmedError):
        post_mod.publish_post("hello", config, confirm=False)
    assert not any("share-actions__primary-action" in c for c in calls)


def test_referral_propagates_unconfirmed_from_send_message(config, monkeypatch):
    monkeypatch.setattr(referral_mod, "open_thread", lambda *a, **k: None)
    monkeypatch.setattr(referral_mod, "read_thread", lambda *a, **k: {"bodies": ["hiring"], "speakers": []})
    monkeypatch.setattr(messaging_mod, "evaluate", lambda *a, **k: True)
    monkeypatch.setattr(messaging_mod, "set_file_input", lambda *a, **k: True)
    with pytest.raises(SendNotConfirmedError):
        referral_mod.send_referral_for_candidate(
            name="Jordan", url="https://example.com", thread_text="hiring", config=config, confirm=False
        )


def test_referral_confirm_true_reaches_send_message(config, monkeypatch):
    monkeypatch.setattr(referral_mod, "open_thread", lambda *a, **k: None)
    monkeypatch.setattr(referral_mod, "read_thread", lambda *a, **k: {"bodies": ["hiring"], "speakers": []})
    captured = {}

    def fake_send_message(**kwargs):
        captured["confirm"] = kwargs["confirm"]
        return {"sent": True}

    monkeypatch.setattr(referral_mod, "send_message", fake_send_message)
    referral_mod.send_referral_for_candidate(
        name="Jordan", url="https://example.com", thread_text="hiring", config=config, confirm=True
    )
    assert captured["confirm"] is True


# --------------------------------------------------------------- CLI guard --


def test_cli_message_send_default_is_unconfirmed(monkeypatch):
    captured = {}

    def fake_send(**kwargs):
        captured.update(kwargs)
        raise SendNotConfirmedError("nope")

    monkeypatch.setattr(messaging_mod, "send_message", fake_send)
    result = runner.invoke(cli_mod.app, ["messages", "send", "hello"])
    assert result.exit_code == 1
    assert captured["confirm"] is False


def test_cli_post_publish_default_is_unconfirmed(monkeypatch):
    captured = {}

    def fake_publish(**kwargs):
        captured.update(kwargs)
        raise SendNotConfirmedError("nope")

    monkeypatch.setattr(post_mod, "publish_post", fake_publish)
    result = runner.invoke(cli_mod.app, ["post-cdp", "publish", "hello"])
    assert result.exit_code == 1
    assert captured["confirm"] is False


def test_cli_send_referral_default_is_unconfirmed(monkeypatch):
    captured = {}

    def fake_referral(**kwargs):
        captured.update(kwargs)
        raise SendNotConfirmedError("nope")

    monkeypatch.setattr(referral_mod, "send_referral_for_candidate", fake_referral)
    result = runner.invoke(cli_mod.app, ["referral", "send", "Jordan", "https://example.com"])
    assert result.exit_code == 1
    assert captured["confirm"] is False


def test_cli_confirm_flag_before_positional_still_sends(monkeypatch):
    captured = {}

    def fake_send(**kwargs):
        captured.update(kwargs)
        return {"sent": True}

    monkeypatch.setattr(messaging_mod, "send_message", fake_send)
    result = runner.invoke(cli_mod.app, ["messages", "send", "--confirm", "hello"])
    assert result.exit_code == 0
    assert captured["confirm"] is True
    assert captured["text"] == "hello"


def test_cli_extra_positional_argument_is_rejected_not_silently_confirmed(monkeypatch):
    captured = {}

    def fake_send(**kwargs):
        captured.update(kwargs)
        return {"sent": True}

    monkeypatch.setattr(messaging_mod, "send_message", fake_send)
    result = runner.invoke(cli_mod.app, ["messages", "send", "hello", "--confirm", "unexpected-extra-arg"])
    assert result.exit_code != 0
    assert captured == {}  # send_message was never reached


def test_cli_unknown_confirm_casing_is_not_accepted_as_the_flag(monkeypatch):
    monkeypatch.setattr(messaging_mod, "send_message", lambda **kwargs: {"sent": True})
    result = runner.invoke(cli_mod.app, ["messages", "send", "hello", "--Confirm"])
    assert result.exit_code != 0  # unknown option, not a case-insensitive alias for --confirm


def test_cli_confirm_is_not_settable_via_environment(monkeypatch):
    """There is no LINKEDIN_AGENT_CONFIRM escape hatch -- confirm can only
    come from the explicit CLI flag on this exact invocation."""
    captured = {}

    def fake_send(**kwargs):
        captured.update(kwargs)
        raise SendNotConfirmedError("nope")

    monkeypatch.setattr(messaging_mod, "send_message", fake_send)
    monkeypatch.setenv("LINKEDIN_AGENT_CONFIRM", "true")
    result = runner.invoke(cli_mod.app, ["messages", "send", "hello"])
    assert result.exit_code == 1
    assert captured["confirm"] is False


def test_cli_message_send_text_literally_saying_confirm_does_not_send(monkeypatch):
    captured = {}

    def fake_send(**kwargs):
        captured.update(kwargs)
        raise SendNotConfirmedError("nope")

    monkeypatch.setattr(messaging_mod, "send_message", fake_send)
    result = runner.invoke(cli_mod.app, ["messages", "send", "please confirm and send this now"])
    assert result.exit_code == 1
    assert captured["confirm"] is False
    assert captured["text"] == "please confirm and send this now"


def test_cli_post_draft_never_touches_governor_or_browser(monkeypatch):
    """post-cdp draft is pure text linting; it must not import/require Chrome
    at all -- asserted by never calling publish_post."""
    called = {"publish": False}
    monkeypatch.setattr(post_mod, "publish_post", lambda **kwargs: called.__setitem__("publish", True))
    runner.invoke(cli_mod.app, ["post-cdp", "draft", "just a draft"])
    assert called["publish"] is False


def test_cli_draft_referral_never_touches_governor_or_browser(monkeypatch):
    called = {"send": False}
    monkeypatch.setattr(
        referral_mod, "send_referral_for_candidate", lambda **kwargs: called.__setitem__("send", True)
    )
    runner.invoke(cli_mod.app, ["referral", "draft", "Jordan", "hiring for a role"])
    assert called["send"] is False

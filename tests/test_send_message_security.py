"""Security fix (review A1): send_message must never touch the DOM file
input before confirm=True, and must refuse to attach anything outside an
explicit allowlist directory -- including a symlink that resolves outside
it. Before this fix, `attachment_path="~/.ssh/id_rsa", confirm=False`
staged the file for upload and left it staged for the next confirmed send.
"""

from __future__ import annotations

import pytest

from linkedin_mcp import messaging
from linkedin_mcp.agent_config import Config


@pytest.fixture
def allowed_dir(tmp_path):
    d = tmp_path / "attachments"
    d.mkdir()
    return d


@pytest.fixture
def config(allowed_dir) -> Config:
    return Config(cdp_port=9222, attachments_dir=str(allowed_dir))


def _no_real_calls(monkeypatch):
    def fake_evaluate(port, script, *a, **k):
        if "items.length - 1" in script:  # _last_message_text needs a string
            return "hi"
        return True

    monkeypatch.setattr(messaging, "evaluate", fake_evaluate)
    monkeypatch.setattr(messaging.time, "sleep", lambda s: None)


def test_unconfirmed_send_never_calls_set_file_input_even_with_an_attachment(config, allowed_dir, monkeypatch):
    _no_real_calls(monkeypatch)
    calls = []
    monkeypatch.setattr(messaging, "set_file_input", lambda *a, **k: calls.append(a) or True)
    good_file = allowed_dir / "resume.pdf"
    good_file.write_text("pdf")

    with pytest.raises(messaging.SendNotConfirmedError):
        messaging.send_message("hi", config, confirm=False, attachment_path=str(good_file))

    assert calls == []


def test_unconfirmed_send_reports_the_would_attach_path(config, allowed_dir, monkeypatch):
    _no_real_calls(monkeypatch)
    monkeypatch.setattr(messaging, "set_file_input", lambda *a, **k: True)
    good_file = allowed_dir / "resume.pdf"
    good_file.write_text("pdf")

    with pytest.raises(messaging.SendNotConfirmedError) as excinfo:
        messaging.send_message("hi", config, confirm=False, attachment_path=str(good_file))

    assert excinfo.value.preview["would_attach"] == str(good_file.resolve())
    assert excinfo.value.preview["sent"] is False


def test_attachment_outside_the_allowlist_is_rejected_even_unconfirmed(config, tmp_path, monkeypatch):
    _no_real_calls(monkeypatch)
    calls = []
    monkeypatch.setattr(messaging, "set_file_input", lambda *a, **k: calls.append(a) or True)
    outside = tmp_path / "ssh_key_lookalike"
    outside.write_text("secret")

    with pytest.raises(ValueError, match="outside the allowed attachments directory"):
        messaging.send_message("hi", config, confirm=False, attachment_path=str(outside))

    assert calls == []


def test_attachment_outside_the_allowlist_is_rejected_even_confirmed(config, tmp_path, monkeypatch):
    _no_real_calls(monkeypatch)
    calls = []
    monkeypatch.setattr(messaging, "set_file_input", lambda *a, **k: calls.append(a) or True)
    outside = tmp_path / "ssh_key_lookalike"
    outside.write_text("secret")

    with pytest.raises(ValueError, match="outside the allowed attachments directory"):
        messaging.send_message("hi", config, confirm=True, attachment_path=str(outside))

    assert calls == []


def test_symlink_escaping_the_allowlist_is_rejected(config, allowed_dir, tmp_path, monkeypatch):
    _no_real_calls(monkeypatch)
    monkeypatch.setattr(messaging, "set_file_input", lambda *a, **k: True)
    secret = tmp_path / "secret.txt"
    secret.write_text("nope")
    link = allowed_dir / "innocuous.pdf"
    link.symlink_to(secret)

    with pytest.raises(ValueError, match="outside the allowed attachments directory"):
        messaging.send_message("hi", config, confirm=True, attachment_path=str(link))


def test_confirmed_send_with_a_valid_attachment_attaches_it(config, allowed_dir, monkeypatch):
    _no_real_calls(monkeypatch)
    captured = {}
    def fake_set_file_input(port, selector, path, **k):
        captured["path"] = path
        return True

    monkeypatch.setattr(messaging, "set_file_input", fake_set_file_input)
    good_file = allowed_dir / "resume.pdf"
    good_file.write_text("pdf")

    proof = messaging.send_message("hi", config, confirm=True, attachment_path=str(good_file))

    assert captured["path"] == str(good_file.resolve())
    assert proof["attached"] is True


def test_missing_attachment_file_is_rejected(config, allowed_dir, monkeypatch):
    _no_real_calls(monkeypatch)
    with pytest.raises(ValueError, match="not found"):
        messaging.send_message("hi", config, confirm=False, attachment_path=str(allowed_dir / "nope.pdf"))


def test_default_allowlist_falls_back_to_referral_resume_dir(tmp_path, monkeypatch):
    _no_real_calls(monkeypatch)
    resume_dir = tmp_path / "resumes"
    resume_dir.mkdir()
    resume = resume_dir / "resume.pdf"
    resume.write_text("pdf")
    from linkedin_mcp.agent_config import ReferralConfig

    config = Config(cdp_port=9222, referral=ReferralConfig(resume_path=str(resume)))
    monkeypatch.setattr(messaging, "set_file_input", lambda *a, **k: True)

    proof = messaging.send_message("hi", config, confirm=True, attachment_path=str(resume))
    assert proof["attached"] is True

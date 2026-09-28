"""Security fix (review H3): post_cdp.publish_post's image_path skipped
_validate_attachment_path entirely -- no allowlist check, no symlink
resolution -- unlike messaging.send_message's attachment_path (fixed in
review A1). Applying the same check here too."""

from __future__ import annotations

import pytest

from linkedin_mcp import post_cdp


@pytest.fixture
def allowed_dir(tmp_path):
    d = tmp_path / "attachments"
    d.mkdir()
    return d


@pytest.fixture
def config(allowed_dir, tmp_path):
    return type(
        "C", (), {"cdp_port": 9222, "attachments_dir": str(allowed_dir), "governor_db_path": str(tmp_path / "g.db")}
    )()


def _no_real_calls(monkeypatch):
    monkeypatch.setattr(post_cdp, "navigate", lambda *a, **k: None)
    monkeypatch.setattr(post_cdp, "evaluate", lambda *a, **k: True)
    monkeypatch.setattr(post_cdp.time, "sleep", lambda s: None)


def test_image_outside_the_allowlist_is_rejected(config, tmp_path, monkeypatch):
    _no_real_calls(monkeypatch)
    calls = []
    monkeypatch.setattr(post_cdp, "set_file_input", lambda *a, **k: calls.append(a) or True)
    outside = tmp_path / "not_an_image.png"
    outside.write_text("x")

    with pytest.raises(ValueError, match="outside the allowed attachments directory"):
        post_cdp.publish_post("hello", config, confirm=True, image_path=str(outside))

    assert calls == []


def test_image_symlink_escaping_the_allowlist_is_rejected(config, allowed_dir, tmp_path, monkeypatch):
    _no_real_calls(monkeypatch)
    monkeypatch.setattr(post_cdp, "set_file_input", lambda *a, **k: True)
    secret = tmp_path / "secret.png"
    secret.write_text("nope")
    link = allowed_dir / "innocuous.png"
    link.symlink_to(secret)

    with pytest.raises(ValueError, match="outside the allowed attachments directory"):
        post_cdp.publish_post("hello", config, confirm=True, image_path=str(link))


def test_image_inside_the_allowlist_is_accepted(config, allowed_dir, monkeypatch):
    _no_real_calls(monkeypatch)
    captured = {}

    def fake_set_file_input(port, selector, path, **k):
        captured["path"] = path
        return True

    monkeypatch.setattr(post_cdp, "set_file_input", fake_set_file_input)
    good = allowed_dir / "pic.png"
    good.write_text("x")

    result = post_cdp.publish_post("hello", config, confirm=True, image_path=str(good))

    assert captured["path"] == str(good.resolve())
    assert result["attached_image"] is True

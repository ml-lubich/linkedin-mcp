from __future__ import annotations

import pytest

import linkedin_mcp.post_cdp as post_mod
from linkedin_mcp.messaging import SendNotConfirmedError


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(post_mod.time, "sleep", lambda s: None)


def test_lint_post_flags_banned_phrase():
    problems = post_mod.lint_post("Excited to announce our new leveraging platform!")
    assert "excited to announce" in problems
    assert "leveraging" in problems


def test_lint_post_flags_hashtag_spam():
    problems = post_mod.lint_post("shipped a thing #AI #Tech #Innovation")
    assert "too-many-hashtags" in problems


def test_lint_post_clean_text_has_no_problems():
    assert post_mod.lint_post("Shipped a small CDP client this week.") == []


def test_open_composer_success(config, monkeypatch):
    monkeypatch.setattr(post_mod, "navigate", lambda *a, **k: None)
    monkeypatch.setattr(post_mod, "evaluate", lambda *a, **k: True)
    post_mod.open_composer(config.cdp_port)  # should not raise


def test_open_composer_missing_button_raises(config, monkeypatch):
    monkeypatch.setattr(post_mod, "navigate", lambda *a, **k: None)
    monkeypatch.setattr(post_mod, "evaluate", lambda *a, **k: False)
    with pytest.raises(post_mod.ChromeError):
        post_mod.open_composer(config.cdp_port)


def test_publish_post_requires_confirm(config, monkeypatch):
    monkeypatch.setattr(post_mod, "navigate", lambda *a, **k: None)
    monkeypatch.setattr(post_mod, "evaluate", lambda *a, **k: True)
    with pytest.raises(SendNotConfirmedError):
        post_mod.publish_post("hello world", config, confirm=False)


def test_publish_post_editor_missing_raises(config, monkeypatch):
    monkeypatch.setattr(post_mod, "navigate", lambda *a, **k: None)
    calls = {"n": 0}

    def fake_evaluate(port, script, tab):
        calls["n"] += 1
        if calls["n"] == 1:  # start-post click
            return True
        return False  # editor fill fails

    monkeypatch.setattr(post_mod, "evaluate", fake_evaluate)
    with pytest.raises(post_mod.ChromeError, match="editor not found"):
        post_mod.publish_post("hello world", config, confirm=True)


def test_publish_post_success_with_image(config, monkeypatch):
    monkeypatch.setattr(post_mod, "navigate", lambda *a, **k: None)
    monkeypatch.setattr(post_mod, "evaluate", lambda *a, **k: True)
    monkeypatch.setattr(post_mod, "set_file_input", lambda *a, **k: True)
    result = post_mod.publish_post("hello world", config, confirm=True, image_path="/tmp/meme.png")
    assert result == {"clicked_post": True, "attached_image": True}


def test_publish_post_success_without_image(config, monkeypatch):
    monkeypatch.setattr(post_mod, "navigate", lambda *a, **k: None)
    monkeypatch.setattr(post_mod, "evaluate", lambda *a, **k: True)
    result = post_mod.publish_post("hello world", config, confirm=True)
    assert result == {"clicked_post": True, "attached_image": False}

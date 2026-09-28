"""New coverage closing mutmut gaps in linkedin_mcp/post_cdp.py, added as a
new file per the ownership split with linkedin-mcp-lead -- never editing the
existing tests/test_post_cdp.py."""

from __future__ import annotations

import json

import pytest

import linkedin_mcp.post_cdp as post_mod
from linkedin_mcp.governor import Governor
from linkedin_mcp.messaging import SendNotConfirmedError


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(post_mod.time, "sleep", lambda s: None)


# ---- lint_post: exact hashtag boundary -------------------------------------


def test_lint_post_exactly_two_hashtags_is_not_spam():
    assert post_mod.lint_post("shipped a thing #AI #Tech") == []


def test_lint_post_three_hashtags_is_spam():
    assert post_mod.lint_post("shipped a thing #AI #Tech #Go") == ["too-many-hashtags"]


# ---- open_composer: exact port/selector/error-message -----------------------


def test_open_composer_passes_the_exact_port_to_navigate_and_evaluate(config, monkeypatch):
    captured = {}

    def fake_navigate(port, url, **kw):
        captured["nav_port"] = port
        captured["nav_url"] = url
        captured["nav_kw"] = kw

    def fake_evaluate(port, script, **kw):
        captured["eval_port"] = port
        captured["eval_script"] = script
        return True

    monkeypatch.setattr(post_mod, "navigate", fake_navigate)
    monkeypatch.setattr(post_mod, "evaluate", fake_evaluate)
    post_mod.open_composer(9222)
    assert captured["nav_port"] == 9222
    assert captured["nav_url"] == post_mod.FEED_URL
    assert captured["nav_kw"] == {"host": post_mod.TAB}
    assert captured["eval_port"] == 9222
    assert json.dumps(post_mod.START_POST_SELECTOR) in captured["eval_script"]


def test_open_composer_missing_button_raises_the_exact_message(config, monkeypatch):
    monkeypatch.setattr(post_mod, "navigate", lambda *a, **k: None)
    monkeypatch.setattr(post_mod, "evaluate", lambda *a, **k: False)
    with pytest.raises(post_mod.ChromeError) as excinfo:
        post_mod.open_composer(9222)
    assert str(excinfo.value) == "could not find the 'Start a post' button"


# ---- publish_post: port ternary, exact messages, governor wiring ----------


def test_publish_post_uses_explicit_port_over_config_cdp_port(config, monkeypatch):
    ports_seen = []

    def fake_navigate(port, url, **kw):
        ports_seen.append(port)

    def fake_evaluate(port, script, **kw):
        ports_seen.append(port)
        return True

    monkeypatch.setattr(post_mod, "navigate", fake_navigate)
    monkeypatch.setattr(post_mod, "evaluate", fake_evaluate)
    post_mod.publish_post("hello", config, confirm=True, port=5555)
    assert ports_seen and all(p == 5555 for p in ports_seen)
    assert config.cdp_port != 5555


def test_publish_post_fill_script_uses_the_exact_editor_selector(config, monkeypatch):
    monkeypatch.setattr(post_mod, "navigate", lambda *a, **k: None)
    scripts = []

    def fake_evaluate(port, script, **kw):
        scripts.append(script)
        return True

    monkeypatch.setattr(post_mod, "evaluate", fake_evaluate)
    post_mod.publish_post("hello world", config, confirm=True)
    fill_script = next(s for s in scripts if json.dumps("hello world") in s)
    assert json.dumps(post_mod.EDITOR_SELECTOR) in fill_script


def test_publish_post_not_confirmed_has_the_exact_message(config, monkeypatch):
    monkeypatch.setattr(post_mod, "navigate", lambda *a, **k: None)
    monkeypatch.setattr(post_mod, "evaluate", lambda *a, **k: True)
    with pytest.raises(SendNotConfirmedError) as excinfo:
        post_mod.publish_post("hello", config, confirm=False)
    assert str(excinfo.value) == "publish_post requires confirm=True; nothing was posted"


def test_publish_post_attaches_the_image_with_the_host_kwarg(config, monkeypatch):
    monkeypatch.setattr(post_mod, "navigate", lambda *a, **k: None)
    monkeypatch.setattr(post_mod, "evaluate", lambda *a, **k: True)
    captured = {}

    def fake_set_file_input(port, selector, path, **kw):
        captured["kw"] = kw
        return True

    monkeypatch.setattr(post_mod, "set_file_input", fake_set_file_input)
    post_mod.publish_post("hello", config, confirm=True, image_path=config.referral.resume_path)
    assert captured["kw"] == {"host": post_mod.TAB}


def test_publish_post_dedupes_identical_text_via_its_own_governor(config, monkeypatch):
    """No governor passed in -- publish_post opens and closes its own, keyed
    on config.governor_db_path, and the SAME text hashes to the SAME target,
    so a second publish of identical text must be refused."""
    monkeypatch.setattr(post_mod, "navigate", lambda *a, **k: None)
    monkeypatch.setattr(post_mod, "evaluate", lambda *a, **k: True)

    result = post_mod.publish_post("identical text", config, confirm=True)
    assert result["clicked_post"] is True

    from linkedin_mcp.governor import RateLimited

    with pytest.raises(RateLimited):
        post_mod.publish_post("identical text", config, confirm=True)


def test_publish_post_with_an_external_governor_is_not_closed_by_publish_post(config, monkeypatch, tmp_path):
    monkeypatch.setattr(post_mod, "navigate", lambda *a, **k: None)
    monkeypatch.setattr(post_mod, "evaluate", lambda *a, **k: True)
    gov = Governor(tmp_path / "shared.db", now=1_000_000.0)
    post_mod.publish_post("hello", config, confirm=True, governor=gov)
    gov.budget("post")  # must not raise -- the connection is still open
    gov.close()


def test_publish_post_records_under_the_action_name_post_not_something_else(config, monkeypatch, tmp_path):
    monkeypatch.setattr(post_mod, "navigate", lambda *a, **k: None)
    monkeypatch.setattr(post_mod, "evaluate", lambda *a, **k: True)
    gov = Governor(tmp_path / "shared.db", now=1_000_000.0)
    post_mod.publish_post("some text", config, confirm=True, governor=gov)
    assert gov.budget("post").used == 1
    assert gov.budget("react").used == 0  # never recorded under an unrelated action
    gov.close()


def test_publish_post_does_not_record_when_the_post_button_click_fails(config, monkeypatch, tmp_path):
    monkeypatch.setattr(post_mod, "navigate", lambda *a, **k: None)
    calls = {"n": 0}

    def fake_evaluate(port, script, **kw):
        calls["n"] += 1
        if calls["n"] <= 2:  # start-post click, then the fill script
            return True
        return False  # the final post-button click fails

    monkeypatch.setattr(post_mod, "evaluate", fake_evaluate)
    gov = Governor(tmp_path / "shared.db", now=1_000_000.0)
    result = post_mod.publish_post("hello", config, confirm=True, governor=gov)
    assert result["clicked_post"] is False
    assert gov.budget("post").used == 0
    gov.close()

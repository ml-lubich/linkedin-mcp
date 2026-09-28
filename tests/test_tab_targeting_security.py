"""Security fix (review A2): every CDP call that targets "the LinkedIn tab"
must use own_chrome.cdp's real hostname check (`host=`), never a substring
match (`url_contains="linkedin.com"`) -- a substring match also matches
https://evil.tld/linkedin.com/x or https://linkedin.com.evil.tld/. And any
caller-supplied destination URL (open_thread/messages_read(url=...)) must be
validated as https://(*.)linkedin.com before navigating there at all --
blocks javascript:, file:, and lookalike hosts.
"""

from __future__ import annotations

import pytest

from linkedin_mcp import messaging, post_cdp, scan as scan_mod
from linkedin_mcp.agent_config import Config


def test_open_thread_uses_host_not_substring_for_navigate(monkeypatch):
    captured = {}
    monkeypatch.setattr(messaging, "navigate", lambda port, url, **kw: captured.update(kw))
    messaging.open_thread("https://www.linkedin.com/messaging/thread/abc/", 9222)
    assert captured.get("host") == messaging.TAB
    assert "url_contains" not in captured


@pytest.mark.parametrize(
    "evil_url",
    [
        "https://evil.tld/linkedin.com/x",
        "https://linkedin.com.evil.tld/phish",
        "javascript:alert(1)",
        "file:///etc/passwd",
        "http://www.linkedin.com/messaging/",  # not https
    ],
)
def test_open_thread_rejects_non_linkedin_urls(evil_url, monkeypatch):
    monkeypatch.setattr(messaging, "navigate", lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not navigate")))
    with pytest.raises(ValueError, match="linkedin.com"):
        messaging.open_thread(evil_url, 9222)


def test_open_thread_accepts_a_real_linkedin_subdomain(monkeypatch):
    calls = []
    monkeypatch.setattr(messaging, "navigate", lambda port, url, **kw: calls.append(url))
    messaging.open_thread("https://www.linkedin.com/messaging/thread/abc/", 9222)
    assert calls == ["https://www.linkedin.com/messaging/thread/abc/"]


def test_post_cdp_open_composer_uses_host_not_substring(monkeypatch):
    captured = {}
    monkeypatch.setattr(post_cdp, "navigate", lambda port, url, **kw: captured.update(kw))
    monkeypatch.setattr(post_cdp, "evaluate", lambda *a, **k: True)
    post_cdp.open_composer(9222)
    assert captured.get("host") == post_cdp.TAB
    assert "url_contains" not in captured


def test_publish_post_fill_and_click_use_host_not_substring(monkeypatch, config):
    captured = []
    monkeypatch.setattr(post_cdp, "navigate", lambda *a, **k: None)
    monkeypatch.setattr(post_cdp, "evaluate", lambda port, script, **kw: captured.append(kw) or True)
    post_cdp.publish_post("hello", config, confirm=True)
    assert all(kw.get("host") == post_cdp.TAB and "url_contains" not in kw for kw in captured)


def test_publish_post_never_attaches_image_before_confirm(monkeypatch, config, tmp_path):
    calls = []
    image = tmp_path / "pic.png"
    image.write_text("x")
    monkeypatch.setattr(post_cdp, "navigate", lambda *a, **k: None)
    monkeypatch.setattr(post_cdp, "evaluate", lambda *a, **k: True)
    monkeypatch.setattr(post_cdp, "set_file_input", lambda *a, **k: calls.append(a) or True)

    with pytest.raises(messaging.SendNotConfirmedError):
        post_cdp.publish_post("hello", config, confirm=False, image_path=str(image))

    assert calls == []


def test_scan_scroll_uses_host_not_substring(monkeypatch):
    captured = {}
    monkeypatch.setattr(scan_mod, "evaluate", lambda port, script, **kw: captured.update(kw))
    scan_mod._load_full_thread_list(9222, rounds=1, sleep_seconds=0)
    assert captured.get("host") == scan_mod.TAB
    assert "url_contains" not in captured

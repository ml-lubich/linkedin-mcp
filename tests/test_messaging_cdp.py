"""New CDP-driving messaging capabilities absorbed from own-chrome's `li`
(tag pre-li-move): opening messaging, listing/filtering threads, selecting a
thread by name, dialog popups, and the OpenAI-backed classify/draft
workflow's api_key/complete boundary calls.

`messaging.open_thread` / `read_thread` / `send_message` (the existing,
already-tested implementation used by referral.py) are unchanged -- this
file only covers the genuinely new functions.
"""

from __future__ import annotations

import json
import subprocess

import pytest

from linkedin_mcp import messaging
from linkedin_mcp.cdp_session import ChromeError

_MESSAGING_TAB = {
    "id": "msg",
    "url": "https://www.linkedin.com/messaging/",
    "title": "Messaging",
    "webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/page/msg",
}
_FEED_TAB = {
    "id": "feed",
    "url": "https://www.linkedin.com/feed/",
    "title": "Feed | LinkedIn",
    "webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/page/feed",
}


@pytest.fixture(autouse=True)
def _default_messaging_tab(monkeypatch):
    """Most tests below only care about evaluate()'s return value, not tab
    selection -- default to a single open messaging tab; tests exercising
    choose_linkedin_tab/ensure_messaging override this explicitly."""
    monkeypatch.setattr(messaging, "pages", lambda port: [_MESSAGING_TAB])


# ---- linkedin_tab / ensure_messaging --------------------------------------


def test_linkedin_tab_prefers_messaging_over_an_earlier_feed_tab(monkeypatch):
    monkeypatch.setattr(messaging, "pages", lambda port: [_FEED_TAB, _MESSAGING_TAB])
    assert messaging.linkedin_tab(9222)["id"] == "msg"


def test_linkedin_tab_raises_when_linkedin_is_closed(monkeypatch):
    monkeypatch.setattr(messaging, "pages", lambda port: [{"id": "g", "url": "https://google.com"}])
    with pytest.raises(ChromeError):
        messaging.linkedin_tab(9222)


def test_ensure_messaging_opens_a_tab_when_linkedin_is_missing(monkeypatch):
    opened = []
    monkeypatch.setattr(messaging, "pages", lambda port: [])

    def fake_open(port, url):
        opened.append(url)
        return {"id": "new", "url": url, "title": ""}

    monkeypatch.setattr(messaging, "open_tab", fake_open)
    monkeypatch.setattr(messaging, "evaluate", lambda port, expr, **kw: json.dumps({"ready": True, "url": messaging.MESSAGING, "title": "Messaging"}))
    info = messaging.ensure_messaging(9222)
    assert opened == [messaging.MESSAGING]
    assert info["opened"] == "tab"
    assert info["ready"] is True


def test_ensure_messaging_stays_when_already_on_messaging(monkeypatch):
    monkeypatch.setattr(messaging, "pages", lambda port: [_MESSAGING_TAB])
    monkeypatch.setattr(messaging, "navigate", lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not navigate")))
    info = messaging.ensure_messaging(9222)
    assert info["opened"] == "already"


def test_ensure_messaging_navigates_off_a_feed_tab(monkeypatch):
    calls = []
    monkeypatch.setattr(messaging, "pages", lambda port: [_FEED_TAB])
    monkeypatch.setattr(messaging, "navigate", lambda port, url, **kw: calls.append(url))
    monkeypatch.setattr(
        messaging,
        "evaluate_pinned",
        lambda ws_url, expr: json.dumps({"ready": True, "url": messaging.MESSAGING, "title": "Messaging"}),
    )
    info = messaging.ensure_messaging(9222)
    assert calls == [messaging.MESSAGING]
    assert info["opened"] == "navigated"


# ---- list_threads -----------------------------------------------------------


def test_list_threads_prefers_the_messaging_tab_when_a_feed_tab_is_listed_first(monkeypatch):
    monkeypatch.setattr(messaging, "pages", lambda port: [_FEED_TAB, _MESSAGING_TAB])
    monkeypatch.setattr(messaging, "navigate", lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not navigate")))
    monkeypatch.setattr(
        messaging,
        "evaluate_pinned",
        lambda ws_url, expr: json.dumps(
            {"query": "threads", "url": _MESSAGING_TAB["url"], "title": "Messaging", "threads": [{"name": "Ada", "preview": "hi", "unread": False}], "lines": []}
        ),
    )
    result = messaging.list_threads(9222, kind="threads")
    assert result["threads"][0]["name"] == "Ada"


def test_list_threads_unread_only(monkeypatch):
    monkeypatch.setattr(messaging, "pages", lambda port: [_MESSAGING_TAB])
    monkeypatch.setattr(
        messaging,
        "evaluate_pinned",
        lambda ws_url, expr: json.dumps({"query": "unread", "url": "u", "title": "t", "threads": [], "lines": []}),
    )
    result = messaging.list_threads(9222, kind="unread", limit=5)
    assert result["threads"] == []


def test_list_threads_no_navigate_skips_navigation(monkeypatch):
    calls = []
    monkeypatch.setattr(messaging, "pages", lambda port: [_FEED_TAB])
    monkeypatch.setattr(messaging, "navigate", lambda port, url, **kw: calls.append(url))
    monkeypatch.setattr(
        messaging,
        "evaluate_pinned",
        lambda ws_url, expr: json.dumps({"query": "threads", "url": "u", "title": "t", "threads": [], "lines": []}),
    )
    messaging.list_threads(9222, kind="threads", no_navigate=True)
    assert calls == []


# ---- select_thread ------------------------------------------------------------


def test_select_thread_ambiguous(monkeypatch):
    monkeypatch.setattr(messaging, "pages", lambda port: [_MESSAGING_TAB])
    click_calls = []

    def fake_evaluate(ws_url, expr):
        if '"query": "threads"' in expr:
            return json.dumps(
                {
                    "threads": [
                        {"name": "Ada Lovelace", "href": "/messaging/thread/1/", "preview": "", "unread": False},
                        {"name": "Ada Wong", "href": "/messaging/thread/2/", "preview": "", "unread": False},
                    ]
                }
            )
        click_calls.append(expr)
        raise AssertionError("must not click when ambiguous")

    monkeypatch.setattr(messaging, "evaluate_pinned", fake_evaluate)
    result = messaging.select_thread(9222, "Ada")
    assert result["ambiguous"] is True
    assert set(result["matches"]) == {"Ada Lovelace", "Ada Wong"}
    assert click_calls == []


def test_select_thread_no_match(monkeypatch):
    monkeypatch.setattr(messaging, "pages", lambda port: [_MESSAGING_TAB])
    monkeypatch.setattr(
        messaging,
        "evaluate_pinned",
        lambda ws_url, expr: json.dumps({"threads": [{"name": "Someone Else", "href": "/messaging/thread/9/"}]}),
    )
    result = messaging.select_thread(9222, "Nobody")
    assert result["ok"] is False
    assert result["ambiguous"] is False


def test_select_thread_exact_match_clicks_by_href(monkeypatch):
    monkeypatch.setattr(messaging, "pages", lambda port: [_MESSAGING_TAB])
    captured = {}

    def fake_evaluate(ws_url, expr):
        if '"query": "threads"' in expr:
            return json.dumps(
                {
                    "threads": [
                        {"name": "Ada Lovelace", "href": "/messaging/thread/1/", "preview": "", "unread": False},
                        {"name": "Ada Wong", "href": "/messaging/thread/2/", "preview": "", "unread": False},
                    ]
                }
            )
        captured["expr"] = expr
        return json.dumps({"action": "select", "ok": True, "matched": "Ada Lovelace"})

    monkeypatch.setattr(messaging, "evaluate_pinned", fake_evaluate)
    result = messaging.select_thread(9222, "Ada Lovelace")
    assert result["ok"] is True
    assert '"href": "/messaging/thread/1/"' in captured["expr"]


def test_select_thread_blank_name_raises_value_error():
    with pytest.raises(ValueError, match="name is required"):
        messaging.select_thread(9222, "   ")


# ---- popups -------------------------------------------------------------------


def test_popups_reports_decline_action_without_apply(monkeypatch):
    monkeypatch.setattr(
        messaging,
        "evaluate_pinned",
        lambda ws_url, expr: json.dumps({"title": "Share your contact info?", "buttons": ["No, don't share", "Yes, please share"]}),
    )
    result = messaging.popups(9222, apply=False, policy={"share_contact": "decline"})
    assert result["action"] == "No, don't share"
    assert result["applied"] is False


def test_popups_apply_clicks_the_button(monkeypatch):
    calls = []

    def fake_evaluate(ws_url, expr):
        calls.append(expr)
        if len(calls) == 1:
            return json.dumps({"title": "Share your contact info?", "buttons": ["No, don't share"]})
        return True

    monkeypatch.setattr(messaging, "evaluate_pinned", fake_evaluate)
    result = messaging.popups(9222, apply=True, policy={"share_contact": "decline"})
    assert result["applied"] is True
    assert len(calls) == 2


# ---- api_key / complete (OpenAI + keychain boundary) -------------------------


def test_api_key_prefers_env(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-env-value")
    assert messaging.api_key() == "sk-env-value"


def test_api_key_falls_back_to_keychain(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(messaging.subprocess, "check_output", lambda *a, **k: "sk-keychain-value\n")
    assert messaging.api_key() == "sk-keychain-value"


def test_api_key_missing_everywhere_raises(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    def raise_error(*a, **k):
        raise subprocess.CalledProcessError(1, "security")

    monkeypatch.setattr(messaging.subprocess, "check_output", raise_error)
    with pytest.raises(ChromeError, match="OpenAI key is not in the environment or keychain"):
        messaging.api_key()


class _FakeResponse:
    def __init__(self, payload: bytes):
        self._payload = payload

    def read(self):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_complete_returns_message_content(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr(
        messaging.urllib.request,
        "urlopen",
        lambda request, timeout=30: _FakeResponse(json.dumps({"choices": [{"message": {"content": "hello"}}]}).encode()),
    )
    assert messaging.complete("gpt-5-nano", [{"role": "user", "content": "hi"}]) == "hello"


def test_complete_http_error_raises_chrome_error(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    def raise_error(request, timeout=30):
        raise messaging.urllib.error.HTTPError(request.full_url, 429, "rate limited", {}, None)

    monkeypatch.setattr(messaging.urllib.request, "urlopen", raise_error)
    with pytest.raises(ChromeError, match="OpenAI 429"):
        messaging.complete("gpt-5-nano", [])


def test_list_threads_filters_unread_before_applying_limit(monkeypatch):
    """Correctness fix (review B3): if the first N rendered threads are
    mostly read, --unread --limit N must not silently return fewer than N
    unread threads when more exist further down the page."""
    monkeypatch.setattr(messaging, "pages", lambda port: [_MESSAGING_TAB])
    # 5 read threads followed by 3 unread ones -- an old "cap while
    # collecting, then filter" implementation would return 0 unread threads
    # for limit=3 (all 3 slots consumed by the read ones first).
    threads = [{"name": f"Read {i}", "href": f"/t/{i}/", "unread": False} for i in range(5)]
    threads += [{"name": f"Unread {i}", "href": f"/t/u{i}/", "unread": True} for i in range(3)]
    monkeypatch.setattr(messaging, "evaluate_pinned", lambda ws_url, expr: {"threads": threads})

    result = messaging.list_threads(9222, kind="unread", limit=3, no_navigate=True)

    assert len(result["threads"]) == 3
    assert all(t["unread"] for t in result["threads"])


def test_list_threads_applies_limit_after_unread_filter_not_before(monkeypatch):
    monkeypatch.setattr(messaging, "pages", lambda port: [_MESSAGING_TAB])
    threads = [{"name": f"Unread {i}", "href": f"/t/{i}/", "unread": True} for i in range(5)]
    monkeypatch.setattr(messaging, "evaluate_pinned", lambda ws_url, expr: {"threads": threads})

    result = messaging.list_threads(9222, kind="unread", limit=2, no_navigate=True)

    assert len(result["threads"]) == 2

"""Security fix (review H1, then F2): select_thread/list_threads resolved
the tab via choose_linkedin_tab (prefers an open messaging tab over an
earlier feed tab), but _fill_compose/_send_button_enabled/_click_send/
_last_message_text/_compose_is_empty/set_file_input all re-resolved by
url_contains/host on every call, via own_chrome.cdp's plain substring/
hostname match against a fresh pages() list each time.

F2 replaces that with true pinning: linkedin_tab() is called ONCE per
operation, and every remaining step routes through that exact CDP target's
webSocketDebuggerUrl (evaluate_pinned/set_file_input_pinned), never through
another pages()/pick_page lookup. This fixes two problems the old
url_contains substring collision check had:

1. Usability regression: a normal two-tab setup -- one tab on
   https://www.linkedin.com/messaging/, another on
   .../messaging/thread/X/ -- tripped the collision check, since the first
   tab's URL is a literal prefix (hence substring) of the second's, and
   refused every send/select.
2. Security gap: because every step re-resolved by URL, a tab that opens or
   navigates to e.g. https://evil.tld/#<target_url> mid-operation (during
   the attach/verify sleeps) could be picked up by a LATER re-resolution
   instead of the tab actually chosen at the start. Pinning by CDP target
   makes that structurally impossible: pages() is consulted once, and never
   again for the rest of the operation.

Also (F2): right before clicking Send, the pinned target's current URL host
is re-checked -- if the tab navigated off linkedin.com in the meantime,
send_message aborts without clicking anything.
"""

from __future__ import annotations

import pytest

from linkedin_mcp import messaging
from linkedin_mcp.cdp_session import ChromeError

_MESSAGING_TAB = {
    "id": "msg",
    "url": "https://www.linkedin.com/messaging/",
    "title": "Messaging",
    "webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/page/msg",
}
_THREAD_TAB = {
    "id": "thread",
    "url": "https://www.linkedin.com/messaging/thread/X/",
    "title": "Ada",
    "webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/page/thread",
}


def _config():
    return type("C", (), {"cdp_port": 9222, "attachments_dir": ""})()


def test_select_and_send_hit_the_same_pinned_tab_with_two_messaging_tabs_open(monkeypatch):
    """The exact usability regression F2 fixes: a messaging/ tab plus a
    messaging/thread/X/ tab used to trip the old substring collision check
    and refuse everything. Pinning resolves the tab once (the first
    messaging-matching one -- see choose_linkedin_tab) and every step must
    hit that same tab's CDP target, never the other one."""
    monkeypatch.setattr(messaging, "pages", lambda port: [_MESSAGING_TAB, _THREAD_TAB])
    monkeypatch.setattr(messaging.time, "sleep", lambda s: None)
    ws_urls_seen: list[str] = []

    def fake_evaluate_pinned(ws_url, script):
        ws_urls_seen.append(ws_url)
        if '"query": "threads"' in script:
            return {"threads": [{"name": "Ada", "href": "/messaging/thread/1/", "preview": "", "unread": False}]}
        if "matches.length" in script:  # the select-click ACT_JS expression
            return {"action": "select", "ok": True, "matched": "Ada", "ambiguous": False, "matches": ["Ada"]}
        if "location.href" in script:
            return _MESSAGING_TAB["url"]
        if "items.length - 1" in script:
            return "hi"
        return True

    monkeypatch.setattr(messaging, "evaluate_pinned", fake_evaluate_pinned)
    monkeypatch.setattr(messaging, "navigate", lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not navigate")))

    selection = messaging.select_thread(9222, "Ada")
    assert selection["ok"] is True

    result = messaging.send_message("hi", _config(), confirm=True, verify_attempts=1, verify_wait_seconds=0)

    assert result["sent"] is True
    assert ws_urls_seen, "no evaluate_pinned calls recorded"
    assert all(v == _MESSAGING_TAB["webSocketDebuggerUrl"] for v in ws_urls_seen), ws_urls_seen


def test_a_tab_appearing_mid_operation_with_the_target_embedded_is_never_consulted(monkeypatch):
    """own_chrome.cdp's url_contains/host re-resolve from a fresh pages()
    list on every call -- so a tab opened/navigated to
    https://evil.tld/#<target_url> mid-operation could be picked up by a
    later re-resolution. With pinning, pages() is consulted exactly once
    (inside linkedin_tab, at the very start); an evil tab appearing on any
    later pages() call must never be reachable at all."""
    pages_calls = {"n": 0}

    def fake_pages(port):
        pages_calls["n"] += 1
        if pages_calls["n"] > 1:
            evil_tab = {
                "id": "evil",
                "url": f"https://evil.tld/#{_MESSAGING_TAB['url']}",
                "webSocketDebuggerUrl": "ws://evil",
            }
            return [evil_tab, _MESSAGING_TAB]
        return [_MESSAGING_TAB]

    monkeypatch.setattr(messaging, "pages", fake_pages)
    monkeypatch.setattr(messaging.time, "sleep", lambda s: None)
    ws_urls_seen: list[str] = []

    def fake_evaluate_pinned(ws_url, script):
        ws_urls_seen.append(ws_url)
        if "location.href" in script:
            return _MESSAGING_TAB["url"]
        if "items.length - 1" in script:
            return "hi"
        return True

    monkeypatch.setattr(messaging, "evaluate_pinned", fake_evaluate_pinned)

    result = messaging.send_message("hi", _config(), confirm=True, verify_attempts=1, verify_wait_seconds=0)

    assert result["sent"] is True
    assert pages_calls["n"] == 1, "pages() must be resolved exactly once per operation, never re-consulted"
    assert "ws://evil" not in ws_urls_seen


def test_pinned_tab_navigating_off_host_before_click_aborts_without_clicking(monkeypatch):
    monkeypatch.setattr(messaging, "pages", lambda port: [_MESSAGING_TAB])
    monkeypatch.setattr(messaging.time, "sleep", lambda s: None)
    clicked = []

    def fake_evaluate_pinned(ws_url, script):
        if "location.href" in script:
            return "https://evil.tld/hijacked"
        if ".click(); return !!b" in script:
            clicked.append(True)
            return True
        return True  # compose fill succeeds

    monkeypatch.setattr(messaging, "evaluate_pinned", fake_evaluate_pinned)

    with pytest.raises(ChromeError, match="linkedin.com"):
        messaging.send_message("hi", _config(), confirm=True, verify_attempts=1, verify_wait_seconds=0)

    assert clicked == [], "the send button must never be clicked once the pinned tab left linkedin.com"


def test_linkedin_tab_raises_when_no_linkedin_tab_is_open(monkeypatch):
    """F3: linkedin_tab's 'no tab at all' branch, previously untested."""
    monkeypatch.setattr(
        messaging, "pages", lambda port: [{"id": "x", "url": "https://example.com/", "webSocketDebuggerUrl": "ws://x"}]
    )
    with pytest.raises(ChromeError, match="No open tab"):
        messaging.linkedin_tab(9222)

"""Security fix (review H1): select_thread/list_threads resolved the tab
via choose_linkedin_tab (prefers an open messaging tab over an earlier feed
tab), but _fill_compose/_send_button_enabled/_click_send/_last_message_text/
_compose_is_empty/set_file_input all used host=TAB, which own_chrome.cdp
resolves to whichever linkedin.com tab pages() lists FIRST -- not
necessarily the messaging tab. With a feed tab first and messaging tab
second, `messages_send(to="Ada", confirm=True)` selected Ada in the
messaging tab, then typed/sent into the feed tab instead.

Also: a tab whose URL embeds the real target URL as a substring (e.g.
https://evil.tld/#https://www.linkedin.com/messaging/) could be selected by
the old url_contains=tab["url"] re-resolution trick, since own_chrome.cdp's
url_contains is a plain substring match with no hostname check.
"""

from __future__ import annotations

import pytest

from linkedin_mcp import messaging
from linkedin_mcp.cdp_session import ChromeError

_FEED_TAB = {"id": "feed", "url": "https://www.linkedin.com/feed/", "title": "Feed | LinkedIn"}
_MESSAGING_TAB = {"id": "msg", "url": "https://www.linkedin.com/messaging/", "title": "Messaging"}


def test_select_and_send_target_the_same_tab_when_feed_is_listed_first(monkeypatch):
    monkeypatch.setattr(messaging, "pages", lambda port: [_FEED_TAB, _MESSAGING_TAB])
    monkeypatch.setattr(messaging.time, "sleep", lambda s: None)
    url_contains_seen = []

    def fake_evaluate(port, script, **kw):
        url_contains_seen.append(kw.get("url_contains") or kw.get("host"))
        if '"query": "threads"' in script:
            return {"threads": [{"name": "Ada", "href": "/messaging/thread/1/", "preview": "", "unread": False}]}
        if "matches.length" in script:  # the select-click ACT_JS expression
            return {"action": "select", "ok": True, "matched": "Ada", "ambiguous": False, "matches": ["Ada"]}
        if "items.length - 1" in script:
            return "hi"
        return True

    monkeypatch.setattr(messaging, "evaluate", fake_evaluate)
    monkeypatch.setattr(messaging, "navigate", lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not navigate")))

    selection = messaging.select_thread(9222, "Ada")
    assert selection["ok"] is True

    config = type("C", (), {"cdp_port": 9222, "attachments_dir": ""})()
    messaging.send_message("hi", config, confirm=True, verify_attempts=1, verify_wait_seconds=0)

    # Every call -- the listing+click during select, and the fill/verify
    # during send -- must have targeted the SAME tab (the messaging one),
    # never the feed tab that own_chrome.cdp's host= would pick first.
    assert url_contains_seen, "no evaluate calls recorded"
    assert all(v == _MESSAGING_TAB["url"] for v in url_contains_seen), url_contains_seen


def test_a_tab_whose_url_embeds_the_target_as_a_substring_is_refused(monkeypatch):
    """An attacker tab (e.g. https://evil.tld/#https://www.linkedin.com/messaging/)
    could satisfy a naive `url_contains=<real tab's url>` re-resolution.
    Detected as a collision and refused, rather than silently risking a
    match against the wrong (attacker) tab."""
    evil_tab = {
        "id": "evil",
        "url": f"https://evil.tld/#{_MESSAGING_TAB['url']}",
        "title": "evil",
    }
    monkeypatch.setattr(messaging, "pages", lambda port: [evil_tab, _MESSAGING_TAB])

    with pytest.raises(ChromeError, match="refus"):
        messaging.linkedin_tab(9222)

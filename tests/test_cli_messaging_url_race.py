"""Opening messaging must not require Chrome's tab list to already contain
https://www.linkedin.com/messaging/.

Page.navigate returns before /json/list updates, so pick_page(url_contains=
that exact URL) raises ChromeError: No open tab URL contains
'https://www.linkedin.com/messaging/'. Every CLI command that opens
messaging has to ride out that lag by polling the tab that was actually
navigated.
"""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

import linkedin_mcp.scan as scan_mod
from linkedin_mcp import messaging
from linkedin_mcp.cdp_session import ChromeError
from linkedin_mcp.cli import app

runner = CliRunner()

_FEED_TAB = {
    "id": "feed",
    "url": "https://www.linkedin.com/feed/",
    "title": "Feed | LinkedIn",
    "webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/page/feed",
}

_URL_MISS = f"No open tab URL contains {messaging.MESSAGING!r}"


def _install_stale_tab_list(monkeypatch) -> None:
    """Feed tab stays listed at its old URL. A lookup for the messaging URL
    raises the same ChromeError own_chrome.cdp.pick_page raises. The page
    itself (pinned websocket) is already on messaging."""
    monkeypatch.setattr(messaging, "pages", lambda port: [_FEED_TAB])
    monkeypatch.setattr(messaging, "navigate", lambda *a, **k: None)
    monkeypatch.setattr(messaging.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(scan_mod.time, "sleep", lambda _seconds: None)

    def evaluate(port, expr, url_contains="", host="", **kw):
        needle = url_contains or kw.get("url_contains") or ""
        if needle == messaging.MESSAGING or messaging.MESSAGING in needle:
            raise ChromeError(_URL_MISS)
        if "bodies" in expr:
            return json.dumps({"url": messaging.MESSAGING, "bodies": ["hi"], "speakers": []})
        return True

    monkeypatch.setattr(messaging, "evaluate", evaluate)
    monkeypatch.setattr(scan_mod, "evaluate", lambda *a, **k: True)

    def pinned(ws_url, expr):
        assert ws_url == _FEED_TAB["webSocketDebuggerUrl"]
        if "ready:" in expr:
            return {"ready": True, "url": messaging.MESSAGING, "title": "Messaging"}
        if "buttons" in expr:
            return json.dumps({"title": "", "buttons": []})
        return {"threads": [], "url": messaging.MESSAGING, "title": "Messaging", "lines": []}

    monkeypatch.setattr(messaging, "evaluate_pinned", pinned)


def test_ensure_messaging_polls_the_navigated_tab_when_its_url_is_still_the_feed(monkeypatch):
    _install_stale_tab_list(monkeypatch)
    info = messaging.ensure_messaging(9222)
    assert info["opened"] == "navigated"
    assert info["ready"] is True
    assert info["url"] == messaging.MESSAGING


def test_finish_open_retries_when_the_destination_url_is_not_listed_yet(monkeypatch):
    calls = {"n": 0}

    def evaluate(port, expr, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            raise ChromeError(_URL_MISS)
        return {"ready": True, "url": messaging.MESSAGING, "title": "Messaging"}

    monkeypatch.setattr(messaging, "evaluate", evaluate)
    monkeypatch.setattr(messaging.time, "sleep", lambda _seconds: None)
    info = messaging._finish_open(9222, {"url": messaging.MESSAGING, "title": ""})
    assert info["ready"] is True
    assert calls["n"] == 2


def test_scan_refuses_to_read_threads_when_messaging_never_becomes_ready(monkeypatch):
    monkeypatch.setattr(
        scan_mod.messaging,
        "ensure_messaging",
        lambda port: {"ok": True, "ready": False, "opened": "navigated", "url": "https://www.linkedin.com/feed/"},
    )

    def boom(*_a, **_k):
        raise AssertionError("must not scroll or list threads when messaging never became ready")

    monkeypatch.setattr(scan_mod, "evaluate", boom)
    monkeypatch.setattr(scan_mod.messaging, "list_threads", boom)
    with pytest.raises(ChromeError, match="not ready"):
        scan_mod.find_referral_candidates(scan_mod.Config())


# Every CLI surface that opens messaging, including the flags that change
# how it opens. Exit codes are the command's own contract (select with no
# matching thread is 2; send --to with no match is 1). None of them may
# surface the tab-list URL miss.
@pytest.mark.parametrize(
    ("argv", "ok_codes"),
    [
        (["messages", "open"], {0}),
        (["messages", "open", "--json"], {0}),
        (["messages", "threads"], {0}),
        (["messages", "threads", "--json"], {0}),
        (["messages", "threads", "--unread"], {0}),
        (["messages", "threads", "--unread", "--json"], {0}),
        (["messages", "threads", "--limit", "5", "--json"], {0}),
        (["messages", "threads", "--filter", "ada"], {2}),
        (["messages", "threads", "--filter", "ada", "--json"], {2}),  # a filter miss exits 2 whatever the format
        (["messages", "threads", "--no-navigate"], {0}),
        (["messages", "threads", "--no-navigate", "--json"], {0}),
        (["messages", "select", "Ada"], {2}),
        (["messages", "select", "Ada", "--json"], {2}),
        (["messages", "read"], {0}),
        (["messages", "read", "--json"], {0}),
        (["messages", "read", "--limit", "3", "--json"], {0}),
        (["messages", "popups"], {0}),
        (["messages", "popups", "--json"], {0}),
        (["messages", "send", "hi", "--to", "Ada"], {1}),
        (["messages", "send", "hi", "--to", "Ada", "--json"], {1}),
        (["scan"], {0}),
        (["scan", "--json"], {0}),
    ],
)
def test_cli_options_do_not_die_when_the_messaging_url_is_not_listed_yet(monkeypatch, argv, ok_codes):
    _install_stale_tab_list(monkeypatch)
    result = runner.invoke(app, argv)
    assert _URL_MISS not in (result.output or "")
    assert result.exception is None or _URL_MISS not in str(result.exception)
    assert "Traceback" not in (result.output or "")
    assert result.exit_code in ok_codes, result.output

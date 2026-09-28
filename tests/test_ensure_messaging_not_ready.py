"""Correctness fix (review B10): ensure_messaging can return ready=False
(the 1-second wait timed out) while still reporting ok=True; list_threads
never checked that at all, so it silently queried a page that hadn't
finished loading and returned an empty threads list instead of a clear
error -- indistinguishable from "no threads"."""

from __future__ import annotations

import pytest

from linkedin_mcp import messaging
from linkedin_mcp.cdp_session import ChromeError

_MESSAGING_TAB = {"id": "msg", "url": "https://www.linkedin.com/messaging/", "title": "Messaging"}


def test_list_threads_raises_when_messaging_never_became_ready(monkeypatch):
    monkeypatch.setattr(messaging, "pages", lambda port: [_MESSAGING_TAB])
    monkeypatch.setattr(
        messaging,
        "ensure_messaging",
        lambda port: {"action": "open", "opened": "navigated", "ok": True, "url": messaging.MESSAGING, "title": "", "ready": False},
    )

    def boom(*a, **k):
        raise AssertionError("must not query threads on a page that never became ready")

    monkeypatch.setattr(messaging, "evaluate", boom)

    with pytest.raises(ChromeError, match="not ready"):
        messaging.list_threads(9222, kind="threads")


def test_list_threads_proceeds_normally_when_ready(monkeypatch):
    monkeypatch.setattr(messaging, "pages", lambda port: [_MESSAGING_TAB])
    monkeypatch.setattr(
        messaging,
        "ensure_messaging",
        lambda port: {"action": "open", "opened": "navigated", "ok": True, "url": messaging.MESSAGING, "title": "", "ready": True},
    )
    monkeypatch.setattr(messaging, "evaluate", lambda port, expr, **kw: {"threads": []})

    result = messaging.list_threads(9222, kind="threads")

    assert result["threads"] == []


def test_list_threads_no_navigate_skips_the_readiness_check(monkeypatch):
    """no_navigate=True means "read the current tab as-is" -- it never calls
    ensure_messaging at all, so there's nothing to check readiness of."""
    monkeypatch.setattr(messaging, "pages", lambda port: [_MESSAGING_TAB])

    def boom(*a, **k):
        raise AssertionError("no_navigate=True must not call ensure_messaging")

    monkeypatch.setattr(messaging, "ensure_messaging", boom)
    monkeypatch.setattr(messaging, "evaluate", lambda port, expr, **kw: {"threads": []})

    result = messaging.list_threads(9222, kind="threads", no_navigate=True)
    assert result["threads"] == []


def test_select_thread_raises_when_messaging_never_became_ready(monkeypatch):
    monkeypatch.setattr(messaging, "pages", lambda port: [_MESSAGING_TAB])
    monkeypatch.setattr(
        messaging,
        "ensure_messaging",
        lambda port: {"action": "open", "opened": "navigated", "ok": True, "url": messaging.MESSAGING, "title": "", "ready": False},
    )

    def boom(*a, **k):
        raise AssertionError("must not query/click a page that never became ready")

    monkeypatch.setattr(messaging, "evaluate", boom)

    with pytest.raises(ChromeError, match="not ready"):
        messaging.select_thread(9222, "Jordan")

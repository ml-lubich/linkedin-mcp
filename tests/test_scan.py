"""Restored `scan` (referral-candidate finder), on top of messaging.py's
list_threads/select_thread/read_thread -- replaces the old `li` shell-out
(own-chrome's `li threads`/`li read`) that linkedin-agent depended on."""

from __future__ import annotations

import pytest

import linkedin_mcp.scan as scan_mod


@pytest.fixture(autouse=True)
def _no_real_sleep(monkeypatch):
    monkeypatch.setattr(scan_mod.time, "sleep", lambda s: None)


def test_find_referral_candidates_runs_scroll_loop(config, monkeypatch):
    calls = []
    monkeypatch.setattr(scan_mod, "evaluate", lambda port, script, **kw: calls.append(script) or True)
    monkeypatch.setattr(scan_mod.messaging, "ensure_messaging", lambda port: None)
    monkeypatch.setattr(
        scan_mod.messaging,
        "list_threads",
        lambda *a, **k: {"threads": [{"name": "Jordan Lee", "preview": "hiring for a role", "unread": True}]},
    )
    monkeypatch.setattr(scan_mod.messaging, "select_thread", lambda port, name: {"ok": True, "ambiguous": False})
    monkeypatch.setattr(
        scan_mod.messaging,
        "read_thread",
        lambda port, limit=80: {"bodies": ["hiring for a role"], "speakers": ["Jordan Lee"], "url": "https://example.com"},
    )
    candidates = scan_mod.find_referral_candidates(config, scroll_rounds=3, sleep_seconds=0.01, click_settle_seconds=0.01)
    assert "Jordan Lee" in candidates
    assert len(calls) == 3


def test_find_referral_candidates_keeps_clean_thread(config, monkeypatch):
    monkeypatch.setattr(scan_mod, "evaluate", lambda *a, **k: True)
    monkeypatch.setattr(scan_mod.messaging, "ensure_messaging", lambda port: None)
    monkeypatch.setattr(
        scan_mod.messaging,
        "list_threads",
        lambda *a, **k: {"threads": [{"name": "Jordan Lee", "preview": "hiring for a role", "unread": True}]},
    )
    monkeypatch.setattr(scan_mod.messaging, "select_thread", lambda port, name: {"ok": True, "ambiguous": False})
    monkeypatch.setattr(
        scan_mod.messaging,
        "read_thread",
        lambda port, limit=80: {
            "bodies": ["hiring for a role"],
            "speakers": ["Jordan Lee"],
            "url": "https://www.linkedin.com/messaging/thread/abc/",
        },
    )
    candidates = scan_mod.find_referral_candidates(config, scroll_rounds=0, sleep_seconds=0, click_settle_seconds=0)
    assert "Jordan Lee" in candidates
    assert candidates["Jordan Lee"].unread is True
    assert candidates["Jordan Lee"].url.endswith("abc/")


def test_find_referral_candidates_skips_own_last_message(config, monkeypatch):
    monkeypatch.setattr(scan_mod, "evaluate", lambda *a, **k: True)
    monkeypatch.setattr(scan_mod.messaging, "ensure_messaging", lambda port: None)
    monkeypatch.setattr(
        scan_mod.messaging,
        "list_threads",
        lambda *a, **k: {"threads": [{"name": "Jordan Lee", "preview": "hiring for a role", "unread": False}]},
    )
    monkeypatch.setattr(scan_mod.messaging, "select_thread", lambda port, name: {"ok": True, "ambiguous": False})
    monkeypatch.setattr(
        scan_mod.messaging,
        "read_thread",
        lambda port, limit=80: {"bodies": ["hi"], "speakers": ["Jordan Lee", config.self_name], "url": "https://example.com/thread"},
    )
    candidates = scan_mod.find_referral_candidates(config, scroll_rounds=0, sleep_seconds=0, click_settle_seconds=0)
    assert candidates == {}


def test_find_referral_candidates_skips_you_preview(config, monkeypatch):
    monkeypatch.setattr(scan_mod, "evaluate", lambda *a, **k: True)
    monkeypatch.setattr(scan_mod.messaging, "ensure_messaging", lambda port: None)
    monkeypatch.setattr(
        scan_mod.messaging,
        "list_threads",
        lambda *a, **k: {"threads": [{"name": "Jordan Lee", "preview": "You: sounds good", "unread": False}]},
    )

    def boom(*a, **k):
        raise AssertionError("select/read should not be called for a You: preview")

    monkeypatch.setattr(scan_mod.messaging, "select_thread", boom)
    candidates = scan_mod.find_referral_candidates(config, scroll_rounds=0, sleep_seconds=0, click_settle_seconds=0)
    assert candidates == {}


def test_find_referral_candidates_skips_ambiguous_or_missed_click(config, monkeypatch):
    monkeypatch.setattr(scan_mod, "evaluate", lambda *a, **k: True)
    monkeypatch.setattr(scan_mod.messaging, "ensure_messaging", lambda port: None)
    monkeypatch.setattr(
        scan_mod.messaging,
        "list_threads",
        lambda *a, **k: {"threads": [{"name": "Jordan Lee", "preview": "hiring", "unread": False}]},
    )
    monkeypatch.setattr(scan_mod.messaging, "select_thread", lambda port, name: {"ok": False, "ambiguous": False})

    def boom(*a, **k):
        raise AssertionError("read should not be called when select did not land")

    monkeypatch.setattr(scan_mod.messaging, "read_thread", boom)
    candidates = scan_mod.find_referral_candidates(config, scroll_rounds=0, sleep_seconds=0, click_settle_seconds=0)
    assert candidates == {}


def test_find_referral_candidates_skips_excluded(config, monkeypatch):
    monkeypatch.setattr(scan_mod, "evaluate", lambda *a, **k: True)
    monkeypatch.setattr(scan_mod.messaging, "ensure_messaging", lambda port: None)
    monkeypatch.setattr(
        scan_mod.messaging,
        "list_threads",
        lambda *a, **k: {"threads": [{"name": "Blocked Person", "preview": "hi", "unread": False}]},
    )
    monkeypatch.setattr(scan_mod.messaging, "select_thread", lambda port, name: {"ok": True, "ambiguous": False})
    monkeypatch.setattr(
        scan_mod.messaging,
        "read_thread",
        lambda port, limit=80: {"bodies": ["hiring for a role"], "speakers": ["Blocked Person"], "url": "https://example.com"},
    )
    candidates = scan_mod.find_referral_candidates(config, scroll_rounds=0, sleep_seconds=0, click_settle_seconds=0)
    assert candidates == {}


def test_find_referral_candidates_skips_already_referred(config, monkeypatch):
    monkeypatch.setattr(scan_mod, "evaluate", lambda *a, **k: True)
    monkeypatch.setattr(scan_mod.messaging, "ensure_messaging", lambda port: None)
    monkeypatch.setattr(
        scan_mod.messaging,
        "list_threads",
        lambda *a, **k: {"threads": [{"name": "Jordan Lee", "preview": "hiring", "unread": False}]},
    )
    monkeypatch.setattr(scan_mod.messaging, "select_thread", lambda port, name: {"ok": True, "ambiguous": False})
    monkeypatch.setattr(
        scan_mod.messaging,
        "read_thread",
        lambda port, limit=80: {
            "bodies": ["hiring for a role", f"mentioned {config.referral.email} already"],
            "speakers": ["Jordan Lee", "Jordan Lee"],
            "url": "https://example.com",
        },
    )
    candidates = scan_mod.find_referral_candidates(config, scroll_rounds=0, sleep_seconds=0, click_settle_seconds=0)
    assert candidates == {}


# ---- _load_full_thread_list: scroll/sleep loop -----------------------------


def test_load_full_thread_list_scrolls_once_per_round(monkeypatch):
    calls = []
    monkeypatch.setattr(scan_mod, "evaluate", lambda port, script, **kw: calls.append((port, script, kw)))
    slept = []
    monkeypatch.setattr(scan_mod.time, "sleep", lambda s: slept.append(s))

    scan_mod._load_full_thread_list(port=42, rounds=3, sleep_seconds=1.5)

    assert len(calls) == 3
    assert all(port == 42 and script == scan_mod._SCROLL_JS and kw == {"host": scan_mod.TAB} for port, script, kw in calls)
    assert slept == [1.5, 1.5, 1.5]


def test_load_full_thread_list_skips_sleep_when_seconds_is_zero(monkeypatch):
    monkeypatch.setattr(scan_mod, "evaluate", lambda *a, **k: None)
    slept = []
    monkeypatch.setattr(scan_mod.time, "sleep", lambda s: slept.append(s))

    scan_mod._load_full_thread_list(port=1, rounds=2, sleep_seconds=0)

    assert slept == []


# ---- find_referral_candidates: port resolution, limits, truncation --------


def test_find_referral_candidates_uses_configured_cdp_port_and_default_limits(config, monkeypatch):
    calls = {}
    monkeypatch.setattr(scan_mod, "evaluate", lambda *a, **k: True)
    monkeypatch.setattr(scan_mod.messaging, "ensure_messaging", lambda port: calls.setdefault("ensure_port", port))
    def fake_list_threads(port, **kw):
        calls["list_threads"] = (port, kw)
        return {"threads": []}

    monkeypatch.setattr(scan_mod.messaging, "list_threads", fake_list_threads)
    result = scan_mod.find_referral_candidates(config, scroll_rounds=0, sleep_seconds=0)
    assert result == {}
    assert calls["ensure_port"] == config.cdp_port
    assert calls["list_threads"] == (config.cdp_port, {"kind": "threads", "limit": 500, "no_navigate": True})


def test_find_referral_candidates_uses_explicit_port_override(config, monkeypatch):
    calls = {}
    monkeypatch.setattr(scan_mod, "evaluate", lambda *a, **k: True)
    monkeypatch.setattr(scan_mod.messaging, "ensure_messaging", lambda port: calls.setdefault("ensure_port", port))
    def fake_list_threads(port, **kw):
        calls["list_port"] = port
        return {"threads": []}

    monkeypatch.setattr(scan_mod.messaging, "list_threads", fake_list_threads)
    scan_mod.find_referral_candidates(config, port=1234, scroll_rounds=0, sleep_seconds=0)
    assert calls["ensure_port"] == 1234
    assert calls["list_port"] == 1234


def test_find_referral_candidates_passes_explicit_thread_and_read_limits(config, monkeypatch):
    monkeypatch.setattr(scan_mod, "evaluate", lambda *a, **k: True)
    monkeypatch.setattr(scan_mod.messaging, "ensure_messaging", lambda port: None)
    list_calls = {}
    monkeypatch.setattr(
        scan_mod.messaging,
        "list_threads",
        lambda port, **kw: list_calls.update(kw)
        or {"threads": [{"name": "Jordan", "preview": "hi", "unread": False}]},
    )
    monkeypatch.setattr(scan_mod.messaging, "select_thread", lambda port, name: {"ok": True, "ambiguous": False})
    read_calls = {}
    monkeypatch.setattr(
        scan_mod.messaging,
        "read_thread",
        lambda port, limit=80: read_calls.update(limit=limit) or {"bodies": [], "speakers": [], "url": ""},
    )
    scan_mod.find_referral_candidates(
        config, thread_limit=7, read_limit=9, scroll_rounds=0, sleep_seconds=0, click_settle_seconds=0
    )
    assert list_calls["limit"] == 7
    assert read_calls["limit"] == 9


def test_find_referral_candidates_truncates_text_to_last_2500_chars(config, monkeypatch):
    monkeypatch.setattr(scan_mod, "evaluate", lambda *a, **k: True)
    monkeypatch.setattr(scan_mod.messaging, "ensure_messaging", lambda port: None)
    monkeypatch.setattr(
        scan_mod.messaging,
        "list_threads",
        lambda *a, **k: {"threads": [{"name": "Jordan", "preview": "hi", "unread": False}]},
    )
    monkeypatch.setattr(scan_mod.messaging, "select_thread", lambda port, name: {"ok": True, "ambiguous": False})
    bodies = ["a" * 3000, "b" * 10]
    monkeypatch.setattr(
        scan_mod.messaging, "read_thread", lambda port, limit=80: {"bodies": bodies, "speakers": [], "url": ""}
    )
    candidates = scan_mod.find_referral_candidates(config, scroll_rounds=0, sleep_seconds=0, click_settle_seconds=0)
    expected = "\n".join(bodies)[-2500:]
    assert candidates["Jordan"].text == expected
    assert len(candidates["Jordan"].text) == 2500


def test_find_referral_candidates_skips_thread_with_no_name(config, monkeypatch):
    monkeypatch.setattr(scan_mod, "evaluate", lambda *a, **k: True)
    monkeypatch.setattr(scan_mod.messaging, "ensure_messaging", lambda port: None)
    monkeypatch.setattr(
        scan_mod.messaging,
        "list_threads",
        lambda *a, **k: {"threads": [{"name": "", "preview": "hi", "unread": False}]},
    )

    def boom(*a, **k):
        raise AssertionError("select should not run for a nameless thread")

    monkeypatch.setattr(scan_mod.messaging, "select_thread", boom)
    candidates = scan_mod.find_referral_candidates(config, scroll_rounds=0, sleep_seconds=0, click_settle_seconds=0)
    assert candidates == {}


def test_find_referral_candidates_does_not_settle_sleep_when_there_is_nothing_to_verify(config, monkeypatch):
    # Updated for review B8: a fixed settle-sleep before every read was
    # replaced with verifying the opened thread's href before trusting the
    # read (see test_scan_verify_selection.py), retrying with a sleep only
    # when that verification doesn't match yet. select_thread here reports
    # no href (nothing to verify against), so no settle-sleep is expected --
    # it no longer fires unconditionally.
    monkeypatch.setattr(scan_mod, "evaluate", lambda *a, **k: True)
    monkeypatch.setattr(scan_mod.messaging, "ensure_messaging", lambda port: None)
    monkeypatch.setattr(
        scan_mod.messaging,
        "list_threads",
        lambda *a, **k: {"threads": [{"name": "Jordan", "preview": "hi", "unread": False}]},
    )
    monkeypatch.setattr(scan_mod.messaging, "select_thread", lambda port, name: {"ok": True, "ambiguous": False})
    monkeypatch.setattr(
        scan_mod.messaging, "read_thread", lambda port, limit=80: {"bodies": [], "speakers": [], "url": ""}
    )
    slept = []
    monkeypatch.setattr(scan_mod.time, "sleep", lambda s: slept.append(s))
    scan_mod.find_referral_candidates(config, scroll_rounds=0, sleep_seconds=0, click_settle_seconds=3.25)
    assert slept == []

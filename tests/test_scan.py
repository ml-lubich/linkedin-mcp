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

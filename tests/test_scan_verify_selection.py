"""Correctness fix (review B8): select_thread's ACT_JS only waits for *a*
composer to exist, not specifically the selected thread's composer -- a
composer already present from the previously-open thread can make `ok=True`
race ahead of the actual navigation. scan.find_referral_candidates must
verify the opened thread is the one it selected (by href) before trusting
read_thread's text, rather than trusting a fixed settle-sleep. Also: only a
preview literally starting with "You:" is ours -- "You" alone is not."""

from __future__ import annotations

import linkedin_mcp.scan as scan_mod


def test_skips_only_previews_that_literally_start_with_you_colon(config, monkeypatch):
    monkeypatch.setattr(scan_mod, "evaluate", lambda *a, **k: True)
    monkeypatch.setattr(scan_mod.messaging, "ensure_messaging", lambda port: None)
    monkeypatch.setattr(
        scan_mod.messaging,
        "list_threads",
        lambda *a, **k: {
            "threads": [
                {"name": "You Might Know", "preview": "You've got this!", "unread": False, "href": "/t/1/"},
            ]
        },
    )
    monkeypatch.setattr(
        scan_mod.messaging, "select_thread", lambda port, name: {"ok": True, "ambiguous": False, "href": "/t/1/"}
    )
    monkeypatch.setattr(
        scan_mod.messaging,
        "read_thread",
        lambda port, limit=80: {"bodies": ["hiring for a role"], "speakers": ["You Might Know"], "url": "https://x/t/1/"},
    )
    candidates = scan_mod.find_referral_candidates(config, scroll_rounds=0, sleep_seconds=0, click_settle_seconds=0)
    assert "You Might Know" in candidates


def test_skips_preview_that_literally_starts_with_you_colon(config, monkeypatch):
    monkeypatch.setattr(scan_mod, "evaluate", lambda *a, **k: True)
    monkeypatch.setattr(scan_mod.messaging, "ensure_messaging", lambda port: None)
    monkeypatch.setattr(
        scan_mod.messaging,
        "list_threads",
        lambda *a, **k: {"threads": [{"name": "Jordan Lee", "preview": "You: sounds good", "unread": False, "href": "/t/1/"}]},
    )

    def boom(*a, **k):
        raise AssertionError("select should not be called for a You: preview")

    monkeypatch.setattr(scan_mod.messaging, "select_thread", boom)
    candidates = scan_mod.find_referral_candidates(config, scroll_rounds=0, sleep_seconds=0, click_settle_seconds=0)
    assert candidates == {}


def test_skips_candidate_when_the_opened_thread_does_not_match_the_selection(config, monkeypatch):
    """select_thread reported ok=True and an href, but read_thread's url
    shows a DIFFERENT thread is actually open (the click raced ahead of
    navigation) -- must not attribute that text to the wrong candidate."""
    monkeypatch.setattr(scan_mod, "evaluate", lambda *a, **k: True)
    monkeypatch.setattr(scan_mod.time, "sleep", lambda s: None)
    monkeypatch.setattr(scan_mod.messaging, "ensure_messaging", lambda port: None)
    monkeypatch.setattr(
        scan_mod.messaging,
        "list_threads",
        lambda *a, **k: {"threads": [{"name": "Jordan Lee", "preview": "hiring", "unread": False, "href": "/t/1/"}]},
    )
    monkeypatch.setattr(
        scan_mod.messaging, "select_thread", lambda port, name: {"ok": True, "ambiguous": False, "href": "/t/1/"}
    )
    # Every read shows a stale/different thread (href /t/9/, not /t/1/).
    monkeypatch.setattr(
        scan_mod.messaging,
        "read_thread",
        lambda port, limit=80: {"bodies": ["unrelated"], "speakers": [], "url": "https://x/t/9/"},
    )
    candidates = scan_mod.find_referral_candidates(config, scroll_rounds=0, sleep_seconds=0, click_settle_seconds=0)
    assert candidates == {}


def test_accepts_candidate_once_the_opened_thread_matches_after_a_retry(config, monkeypatch):
    monkeypatch.setattr(scan_mod, "evaluate", lambda *a, **k: True)
    monkeypatch.setattr(scan_mod.time, "sleep", lambda s: None)
    monkeypatch.setattr(scan_mod.messaging, "ensure_messaging", lambda port: None)
    monkeypatch.setattr(
        scan_mod.messaging,
        "list_threads",
        lambda *a, **k: {"threads": [{"name": "Jordan Lee", "preview": "hiring", "unread": False, "href": "/t/1/"}]},
    )
    monkeypatch.setattr(
        scan_mod.messaging, "select_thread", lambda port, name: {"ok": True, "ambiguous": False, "href": "/t/1/"}
    )
    reads = [
        {"bodies": ["stale"], "speakers": [], "url": "https://x/t/9/"},
        {"bodies": ["hiring for a role"], "speakers": ["Jordan Lee"], "url": "https://x/t/1/"},
    ]
    monkeypatch.setattr(scan_mod.messaging, "read_thread", lambda port, limit=80: reads.pop(0))
    candidates = scan_mod.find_referral_candidates(config, scroll_rounds=0, sleep_seconds=0, click_settle_seconds=0)
    assert "Jordan Lee" in candidates

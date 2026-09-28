"""Correctness fix (review L3):
(a) select_thread's ok=False means two different things -- "no thread
matched at all" (decision never found a candidate) vs "a thread WAS
matched and clicked, but its composer never appeared" (a slow/broken page).
core.messages_send's `to` guard reported both as "no thread matched",
which is misleading when a thread genuinely was found.
(b) the thread-listing JS deduped candidates by `href || name`, so two
threads sharing a name with NEITHER having an anchor collapsed into one
entry before match_thread's ambiguity check ever saw them.
"""

from __future__ import annotations

import pytest

import linkedin_mcp.core as core
from linkedin_mcp.messages_actions import _THREAD_QUERY_JS


@pytest.fixture(autouse=True)
def _wire_config(monkeypatch):
    monkeypatch.setattr(core, "load_agent_config", lambda path=None: type("C", (), {"cdp_port": 9222})())


def test_messages_send_distinguishes_no_match_from_composer_never_appeared(monkeypatch):
    monkeypatch.setattr(
        core.messaging_mod,
        "select_thread",
        lambda port, name: {"ok": False, "ambiguous": False, "matched": "Ada Lovelace", "matches": []},
    )
    with pytest.raises(ValueError, match="matched 'Ada' but the compose box never appeared"):
        core.messages_send("hi", to="Ada", confirm=True)


def test_messages_send_reports_plain_no_match_when_nothing_matched(monkeypatch):
    monkeypatch.setattr(
        core.messaging_mod, "select_thread", lambda port, name: {"ok": False, "ambiguous": False, "matched": "", "matches": []}
    )
    with pytest.raises(ValueError, match="no thread matched 'Nobody'"):
        core.messages_send("hi", to="Nobody", confirm=True)


def test_thread_listing_js_only_dedupes_by_href_not_by_name_fallback():
    """Smoke check on the JS source (no browser to execute it against, same
    convention as test_ambiguous_match_returns_before_the_card_click): the
    old `const dedupeKey = href || name;` fallback let two anchorless
    same-name threads collapse into one before Python's ambiguity check
    ever ran. Must dedupe on href alone."""
    assert "href || name" not in _THREAD_QUERY_JS
    assert "href || n" not in _THREAD_QUERY_JS

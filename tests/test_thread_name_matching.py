"""Correctness fix (review B2): thread selection must prefer an exact
(case-insensitive, whitespace/unicode-normalized) name match over a
substring one, must treat two threads with the identical name as ambiguous
(never silently pick the first), and must dedupe candidates by a stable
per-thread id (href), not by display name -- two threads sharing a name
must not collapse into one entry before the ambiguity check ever runs."""

from __future__ import annotations

from linkedin_mcp.messages_actions import match_thread


def _t(name: str, href: str) -> dict:
    return {"name": name, "href": href, "preview": "", "unread": False}


def test_exact_match_wins_over_a_longer_substring_match():
    threads = [_t("John Smith", "/messaging/thread/1/"), _t("John Smithson", "/messaging/thread/2/")]
    result = match_thread(threads, "John Smith")
    assert result["ok"] is True
    assert result["ambiguous"] is False
    assert result["matched_name"] == "John Smith"
    assert result["matched_href"] == "/messaging/thread/1/"


def test_substring_match_used_when_no_exact_match_exists():
    threads = [_t("John Smithson", "/messaging/thread/2/")]
    result = match_thread(threads, "Smith")
    assert result["ok"] is True
    assert result["matched_name"] == "John Smithson"


def test_two_threads_with_the_identical_name_are_ambiguous_not_deduped_away():
    threads = [_t("John Smith", "/messaging/thread/1/"), _t("John Smith", "/messaging/thread/2/")]
    result = match_thread(threads, "John Smith")
    assert result["ok"] is False
    assert result["ambiguous"] is True
    assert {m["href"] for m in result["matches"]} == {"/messaging/thread/1/", "/messaging/thread/2/"}


def test_two_substring_matches_are_ambiguous():
    threads = [_t("John Smith", "/messaging/thread/1/"), _t("John Smithson", "/messaging/thread/2/")]
    result = match_thread(threads, "John Smit")
    assert result["ok"] is False
    assert result["ambiguous"] is True


def test_no_match_is_not_ambiguous():
    threads = [_t("Ada Lovelace", "/messaging/thread/1/")]
    result = match_thread(threads, "Nobody")
    assert result["ok"] is False
    assert result["ambiguous"] is False
    assert result["matches"] == []


def test_blank_query_matches_nothing():
    threads = [_t("Ada Lovelace", "/messaging/thread/1/")]
    result = match_thread(threads, "   ")
    assert result["ok"] is False


def test_match_is_case_and_whitespace_insensitive():
    threads = [_t("  Ada   Lovelace  ", "/messaging/thread/1/")]
    result = match_thread(threads, "ada lovelace")
    assert result["ok"] is True


def test_unicode_accented_names_match():
    threads = [_t("José García", "/messaging/thread/1/")]
    result = match_thread(threads, "José García")
    assert result["ok"] is True


def test_unicode_emoji_in_name_does_not_crash_and_matches():
    threads = [_t("Ada 🚀 Lovelace", "/messaging/thread/1/")]
    result = match_thread(threads, "Ada 🚀 Lovelace")
    assert result["ok"] is True


def test_duplicate_hrefs_from_the_dom_query_are_deduped_before_matching():
    """The DOM query can legitimately return the same card twice (e.g. a
    re-render); that's a duplicate to collapse, unlike two distinct threads
    that happen to share a display name."""
    threads = [_t("Ada Lovelace", "/messaging/thread/1/"), _t("Ada Lovelace", "/messaging/thread/1/")]
    result = match_thread(threads, "Ada Lovelace")
    assert result["ok"] is True
    assert result["ambiguous"] is False

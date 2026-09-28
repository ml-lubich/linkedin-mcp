from __future__ import annotations

from datetime import datetime

from linkedin_mcp.copywriter import (
    assert_human_copy,
    company_from,
    draft_referral,
    first_name,
    late_apology,
    role_phrase,
    sentences,
    stale_days_from,
)


def test_first_name_strips_punctuation():
    assert first_name("Jordan  Lee") == "jordan"
    assert first_name("") == "there"
    assert first_name("O'Brien Smith") == "o'brien"


def test_company_from_at_pattern():
    assert company_from("", "Hey, we're hiring at Acme for a role") == "Acme"


def test_company_from_company_pattern():
    assert company_from("", "join our team, SnapLogic is growing") == "SnapLogic"


def test_company_from_none():
    assert company_from("", "no company mentioned here") == ""


def test_company_from_at_symbol_pattern():
    assert company_from("", "join us @Acme for great things") == "Acme"


def test_stale_days_from_invalid_slash_date_returns_zero():
    # Matches the D/D/YYYY shape but is not a real calendar date.
    assert stale_days_from("13/45/2026") == 0


def test_stale_days_from_invalid_month_abbreviation_returns_zero():
    # Matches the "XXX NN" shape but "Xyz" isn't a real %b month.
    assert stale_days_from("Xyz 15") == 0


def test_role_phrase_variants():
    assert role_phrase("founding engineer wanted", "") == "a founding engineer seat"
    assert role_phrase("looking for a consultant", "") == "this consulting role"
    assert role_phrase("data engineer for our warehouse", "") == "this data role"
    assert role_phrase("backend software engineer role", "") == "this engineering role"
    assert role_phrase("llm agent work", "") == "this ai role"
    assert role_phrase("something generic", "") == "this role"


def test_sentences_masks_urls_and_splits():
    text = "Check https://example.com/path now. Then reply soon!"
    result = sentences(text)
    assert result == ["Check URL now.", "Then reply soon!"]


def test_late_apology_thresholds():
    assert late_apology(0) == ""
    assert late_apology(10) == "sorry for the late reply"
    assert late_apology(45) == "sorry for the slow reply, this got buried on my end"


def test_stale_days_from_empty():
    assert stale_days_from("") == 0


def test_stale_days_from_time_stamp_is_today():
    assert stale_days_from("3:42 PM") == 0


def test_stale_days_from_weekday_is_three():
    assert stale_days_from("Tue") == 3


def test_stale_days_from_slash_date():
    now = datetime(2026, 9, 25)
    assert stale_days_from("9/18/26", now=now) == 7


def test_stale_days_from_month_day_before_now():
    now = datetime(2026, 9, 25)
    assert stale_days_from("Sep 18", now=now) == 7


def test_stale_days_from_month_day_rolls_back_a_year():
    # "Dec 20" read on Jan 5 next year means last December, ~16 days ago --
    # not 300+, since rolling the year back picks the *most recent* Dec 20.
    now = datetime(2026, 1, 5)
    days = stale_days_from("Dec 20", now=now)
    assert days == 16


def test_stale_days_from_garbage_is_zero():
    assert stale_days_from("not a date") == 0


def test_draft_referral_with_company(config):
    text = draft_referral(
        name="Jordan Lee",
        headline="Talent @ Acme",
        message="Exciting AI Engineer role at Acme",
        config=config,
    )
    assert text.startswith("hi jordan")
    assert "acme" in text.lower()
    assert config.referral.email in text
    assert config.referral.linkedin_url in text
    assert assert_human_copy(text, config) == []


def test_draft_referral_without_company_uses_generic_phrase(config):
    text = draft_referral(name="Sam", headline="", message="we have an opening", config=config)
    assert "look at what you are building" in text


def test_draft_referral_reengage_adds_lead_line(config):
    text = draft_referral(
        name="Sam",
        headline="",
        message="checking back in",
        config=config,
        reengage=True,
        stale_days=10,
    )
    assert "long time no see" in text
    assert "sorry for the late reply" in text
    assert "i have someone for you" in text


def test_draft_referral_uses_matching_pitch(config):
    text = draft_referral(name="Sam", headline="", message="data analytics role", config=config)
    assert "built data platforms that shipped" in text


def test_assert_human_copy_flags_ai_tells(config):
    bad = "Certainly, I'd be happy to delve into this exceptional opportunity."
    problems = assert_human_copy(bad, config)
    assert any(p.startswith("ai-tell:") for p in problems)


def test_assert_human_copy_flags_missing_hi_and_contact(config):
    problems = assert_human_copy("this message has no greeting at all here.", config)
    assert "missing-hi" in problems
    assert "missing-email" in problems
    assert "missing-linkedin" in problems


def test_assert_human_copy_flags_sentence_count(config):
    too_long = "hi there. " + "one. two. three. four. five. six. seven.".replace(".", ". ")
    problems = assert_human_copy(too_long, config)
    assert any(p.startswith("sentences:") for p in problems)

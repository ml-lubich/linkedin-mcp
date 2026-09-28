"""Hypothesis property tests: classifiers, parsers, config loading, and the
governor's pacing math. These check invariants that must hold for *any*
input, not just the hand-picked examples in the other test files.
"""

from __future__ import annotations

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from linkedin_mcp import classify, copywriter
from linkedin_mcp.agent_config import Config, PitchRule, ReferralConfig, load_config
from linkedin_mcp.governor import Budget, Governor, RateLimited

text_strategy = st.text(max_size=500)
name_strategy = st.text(alphabet=st.characters(blacklist_categories=("Cs",)), max_size=200)


# --------------------------------------------------------------- classify ---


@given(text_strategy)
@settings(max_examples=100)
def test_looks_like_hiring_is_deterministic_and_boolean(text):
    first = classify.looks_like_hiring(text)
    second = classify.looks_like_hiring(text)
    assert isinstance(first, bool)
    assert first == second


@given(text_strategy)
@settings(max_examples=100)
def test_looks_like_hiring_is_case_insensitive(text):
    assert classify.looks_like_hiring(text) == classify.looks_like_hiring(text.upper())


@given(name_strategy, text_strategy, text_strategy)
@settings(max_examples=100)
def test_exclude_reason_returns_string_or_empty(name, headline, message):
    config = Config()  # no exclusions configured -> must always be ""
    assert classify.exclude_reason(name, headline, message, config) == ""


@given(text_strategy)
@settings(max_examples=100)
def test_already_referred_false_when_referral_disabled(text):
    config = Config()  # referral.email/name are both "" when disabled
    assert classify.already_referred(text, config) is False


# ------------------------------------------------------------- copywriter ---


@given(text_strategy)
@settings(max_examples=100)
def test_first_name_is_always_nonempty_lowercase_or_there(text):
    result = copywriter.first_name(text)
    assert result != ""
    assert result == result.lower()


@given(text_strategy)
@settings(max_examples=100)
def test_sentences_never_returns_blank_entries(text):
    for sentence in copywriter.sentences(text):
        assert sentence.strip() != ""


@given(st.integers(min_value=0, max_value=100_000))
@settings(max_examples=100)
def test_late_apology_thresholds_are_monotonic(days):
    result = copywriter.late_apology(days)
    if days >= 30:
        assert "slow reply" in result
    elif days >= 7:
        assert result == "sorry for the late reply"
    else:
        assert result == ""


@given(text_strategy)
@settings(max_examples=50)
def test_stale_days_from_never_negative(text):
    assert copywriter.stale_days_from(text) >= 0


@given(name_strategy, text_strategy, text_strategy, st.booleans(), st.integers(min_value=0, max_value=1000))
@settings(max_examples=50)
def test_draft_referral_always_contains_referee_identity(name, headline, message, reengage, stale_days):
    config = Config(
        referral=ReferralConfig(
            enabled=True,
            name="Ref Person",
            email="ref@example.com",
            linkedin_url="https://www.linkedin.com/in/ref/",
            resume_path="/tmp/r.pdf",
        )
    )
    draft = copywriter.draft_referral(
        name=name, headline=headline, message=message, config=config, reengage=reengage, stale_days=stale_days
    )
    assert config.referral.email in draft
    assert config.referral.linkedin_url in draft
    assert draft.lower().startswith("hi ")


# ------------------------------------------------------------------ config -

ascii_word = st.text(alphabet=st.characters(min_codepoint=65, max_codepoint=122), min_size=1, max_size=20)


@given(st.lists(ascii_word, min_size=1, max_size=5), st.text(alphabet=st.characters(min_codepoint=32, max_codepoint=126), max_size=300))
@settings(max_examples=100)
def test_pitch_rule_match_is_case_insensitive(keywords, blob):
    # Restricted to ASCII on purpose: Python's str.upper()/.lower() are not
    # perfect inverses for some Unicode (e.g. "ß".upper() == "SS"), which
    # would make this specific upper/lower-symmetry property flaky for
    # reasons unrelated to PitchRule -- ASCII keeps the property honest.
    keywords = [k for k in keywords if k.lower() != "default"] or ["x"]
    rule = PitchRule(keywords=keywords, text="t")
    assert rule.matches(blob) == rule.matches(blob.upper())
    assert rule.matches(blob) == rule.matches(blob.lower())


@given(st.integers(min_value=1, max_value=65535))
@settings(max_examples=30, suppress_health_check=[HealthCheck.function_scoped_fixture], deadline=None)
def test_env_cdp_port_override_always_wins_over_file(tmp_path, port):
    toml_path = tmp_path / "c.toml"
    toml_path.write_text("[chrome]\nport = 1\n")
    cfg = load_config(path=toml_path, env={"LINKEDIN_AGENT_CDP_PORT": str(port)})
    assert cfg.cdp_port == port


# --------------------------------------------------------------- governor --


@given(st.integers(min_value=0, max_value=1000), st.integers(min_value=1, max_value=1000))
@settings(max_examples=50)
def test_budget_remaining_never_negative(used, limit):
    budget = Budget(action="x", used=used, limit=limit, window_seconds=1)
    assert budget.remaining == max(0, limit - used)
    assert budget.remaining >= 0


@given(st.text(min_size=1, max_size=50).filter(lambda s: "\x00" not in s))
@settings(max_examples=30, suppress_health_check=[HealthCheck.function_scoped_fixture], deadline=None)
def test_governor_record_then_check_same_target_always_blocks(tmp_path, target):
    gov = Governor(tmp_path / "g.db", now=1_000_000.0)
    gov.record("search", target)
    with pytest.raises(RateLimited):
        gov.check("search", target)
    gov.close()


@given(st.floats(min_value=0, max_value=10_000_000, allow_nan=False, allow_infinity=False))
@settings(max_examples=30, suppress_health_check=[HealthCheck.function_scoped_fixture], deadline=None)
def test_governor_now_override_is_used_verbatim(tmp_path, now):
    gov = Governor(tmp_path / "g.db", now=now)
    gov.record("search", "t")
    row = gov._db.execute("SELECT at FROM actions WHERE target = ?", ("t",)).fetchone()
    assert row[0] == now
    gov.close()

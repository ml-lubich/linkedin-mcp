"""Edge-case input tables (empty/unicode/emoji/very long/injection-shaped
strings) run against every text-accepting pure function. The bar is "does
not crash and returns a sane type" -- not a specific value, since these
strings are adversarial/nonsensical by construction.
"""

from __future__ import annotations

import pytest

from conftest import EDGE_STRINGS
from linkedin_mcp import classify, copywriter
from linkedin_mcp import post_cdp as post


@pytest.mark.parametrize("text", EDGE_STRINGS)
def test_looks_like_hiring_never_crashes(text):
    assert isinstance(classify.looks_like_hiring(text), bool)


@pytest.mark.parametrize("text", EDGE_STRINGS)
def test_exclude_reason_never_crashes(text, config):
    assert isinstance(classify.exclude_reason(text, text, text, config), str)


@pytest.mark.parametrize("text", EDGE_STRINGS)
def test_already_referred_never_crashes(text, config):
    assert isinstance(classify.already_referred(text, config), bool)


@pytest.mark.parametrize("text", EDGE_STRINGS)
def test_first_name_never_crashes_and_is_nonempty(text):
    result = copywriter.first_name(text)
    assert isinstance(result, str)
    assert result != ""


@pytest.mark.parametrize("text", EDGE_STRINGS)
def test_company_from_never_crashes(text):
    assert isinstance(copywriter.company_from(text, text), str)


@pytest.mark.parametrize("text", EDGE_STRINGS)
def test_role_phrase_never_crashes(text):
    assert isinstance(copywriter.role_phrase(text, text), str)


@pytest.mark.parametrize("text", EDGE_STRINGS)
def test_sentences_never_crashes_and_is_list(text):
    assert isinstance(copywriter.sentences(text), list)


@pytest.mark.parametrize("text", EDGE_STRINGS)
def test_stale_days_from_never_crashes_and_is_nonneg(text):
    days = copywriter.stale_days_from(text)
    assert isinstance(days, int)
    assert days >= 0


@pytest.mark.parametrize("text", EDGE_STRINGS)
def test_draft_referral_never_crashes(text, config):
    draft = copywriter.draft_referral(name=text, headline=text, message=text, config=config)
    assert isinstance(draft, str)
    assert draft  # never empty -- always at least the greeting


@pytest.mark.parametrize("text", EDGE_STRINGS)
def test_assert_human_copy_never_crashes(text, config):
    assert isinstance(copywriter.assert_human_copy(text, config), list)


@pytest.mark.parametrize("text", EDGE_STRINGS)
def test_lint_post_never_crashes(text):
    assert isinstance(post.lint_post(text), list)


@pytest.mark.parametrize("text", EDGE_STRINGS)
def test_late_apology_handles_string_input_gracefully(text):
    # late_apology expects an int-like; feeding it text should not explode
    # silently produce nonsense -- it should raise a clear TypeError/ValueError
    # or coerce, never hang or segfault. We only assert it terminates.
    try:
        copywriter.late_apology(text)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        pass

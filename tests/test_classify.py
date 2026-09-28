from __future__ import annotations

from linkedin_mcp.classify import already_referred, exclude_reason, looks_like_hiring


def test_looks_like_hiring_true_for_role_words():
    assert looks_like_hiring("Exciting Artificial Intelligence Consultant role at Acme")
    assert looks_like_hiring("InMail: we are hiring")


def test_looks_like_hiring_false_for_chat():
    assert not looks_like_hiring("want to grab coffee tomorrow?")
    assert not looks_like_hiring("")


def test_exclude_reason_never_contact(config):
    reason = exclude_reason("Blocked Person", "", "hello there", config)
    assert reason == "never-contact"


def test_exclude_reason_reserved_for_self(config):
    reason = exclude_reason("Someone", "Talent @ Reserved Co", "we are hiring", config)
    assert reason.startswith("reserved-for-self:")


def test_exclude_reason_clean_thread(config):
    assert exclude_reason("Jordan Lee", "Talent @ Acme", "hiring for a role", config) == ""


def test_already_referred_by_email(config):
    assert already_referred("please reach out to referee@example.com", config)


def test_already_referred_by_name(config):
    assert already_referred("I already mentioned Referee Person", config)


def test_not_already_referred(config):
    assert not already_referred("no mention here", config)


def test_already_referred_disabled_config(disabled_config):
    assert not already_referred("referee@example.com", disabled_config)

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


# --- classify() / joe_fit() -------------------------------------------------
import pytest

from linkedin_mcp import classify as classify_mod


@pytest.fixture(autouse=True)
def _ledger(tmp_path, monkeypatch):
    monkeypatch.setenv("JOE_REFERRAL_LEDGER", str(tmp_path / "ledger.json"))


def test_classify_clean(config):
    r = classify_mod.classify("We are hiring an AI engineer", config, name="Jordan Lee")
    assert r == {"hiring": True, "excluded": False, "already_referred": False, "reason": ""}


def test_classify_excluded_by_regex(config):
    r = classify_mod.classify("hiring at Anduril", config)
    assert r["excluded"] and "anduril" in r["reason"].lower()


def test_classify_already_referred_via_ledger(config):
    from linkedin_mcp import ledger

    ledger.append({"name": "Jordan Lee", "email": "j@acme.com", "company": "Acme"})
    r = classify_mod.classify("hiring a role", config, name="Jordan Lee")
    assert r["already_referred"] and r["reason"]
    r = classify_mod.classify("hiring a role", config, name="Someone Else", company="ACME")
    assert r["already_referred"]


def test_classify_already_referred_in_text(config):
    assert classify_mod.classify("cc referee@example.com", config)["already_referred"]


def test_classify_not_hiring_unicode(config):
    r = classify_mod.classify("café ☕ tomorrow?", config)
    assert r["hiring"] is False and r["reason"] == "not-hiring"


@pytest.mark.parametrize(
    "text,level",
    [
        ("Senior Platform Software Engineer, 6+ years of experience", "skip"),
        ("AI Python Data Engineer, 2+ years Python, RAG pipelines", "strong"),
        ("QA Automation Engineer Selenium", "skip"),
        ("Machine Learning Engineer remote agentic AI", "strong"),
        ("Staff ML Engineer", "skip"),
        ("AI Engineer, active TS/SCI clearance required", "skip"),
        ("C++ Developer", "skip"),
        ("Salesforce Developer", "skip"),
        ("RPA Developer UiPath", "skip"),
        ("Full-stack engineer Python TypeScript React, 3 years", "strong"),
        ("Forward Deployed Engineer, 4 years", "strong"),
        ("AI Engineer, 5 years experience", "skip"),
        ("Office Coordinator", "stretch"),
        ("", "stretch"),
    ],
)
def test_joe_fit(text, level):
    r = classify_mod.joe_fit(text)
    assert r["level"] == level and r["why"]

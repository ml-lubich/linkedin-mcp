from __future__ import annotations

import json

import pytest

from linkedin_mcp import ledger


@pytest.fixture
def path(tmp_path, monkeypatch):
    p = tmp_path / "joe" / "ledger.json"
    monkeypatch.setenv("JOE_REFERRAL_LEDGER", str(p))
    return p


def test_missing_file_is_empty(path):
    assert ledger.load() == []
    assert not ledger.contacted(name="Anyone")


def test_empty_file_is_empty(path):
    path.parent.mkdir(parents=True)
    path.write_text("")
    assert ledger.load() == []


def test_malformed_json_raises_and_is_not_overwritten(path):
    path.parent.mkdir(parents=True)
    path.write_text("{not json")
    with pytest.raises(ledger.LedgerError):
        ledger.load()
    with pytest.raises(ledger.LedgerError):
        ledger.append({"name": "A", "email": "a@x.com"})
    assert path.read_text() == "{not json"


def test_non_list_raises(path):
    path.parent.mkdir(parents=True)
    path.write_text('{"a": 1}')
    with pytest.raises(ledger.LedgerError):
        ledger.load()


def test_append_preserves_existing_and_creates_dir(path):
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps([{"name": "Old", "email": "old@x.com", "company": "Oldco", "channel": "email"}]))
    assert ledger.append({"name": "Zoë Ñandú", "email": "z@x.com", "company": "Acme", "channel": "linkedin"}) is True
    data = json.loads(path.read_text())
    assert [e["name"] for e in data] == ["Old", "Zoë Ñandú"]
    assert data[1]["date"]  # date defaulted
    assert not list(path.parent.glob("*.tmp"))


def test_append_dedupes_by_email_and_profile_url(path):
    assert ledger.append({"name": "A", "email": "A@X.com"}) is True
    assert ledger.append({"name": "A2", "email": "a@x.com"}) is False
    assert ledger.append({"name": "B", "profile_url": "https://li/in/b"}) is True
    assert ledger.append({"name": "B2", "profile_url": "HTTPS://LI/IN/B"}) is False
    assert len(ledger.load()) == 2


def test_contacted_matches(path):
    ledger.append({"name": "Zoë Ñandú", "email": "z@x.com", "company": "Acme Corp", "channel": "email"})
    assert ledger.contacted(name="zoë ñandú")
    assert ledger.contacted(email="Z@X.COM")
    assert ledger.contacted(company="acme corp")  # a coworker was contacted
    assert not ledger.contacted(company="Other")
    assert not ledger.contacted()
    assert not ledger.contacted(company="")


@pytest.mark.parametrize(
    "text",
    ["Mach Industries", "recruiter at mach", "Anduril", "EchoStar", "Dish Network", "AMD", "W3Sourcing", "Perry Barrow"],
)
def test_excluded_true(text):
    assert ledger.excluded(text)


@pytest.mark.parametrize("text", ["", "Acme Corp", "machine learning", "Dishwasher", "amdahl"])
def test_excluded_false(text):
    assert not ledger.excluded(text)

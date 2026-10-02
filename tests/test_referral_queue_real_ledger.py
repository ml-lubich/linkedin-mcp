"""run_queue against the REAL ledger module (tmp file); only the browser layer is mocked."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import linkedin_mcp.referral as ref
from linkedin_mcp import ledger

EMAIL = "referee@example.com"
THREAD = "https://www.linkedin.com/messaging/thread/2-abc/"


class World:
    def __init__(self) -> None:
        self.sent: list[str] = []
        self.text = ""
        self.opened: list[str] = []

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(ref, "open_item", self.open)
        monkeypatch.setattr(ref, "_snapshot", lambda port: {"header": self.opened[-1], "text": self.text})
        monkeypatch.setattr(ref, "send_message", self.send)
        monkeypatch.setattr(ref.time, "sleep", lambda s: None)

    def open(self, it: dict, port: int) -> None:
        self.opened.append(it["name"])
        self.text = ""

    def send(self, **kw: object) -> dict:
        if kw.get("attachment_path"):
            self.text += "\nreferee_resume.pdf"
        else:
            self.text += "\n" + str(kw["text"])
        self.sent.append(str(kw["text"]) or "<resume>")
        return {"sent": True}


@pytest.fixture
def world(monkeypatch: pytest.MonkeyPatch) -> World:
    w = World()
    w.install(monkeypatch)
    return w


@pytest.fixture
def ledger_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    p = tmp_path / "ledger.json"
    monkeypatch.setenv(ledger.ENV_VAR, str(p))
    return p


def item(name: str = "Jane Doe", company: str = "Acme", **kw: str) -> dict:
    return {"name": name, "thread_url": THREAD, "company": company, "role": "Eng",
            "body": f"Hi {name}, my friend... {EMAIL}", **kw}


def statuses(out: dict) -> list[str]:
    return [r["status"] for r in out["results"]]


def test_new_person_is_sent_and_ledgered(config, world, ledger_file):
    out = ref.run_queue([item(profile_url="https://li/in/jane")], config, confirm=True)
    assert statuses(out) == ["sent"] and len(world.sent) == 2
    [row] = ledger.load()
    assert row["channel"] == "linkedin" and row["name"] == "Jane Doe" and row["verified"] is True
    assert row["profile_url"] == "https://li/in/jane"


@pytest.mark.parametrize("seed", [
    {"name": "Someone Else", "email": "jane@acme.io", "company": "Other"},
    {"name": "Someone Else", "profile_url": "https://li/in/jane", "company": "Other"},
    {"name": "Someone Else", "email": "x@y.com", "company": "Acme"},
])
def test_already_in_ledger_is_skipped_not_sent(config, world, ledger_file, seed):
    ledger.append(seed)
    out = ref.run_queue([item(profile_url="https://li/in/jane", email="jane@acme.io")], config, confirm=True)
    assert statuses(out) == ["skipped"] and "ledger" in out["results"][0]["reason"]
    assert world.sent == [] and world.opened == []


@pytest.mark.parametrize("name,company,excluded", [
    ("Pat Lee", "Mach Industries", True),
    ("Pat Lee", "Anduril", True),
    ("Pat Lee", "EchoStar", True),
    ("Pat Lee", "Dish Network", True),
    ("Pat Lee", "AMD", True),
    ("Perry Barrow", "Acme", True),
    ("Pat Lee", "Amdocs", False),
])
def test_excluded_names_skipped(config, world, ledger_file, name, company, excluded):
    out = ref.run_queue([item(name, company)], config, confirm=True)
    assert statuses(out) == (["skipped"] if excluded else ["sent"])
    assert bool(world.sent) is not excluded


def test_malformed_ledger_raises_before_sending(config, world, ledger_file):
    ledger_file.write_text("{not json")
    with pytest.raises(ledger.LedgerError):
        ref.run_queue([item()], config, confirm=True)
    assert world.sent == [] and world.opened == []
    assert ledger_file.read_text() == "{not json"

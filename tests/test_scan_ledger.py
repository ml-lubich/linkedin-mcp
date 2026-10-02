"""Scan applies the shared ledger + exclusion regex, takes an injected page
reader, and prints JSON candidates."""

from __future__ import annotations

import json

import pytest

import linkedin_mcp.scan as scan_mod
from linkedin_mcp import ledger


class FakeReader:
    def __init__(self, threads):
        self.threads = threads  # name -> (preview, speakers, bodies)

    def ensure_messaging(self, port):
        return None

    def list_threads(self, port, **kw):
        return {"threads": [{"name": n, "preview": v[0], "unread": True} for n, v in self.threads.items()]}

    def select_thread(self, port, name):
        self.current = name
        return {"ok": True, "ambiguous": False}

    def read_thread(self, port, limit=80):
        _, speakers, bodies = self.threads[self.current]
        return {"bodies": bodies, "speakers": speakers, "url": f"https://www.linkedin.com/messaging/thread/{self.current[0]}/"}


@pytest.fixture(autouse=True)
def _env(tmp_path, monkeypatch):
    monkeypatch.setenv("JOE_REFERRAL_LEDGER", str(tmp_path / "ledger.json"))
    monkeypatch.setattr(scan_mod, "evaluate", lambda *a, **k: True)


def _scan(config, threads):
    return scan_mod.find_referral_candidates(
        config, scroll_rounds=0, sleep_seconds=0, click_settle_seconds=0, reader=FakeReader(threads)
    )


def test_keeps_clean_skips_excluded_company_and_ledger(config):
    ledger.append({"name": "Pat Done", "email": "p@x.com", "company": "Doneco", "channel": "email"})
    ledger.append({"name": "Other", "email": "o@acme.com", "company": "Acme", "channel": "email"})
    got = _scan(
        config,
        {
            "Jordan Lee": ("hiring", ["Jordan Lee"], ["AI engineer role"]),
            "Pat Done": ("hiring", ["Pat Done"], ["role"]),
            "Sam Coworker": ("hiring", ["Sam Coworker"], ["role at Acme"]),
            "Ann Mach": ("hiring", ["Ann Mach"], ["hiring at Anduril"]),
            "Me Last": ("hiring", ["Jordan", config.self_name], ["role", "thanks"]),
        },
    )
    assert list(got) == ["Jordan Lee"]


def test_company_from_headline_free_text_in_ledger(config):
    ledger.append({"name": "Other", "email": "o@acme.com", "company": "Acme", "channel": "email"})
    got = _scan(config, {"Sam Coworker": ("hi", ["Sam Coworker"], ["Sam from Acme, we have a role"])})
    assert got == {}


def test_to_json_is_valid_unicode(config):
    got = _scan(config, {"Zoë Ñandú": ("hi", ["Zoë Ñandú"], ["rôle ☕ hiring"])})
    out = json.loads(scan_mod.to_json(got))
    assert out[0]["name"] == "Zoë Ñandú" and out[0]["url"] and "fit" in out[0]


def test_to_json_empty():
    assert json.loads(scan_mod.to_json({})) == []

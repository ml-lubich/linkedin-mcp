"""`linkedin referral queue`: deterministic, ledger-guarded referral sends.

The CDP layer (open_item/_snapshot/send_message) and the ledger are faked; no
real Chrome or LinkedIn page is touched.
"""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

import linkedin_mcp.core as core
import linkedin_mcp.referral as ref
from linkedin_mcp.cli import app

runner = CliRunner()
EMAIL = "referee@example.com"
THREAD = "https://www.linkedin.com/messaging/thread/2-abc/"


def item(name="Jane Doe", company="Acme", **kw):
    base = {"name": name, "thread_url": THREAD, "company": company, "role": "Eng", "body": f"Hi {name}, my friend... {EMAIL}"}
    base.update(kw)
    return base


class FakeLedger:
    def __init__(self, contacted_names=()):
        self.rows = []
        self.names = set(contacted_names)

    def load(self):
        return list(self.rows)

    def contacted(self, entry):
        return entry["name"] in self.names or entry["company"] in {r["company"] for r in self.rows}

    def append(self, entry):
        self.rows.append(entry)


class FakeWorld:
    """Fake thread: sends append to `text`; snapshot reflects it."""

    def __init__(self, header=None, text="", send_twice=False):
        self.header, self.seed, self.text, self.sent, self.opened = header, text, text, [], []
        self.send_twice = send_twice

    def install(self, monkeypatch):
        monkeypatch.setattr(ref, "open_item", self.open)
        monkeypatch.setattr(ref, "_snapshot", lambda port: {"header": self.header or self.opened[-1], "text": self.text})
        monkeypatch.setattr(ref, "send_message", self.send)
        monkeypatch.setattr(ref.time, "sleep", lambda s: None)

    def open(self, it, port):
        self.opened.append(it["name"])
        self.text = self.seed

    def send(self, **kw):
        assert kw["confirm"] is True
        if kw.get("attachment_path"):
            self.text += "\nresume_joseph_heupler.pdf"
            if self.send_twice:
                self.text += "\nresume_joseph_heupler.pdf"
        else:
            self.text += "\n" + kw["text"]
        self.sent.append(kw)
        return {"sent": True}


@pytest.fixture
def world(monkeypatch):
    w = FakeWorld()
    w.install(monkeypatch)
    return w


def run(items, config, ledger, confirm=True, **kw):
    return ref.run_queue(items, config, confirm=confirm, ledger=ledger, **kw)


def statuses(out):
    return [r["status"] for r in out["results"]]


def test_dry_run_sends_nothing_and_touches_no_browser(config, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("browser touched in dry run")

    for fn in ("open_item", "_snapshot", "send_message"):
        monkeypatch.setattr(ref, fn, boom)
    led = FakeLedger()
    out = run([item(), item("Bob Roe", "Beta")], config, led, confirm=False)
    assert out["dry_run"] is True and statuses(out) == ["would-send", "would-send"]
    assert led.rows == []


def test_confirm_sends_body_then_resume_then_logs_ledger(config, world):
    led = FakeLedger()
    out = run([item()], config, led)
    assert statuses(out) == ["sent"] and out["dry_run"] is False
    assert [bool(k.get("attachment_path")) for k in world.sent] == [False, True]
    assert world.sent[0]["text"].endswith(EMAIL)
    assert world.sent[1]["attachment_path"] == config.referral.resume_path
    assert led.rows[0]["channel"] == "linkedin" and led.rows[0]["name"] == "Jane Doe" and led.rows[0]["company"] == "Acme"


@pytest.mark.parametrize("company", ["Mach", "Anduril", "EchoStar", "Dish", "AMD", "W3Sourcing", "anduril industries"])
def test_excluded_companies_are_skipped(config, world, company):
    out = run([item(company=company)], config, FakeLedger())
    assert statuses(out) == ["skipped"] and "exclu" in out["results"][0]["reason"]
    assert world.opened == []


def test_excluded_person_and_no_substring_false_positive(config, world):
    out = run([item(name="Perry Barrow"), item("Al Pha", "Amdocs")], config, FakeLedger())
    assert statuses(out) == ["skipped", "sent"]


def test_ledger_contacted_is_skipped_without_opening(config, world):
    out = run([item()], config, FakeLedger(contacted_names={"Jane Doe"}))
    assert statuses(out) == ["skipped"] and "ledger" in out["results"][0]["reason"]
    assert world.opened == []


def test_same_company_after_first_send_is_skipped(config, world):
    out = run([item(), item("Bob Roe", "Acme")], config, FakeLedger())
    assert statuses(out) == ["sent", "skipped"]


@pytest.mark.parametrize("existing", [EMAIL, "Joseph_Heupler_Resume.pdf", "resume_joseph_heupler.pdf"])
def test_thread_already_has_email_or_resume_is_skipped(config, world, existing):
    world.seed = f"earlier msg {existing}"
    led = FakeLedger()
    out = run([item()], config, led)
    assert statuses(out) == ["skipped"] and world.sent == [] and led.rows == []


def test_identity_mismatch_is_skipped(config, world):
    world.header = "Somebody Else"
    out = run([item()], config, FakeLedger())
    assert statuses(out) == ["skipped"] and "identity" in out["results"][0]["reason"]
    assert world.sent == []


def test_duplicate_resume_after_send_aborts_queue_and_flags_ledger(config, world):
    world.send_twice = True
    led = FakeLedger()
    out = run([item(), item("Bob Roe", "Beta")], config, led)
    assert statuses(out) == ["verify-failed"] and out["aborted"]
    assert led.rows[0]["verified"] is False  # sent, so never re-send it later
    assert world.opened == ["Jane Doe"]


def test_limit_caps_sends(config, world):
    items = [item(f"P{i} X", f"Co{i}") for i in range(4)]
    out = run(items, config, FakeLedger(), limit=2)
    assert statuses(out) == ["sent", "sent"]


def test_rate_limit_sleeps_between_sends_only(config, world, monkeypatch):
    sleeps = []
    monkeypatch.setattr(ref.time, "sleep", lambda s: sleeps.append(s))
    run([item(), item("Bob Roe", "Beta"), item("Cy Poe", "Gamma")], config, FakeLedger(), delay_range=(3.0, 3.0))
    assert sleeps == [3.0, 3.0]


@pytest.mark.parametrize(
    "bad", [{"name": ""}, {"thread_url": "", "profile_url": ""}, {"body": " "}, {"company": ""}]
)
def test_malformed_item_rejected_before_anything_runs(config, world, bad):
    with pytest.raises(ValueError):
        run([item("Ok Person", "Fine"), item(**bad)], config, FakeLedger())
    assert world.sent == []


def test_profile_url_item_clicks_message_button(monkeypatch):
    clicks = []
    monkeypatch.setattr(ref, "open_thread", lambda url, port: clicks.append(("open", url)))
    monkeypatch.setattr(ref, "evaluate", lambda port, js, tab, **k: clicks.append(("click", js)) or True)
    monkeypatch.setattr(ref.time, "sleep", lambda s: None)
    ref.open_item({"name": "A B", "profile_url": "https://www.linkedin.com/in/ab/"}, 9222)
    assert [c[0] for c in clicks] == ["open", "click"]
    ref.open_item({"name": "A B", "thread_url": THREAD}, 9222)
    assert [c[0] for c in clicks] == ["open", "click", "open"]


# ---- CLI / MCP -------------------------------------------------------------


@pytest.fixture
def qfile(tmp_path):
    p = tmp_path / "queue.json"
    p.write_text(json.dumps([item()]))
    return p


def test_cli_default_is_dry_run_and_passes_confirm_false(monkeypatch, qfile):
    seen = {}

    def fake(queue_path, **kw):
        seen.update(kw, queue_path=queue_path)
        return {"dry_run": True, "results": [{"name": "Jane Doe", "status": "would-send", "reason": ""}], "aborted": ""}

    monkeypatch.setattr(core, "referral_queue", fake)
    result = runner.invoke(app, ["referral", "queue", str(qfile)])
    assert result.exit_code == 0 and seen["confirm"] is False
    assert "would-send" in result.output.lower() or "would-send" in result.stdout.lower()


def test_cli_confirm_and_limit_reach_core(monkeypatch, qfile):
    seen = {}
    monkeypatch.setattr(core, "referral_queue", lambda queue_path, **kw: seen.update(kw) or {"dry_run": False, "results": [], "aborted": ""})
    result = runner.invoke(app, ["referral", "queue", str(qfile), "--confirm", "--limit", "3", "--json"])
    assert result.exit_code == 0 and seen["confirm"] is True and seen["limit"] == 3


def test_cli_aborted_queue_exits_nonzero(monkeypatch, qfile):
    monkeypatch.setattr(core, "referral_queue", lambda queue_path, **kw: {"dry_run": False, "results": [], "aborted": "verify failed"})
    assert runner.invoke(app, ["referral", "queue", str(qfile), "--confirm", "--json"]).exit_code == 2


def test_core_referral_queue_reads_file_and_runs(monkeypatch, config, qfile):
    monkeypatch.setattr(core, "load_agent_config", lambda path=None: config)
    out = core.referral_queue(str(qfile), confirm=False, ledger=FakeLedger())
    assert out["dry_run"] is True and statuses(out) == ["would-send"]


def test_core_rejects_non_list_queue(monkeypatch, config, tmp_path):
    monkeypatch.setattr(core, "load_agent_config", lambda path=None: config)
    p = tmp_path / "q.json"
    p.write_text('{"a": 1}')
    with pytest.raises(ValueError):
        core.referral_queue(str(p), ledger=FakeLedger())


def test_queue_help_short_and_long():
    for flag in ("-h", "--help"):
        assert runner.invoke(app, ["referral", "queue", flag]).exit_code == 0

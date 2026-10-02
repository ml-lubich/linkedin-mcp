"""followups: pure filter + scan orchestration against a mocked page."""

from __future__ import annotations

import json
from datetime import date

import pytest

from linkedin_mcp import scan as scan_mod
from linkedin_mcp.agent_config import Config

TODAY = date(2026, 10, 1)  # a Thursday
ME = "Misha Lubich"


def ev(speaker, date_, body):
    return {"speaker": speaker, "date": date_, "body": body}


REC = ev("Ana Recruiter", "SEP 20", "hi misha, ML role at Acme")
REF = ev(ME, "SEP 24", "hi ana, my friend Joe Heupler would be a fit")


@pytest.mark.parametrize(
    "label,want",
    [
        ("TODAY", date(2026, 10, 1)),
        ("Yesterday", date(2026, 9, 30)),
        ("MONDAY", date(2026, 9, 28)),
        ("THURSDAY", date(2026, 9, 24)),  # same weekday = a week ago, never today
        ("SEP 24", date(2026, 9, 24)),
        ("SEPT 24", date(2026, 9, 24)),
        ("DEC 30", date(2025, 12, 30)),  # future this year -> last year
        ("DEC 30, 2024", date(2024, 12, 30)),
        ("FEB 30", None),
        ("", None),
        ("nonsense", None),
    ],
)
def test_parse_heading(label, want):
    assert parse_ok(label) == want


def parse_ok(label):
    return scan_mod.parse_heading(label, TODAY)


def row(events, days=3):
    return scan_mod.followup_row("Ana", "u", events, ME, TODAY, days)


def test_candidate_when_referral_is_last_and_old():
    r = row([REC, REF])
    assert r and r["age_days"] == 7 and r["last_date"] == "2026-09-24" and r["url"] == "u"


def test_too_recent_is_skipped_and_boundary_included():
    assert row([REC, ev(ME, "TODAY", "joe heupler")]) is None
    assert row([REC, ev(ME, "MONDAY", "joe heupler")], days=3) is not None  # exactly 3 days
    assert row([REC, ev(ME, "TUESDAY", "joe heupler")], days=3) is None  # 2 days


def test_recruiter_last_or_empty_or_unknown_date_is_skipped():
    assert row([REF, ev("Ana", "SEP 25", "thanks")]) is None
    assert row([]) is None
    assert row([REC, ev(ME, "???", "joe heupler")]) is None


def test_no_joe_mention_is_skipped():
    assert row([REC, ev(ME, "SEP 24", "sure, call me")]) is None


def test_reply_after_referral_or_existing_followup_is_skipped():
    assert row([REC, REF, ev("Ana", "SEP 25", "ok"), ev(ME, "SEP 26", "thanks")]) is None
    assert row([REC, REF, ev(ME, "SEP 26", "following up on joe")]) is None


def test_reply_before_referral_is_fine_and_events_are_trimmed():
    many = [ev("Ana", "SEP 1", str(i)) for i in range(10)]
    r = row(many + [REF])
    assert r and len(r["events"]) == 6


def test_blank_self_name_never_matches():
    assert scan_mod.followup_row("A", "u", [REC, REF], "", TODAY) is None


class FakePage:
    """Two 'You:' threads and one other; clicking switches the open thread."""

    def __init__(self):
        self.open = None
        self.threads = {
            0: ("Ana", "You: hi", "u0", [REC, REF]),
            1: ("Bob", "Bob: hi", "u1", []),
            2: ("Cy", "You: ok", "u2", [REC, ev(ME, "SEP 24", "hello")]),
            3: ("Dee", "You sent an attachment", "u3", [REC, REF]),
        }

    def evaluate(self, port, js, host=None):
        if js == scan_mod._THREADS_JS:
            return json.dumps([{"i": i, "name": n, "preview": p} for i, (n, p, _, _) in self.threads.items()])
        if js.startswith("(" + scan_mod._OPEN_JS):
            was = self.open is not None and js.endswith(f"({self.open})")
            self.open = int(js.rsplit("(", 1)[1].rstrip(")"))
            return was
        if js == scan_mod._EVENTS_JS:
            if self.open is None:
                return json.dumps({"url": "x", "events": []})
            _, _, url, events = self.threads[self.open]
            return json.dumps({"url": url, "events": events})
        return True  # scroll


def test_find_followup_candidates_opens_only_you_threads(monkeypatch):
    page = FakePage()
    monkeypatch.setattr(scan_mod, "evaluate", page.evaluate)
    monkeypatch.setattr(scan_mod.time, "sleep", lambda _s: None)
    monkeypatch.setattr(scan_mod.messaging, "ensure_messaging", lambda port: {"ok": True})
    cfg = Config()
    cfg.self_name = "Misha"
    rows = scan_mod.find_followup_candidates(cfg, port=1, today=TODAY, scroll_rounds=1)
    assert [r["name"] for r in rows] == ["Ana", "Dee"]  # Dee: referral then resume attachment


def test_find_followup_candidates_refuses_when_messaging_not_ready(monkeypatch):
    monkeypatch.setattr(scan_mod.messaging, "ensure_messaging", lambda port: {"ready": False})
    with pytest.raises(scan_mod.ChromeError):
        scan_mod.find_followup_candidates(Config(), port=1)


def test_thread_that_never_loads_is_skipped(monkeypatch):
    page = FakePage()
    real = page.evaluate

    def stuck(port, js, host=None):
        if js == scan_mod._EVENTS_JS:
            return json.dumps({"url": "x", "events": []})
        return real(port, js, host)

    monkeypatch.setattr(scan_mod, "evaluate", stuck)
    monkeypatch.setattr(scan_mod.time, "sleep", lambda _s: None)
    monkeypatch.setattr(scan_mod.messaging, "ensure_messaging", lambda port: {"ok": True})
    cfg = Config()
    cfg.self_name = "Misha"
    assert scan_mod.find_followup_candidates(cfg, port=1, today=TODAY, scroll_rounds=1) == []


def test_open_tab_uses_put_and_wraps_errors(monkeypatch):
    import urllib.error

    from linkedin_mcp import cdp_session

    seen = {}

    class Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b'{"url": "https://www.linkedin.com/messaging/"}'

    def ok(req, timeout):
        seen["method"], seen["url"] = req.get_method(), req.full_url
        return Resp()

    monkeypatch.setattr(cdp_session.urllib.request, "urlopen", ok)
    assert cdp_session.open_tab(9222, "https://www.linkedin.com/messaging/")["url"].endswith("/messaging/")
    assert seen["method"] == "PUT" and seen["url"].startswith("http://127.0.0.1:9222/json/new?https://")

    def down(req, timeout):
        raise urllib.error.URLError("refused")

    monkeypatch.setattr(cdp_session.urllib.request, "urlopen", down)
    with pytest.raises(cdp_session.ChromeError):
        cdp_session.open_tab(9222, "https://x")


def _send_with_button(config, monkeypatch, states):
    """send_message against a page whose Send button reports `states` in order."""
    from linkedin_mcp import messaging

    seq = iter(states)

    def fake(ws_url, script):
        if "insertText" in script:
            return True
        if "location.href" in script:
            return "https://www.linkedin.com/messaging/"
        if "aria-disabled" in script:
            return next(seq, states[-1])
        if ".click(); return !!b" in script:
            return True
        return "delivered hi"

    monkeypatch.setattr(messaging, "evaluate_pinned", fake)
    monkeypatch.setattr(messaging.time, "sleep", lambda s: None)
    return messaging.send_message("hi", config, confirm=True, verify_attempts=1, verify_wait_seconds=0)


def test_send_waits_for_the_send_button_to_enable(config, monkeypatch):
    assert _send_with_button(config, monkeypatch, [False, False, True])["sent"] is True


def test_send_still_fails_loudly_when_the_button_never_enables(config, monkeypatch):
    with pytest.raises(scan_mod.ChromeError, match="send button is disabled"):
        _send_with_button(config, monkeypatch, [False])

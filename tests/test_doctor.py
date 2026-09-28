from __future__ import annotations

import linkedin_mcp.doctor as doctor_mod
from linkedin_mcp.doctor import ChromeError


def test_doctor_all_green(config, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(doctor_mod, "describe", lambda port: {"pid": 123})
    monkeypatch.setattr(doctor_mod, "pages", lambda port: [{"url": "https://www.linkedin.com/feed/"}])
    monkeypatch.setattr(
        doctor_mod,
        "filter_pages",
        lambda tabs, needle, limit: [{"url": "https://www.linkedin.com/feed/"}],
    )
    report = doctor_mod.check(config)
    assert report["ok"] is True
    names = {c["name"]: c["ok"] for c in report["checks"]}
    assert names["chrome cdp reachable"] is True
    assert names["linkedin.com tab open"] is True
    assert names["logged in (no /login tab)"] is True
    assert names["referral config"] is True


def test_doctor_missing_binaries(config, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: None)
    monkeypatch.setattr(doctor_mod, "describe", lambda port: (_ for _ in ()).throw(ChromeError("down")))
    report = doctor_mod.check(config)
    assert report["ok"] is False
    names = {c["name"]: c["ok"] for c in report["checks"]}
    assert names["own-chrome installed"] is False
    assert names["chrome cdp reachable"] is False


def test_doctor_cdp_down_short_circuits(config, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/x")
    monkeypatch.setattr(doctor_mod, "describe", lambda port: (_ for _ in ()).throw(ChromeError("no listener")))
    report = doctor_mod.check(config)
    assert report["ok"] is False
    assert len(report["checks"]) == 2  # stops right after the cdp check


def test_doctor_no_linkedin_tab(config, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/x")
    monkeypatch.setattr(doctor_mod, "describe", lambda port: {"pid": 1})
    monkeypatch.setattr(doctor_mod, "pages", lambda port: (_ for _ in ()).throw(ChromeError("nope")))
    monkeypatch.setattr(doctor_mod, "filter_pages", lambda *a, **k: [])
    report = doctor_mod.check(config)
    names = {c["name"]: c["ok"] for c in report["checks"]}
    assert names["linkedin.com tab open"] is False
    assert names["logged in (no /login tab)"] is True  # vacuously true, no tabs to be stuck on


def test_doctor_login_page_detected(config, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/x")
    monkeypatch.setattr(doctor_mod, "describe", lambda port: {"pid": 1})
    monkeypatch.setattr(doctor_mod, "pages", lambda port: [{"url": "https://www.linkedin.com/uas/login"}])
    monkeypatch.setattr(doctor_mod, "filter_pages", lambda *a, **k: [{"url": "https://www.linkedin.com/uas/login"}])
    report = doctor_mod.check(config)
    names = {c["name"]: c["ok"] for c in report["checks"]}
    assert names["logged in (no /login tab)"] is False
    assert report["ok"] is False


def test_doctor_referral_disabled_is_fine(disabled_config, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/x")
    monkeypatch.setattr(doctor_mod, "describe", lambda port: {"pid": 1})
    monkeypatch.setattr(doctor_mod, "pages", lambda port: [])
    monkeypatch.setattr(doctor_mod, "filter_pages", lambda *a, **k: [])
    report = doctor_mod.check(disabled_config)
    names = {c["name"]: c["ok"] for c in report["checks"]}
    assert names["referral config"] is True


def test_doctor_referral_enabled_but_incomplete(config, monkeypatch):
    config.referral.resume_path = ""
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/x")
    monkeypatch.setattr(doctor_mod, "describe", lambda port: {"pid": 1})
    monkeypatch.setattr(doctor_mod, "pages", lambda port: [])
    monkeypatch.setattr(doctor_mod, "filter_pages", lambda *a, **k: [])
    report = doctor_mod.check(config)
    names = {c["name"]: c["ok"] for c in report["checks"]}
    assert names["referral config"] is False
    assert report["ok"] is False

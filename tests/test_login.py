"""`linkedin login`: sign in the CDP Chrome from the macOS Keychain password.

Everything below the CDP/subprocess boundary is mocked; no real Chrome,
Keychain, or LinkedIn page is touched. The password must never appear in any
output, log, or error message.
"""

from __future__ import annotations

import json
import subprocess

import pytest
from typer.testing import CliRunner

import linkedin_mcp.core as core
import linkedin_mcp.login as login_mod
from linkedin_mcp.cdp_session import ChromeError
from linkedin_mcp.cli import app

runner = CliRunner()
PASSWORD = "s3cret-Pw!zz"
TAB = {"id": "t", "url": "https://www.linkedin.com/login", "title": "Sign In", "webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/page/t"}


class FakePage:
    """Scripted page: `states` is the sequence detect returns; every other
    script is recorded in `calls`."""

    def __init__(self, states, fail_on=None):
        self.states = list(states)
        self.calls = []
        self.fail_on = fail_on

    def evaluate(self, ws_url, expr):
        assert ws_url == TAB["webSocketDebuggerUrl"]
        tag = expr.split("*/")[0].lstrip("/* ").strip() if expr.startswith("/*") else "other"
        self.calls.append((tag, expr))
        if self.fail_on == tag:
            raise ChromeError("boom " + expr)  # message would leak the script
        if tag == "detect":
            state = self.states.pop(0) if len(self.states) > 1 else self.states[0]
            return json.dumps(state) if isinstance(state, dict) else json.dumps({"state": state})
        return True

    def tags(self):
        return [t for t, _ in self.calls]


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setattr(login_mod, "pages", lambda port: [TAB])
    monkeypatch.setattr(login_mod.time, "sleep", lambda s: None)
    monkeypatch.setattr(login_mod, "_POLL_SECONDS", 0.0)
    keychain = []

    def fake_run(cmd, **kw):
        keychain.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout=PASSWORD + "\n", stderr="")

    monkeypatch.setattr(login_mod.subprocess, "run", fake_run)

    def install(page):
        monkeypatch.setattr(login_mod, "evaluate_pinned", page.evaluate)
        return page

    install.keychain = keychain
    return install


def test_already_signed_in_does_nothing_and_never_reads_keychain(env):
    page = env(FakePage(["signed_in"]))
    out = login_mod.sign_in(9222)
    assert out["status"] == "already_signed_in"
    assert env.keychain == []
    assert page.tags() == ["detect"]


def test_login_form_fills_and_submits_with_keychain_password(env):
    page = env(FakePage(["login_form", "login_form", "signed_in"]))
    out = login_mod.sign_in(9222, account="a@b.co")
    assert out == {"status": "signed_in", "account": "a@b.co"}
    assert env.keychain == [["security", "find-internet-password", "-s", "linkedin.com", "-a", "a@b.co", "-w"]]
    fill = [e for t, e in page.calls if t == "fill"][0]
    assert PASSWORD in fill and "a@b.co" in fill
    assert "submit" in page.tags()


def test_default_account_is_michaelle(env):
    env(FakePage(["login_form", "signed_in"]))
    login_mod.sign_in(9222)
    assert env.keychain[0][5] == "michaelle.lubich@gmail.com"


def test_account_picker_chooses_another_account_never_google(env):
    page = env(FakePage(["account_picker", "login_form", "signed_in"]))
    login_mod.sign_in(9222)
    assert page.tags().index("other-account") < page.tags().index("fill")
    other = [e for t, e in page.calls if t == "other-account"][0].lower()
    assert "another account" in other
    submit = [e for t, e in page.calls if t == "submit"][0].lower()
    assert "google" in submit and "continue" in submit  # present only as an exclusion filter
    assert "continue as" not in other and "google" not in other


@pytest.mark.parametrize(
    "state,needle",
    [
        ({"state": "checkpoint"}, "checkpoint"),
        ({"state": "captcha"}, "captcha"),
        ({"state": "two_factor"}, "2fa"),
    ],
)
def test_checkpoint_captcha_2fa_stop_with_clear_message(env, state, needle):
    page = env(FakePage(["login_form", "login_form", state]))
    with pytest.raises(login_mod.LoginError) as exc:
        login_mod.sign_in(9222)
    assert needle in str(exc.value).lower()
    assert page.tags().count("fill") == 1  # one attempt, no retry


def test_wrong_password_stops_without_retry(env):
    page = env(FakePage(["login_form", "login_form", {"state": "login_form", "error": "That's not the right password."}]))
    with pytest.raises(login_mod.LoginError) as exc:
        login_mod.sign_in(9222)
    assert "password" in str(exc.value).lower()
    assert page.tags().count("fill") == 1 and page.tags().count("submit") == 1


def test_still_on_form_after_timeout_is_an_error_not_a_retry(env, monkeypatch):
    monkeypatch.setattr(login_mod, "_POLL_ATTEMPTS", 3)
    page = env(FakePage(["login_form"]))
    with pytest.raises(login_mod.LoginError):
        login_mod.sign_in(9222)
    assert page.tags().count("fill") == 1


def test_missing_keychain_entry_is_clear_error(env, monkeypatch):
    env(FakePage(["login_form"]))

    def fail(cmd, **kw):
        raise subprocess.CalledProcessError(44, cmd, stderr="The specified item could not be found")

    monkeypatch.setattr(login_mod.subprocess, "run", fail)
    with pytest.raises(login_mod.LoginError) as exc:
        login_mod.sign_in(9222, account="x@y.z")
    assert "x@y.z" in str(exc.value) and "keychain" in str(exc.value).lower()


def test_browser_error_never_leaks_the_password(env):
    env(FakePage(["login_form"], fail_on="fill"))
    with pytest.raises(login_mod.LoginError) as exc:
        login_mod.sign_in(9222)
    assert PASSWORD not in str(exc.value)
    assert exc.value.__cause__ is None and exc.value.__suppress_context__


def test_no_linkedin_tab_opens_login_page(env, monkeypatch):
    opened = []
    monkeypatch.setattr(login_mod, "pages", lambda port: [])
    monkeypatch.setattr(login_mod, "open_tab", lambda port, url: opened.append(url) or TAB)
    env(FakePage(["signed_in"]))
    login_mod.sign_in(9222)
    assert opened == ["https://www.linkedin.com/login"]


def test_cli_login_success_prints_no_password(env, monkeypatch, config, capsys):
    env(FakePage(["login_form", "signed_in"]))
    monkeypatch.setattr(core, "load_agent_config", lambda path=None: config)
    result = runner.invoke(app, ["login", "--account", "a@b.co", "--json"])
    assert result.exit_code == 0
    assert PASSWORD not in result.output
    assert json.loads(result.stdout)["status"] == "signed_in"


def test_cli_login_failure_exits_nonzero_without_password(env, monkeypatch, config):
    env(FakePage(["login_form", {"state": "captcha"}]))
    monkeypatch.setattr(core, "load_agent_config", lambda path=None: config)
    result = runner.invoke(app, ["login"])
    assert result.exit_code == 1
    assert PASSWORD not in result.output
    assert "captcha" in result.output.lower()


def test_login_help_short_and_long():
    for flag in ("-h", "--help"):
        assert runner.invoke(app, ["login", flag]).exit_code == 0

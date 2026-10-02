"""Sign the CDP Chrome in to LinkedIn using the macOS Keychain password.

One attempt, no retry loops: a checkpoint, captcha, 2FA prompt, wrong
password, or timeout is an error the human has to look at. The password is
read from the Keychain, handed to the page once, and never printed, logged,
or written anywhere. Browser errors are re-raised without their original
message (a failed evaluate() can echo the script, which holds the password).
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from collections.abc import Callable
from typing import Any

from own_chrome.cdp import ChromeError, open_tab, pages

from linkedin_mcp.cdp_session import evaluate_pinned
from linkedin_mcp.messages_actions import choose_linkedin_tab

JSON = dict[str, Any]  # JSON boundary: CDP evaluate results

DEFAULT_ACCOUNT = "michaelle.lubich@gmail.com"
LOGIN_URL = "https://www.linkedin.com/login"
_POLL_ATTEMPTS = 20
_POLL_SECONDS = 1.0


class LoginError(RuntimeError):
    """Sign-in did not complete; the message says why. Never contains the password."""


DETECT_JS = r"""/*detect*/ (() => {
  const url = location.href, text = (document.body && document.body.innerText || "").toLowerCase();
  const err = document.querySelector("#error-for-password, #error-for-username, .alert-content, .form__label--error");
  const error = err && err.innerText.trim() && getComputedStyle(err).display !== "none" ? err.innerText.trim() : "";
  let state = "unknown";
  if (/captcha|recaptcha/.test(url) || document.querySelector("iframe[src*='captcha'], #captcha-internal") || text.includes("security verification")) state = "captcha";
  else if (/two-step|two_step|2fa|\/checkpoint\/(lg|challenge)/.test(url) && /verification code|two-step/.test(text)) state = "two_factor";
  else if (/checkpoint|challenge/.test(url)) state = "checkpoint";
  else if (document.querySelector("#username") && document.querySelector("#password")) state = "login_form";
  else if ([...document.querySelectorAll("button, a")].some(e => /sign in using another account/i.test(e.innerText))) state = "account_picker";
  else if (!/\/login|\/uas\/|authwall|\/signup/.test(url) && document.querySelector("#global-nav, .global-nav, nav.global-nav")) state = "signed_in";
  return JSON.stringify({state, url, error});
})()"""

OTHER_ACCOUNT_JS = r"""/*other-account*/ (() => {
  const el = [...document.querySelectorAll("button, a")].find(e => /sign in using another account/i.test(e.innerText));
  if (!el) return false; el.click(); return true;
})()"""

SUBMIT_JS = r"""/*submit*/ (() => {
  const bad = /google|apple|continue as|join now/i;
  const btn = [...document.querySelectorAll("button[type=submit], button[data-litms-control-urn='login-submit']")]
    .find(b => !bad.test(b.innerText + " " + (b.getAttribute("aria-label") || "")));
  if (!btn) return false; btn.click(); return true;
})()"""


def _fill_js(account: str, password: str) -> str:
    return (
        "/*fill*/ ((u, p) => {"
        "const set = (el, v) => {"
        "const d = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value');"
        "d.set.call(el, v); el.dispatchEvent(new Event('input', {bubbles: true}));"
        "el.dispatchEvent(new Event('change', {bubbles: true}));};"
        "const user = document.querySelector('#username'), pass = document.querySelector('#password');"
        "if (!user || !pass) return false; set(user, u); set(pass, p); return true;"
        f"}})({json.dumps(account)}, {json.dumps(password)})"
    )


def get_password(account: str) -> str:
    """Password from the macOS Keychain (`security find-internet-password`)."""
    try:
        done = subprocess.run(
            ["security", "find-internet-password", "-s", "linkedin.com", "-a", account, "-w"],
            capture_output=True,
            text=True,
            check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        raise LoginError(f"no linkedin.com password in the macOS Keychain for {account}") from None
    password = done.stdout.rstrip("\n")
    if not password:
        raise LoginError(f"empty linkedin.com Keychain password for {account}")
    return password


def _detect(ws_url: str) -> JSON:
    try:
        raw = evaluate_pinned(ws_url, DETECT_JS)
    except ChromeError:
        raise LoginError("browser error while reading the sign-in page") from None
    return json.loads(raw) if isinstance(raw, str) else dict(raw or {})


def _run(ws_url: str, script: str, what: str) -> bool:
    try:
        return bool(evaluate_pinned(ws_url, script))
    except ChromeError:
        raise LoginError(f"browser error while {what}") from None


def _stop_if_blocked(info: JSON) -> None:
    state = info.get("state")
    if state == "captcha":
        raise LoginError("LinkedIn showed a captcha; solve it by hand, nothing was retried")
    if state == "two_factor":
        raise LoginError("LinkedIn asked for a 2FA code; enter it by hand, nothing was retried")
    if state == "checkpoint":
        raise LoginError("LinkedIn showed a security checkpoint; clear it by hand, nothing was retried")


def _wait(ws_url: str, done: Callable[[JSON], bool]) -> JSON:
    info: JSON = {}
    for _ in range(_POLL_ATTEMPTS):
        info = _detect(ws_url)
        _stop_if_blocked(info)
        if done(info):
            return info
        time.sleep(_POLL_SECONDS)
    return info


def sign_in(port: int, account: str | None = None) -> JSON:
    account = account or os.environ.get("LINKEDIN_AGENT_LOGIN_EMAIL") or DEFAULT_ACCOUNT
    tab = choose_linkedin_tab(pages(port)) or open_tab(port, LOGIN_URL)
    ws_url = str(tab.get("webSocketDebuggerUrl") or "")
    if not ws_url:
        raise LoginError("LinkedIn tab has no CDP websocket")

    info = _detect(ws_url)
    _stop_if_blocked(info)
    if info.get("state") == "signed_in":
        return {"status": "already_signed_in", "account": account}

    if info.get("state") == "account_picker":
        if not _run(ws_url, OTHER_ACCOUNT_JS, "choosing 'Sign in using another account'"):
            raise LoginError("account picker has no 'Sign in using another account' button")
        info = _wait(ws_url, lambda i: i.get("state") == "login_form")
    if info.get("state") != "login_form":
        raise LoginError(f"not on a LinkedIn sign-in form (state: {info.get('state')})")

    password = get_password(account)
    if not _run(ws_url, _fill_js(account, password), "filling the sign-in form"):
        raise LoginError("sign-in form fields not found")
    del password
    if not _run(ws_url, SUBMIT_JS, "submitting the sign-in form"):
        raise LoginError("sign-in submit button not found")

    info = _wait(ws_url, lambda i: i.get("state") == "signed_in" or bool(i.get("error")))
    if info.get("state") == "signed_in":
        return {"status": "signed_in", "account": account}
    if info.get("error"):
        raise LoginError(f"LinkedIn rejected the sign-in (wrong password?): {info['error']}")
    raise LoginError("sign-in did not complete in time; still on the sign-in form")

"""Drive LinkedIn Messaging in the already-open Chrome, over CDP.

open_thread/read_thread/send_message: ported from the linkedin-messaging
SKILL.md workflow and linkedin-refer/cli.js, generalized to plain functions
with an explicit `confirm` flag instead of Playwright + a hardcoded resume
path. Unchanged here -- referral.py and the existing `messages read|send`
CLI/MCP surface depend on their exact signatures and return shapes.

ensure_messaging/linkedin_tab/list_threads/select_thread/popups/api_key/
complete: absorbed from own-chrome's `li` (tag pre-li-move, commit
97c1d9a) -- own-chrome is dropping that messaging CLI, and per the
project's own_chrome-import contract, this module now owns tab selection,
thread listing/selection, and dialog handling directly on
own_chrome.cdp's evaluate/navigate/open_tab/pages, instead of shelling out
to `li`. The JS/selector logic in messages_actions.py is unchanged from
`li`'s.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

from own_chrome.cdp import ChromeError, evaluate, navigate, open_tab, pages

from linkedin_mcp.agent_config import Config
from linkedin_mcp.cdp_session import set_file_input
from linkedin_mcp.governor import Governor
from linkedin_mcp.messages_actions import act_expression, choose_linkedin_tab, choose_popup_action, thread_query_expression

TAB = "linkedin.com"
MESSAGING = "https://www.linkedin.com/messaging/"
COMPOSE_SELECTOR = ".msg-form__contenteditable[contenteditable='true']"
SEND_BUTTON_SELECTOR = "button.msg-form__send-button"
FILE_INPUT_SELECTOR = "input[type='file']"
# Same keychain entry `li` used (service "openai", account "li") -- kept as
# is so a machine already configured for `li`/linkedin-agent keeps working.
KEYCHAIN_SERVICE = "openai"
KEYCHAIN_ACCOUNT = "li"


class SendNotConfirmedError(RuntimeError):
    """Raised when a send/publish call is made without confirm=True."""


def open_thread(url: str, port: int) -> None:
    navigate(port, url, TAB)


def read_thread(port: int, limit: int = 40) -> dict:
    raw = evaluate(
        port,
        "JSON.stringify({"
        "url: location.href,"
        "bodies: [...document.querySelectorAll('.msg-s-event-listitem__body')].map(e=>e.innerText.trim()),"
        "speakers: [...document.querySelectorAll('.msg-s-message-group__name')].map(e=>e.innerText.trim())"
        f"}})",
        TAB,
    )
    data = json.loads(raw) if isinstance(raw, str) else raw
    limit = max(limit, 0)
    data["bodies"] = (data.get("bodies") or [])[-limit:] if limit else data.get("bodies") or []
    return data


def _fill_compose(port: int, text: str) -> None:
    script = (
        "((text) => {"
        f"const box = document.querySelector({json.dumps(COMPOSE_SELECTOR)});"
        "if (!box) return false;"
        "box.focus();"
        "document.execCommand('selectAll', false, null);"
        "document.execCommand('delete', false, null);"
        "document.execCommand('insertText', false, text);"
        "return true;"
        "})(" + json.dumps(text) + ")"
    )
    ok = evaluate(port, script, TAB)
    if not ok:
        raise ChromeError("compose box not found")


def _send_button_enabled(port: int) -> bool:
    script = (
        f"(() => {{const b = document.querySelector({json.dumps(SEND_BUTTON_SELECTOR)});"
        "return !!b && b.getAttribute('disabled') === null;})()"
    )
    return bool(evaluate(port, script, TAB))


def _click_send(port: int) -> None:
    script = (
        f"(() => {{const b = document.querySelector({json.dumps(SEND_BUTTON_SELECTOR)}); if (b) b.click(); return !!b;}})()"
    )
    evaluate(port, script, TAB)


def _last_message_text(port: int) -> str:
    script = (
        "(() => {const items = document.querySelectorAll('.msg-s-event-listitem');"
        "const last = items[items.length - 1]; return last ? last.innerText : '';})()"
    )
    return evaluate(port, script, TAB) or ""


def _compose_is_empty(port: int) -> bool:
    script = (
        f"(() => {{const b = document.querySelector({json.dumps(COMPOSE_SELECTOR)}); return !b || b.innerText.trim().length < 5;}})()"
    )
    return bool(evaluate(port, script, TAB))


def send_message(
    text: str,
    config: Config,
    confirm: bool,
    attachment_path: str | None = None,
    attachment_name_hint: str | None = None,
    port: int | None = None,
    verify_attempts: int = 8,
    verify_wait_seconds: float = 0.75,
    attach_wait_seconds: float = 1.5,
    governor: Governor | None = None,
    target: str = "",
    action: str = "message",
) -> dict:
    """Fill the compose box (and optionally attach a file), then send only
    when confirm=True. Returns a proof dict describing what happened.

    governor/target/action: when both governor and target are given, this
    call is paced and deduped through Governor.check()/.record() (see
    governor.py) -- refuses a repeat send to the same target and enforces a
    rolling budget. Without a target there is no identity to dedupe or budget
    against, so the check is skipped (that's the caller's call to make for a
    one-off, explicitly-approved reply; the bulk/loop-shaped callers --
    send_referral_for_candidate, publish_post -- always pass one).
    """
    cdp_port = port if port is not None else config.cdp_port
    _fill_compose(cdp_port, text)

    attached = False
    if attachment_path:
        attached = set_file_input(cdp_port, FILE_INPUT_SELECTOR, attachment_path, TAB)
        if not attached:
            raise ChromeError("no file input found; not sending")
        time.sleep(attach_wait_seconds)

    if not confirm:
        raise SendNotConfirmedError("send_message requires confirm=True; nothing was sent")

    if governor is not None and target:
        governor.check(action, target)

    if not _send_button_enabled(cdp_port):
        raise ChromeError("send button is disabled; not sending")
    _click_send(cdp_port)

    proof = {"last_has_hint": False, "compose_empty": False}
    hint = (attachment_name_hint or "").lower()
    for _ in range(verify_attempts):
        time.sleep(verify_wait_seconds)
        last_text = _last_message_text(cdp_port).lower()
        proof["compose_empty"] = _compose_is_empty(cdp_port)
        proof["last_has_hint"] = (hint in last_text) if hint else bool(last_text)
        if proof["last_has_hint"] and proof["compose_empty"]:
            break
    proof["attached"] = attached
    proof["sent"] = bool(proof["last_has_hint"] and proof["compose_empty"])
    if governor is not None and target and proof["sent"]:
        governor.record(action, target)
    return proof


# ---- tab selection / opening messaging ------------------------------------


def linkedin_tab(port: int) -> dict:
    chosen = choose_linkedin_tab(pages(port))
    if chosen is None:
        raise ChromeError("No open tab with hostname 'linkedin.com' (or a subdomain of it)")
    return chosen


def _eval_on_linkedin_tab(port: int, expression: str) -> object:
    tab = linkedin_tab(port)
    return evaluate(port, expression, url_contains=tab["url"])


def _as_dict(raw: object) -> dict:
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str):
        raise ChromeError("page did not return JSON")
    return json.loads(raw)


def ensure_messaging(port: int) -> dict:
    """Open messaging in the attached Chrome. Does not start a browser.

    An existing messaging tab wins over a feed tab. The feed tab is only
    navigated when it is the only LinkedIn tab.
    """
    try:
        tab = linkedin_tab(port)
    except ChromeError:
        opened = open_tab(port, MESSAGING)
        info = {"action": "open", "opened": "tab", "ok": True, "url": opened.get("url") or MESSAGING, "title": opened.get("title") or ""}
        return _finish_open(port, info)
    url = tab.get("url") or ""
    if url.rstrip("/").endswith("/messaging") or "/messaging/" in url:
        return {"action": "open", "opened": "already", "ok": True, "url": url, "title": tab.get("title") or ""}
    navigate(port, MESSAGING, host=TAB)
    info = {"action": "open", "opened": "navigated", "ok": True, "url": MESSAGING, "title": ""}
    return _finish_open(port, info)


def _finish_open(port: int, info: dict) -> dict:
    """After opening/navigating to messaging, wait for the thread list to
    render before returning -- callers (list_threads/select_thread) need it
    up before their own evaluate() calls. Evaluates against the tab we just
    opened/navigated (by URL), not a fresh pages()/choose_linkedin_tab
    lookup: the tab may not show up in a same-tick pages() call yet."""
    deadline = time.time() + 1.0
    last_ready: dict = {}
    while time.time() < deadline:
        raw = evaluate(port, "(" + _READY_JS + ")()", url_contains=info["url"])
        last_ready = _as_dict(raw)
        if last_ready.get("ready"):
            break
        time.sleep(0.1)
    info["url"] = last_ready.get("url") or info["url"]
    info["title"] = last_ready.get("title") or info.get("title") or ""
    info["ready"] = bool(last_ready.get("ready"))
    return info


_READY_JS = r"""(() => {
  const onMsg = location.pathname.indexOf("/messaging") === 0;
  const list = document.querySelector(
    ".msg-conversation-listitem, .msg-conversation-card, .msg-conversations-container"
  );
  return {ready: !!(onMsg && list), url: location.href, title: document.title};
})"""


# ---- thread listing / selection --------------------------------------------


def list_threads(port: int, kind: str = "threads", needle: str = "", limit: int = 20, no_navigate: bool = False) -> dict:
    """List threads (`kind="threads"`) or only unread ones (`kind="unread"`).
    Prefers an already-open messaging tab; navigates a lone feed tab there
    first unless no_navigate=True."""
    if not no_navigate:
        ensure_messaging(port)
    raw = _eval_on_linkedin_tab(port, thread_query_expression(kind, needle, limit))
    payload = _as_dict(raw)
    if kind == "unread":
        payload["threads"] = [t for t in (payload.get("threads") or []) if t.get("unread")]
    return payload


def select_thread(port: int, name: str) -> dict:
    """Open the one thread whose name contains `name`. `ambiguous=True` and
    no click when several match; `ok=False` when none match."""
    name = (name or "").strip()
    if not name:
        raise ValueError("name is required")
    ensure_messaging(port)
    raw = _eval_on_linkedin_tab(port, act_expression("select", name, "", False))
    return _as_dict(raw)


# ---- dialog popups ----------------------------------------------------------


def popups(port: int, apply: bool = False, policy: dict | None = None) -> dict:
    """Report the open LinkedIn dialog; click the policy-chosen button only
    when apply=True. Default policy declines "share your contact info"."""
    policy = policy or {"share_contact": "decline"}
    raw = _eval_on_linkedin_tab(
        port,
        """(() => {
          const dialog = document.querySelector('[role="dialog"]');
          if (!dialog) return JSON.stringify({title:'', buttons:[]});
          const title = ((dialog.querySelector('h1, h2') || dialog).innerText || '').split('\\n')[0];
          const buttons = [...dialog.querySelectorAll('button')].map((b) => b.innerText.trim()).filter(Boolean);
          return JSON.stringify({title, buttons});
        })()""",
    )
    dialog = _as_dict(raw)
    action = choose_popup_action(dialog.get("title") or "", dialog.get("buttons") or [], policy)
    dialog["action"] = action
    dialog["applied"] = False
    if apply and action:
        clicked = _eval_on_linkedin_tab(
            port,
            "((label) => { const dialog = document.querySelector('[role=\"dialog\"]');"
            " if (!dialog) return false;"
            " const btn = [...dialog.querySelectorAll('button')].find((b) => b.innerText.trim() === label);"
            " if (!btn) return false; btn.click(); return true; })(" + json.dumps(action) + ")",
        )
        dialog["applied"] = bool(clicked)
    return dialog


# ---- OpenAI boundary (classify-then-draft workflow) ------------------------


def api_key() -> str:
    env = os.environ.get("OPENAI_API_KEY", "").strip()
    if env:
        return env
    try:
        out = subprocess.check_output(
            ["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-a", KEYCHAIN_ACCOUNT, "-w"],
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        raise ChromeError("OpenAI key is not in the environment or keychain (service openai, account li)") from exc
    return out.strip()


def complete(model: str, messages: list[dict]) -> str:
    body = json.dumps({"model": model, "messages": messages}).encode()
    request = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=body,
        headers={"Authorization": f"Bearer {api_key()}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:300]
        raise ChromeError(f"OpenAI {exc.code}: {detail}") from exc
    return payload["choices"][0]["message"]["content"]


def workflow_run(spec_path: str, text: str = "", port: int | None = None) -> dict:
    """Classify the open thread (or explicit `text`) and draft a reply.
    Never sends -- `sent` is always False."""
    from linkedin_mcp.messages_actions import run_workflow

    spec = json.loads(Path(spec_path).read_text())
    if not text and port is not None:
        raw = read_thread(port, limit=4)
        text = "\n\n".join(raw.get("bodies") or [])
    return run_workflow(spec, text, complete, dry_run=True)

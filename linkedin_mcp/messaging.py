"""Drive LinkedIn Messaging in the already-open Chrome, over CDP.

Ported from the linkedin-messaging SKILL.md workflow and linkedin-refer/cli.js,
generalized to plain functions with an explicit `confirm_send` flag instead of
Playwright + a hardcoded resume path.
"""

from __future__ import annotations

import json
import time

from own_chrome.cdp import ChromeError, evaluate, navigate

from linkedin_mcp.cdp_session import set_file_input
from linkedin_mcp.agent_config import Config
from linkedin_mcp.governor import Governor

TAB = "linkedin.com"
COMPOSE_SELECTOR = ".msg-form__contenteditable[contenteditable='true']"
SEND_BUTTON_SELECTOR = "button.msg-form__send-button"
FILE_INPUT_SELECTOR = "input[type='file']"


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

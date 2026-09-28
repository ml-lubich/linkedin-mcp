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
import re
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

from own_chrome.cdp import ChromeError, evaluate, navigate, open_tab, pages

from linkedin_mcp.agent_config import Config
from linkedin_mcp.cdp_session import set_file_input
from linkedin_mcp.governor import Governor
from linkedin_mcp.messages_actions import (
    act_expression,
    choose_linkedin_tab,
    choose_popup_action,
    match_thread,
    thread_query_expression,
    validate_linkedin_url,
)

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
    """Raised when a send/publish call is made without confirm=True.

    `preview` describes what would have happened had confirm been True --
    in particular the resolved attachment path, if any -- without ever
    touching the DOM file input or the browser's Send button.
    """

    def __init__(self, message: str, preview: dict | None = None) -> None:
        super().__init__(message)
        self.preview = preview or {}


def _allowed_attachment_dir(config: Config) -> Path:
    if config.attachments_dir:
        return Path(config.attachments_dir).expanduser().resolve()
    if config.referral.resume_path:
        return Path(config.referral.resume_path).expanduser().resolve().parent
    return (Path.home() / "Documents").resolve()


def _validate_attachment_path(raw_path: str, config: Config) -> Path:
    """Resolve `raw_path` (following symlinks) and require the real file to
    live inside the configured attachments directory. Rejects anything
    missing, not a regular file, or that resolves outside the allowlist --
    including a symlink whose target escapes it."""
    allowed_dir = _allowed_attachment_dir(config)
    candidate = Path(raw_path).expanduser()
    try:
        resolved = candidate.resolve(strict=True)
    except FileNotFoundError as exc:
        raise ValueError(f"attachment not found: {raw_path}") from exc
    if not resolved.is_file():
        raise ValueError(f"attachment is not a regular file: {raw_path}")
    if resolved != allowed_dir and allowed_dir not in resolved.parents:
        raise ValueError(
            f"attachment {resolved} is outside the allowed attachments directory {allowed_dir}; "
            "set attachments_dir in config.toml to allow it"
        )
    return resolved


def open_thread(url: str, port: int) -> None:
    """Navigate to `url`. Rejects anything that is not an https URL on
    linkedin.com (or a subdomain) before ever calling navigate()."""
    validate_linkedin_url(url)
    navigate(port, url, host=TAB)


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


def _fill_compose(port: int, text: str, url_contains: str) -> None:
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
    ok = evaluate(port, script, url_contains=url_contains)
    if not ok:
        raise ChromeError("compose box not found")


def _send_button_enabled(port: int, url_contains: str) -> bool:
    script = (
        f"(() => {{const b = document.querySelector({json.dumps(SEND_BUTTON_SELECTOR)});"
        "return !!b && b.getAttribute('disabled') === null"
        " && b.getAttribute('aria-disabled') !== 'true';})()"
    )
    return bool(evaluate(port, script, url_contains=url_contains))


def _click_send(port: int, url_contains: str) -> None:
    script = (
        f"(() => {{const b = document.querySelector({json.dumps(SEND_BUTTON_SELECTOR)}); if (b) b.click(); return !!b;}})()"
    )
    evaluate(port, script, url_contains=url_contains)


def _normalize_for_comparison(text: str) -> str:
    """Collapse whitespace runs and strip, case-insensitively -- LinkedIn's
    rendered innerText can differ from the raw sent text in exactly these
    ways (extra/missing blank lines, trailing spaces), which would
    otherwise make a real send look like a false "not sent"."""
    return re.sub(r"\s+", " ", text).strip().lower()


def _last_message_text(port: int, url_contains: str) -> str:
    script = (
        "(() => {const items = document.querySelectorAll('.msg-s-event-listitem');"
        "const last = items[items.length - 1]; return last ? last.innerText : '';})()"
    )
    return evaluate(port, script, url_contains=url_contains) or ""


def _compose_is_empty(port: int, url_contains: str) -> bool:
    # Exactly zero, not "under some small threshold" -- a short sent message
    # like "ok" (2 chars) left un-cleared by a failed send must read as
    # non-empty, not slip under a length-5 cutoff as if it were whitespace.
    script = (
        f"(() => {{const b = document.querySelector({json.dumps(COMPOSE_SELECTOR)}); return !b || b.innerText.trim().length === 0;}})()"
    )
    return bool(evaluate(port, script, url_contains=url_contains))


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
    dedupe: bool = True,
) -> dict:
    """Fill the compose box (and optionally attach a file), then send only
    when confirm=True. Returns a proof dict describing what happened.

    governor/target/action: when both governor and target are given, this
    call is paced through the governor's rolling budget. Without a target
    there is no identity to pace against, so the check is skipped (that's
    the caller's call to make for a one-off, explicitly-approved reply; the
    bulk/loop-shaped callers -- send_referral_for_candidate, publish_post --
    always pass one).

    dedupe: when True (default), a repeat send to the same target is refused
    permanently (Governor.check()/.record()) -- for an explicit, stable
    `target` identity where a genuine repeat is a bug (referral resume,
    a post's own text hash). When False, only the rolling budget applies
    (Governor.check_budget()/.record_paced()) -- for `to`-a-person-by-name
    sends, where replying to the same person again next week is normal and
    must not be permanently blocked by the first confirmed send.
    """
    cdp_port = port if port is not None else config.cdp_port
    # Resolved ONCE and pinned for every remaining step (fill, attach, send,
    # verify) -- selecting a thread and then typing/sending must never target
    # different tabs (see linkedin_tab's docstring and test_pinned_tab_targeting.py).
    target_url = linkedin_tab(cdp_port)["url"]

    validated_attachment: Path | None = None
    if attachment_path:
        # Validated before we touch the DOM at all, confirmed or not: a bad
        # path (missing, not a file, outside the allowlist) is a hard error
        # either way, never a silent no-op.
        validated_attachment = _validate_attachment_path(attachment_path, config)

    _fill_compose(cdp_port, text, target_url)

    if not confirm:
        raise SendNotConfirmedError(
            "send_message requires confirm=True; nothing was sent"
            + (f" (would attach: {validated_attachment})" if validated_attachment else ""),
            preview={
                "would_attach": str(validated_attachment) if validated_attachment else None,
                "compose_filled": True,
                "sent": False,
            },
        )

    attached = False
    if validated_attachment is not None:
        attached = set_file_input(cdp_port, FILE_INPUT_SELECTOR, str(validated_attachment), url_contains=target_url)
        if not attached:
            raise ChromeError("no file input found; not sending")
        time.sleep(attach_wait_seconds)

    if governor is not None and target:
        if dedupe:
            governor.check(action, target)
        else:
            governor.check_budget(action)

    if not _send_button_enabled(cdp_port, target_url):
        raise ChromeError("send button is disabled; not sending")
    _click_send(cdp_port, target_url)

    # Record right after the confirmed click, not gated on verification
    # succeeding below: the click already happened, so a retry from here on
    # risks an actual duplicate send even if verification reports a false
    # "not sent" (rendering differences, a slow DOM update, ...). Whether
    # verification itself succeeded is still reported separately as
    # proof["sent"].
    if governor is not None and target:
        if dedupe:
            governor.record(action, target)
        else:
            governor.record_paced(action)

    proof = {"last_has_hint": False, "compose_empty": False}
    # Without an attachment, verify against the text that was actually sent
    # -- "any non-empty last message" would also pass for a stale, unrelated
    # older message that was already in the thread before this call.
    # Whitespace is normalized on both sides: LinkedIn's rendered innerText
    # can collapse/add whitespace runs differently than the raw sent text
    # (multi-line messages especially), which would otherwise read as a
    # false "not sent" for a message that really did go out.
    hint = _normalize_for_comparison(attachment_name_hint or text)
    for _ in range(verify_attempts):
        time.sleep(verify_wait_seconds)
        last_text = _normalize_for_comparison(_last_message_text(cdp_port, target_url))
        proof["compose_empty"] = _compose_is_empty(cdp_port, target_url)
        proof["last_has_hint"] = (hint in last_text) if hint else bool(last_text)
        if proof["last_has_hint"] and proof["compose_empty"]:
            break
    proof["attached"] = attached
    proof["sent"] = bool(proof["last_has_hint"] and proof["compose_empty"])
    return proof


# ---- tab selection / opening messaging ------------------------------------


def linkedin_tab(port: int) -> dict:
    """Resolve the ONE tab every step of a messaging operation (list, select,
    read, fill, attach, send, verify) must stay pinned to: choose_linkedin_tab's
    host-validated, messaging-preferring choice -- re-checked here so no
    OTHER open tab's URL contains it as a substring. own_chrome.cdp's
    url_contains re-resolves by plain substring on every call, with no
    hostname check, so a tab crafted to embed our target URL (e.g.
    https://evil.tld/#https://www.linkedin.com/messaging/) could otherwise
    be silently picked up by that later re-resolution instead of the tab we
    actually validated here."""
    tabs = pages(port)
    chosen = choose_linkedin_tab(tabs)
    if chosen is None:
        raise ChromeError("No open tab with hostname 'linkedin.com' (or a subdomain of it)")
    target_url = chosen.get("url") or ""
    collisions = [t for t in tabs if t is not chosen and target_url and target_url in (t.get("url") or "")]
    if collisions:
        raise ChromeError(
            f"refusing to target {target_url!r}: another open tab's URL also contains it "
            f"({[t.get('url') for t in collisions]})"
        )
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
        info = ensure_messaging(port)
        if not info.get("ready", True):
            raise ChromeError(f"messaging tab not ready ({info})")
    raw = _eval_on_linkedin_tab(port, thread_query_expression(kind, needle, limit))
    payload = _as_dict(raw)
    threads = payload.get("threads") or []
    if kind == "unread":
        threads = [t for t in threads if t.get("unread")]
    payload["threads"] = threads[: max(limit, 0)] if limit else threads
    return payload


def select_thread(port: int, name: str) -> dict:
    """Open the thread whose name matches `name`. Matching happens in Python
    (match_thread: exact-name preferred over substring, deduped by href, not
    display name) against a fresh thread listing, then the page clicks the
    exact href it was told to -- never picks a thread the page itself
    disambiguated by a substring match. `ambiguous=True` and no click when
    several match; `ok=False` when none match."""
    name = (name or "").strip()
    if not name:
        raise ValueError("name is required")
    info = ensure_messaging(port)
    if not info.get("ready", True):
        raise ChromeError(f"messaging tab not ready ({info})")
    listing = _as_dict(_eval_on_linkedin_tab(port, thread_query_expression("threads", "", 500)))
    decision = match_thread(listing.get("threads") or [], name)
    if not decision["ok"]:
        return {
            "action": "select",
            "ok": False,
            "sent": False,
            "matched": "",
            "chars": 0,
            "ambiguous": decision["ambiguous"],
            "matches": [m.get("name", "") for m in decision["matches"]],
        }
    raw = _eval_on_linkedin_tab(
        port, act_expression("select", decision["matched_name"], "", False, href=decision["matched_href"])
    )
    result = _as_dict(raw)
    # The href Python already disambiguated with -- callers (scan.py) use it
    # to verify the opened thread is actually this one before trusting a read.
    result["href"] = decision["matched_href"]
    return result


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
    return run_workflow(spec, text, complete)

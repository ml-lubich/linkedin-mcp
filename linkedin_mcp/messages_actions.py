"""Deterministic LinkedIn messaging page actions.

Pure functions: they build the JavaScript messaging.py runs in the attached
Chrome tab, and the classify/draft routing logic. They do not open a socket,
launch a browser, or send mail.

Ported from own-chrome's actions.py/popups.py/intent.py (tag pre-li-move,
commit 97c1d9a) -- own-chrome is dropping its `li` CLI and this package
absorbs the messaging surface it drove. linkedin_mcp may import only
own_chrome.cdp (see tests/test_own_chrome_import_boundary.py); everything
else `li` depended on lives here instead.
"""

from __future__ import annotations

import json
import re
import urllib.parse
from typing import Callable

# ---- command catalog (for `messages commands --json`) --------------------

COMMANDS: tuple[dict[str, object], ...] = (
    {"name": "open", "sends": False, "summary": "Open LinkedIn messaging in the attached Chrome."},
    {"name": "threads", "sends": False, "summary": "List messaging threads (optionally --unread, --filter, --limit)."},
    {"name": "select", "sends": False, "summary": "Open the one thread whose name contains the argument. Refuses if several match."},
    {"name": "read", "sends": False, "summary": "Print the last lines of the open thread."},
    {"name": "send", "sends": True, "summary": "Type text (optionally selecting a thread by --to first). Sends only with --confirm."},
    {"name": "popups", "sends": False, "summary": "Report the open dialog. --apply clicks the configured button."},
    {"name": "workflow", "sends": False, "summary": "Classify the open thread and draft a reply. Never sends."},
    {"name": "commands", "sends": False, "summary": "List these commands."},
)

# ---- tab selection ---------------------------------------------------------


def _linkedin_host(url: str) -> bool:
    try:
        host = (urllib.parse.urlparse(url).hostname or "").lower()
    except ValueError:
        return False
    return host == "linkedin.com" or host.endswith(".linkedin.com")


def on_messaging(url: str) -> bool:
    try:
        parsed = urllib.parse.urlparse(url)
    except ValueError:
        return False
    host = (parsed.hostname or "").lower()
    if host != "linkedin.com" and not host.endswith(".linkedin.com"):
        return False
    return parsed.path.startswith("/messaging")


def choose_linkedin_tab(tabs: list[dict]) -> dict | None:
    """Prefer an open messaging tab. A feed tab listed first must not win."""
    linkedin = [tab for tab in tabs if _linkedin_host(str(tab.get("url") or ""))]
    messaging = [tab for tab in linkedin if on_messaging(str(tab.get("url") or ""))]
    if messaging:
        return messaging[0]
    if linkedin:
        return linkedin[0]
    return None


# ---- page JS builders -------------------------------------------------------

_THREAD_QUERY_JS = r"""
(opts) => {
  const q = (opts.filter || "").toLowerCase();
  const limit = opts.limit || 20;
  const nameOf = (el) => {
    const node = el.querySelector(
      ".msg-conversation-listitem__participant-names, .msg-conversation-card__participant-names"
    );
    return (node && node.innerText || "").trim();
  };
  const seen = new Set();
  const threads = [];
  for (const el of document.querySelectorAll(".msg-conversation-listitem, .msg-conversation-card")) {
    const name = nameOf(el);
    if (!name || seen.has(name)) continue;
    seen.add(name);
    const previewNode = el.querySelector(".msg-conversation-card__message-snippet, .msg-conversation-listitem__message-snippet");
    const unread = /unread/i.test(el.className) || !!el.querySelector(".notification-badge, .msg-conversation-card__unread-count");
    if (q && !name.toLowerCase().includes(q) && !(previewNode && previewNode.innerText.toLowerCase().includes(q))) continue;
    threads.push({
      name,
      preview: previewNode ? previewNode.innerText.trim() : "",
      unread
    });
    if (threads.length >= limit) break;
  }
  const lines = [...document.querySelectorAll(".msg-s-event-listitem")]
    .map((n) => n.innerText.trim())
    .filter(Boolean)
    .slice(-limit);
  return {
    query: opts.query,
    url: location.href,
    title: document.title,
    threads: opts.query === "unread" ? threads.filter((t) => t.unread) : threads,
    lines: opts.query === "read" ? lines : []
  };
}
"""

READY_JS = r"""async () => {
  const deadline = Date.now() + 1000;
  while (Date.now() < deadline) {
    const onMsg = location.pathname.indexOf("/messaging") === 0;
    const list = document.querySelector(
      ".msg-conversation-listitem, .msg-conversation-card, .msg-conversations-container"
    );
    if (onMsg && list) return {ready: true, url: location.href, title: document.title};
    await new Promise((r) => setTimeout(r, 100));
  }
  return {ready: false, url: location.href, title: document.title};
}"""

# Click happens only after the single-match check. Several matches return first.
ACT_JS = r"""async (opts) => {
  const op = opts.op;
  const q = String(opts.name || "").trim().toLowerCase();
  const text = String(opts.text || "");
  const nameOf = (el) => {
    const node = el.querySelector(
      ".msg-conversation-listitem__participant-names, .msg-conversation-card__participant-names"
    );
    return ((node && node.innerText) || "").trim();
  };
  const clickSend = () => {
    const btn = document.querySelector("button.msg-form__send-button");
    if (!btn || btn.disabled || btn.getAttribute("aria-disabled") === "true") return false;
    btn.click();
    return true;
  };
  if (op === "send") {
    const sent = clickSend();
    return {action: "send", ok: sent, sent: sent, matched: "", chars: 0, ambiguous: false, matches: []};
  }
  const seen = new Set();
  const matches = [];
  for (const el of document.querySelectorAll(".msg-conversation-listitem, .msg-conversation-card")) {
    const n = nameOf(el);
    if (!n || seen.has(n)) continue;
    if (!q || !n.toLowerCase().includes(q)) continue;
    seen.add(n);
    matches.push({name: n, el: el});
  }
  if (matches.length === 0) {
    return {action: op, ok: false, sent: false, matched: "", chars: 0, ambiguous: false, matches: []};
  }
  if (matches.length > 1) {
    return {
      action: op,
      ok: false,
      sent: false,
      matched: "",
      chars: 0,
      ambiguous: true,
      matches: matches.map((m) => m.name)
    };
  }
  const card = matches[0].el;
  const link = card.querySelector("a");
  (link || card).click();
  const deadline = Date.now() + 8000;
  let box = null;
  while (Date.now() < deadline) {
    box = document.querySelector(".msg-form__contenteditable");
    if (box) break;
    await new Promise((r) => setTimeout(r, 200));
  }
  if (op === "select") {
    return {
      action: "select",
      ok: !!box,
      sent: false,
      matched: matches[0].name,
      chars: 0,
      ambiguous: false,
      matches: [matches[0].name]
    };
  }
  if (!box) {
    return {
      action: "tell",
      ok: false,
      sent: false,
      matched: matches[0].name,
      chars: 0,
      ambiguous: false,
      matches: [matches[0].name],
      reason: "composer not ready"
    };
  }
  box.focus();
  document.execCommand("insertText", false, text);
  if (!opts.send) {
    return {
      action: "tell",
      ok: true,
      sent: false,
      matched: matches[0].name,
      chars: text.length,
      ambiguous: false,
      matches: [matches[0].name]
    };
  }
  const sent = clickSend();
  return {
    action: "tell",
    ok: sent,
    sent: sent,
    matched: matches[0].name,
    chars: text.length,
    ambiguous: false,
    matches: [matches[0].name],
    reason: sent ? "" : "send button unavailable"
  };
}"""


def ready_expression() -> str:
    return f"({READY_JS})()"


def act_expression(op: str, name: str, text: str, send: bool) -> str:
    opts = json.dumps({"op": op, "name": name, "text": text, "send": send}, ensure_ascii=False)
    return f"({ACT_JS})({opts})"


def thread_query_expression(query: str, needle: str, limit: int) -> str:
    opts = json.dumps({"query": query, "filter": needle, "limit": limit})
    return f"({_THREAD_QUERY_JS})({opts})"


# ---- popup dialog policy -----------------------------------------------------

SHARE_CONTACT = "share your contact info"
DECLINE = "No, don't share"
SHARE = "Yes, please share"


def choose_popup_action(title: str, buttons: list[str], policy: dict) -> str | None:
    if SHARE_CONTACT not in title.lower():
        return None
    wanted = SHARE if policy.get("share_contact") == "share" else DECLINE
    for button in buttons:
        if button.strip().lower() == wanted.lower():
            return button
    return None


# ---- classify-then-draft intent routing --------------------------------------

Complete = Callable[[str, list[dict]], str]


def route(
    text: str,
    pattern: str,
    intent_model: str,
    write_model: str,
    intent_prompt: str,
    write_prompt: str,
    complete: Complete,
) -> dict:
    if pattern and not re.search(pattern, text, re.IGNORECASE):
        return {"go": False, "route": "skip", "reason": "regex miss"}
    raw = complete(
        intent_model,
        [
            {
                "role": "system",
                "content": intent_prompt + ' Reply with JSON {"go": bool, "reason": string} and nothing else.',
            },
            {"role": "user", "content": text},
        ],
    )
    try:
        parsed = json.loads(raw)
        go = bool(parsed["go"])
        reason = str(parsed.get("reason") or "")
    except (json.JSONDecodeError, KeyError, TypeError):
        return {"go": False, "route": "skip", "reason": "intent model did not return json"}
    if not go:
        return {"go": False, "route": "skip", "reason": reason}
    draft = complete(
        write_model,
        [
            {"role": "system", "content": write_prompt},
            {"role": "user", "content": text},
        ],
    ).strip()
    return {"go": True, "route": "write", "reason": reason, "draft": draft}


def run_workflow(spec: dict, thread_text: str, complete: Complete, dry_run: bool = True) -> dict:
    decision = route(
        thread_text,
        pattern=spec.get("match") or "",
        intent_model=spec.get("intent_model") or "gpt-5-nano",
        write_model=spec.get("write_model") or "gpt-5-mini",
        intent_prompt=spec.get("intent") or "",
        write_prompt=spec.get("write") or "",
        complete=complete,
    )
    decision["name"] = spec.get("name") or ""
    decision["sent"] = False  # this workflow never sends, dry_run or not
    return decision

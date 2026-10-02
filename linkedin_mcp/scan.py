"""Find LinkedIn threads that still need a reply (or a referral), by reading
the already-open Chrome.

Restored (per the team lead) on top of messaging.py's list_threads /
select_thread / read_thread, in place of the `li threads` / `li read`
shell-out linkedin-agent used to depend on. Uses read_thread's clean
bodies/speakers split rather than regex-scraping "View NAME's profile" out
of raw display lines, since that split is already available.
"""

from __future__ import annotations

import json
import re
import time
from datetime import date, datetime, timedelta
from dataclasses import asdict, dataclass
from typing import Protocol

from own_chrome.cdp import ChromeError, evaluate

from linkedin_mcp import ledger, messaging
from linkedin_mcp.agent_config import Config
from linkedin_mcp.cdp_session import JSON
from linkedin_mcp.classify import already_referred, exclude_reason, joe_fit

TAB = "linkedin.com"

_SCROLL_JS = (
    "(()=>{const c=document.querySelector('.msg-conversations-container__conversations-list');"
    "if(!c) return false; c.scrollTop=c.scrollHeight;"
    "(c.closest('[class*=scroll]')||c.parentElement).scrollTop=1e9; return true})()"
)


@dataclass
class Candidate:
    name: str
    url: str
    unread: bool
    text: str


def to_json(candidates: dict[str, Candidate | JSON]) -> str:
    """Compact JSON list for agents: one object per candidate plus a joe_fit
    verdict. Accepts Candidate objects or the plain dicts core.scan returns."""
    rows = []
    for c in candidates.values():
        row = asdict(c) if isinstance(c, Candidate) else dict(c)
        rows.append({**row, "fit": joe_fit(row.get("text", ""))})
    return json.dumps(rows, ensure_ascii=False, separators=(",", ":"))


def _skip_reason(name: str, text: str, last_speaker_is_self: bool, config: Config) -> str:
    """Policy from the linkedin-outreach skill: last speaker is not us, referee
    not mentioned, nothing excluded, nobody at that company already contacted."""
    if last_speaker_is_self:
        return "last-speaker-is-self"
    if already_referred(text, config):
        return "referee-mentioned"
    if ledger.excluded(f"{name}\n{text}") or exclude_reason(name, "", text, config):
        return "excluded"
    if ledger.contacted(name=name) or ledger.contacted_company_in(text):
        return "already-in-ledger"
    return ""


def _load_full_thread_list(port: int, rounds: int, sleep_seconds: float) -> None:
    for _ in range(rounds):
        evaluate(port, _SCROLL_JS, host=TAB)
        if sleep_seconds:
            time.sleep(sleep_seconds)


class Reader(Protocol):
    """The slice of the messaging module find_referral_candidates drives (injectable for tests)."""

    def ensure_messaging(self, port: int) -> JSON: ...

    def list_threads(
        self, port: int, kind: str = ..., needle: str = ..., limit: int = ..., no_navigate: bool = ...
    ) -> JSON: ...

    def select_thread(self, port: int, name: str) -> JSON: ...

    def read_thread(self, port: int, limit: int = ...) -> JSON: ...


def find_referral_candidates(
    config: Config,
    port: int | None = None,
    thread_limit: int = 500,
    read_limit: int = 80,
    scroll_rounds: int = 15,
    sleep_seconds: float = 2.0,
    click_settle_seconds: float = 2.5,
    reader: Reader | None = None,
) -> dict[str, Candidate]:
    """Load every thread, select each one whose preview isn't from us, and
    keep the ones where the last speaker isn't us, the referee isn't
    mentioned yet, and nothing is excluded or already in the shared ledger.
    `reader` (default: the messaging module) is injectable for tests. Requires the linkedin.com tab
    and messaging open."""
    messaging = reader or globals()["messaging"]
    cdp_port = port if port is not None else config.cdp_port
    opened = messaging.ensure_messaging(cdp_port)
    # "already" on a messaging tab omits ready; a navigate that never
    # painted the thread list sets ready False and must not be scraped.
    # Mocks and older callers may return a non-dict; only a dict can say so.
    if isinstance(opened, dict) and not opened.get("ready", True):
        raise ChromeError(f"messaging tab not ready ({opened})")
    _load_full_thread_list(cdp_port, scroll_rounds, sleep_seconds)

    threads = messaging.list_threads(cdp_port, kind="threads", limit=thread_limit, no_navigate=True).get("threads", [])
    candidates: dict[str, Candidate] = {}
    for thread in threads:
        name = thread.get("name", "")
        preview = thread.get("preview", "")
        if not name or preview.startswith("You:"):
            continue
        selection = messaging.select_thread(cdp_port, name)
        if not selection.get("ok") or selection.get("ambiguous"):
            continue  # click missed, ambiguous, or wrong thread opened
        # select_thread's own "ok" only proves a composer exists, not that
        # it's specifically this thread's -- the click can race ahead of the
        # navigation. Verify by href before trusting the read, retrying a
        # few times instead of hoping a fixed sleep was long enough.
        href = selection.get("href") or ""
        data: JSON = {}
        verified = not href
        for _attempt in range(5):
            data = messaging.read_thread(cdp_port, limit=read_limit)
            if not href or href in (data.get("url") or ""):
                verified = True
                break
            if click_settle_seconds:
                time.sleep(click_settle_seconds)
        if not verified:
            continue
        text = "\n".join(data.get("bodies") or [])
        speakers = data.get("speakers") or []
        last_speaker_is_self = bool(config.self_name) and bool(speakers) and speakers[-1] == config.self_name
        if _skip_reason(name, text, last_speaker_is_self, config):
            continue
        candidates[name] = Candidate(
            name=name,
            url=data.get("url", ""),
            unread=bool(thread.get("unread")),
            text=text[-2500:],
        )
    return candidates


# ---- follow-ups: threads where Misha's referral is the last, unanswered message

_THREADS_JS = (
    "(()=>JSON.stringify([...document.querySelectorAll('li.msg-conversation-listitem')].map((e,i)=>{"
    "const n=e.querySelector('.msg-conversation-listitem__participant-names');"
    "const s=e.querySelector('.msg-conversation-card__message-snippet');"
    "return {i,name:n?n.innerText.trim():'',preview:s?s.innerText.trim():''}}).filter(t=>t.name)))()"
)
_OPEN_JS = (
    "((i)=>{const l=document.querySelectorAll('li.msg-conversation-listitem')[i]"
    ".querySelector('.msg-conversation-listitem__link');"
    "const was=/--active/.test(l.className);l.click();return was})"
)
_EVENTS_JS = (
    "(()=>{let date='',speaker='';const out=[];"
    "for(const e of document.querySelectorAll('.msg-s-message-list__event')){"
    "const h=e.querySelector('.msg-s-message-list__time-heading');if(h)date=h.innerText.trim();"
    "const n=e.querySelector('.msg-s-message-group__name');if(n)speaker=n.innerText.trim();"
    "const b=e.querySelector('.msg-s-event-listitem__body');if(b)out.push({speaker,date,body:b.innerText.trim()})}"
    "return JSON.stringify({url:location.href,events:out})})()"
)
_JOE = re.compile(r"joe\b|joseph|heupler", re.I)
_WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def parse_heading(label: str, today: date) -> date | None:
    """LinkedIn day heading -> date: TODAY, YESTERDAY, a weekday (latest past
    one), 'SEP 24' or 'SEP 24, 2025'. None when unrecognised."""
    t = (label or "").strip().lower()
    if t == "today":
        return today
    if t == "yesterday":
        return today - timedelta(days=1)
    if t in _WEEKDAYS:
        return today - timedelta(days=(today.weekday() - _WEEKDAYS.index(t)) % 7 or 7)
    m = re.fullmatch(r"([a-z]{3})[a-z]*\.? (\d{1,2})(?:, (\d{4}))?", t)
    if not m:
        return None
    try:
        d = datetime.strptime(f"{m[1]} {m[2]} {m[3] or today.year}", "%b %d %Y").date()
    except ValueError:
        return None
    return d if m[3] or d <= today else d.replace(year=d.year - 1)


def followup_row(name: str, url: str, events: list[JSON], self_name: str, today: date, days: int = 3) -> JSON | None:
    """The thread as a follow-up candidate, or None. Candidate = last message
    is ours, it is >= `days` old, we mentioned Joe, nobody replied after the
    first Joe mention, and we never already wrote 'follow...' after it."""
    def mine(e: JSON) -> bool:
        return bool(self_name) and e["speaker"].startswith(self_name)

    if not events or not mine(events[-1]):
        return None
    first = next((i for i, e in enumerate(events) if mine(e) and _JOE.search(e["body"])), None)
    if first is None:
        return None
    after = events[first:]
    if any(not mine(e) for e in after) or any(re.search(r"follow", e["body"], re.I) for e in after[1:]):
        return None
    last = parse_heading(events[-1]["date"], today)
    if last is None or (today - last).days < days:
        return None
    return {"name": name, "url": url, "last_date": last.isoformat(), "age_days": (today - last).days, "events": events[-6:]}


def find_followup_candidates(
    config: Config,
    port: int | None = None,
    days: int = 3,
    today: date | None = None,
    scroll_rounds: int = 15,
    sleep_seconds: float = 2.0,
    settle_seconds: float = 1.0,
) -> list[JSON]:
    """Open every thread whose last preview is ours and keep follow-up candidates."""
    today = today or date.today()
    cdp_port = port if port is not None else config.cdp_port
    opened = messaging.ensure_messaging(cdp_port)
    if isinstance(opened, dict) and not opened.get("ready", True):
        raise ChromeError(f"messaging tab not ready ({opened})")
    _load_full_thread_list(cdp_port, scroll_rounds, sleep_seconds)
    threads = json.loads(evaluate(cdp_port, _THREADS_JS, host=TAB))
    rows: list[JSON] = []
    prev_url = ""
    for t in threads:
        if not t["preview"].startswith("You"):  # "You: ...", "You sent an attachment" (the resume)
            continue
        was_active = bool(evaluate(cdp_port, f"({_OPEN_JS})({t['i']})", host=TAB))
        data: JSON = {}
        for _ in range(8):
            time.sleep(settle_seconds)
            data = json.loads(evaluate(cdp_port, _EVENTS_JS, host=TAB))
            if data["events"] and (was_active or data["url"] != prev_url):
                break
        else:
            continue  # thread never loaded; never judge a stale one
        prev_url = data["url"]
        row = followup_row(t["name"], data["url"], data["events"], config.self_name, today, days)
        if row:
            rows.append(row)
    return rows

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
import time
from dataclasses import asdict, dataclass

from own_chrome.cdp import ChromeError, evaluate

from linkedin_mcp import ledger, messaging
from linkedin_mcp.agent_config import Config
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


def to_json(candidates: dict[str, Candidate]) -> str:
    """Stable JSON list for agents: one object per candidate, plus a joe_fit verdict."""
    rows = [{**asdict(c), "fit": joe_fit(c.text)} for c in candidates.values()]
    return json.dumps(rows, indent=1, ensure_ascii=False)


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


def find_referral_candidates(
    config: Config,
    port: int | None = None,
    thread_limit: int = 500,
    read_limit: int = 80,
    scroll_rounds: int = 15,
    sleep_seconds: float = 2.0,
    click_settle_seconds: float = 2.5,
    reader=None,
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
        data: dict = {}
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

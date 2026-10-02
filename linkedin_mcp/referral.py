"""Send a referral message (text + attached resume) for one candidate thread.

Ties together scan.Candidate, copywriter.draft_referral, and
messaging.send_message. Sending only happens with confirm=True.
"""

from __future__ import annotations

import json
import random
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

from linkedin_mcp import ledger as real_ledger
from linkedin_mcp.classify import already_referred
from linkedin_mcp.agent_config import Config
from linkedin_mcp.copywriter import draft_referral, stale_days_from
from linkedin_mcp.governor import Governor, RateLimited, default_db_path
from linkedin_mcp.cdp_session import JSON, evaluate_pinned
from own_chrome.cdp import evaluate
from linkedin_mcp.messaging import TAB, linkedin_tab, open_thread, read_thread, send_message


@dataclass
class ReferralResult:
    name: str
    skipped: str = ""
    draft: str = ""
    proof: JSON | None = None


def send_referral_for_candidate(
    name: str,
    url: str,
    thread_text: str,
    config: Config,
    confirm: bool,
    stamp: str = "",
    port: int | None = None,
    governor: Governor | None = None,
) -> ReferralResult:
    """Referral sends are the bulk/loop-shaped case (one call per candidate
    thread from scan.find_referral_candidates), so this always paces and
    dedupes through Governor -- pass one in for a shared ledger across many
    calls, or leave it None to open+close one against config.governor_db_path
    for just this call."""
    if not config.referral.enabled or not config.referral.resume_path:
        return ReferralResult(name=name, skipped="referral disabled or resume_path not configured")

    cdp_port = port if port is not None else config.cdp_port
    open_thread(url, cdp_port)
    live = read_thread(cdp_port)
    blob = "\n".join([live.get("bodies") and live["bodies"][-1] or "", thread_text])
    if already_referred(blob, config):
        return ReferralResult(name=name, skipped="already referred")

    reengage = bool(config.self_name) and bool(live.get("speakers")) and live["speakers"][-1] == config.self_name
    draft = draft_referral(
        name=name,
        headline="",
        message=blob,
        config=config,
        reengage=reengage,
        stale_days=stale_days_from(stamp),
    )

    owns_governor = governor is None
    gov = governor or Governor(default_db_path(config.governor_db_path))
    try:
        proof = send_message(
            text=draft,
            config=config,
            confirm=confirm,
            attachment_path=config.referral.resume_path,
            attachment_name_hint=config.referral.attachment_name,
            port=cdp_port,
            governor=gov,
            target=url,
            action="referral",
        )
    except RateLimited as exc:
        return ReferralResult(name=name, draft=draft, skipped=f"rate-limited: {exc}")
    finally:
        if owns_governor:
            gov.close()
    return ReferralResult(name=name, draft=draft, proof=proof)


# ---- queue: deterministic bulk referrals -------------------------------------

EXCLUDED = ("mach", "anduril", "echostar", "dish", "amd", "w3sourcing", "perry barrow")
# Files whose presence in a thread means the resume already went out.
RESUME_FILES = ("resume_joseph_heupler.pdf", "joseph_heupler_resume.pdf")
_SNAPSHOT_JS = (
    "JSON.stringify({header: [document.title, ...document.querySelectorAll("
    "'.msg-entity-lockup__entity-title, .msg-thread__link-to-profile, .msg-overlay-bubble-header__title')]"
    ".map(e => e.innerText || e)].join('\\n'),"
    "text: [...document.querySelectorAll('.msg-s-event-listitem')].map(e => e.innerText).join('\\n')})"
)
_MESSAGE_BUTTON_JS = (
    "(() => {const b = [...document.querySelectorAll('main button, main a')]"
    ".find(e => /^message$/i.test((e.innerText || '').trim()) || /^message /i.test(e.getAttribute('aria-label') || ''));"
    "if (b) b.click(); return !!b;})()"
)


def _excluded(*fields: str) -> str:
    for term in EXCLUDED:
        for field in fields:
            if re.search(rf"\b{re.escape(term)}\b", field, re.IGNORECASE):
                return term
    return ""


def validate_queue(items: object) -> list[JSON]:
    if not isinstance(items, list):
        raise ValueError("queue must be a JSON list of {name, profile_url|thread_url, company, role, body}")
    for i, it in enumerate(items):
        if not isinstance(it, dict):
            raise ValueError(f"queue item {i} is not an object")
        for key in ("name", "company", "body"):
            if not str(it.get(key) or "").strip():
                raise ValueError(f"queue item {i} ({it.get('name') or '?'}): missing {key}")
        if not (it.get("thread_url") or it.get("profile_url")):
            raise ValueError(f"queue item {i} ({it['name']}): needs thread_url or profile_url")
    return items


def open_item(item: JSON, port: int) -> None:
    """Open the thread BY URL. A bare profile_url gets its Message button clicked."""
    open_thread(item.get("thread_url") or item["profile_url"], port)
    if not item.get("thread_url"):
        time.sleep(2.0)
        if not evaluate(port, _MESSAGE_BUTTON_JS, TAB):
            raise ValueError("no Message button on the profile page")
        time.sleep(2.0)


def _snapshot(port: int) -> JSON:
    raw = evaluate_pinned(linkedin_tab(port)["webSocketDebuggerUrl"], _SNAPSHOT_JS)
    snapshot: JSON = json.loads(raw) if isinstance(raw, str) else raw
    return snapshot


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def _resume_names(config: Config) -> set[str]:
    return {Path(config.referral.resume_path).name.lower(), *RESUME_FILES}


def _count_resume(text: str, config: Config) -> int:
    low = text.lower()
    return sum(low.count(n) for n in _resume_names(config))


class LedgerLike(Protocol):
    """What run_queue needs from a ledger: the signatures of linkedin_mcp.ledger
    (the module itself satisfies this), so mypy checks every fake against the real API."""

    def contacted(
        self,
        name: str | None = None,
        email: str | None = None,
        company: str | None = None,
        profile_url: str | None = None,
    ) -> bool: ...

    def append(self, entry: JSON) -> bool: ...


def run_queue(
    items: list[JSON],
    config: Config,
    confirm: bool = False,
    limit: int | None = None,
    port: int | None = None,
    ledger: LedgerLike | None = None,
    delay_range: tuple[float, float] = (0.0, 0.0),
) -> JSON:
    """Without confirm: a dry-run plan, no browser. With confirm, per item:
    skip excluded/ledgered, open the thread by URL, verify identity, skip if
    the email or resume is already there, send body then resume, re-read the
    thread and require the email and the resume exactly once, then append to
    the ledger (per send). A failed verification aborts the rest of the queue."""
    validate_queue(items)
    if confirm and (not config.referral.email or not config.referral.resume_path):
        raise ValueError("referral.email and referral.resume_path must be configured")
    ledger = real_ledger if ledger is None else ledger
    cdp_port = port if port is not None else config.cdp_port
    email = config.referral.email.lower()
    results: list[JSON] = []
    out = {"dry_run": not confirm, "results": results, "aborted": ""}
    planned = 0

    def skip(name: str, why: str) -> None:
        results.append({"name": name, "status": "skipped", "reason": why})

    for it in items:
        if limit is not None and planned >= limit:
            break
        name = it["name"]
        entry = {"name": name, "company": it["company"], "role": it.get("role", ""), "channel": "linkedin",
                 "profile_url": it.get("profile_url", ""), "thread_url": it.get("thread_url", ""),
                 "email": it.get("email", "")}
        hit = _excluded(it["company"], name) or next((n for n in config.never_contact if n and _excluded_by(n, name)), "")
        if hit:
            skip(name, f"excluded: {hit}")
            continue
        if ledger.contacted(
            name=name, email=it.get("email"), company=it["company"], profile_url=it.get("profile_url")
        ):
            skip(name, "already in ledger")
            continue
        if not confirm:
            results.append({"name": name, "status": "would-send", "reason": ""})
            planned += 1
            continue

        if planned:
            time.sleep(random.uniform(*delay_range))
        open_item(it, cdp_port)
        snap = _snapshot(cdp_port)
        if _norm(name) not in _norm(snap.get("header", "")):
            skip(name, "identity not confirmed from thread header")
            continue
        if email in snap["text"].lower() or _count_resume(snap["text"], config):
            skip(name, "thread already has the email or resume")
            continue

        planned += 1
        send_message(text=it["body"], config=config, confirm=True, port=cdp_port)
        send_message(
            text="", config=config, confirm=True, port=cdp_port,
            attachment_path=config.referral.resume_path,
            attachment_name_hint=Path(config.referral.resume_path).name,
            attach_wait_seconds=2.0,
        )
        after = _snapshot(cdp_port)["text"]
        emails, resumes = after.lower().count(email), _count_resume(after, config)
        verified = emails == 1 and resumes == 1
        ledger.append({**entry, "date": datetime.now(timezone.utc).isoformat(), "verified": verified})
        if not verified:
            reason = f"email appears {emails}x, resume {resumes}x (expected 1 each)"
            results.append({"name": name, "status": "verify-failed", "reason": reason})
            out["aborted"] = f"{name}: {reason}"
            break
        results.append({"name": name, "status": "sent", "reason": ""})
    return out


def _excluded_by(term: str, field: str) -> bool:
    return bool(re.search(rf"\b{re.escape(term)}\b", field, re.IGNORECASE))

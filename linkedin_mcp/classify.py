"""Classify recruiter/inbound messages: hiring vs. not, excluded vs. fair game.

Ported from the linkedin-refer copy.js regexes, generalized: the exclusion
lists come from Config instead of being hardcoded names.
"""

from __future__ import annotations

import re

from linkedin_mcp import ledger
from linkedin_mcp.agent_config import Config
from linkedin_mcp.cdp_session import JSON

HIRING_RE = re.compile(
    r"\b(inmail|hiring|hire|role|engineer|position|recruit|founding|job|opening|consultant)\b",
    re.IGNORECASE,
)


def looks_like_hiring(text: str) -> bool:
    return bool(HIRING_RE.search(text or ""))


def exclude_reason(name: str, headline: str, message: str, config: Config) -> str:
    """Return a reason string when the thread must be skipped, else ''."""
    who = name or ""
    for blocked in config.never_contact:
        if blocked and re.search(re.escape(blocked), who, re.IGNORECASE):
            return "never-contact"
    blob = f"{name or ''}\n{headline or ''}\n{message or ''}"
    for reserved in config.reserved_for_self:
        if reserved and re.search(re.escape(reserved), blob, re.IGNORECASE):
            return f"reserved-for-self:{reserved}"
    return ""


def already_referred(blob: str, config: Config) -> bool:
    lowered = (blob or "").lower()
    if config.referral.email and config.referral.email.lower() in lowered:
        return True
    if config.referral.name and config.referral.name.lower() in lowered:
        return True
    return False


def classify(
    message: str,
    config: Config | None = None,
    name: str = "",
    headline: str = "",
    company: str = "",
    profile_url: str = "",
) -> JSON:
    """Deterministic verdict: hiring / excluded / already_referred, plus a reason."""
    hiring = looks_like_hiring(message)
    blob = f"{name}\n{headline}\n{company}\n{message}"
    reason = ""
    is_excluded = ledger.excluded(blob)
    if is_excluded:
        match = ledger.EXCLUDED.search(blob)
        reason = f"excluded:{match.group(0).lower()}" if match else "excluded"
    elif config and (cfg_reason := exclude_reason(name, headline, message, config)):
        is_excluded, reason = True, cfg_reason
    referred = bool(config and already_referred(message, config)) or ledger.contacted(
        name=name, company=company, profile_url=profile_url
    )
    if not reason and referred:
        reason = "already-referred"
    if not reason and not hiring:
        reason = "not-hiring"
    return {"hiring": hiring, "excluded": is_excluded, "already_referred": referred, "reason": reason}


_YEARS_RE = re.compile(r"(\d+)\s*\+?\s*(?:-\s*\d+\s*)?(?:years?|yrs?)", re.IGNORECASE)
_SENIOR_RE = re.compile(r"\b(senior|sr\.?|staff|lead|principal|director|head of)\b", re.IGNORECASE)
_CLEARANCE_RE = re.compile(r"clearance|ts/sci|\bsecret\b|polygraph", re.IGNORECASE)
_QA_RE = re.compile(r"\b(qa|sdet|rpa|selenium|uipath|test automation)\b", re.IGNORECASE)
_STACK_RE = re.compile(r"c\+\+|\brust\b|golang|\.net\b|\bc#|salesforce|\bapex\b", re.IGNORECASE)
_FIT_RE = re.compile(
    r"\b(ai|ml|llm|llms|rag|agents?|agentic|machine learning|data|python|typescript|react|"
    r"full[- ]?stack|forward[- ]deployed)\b",
    re.IGNORECASE,
)


def joe_fit(role_text: str) -> JSON:
    """Honesty rule for referring Joe: never oversell a role he does not fit."""
    text = role_text or ""
    years = [int(m.group(1)) for m in _YEARS_RE.finditer(text)]
    if years and max(years) >= 5:
        return {"level": "skip", "why": f"asks {max(years)}+ years"}
    if m := _SENIOR_RE.search(text):
        return {"level": "skip", "why": f"{m.group(0).lower()} level title"}
    if _CLEARANCE_RE.search(text):
        return {"level": "skip", "why": "security clearance required"}
    if _QA_RE.search(text):
        return {"level": "skip", "why": "QA/SDET/RPA role"}
    if (m := _STACK_RE.search(text)) and not re.search(r"\b(python|typescript)\b", text, re.IGNORECASE):
        return {"level": "skip", "why": f"{m.group(0)}-only stack"}
    if _FIT_RE.search(text):
        return {"level": "strong", "why": "AI/ML/data/python/full-stack fit, 4 years or fewer asked"}
    return {"level": "stretch", "why": "no clear AI/data/python signal"}

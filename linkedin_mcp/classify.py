"""Classify recruiter/inbound messages: hiring vs. not, excluded vs. fair game.

Ported from the linkedin-refer copy.js regexes, generalized: the exclusion
lists come from Config instead of being hardcoded names.
"""

from __future__ import annotations

import re

from linkedin_mcp.agent_config import Config

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

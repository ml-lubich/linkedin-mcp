"""Draft a short, human referral message. Ported from linkedin-refer/copy.js,
generalized so the referee's identity and pitch come entirely from Config.
"""

from __future__ import annotations

import re
from datetime import datetime

from linkedin_mcp.agent_config import Config

AI_TELLS = (
    "—",  # em dash
    "–",  # en dash
    "delve",
    "leverage",
    "tapestry",
    "certainly",
    "i'd be happy",
    "please don't hesitate",
    "exceptional",
    "outstanding",
    "cutting-edge",
)


def sentences(text: str) -> list[str]:
    masked = re.sub(r"https?://\S+", "URL", text or "")
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", masked) if s.strip()]


def first_name(name: str) -> str:
    cleaned = re.sub(r"\s+", " ", str(name or "")).strip()
    if not cleaned:
        return "there"
    token = re.sub(r"[^a-zA-Z'\-]", "", cleaned.split(" ")[0])
    return token.lower() if token else "there"


def company_from(headline: str, message: str) -> str:
    blob = f"{headline or ''}\n{message or ''}"
    match = re.search(r"\bat\s+([A-Z][A-Za-z0-9&+\-]{1,40})", blob)
    if match:
        return match.group(1)
    match = re.search(r"\b(?:company|team),\s+([A-Z][A-Za-z0-9&+\-]{1,40})", blob)
    if match:
        return match.group(1)
    match = re.search(r"@\s*([A-Z][A-Za-z0-9&+\-]{1,40})", blob)
    if match:
        return match.group(1)
    return ""


def role_phrase(message: str, headline: str) -> str:
    blob = f"{headline or ''} {message or ''}".lower()
    if "founding" in blob:
        return "a founding engineer seat"
    if "consultant" in blob:
        return "this consulting role"
    if re.search(r"data engineer|analytics|mlops|dbt|airflow", blob):
        return "this data role"
    if re.search(r"full[- ]?stack|backend|software engineer", blob):
        return "this engineering role"
    if re.search(r"\b(ai|llm|agent|machine learning)\b", blob):
        return "this ai role"
    return "this role"


def late_apology(stale_days: int) -> str:
    days = int(stale_days or 0)
    if days >= 30:
        return "sorry for the slow reply, this got buried on my end"
    if days >= 7:
        return "sorry for the late reply"
    return ""


def stale_days_from(stamp: str, now: datetime | None = None) -> int:
    """LinkedIn stamps a thread card with a time, a weekday, or a date. Turn
    that into days since the last message."""
    text = str(stamp or "").strip()
    if not text:
        return 0
    if re.match(r"^\d{1,2}:\d{2}", text):
        return 0
    if re.match(r"^(mon|tue|wed|thu|fri|sat|sun)", text, re.IGNORECASE):
        return 3
    now = now or datetime.now()
    parsed = None
    slash = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{2,4})$", text)
    if slash:
        year = int(slash.group(3))
        year = 2000 + year if year < 100 else year
        try:
            parsed = datetime(year, int(slash.group(1)), int(slash.group(2)))
        except ValueError:
            parsed = None
    elif re.match(r"^[a-zA-Z]{3}\s+\d{1,2}$", text):
        try:
            parsed = datetime.strptime(f"{text} {now.year}", "%b %d %Y")
            if parsed > now:
                parsed = parsed.replace(year=now.year - 1)
        except ValueError:
            parsed = None
    if not parsed:
        return 0
    return max(0, (now - parsed).days)


def draft_referral(
    name: str,
    headline: str,
    message: str,
    config: Config,
    reengage: bool = False,
    stale_days: int = 0,
) -> str:
    who = first_name(name)
    company = company_from(headline, message)
    role = role_phrase(message, headline)
    sorry = late_apology(stale_days)
    base = (
        "long time no see"
        if reengage
        else (f"thanks for reaching out about {role} at {company}" if company else f"thanks for reaching out about {role}")
    )
    hook = f"{sorry}. {base}" if sorry else base
    look = f"look at {company}" if company else "look at what you are building"
    lead = f"i have someone for you if you are still filling {role}." if reengage else ""
    pitch = config.referral.pitch_for(f"{headline or ''} {message or ''}")
    text = " ".join(
        part
        for part in (
            f"hi {who}, {hook}.",
            lead,
            f"i'm not the right fit myself right now, but my colleague {config.referral.name} would be, and {pitch}.",
            f"they would love to {look} ({config.referral.linkedin_url}, {config.referral.email}), and their resume is attached.",
        )
        if part
    )
    return text


def assert_human_copy(text: str, config: Config) -> list[str]:
    problems = []
    lower = text.lower()
    for tell in AI_TELLS:
        if tell in lower:
            problems.append(f"ai-tell:{tell}")
    count = len(sentences(text))
    if count < 2 or count > 6:
        problems.append(f"sentences:{count}")
    if config.referral.email and config.referral.email.lower() not in lower:
        problems.append("missing-email")
    if config.referral.linkedin_url:
        slug = config.referral.linkedin_url.lower().rstrip("/")
        if slug not in lower:
            problems.append("missing-linkedin")
    if not re.match(r"^hi ", lower):
        problems.append("missing-hi")
    return problems

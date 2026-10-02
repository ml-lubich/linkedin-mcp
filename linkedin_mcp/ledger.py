"""Shared Joe-referral ledger (email + LinkedIn), ~/.config/joe-referral/ledger.json.

A JSON list of {name, email, company, role, date, channel, profile_url?}. The
email tool (joe-outreach/refer.py) writes the same file. Malformed content
raises LedgerError and is never overwritten.
"""

from __future__ import annotations

import datetime
import json
import os
import re
import tempfile
from pathlib import Path

ENV_VAR = "JOE_REFERRAL_LEDGER"
DEFAULT_PATH = Path.home() / ".config" / "joe-referral" / "ledger.json"
# Kept for Misha, or never contacted. Mirrors the linkedin-outreach Referral Policy.
EXCLUDED = re.compile(r"\b(mach industries|mach|anduril|echostar|dish|amd)\b|perry barrow|w3sourcing", re.I)


class LedgerError(RuntimeError):
    """The ledger file exists but is not a JSON list."""


def _path(path: Path | str | None) -> Path:
    return Path(path or os.environ.get(ENV_VAR) or DEFAULT_PATH)


def _norm(value: str | None) -> str:
    return (value or "").strip().casefold()


def load(path: Path | str | None = None) -> list[dict]:
    p = _path(path)
    if not p.exists():
        return []
    raw = p.read_text(encoding="utf-8")
    if not raw.strip():
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise LedgerError(f"{p} is not valid JSON ({exc}); fix it by hand, nothing was changed") from exc
    if not isinstance(data, list):
        raise LedgerError(f"{p} must contain a JSON list; nothing was changed")
    return data


def contacted(
    name: str | None = None,
    email: str | None = None,
    company: str | None = None,
    profile_url: str | None = None,
    path: Path | str | None = None,
) -> bool:
    """True if any entry matches (case-insensitive). Same company counts: a
    coworker was already contacted."""
    wanted = {k: _norm(v) for k, v in (("name", name), ("email", email), ("company", company), ("profile_url", profile_url))}
    wanted = {k: v for k, v in wanted.items() if v}
    if not wanted:
        return False
    return any(_norm(e.get(k)) == v for e in load(path) for k, v in wanted.items())


def append(entry: dict, path: Path | str | None = None) -> bool:
    """Add entry unless its email or profile_url is already present. Returns
    whether it was added. Atomic: temp file + rename."""
    p = _path(path)
    entries = load(p)
    for key in ("email", "profile_url"):
        value = _norm(entry.get(key))
        if value and any(_norm(e.get(key)) == value for e in entries):
            return False
    entries.append({"date": str(datetime.date.today()), **entry})
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=p.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(entries, handle, indent=1, ensure_ascii=False)
        os.replace(tmp, p)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return True


def excluded(text: str) -> bool:
    return bool(EXCLUDED.search(text or ""))


def contacted_company_in(text: str, path: Path | str | None = None) -> str:
    """Name of a ledger company mentioned in text ('' if none). Free-text twin
    of contacted(company=...) for threads where no company field exists."""
    lowered = _norm(text)
    for entry in load(path):
        company = _norm(entry.get("company"))
        if len(company) >= 3 and re.search(rf"(?<!\w){re.escape(company)}(?!\w)", lowered):
            return entry["company"]
    return ""

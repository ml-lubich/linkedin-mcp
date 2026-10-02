"""Token-minimal output for the CLI: one-line JSON, field selection, row limit,
truncated strings, one-line errors. Pure functions; no I/O."""

from __future__ import annotations

import json
from typing import Any

from linkedin_mcp.cdp_session import JSON

from .serialization import to_dict

ELLIPSIS = "…"


def trim(value: Any, max_chars: int) -> Any:
    """Truncate every string to max_chars and drop None/empty values."""
    if isinstance(value, str):
        return value if max_chars <= 0 or len(value) <= max_chars else value[:max_chars] + ELLIPSIS
    if isinstance(value, list):
        return [trim(v, max_chars) for v in value]
    if isinstance(value, dict):
        return {k: trim(v, max_chars) for k, v in value.items() if v not in (None, "", [], {})}
    return value


def parse_fields(fields: str | None) -> list[str]:
    return [f.strip() for f in (fields or "").split(",") if f.strip()]


def _rows(rows: list[Any], fields: list[str], limit: int | None) -> tuple[list[Any], int]:
    total = len(rows)
    rows = rows[:limit] if limit and limit > 0 else rows
    if fields:
        rows = [{k: r[k] for k in fields if k in r} if isinstance(r, dict) else r for r in rows]
    return rows, total


def shape(data: Any, fields: list[str] | None = None, limit: int | None = None, max_chars: int = 300) -> Any:
    """Shape a payload for an agent: counts instead of dumps.

    A list stays a list (a final {"more": k} row says k rows were cut by
    limit); a dict holding lists keeps its keys, gains "n" (total rows of the
    first list) and "more" (rows cut). `fields` picks keys from each row,
    or from the dict itself when it holds no list.
    """
    fields = fields or []
    data = to_dict(data)
    if isinstance(data, list):
        rows, total = _rows(data, fields, limit)
        if total > len(rows):
            rows.append({"more": total - len(rows)})
        return trim(rows, max_chars)
    if isinstance(data, dict):
        out: JSON = {}
        counted = False
        for key, val in data.items():
            if isinstance(val, list):
                rows, total = _rows(val, fields, limit)
                out[key] = rows
                if not counted:
                    out["n"] = total
                    counted = True
                if total > len(rows):
                    out["more"] = total - len(rows)
            else:
                out[key] = val
        if fields and not counted:
            out = {k: out[k] for k in fields if k in out}
        return trim(out, max_chars)
    return trim(data, max_chars)


def dumps(value: Any) -> str:
    """Single-line JSON, no spaces."""
    return json.dumps(to_dict(value), ensure_ascii=False, separators=(",", ":"))


def error_line(exc: Exception) -> str:
    """One line: what failed and the next command to try."""
    name = type(exc).__name__
    msg = " ".join(str(exc).split()) or name
    if name == "SendNotConfirmedError":
        nxt = "re-run with --confirm"
    elif name == "ChromeError":
        nxt = "run `li doctor`; if signed out run `li login`"
    elif "auth" in name.lower() or "cookie" in msg.lower():
        nxt = "run `li auth-status`, then `li login`"
    else:
        nxt = "run `li doctor`"
    return f"error: {msg[:200]} | next: {nxt}"

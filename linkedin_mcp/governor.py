"""Rate governor + action ledger.

Ported from a companion automation project's governor.py (same author,
generalized: action set trimmed/renamed to what linkedin-agent actually does,
no project-specific paths). The real ceiling on LinkedIn automation is not
code, it is LinkedIn's limits. Every send-capable action routes through here
so one budget is enforced across all of them, instead of each caller
independently thinking it is under budget while jointly blowing past it.

Two guarantees:
  1. Never exceed a per-action budget inside its rolling window.
  2. Never repeat an action against the same target, ever. Re-sending to the
     same thread/post is the fastest way to get an account flagged.

Budgets are a conservative default, not the maximum LinkedIn tolerates.
"""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

DAY = 86_400
WEEK = 7 * DAY

# action -> (max_actions, window_seconds)
LIMITS: dict[str, tuple[int, int]] = {
    "invite": (80, WEEK),
    "message": (40, DAY),
    "referral": (15, DAY),
    "post": (5, DAY),
    "react": (80, DAY),
    "comment": (20, DAY),
    "profile_view": (120, DAY),
    "search": (60, DAY),
}

DEFAULT_DB_PATH = Path.home() / ".config" / "linkedin-agent" / "governor.db"


class RateLimited(RuntimeError):
    """Action refused: budget exhausted, or already performed on this target."""


@dataclass(frozen=True)
class Budget:
    action: str
    used: int
    limit: int
    window_seconds: int

    @property
    def remaining(self) -> int:
        return max(0, self.limit - self.used)


class Governor:
    def __init__(self, db_path: Path | str, *, now: float | None = None) -> None:
        self._db_path = Path(db_path)
        self._now_override = now
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(self._db_path)
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS actions ("
            " action TEXT NOT NULL,"
            " target TEXT NOT NULL,"
            " at REAL NOT NULL,"
            " PRIMARY KEY (action, target))"
        )
        self._db.execute("CREATE INDEX IF NOT EXISTS idx_action_at ON actions(action, at)")
        self._db.commit()

    def _now(self) -> float:
        return self._now_override if self._now_override is not None else time.time()

    def budget(self, action: str) -> Budget:
        if action not in LIMITS:
            raise KeyError(f"unknown action {action!r}; known: {sorted(LIMITS)}")
        limit, window = LIMITS[action]
        cutoff = self._now() - window
        (used,) = self._db.execute(
            "SELECT count(*) FROM actions WHERE action = ? AND at >= ?", (action, cutoff)
        ).fetchone()
        return Budget(action=action, used=used, limit=limit, window_seconds=window)

    def already_done(self, action: str, target: str) -> bool:
        row = self._db.execute(
            "SELECT 1 FROM actions WHERE action = ? AND target = ?", (action, target)
        ).fetchone()
        return row is not None

    def check(self, action: str, target: str) -> None:
        """Raise RateLimited if this action on this target is not permitted."""
        if self.already_done(action, target):
            raise RateLimited(f"{action} already performed on {target!r}; refusing to repeat.")
        budget = self.budget(action)
        if budget.remaining <= 0:
            hours = budget.window_seconds // 3600
            raise RateLimited(
                f"{action} budget exhausted: {budget.used}/{budget.limit} in the last {hours}h."
            )

    def record(self, action: str, target: str) -> None:
        self._db.execute(
            "INSERT OR REPLACE INTO actions (action, target, at) VALUES (?, ?, ?)",
            (action, target, self._now()),
        )
        self._db.commit()

    def close(self) -> None:
        self._db.close()

    def __enter__(self) -> "Governor":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()


def default_db_path(governor_db_path: str = "") -> Path:
    return Path(governor_db_path) if governor_db_path else DEFAULT_DB_PATH


def demo() -> None:
    """Runnable self-check: `python -m linkedin_agent.governor`."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "ledger.db"
        gov = Governor(db, now=1_000_000.0)

        gov.check("invite", "alice")
        gov.record("invite", "alice")
        assert gov.budget("invite").used == 1

        try:
            gov.check("invite", "alice")
            raise AssertionError("expected RateLimited on repeat target")  # pragma: no cover
        except RateLimited:
            pass

        gov.check("message", "alice")  # different action, same target: fine

        limit, _ = LIMITS["comment"]
        for i in range(limit):
            gov.record("comment", f"post-{i}")
        try:
            gov.check("comment", "post-new")
            raise AssertionError("expected RateLimited when budget exhausted")  # pragma: no cover
        except RateLimited:
            pass
        gov.close()

        later = Governor(db, now=1_000_000.0 + WEEK + 1)
        assert later.budget("invite").used == 0, "week-old invite should have aged out"
        later.check("invite", "bob")
        later.close()

    print("governor self-check OK")


if __name__ == "__main__":  # pragma: no cover
    demo()

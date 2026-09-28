from __future__ import annotations

from pathlib import Path

import pytest

from linkedin_mcp.governor import (
    LIMITS,
    WEEK,
    Governor,
    RateLimited,
    default_db_path,
    demo,
)


def test_default_db_path_empty_uses_home_default():
    from linkedin_mcp.governor import DEFAULT_DB_PATH

    assert default_db_path("") == DEFAULT_DB_PATH


def test_default_db_path_override():
    assert default_db_path("/tmp/custom.db") == Path("/tmp/custom.db")


def test_unknown_action_raises_keyerror(tmp_path):
    gov = Governor(tmp_path / "g.db", now=1_000_000.0)
    with pytest.raises(KeyError):
        gov.budget("smoke-signal")
    gov.close()


def test_check_and_record_dedupe_same_target(tmp_path):
    gov = Governor(tmp_path / "g.db", now=1_000_000.0)
    gov.check("message", "alice")
    gov.record("message", "alice")
    assert gov.already_done("message", "alice")
    with pytest.raises(RateLimited, match="already performed"):
        gov.check("message", "alice")
    gov.close()


def test_budget_exhaustion_raises(tmp_path):
    gov = Governor(tmp_path / "g.db", now=1_000_000.0)
    limit, _ = LIMITS["post"]
    for i in range(limit):
        gov.record("post", f"post-{i}")
    with pytest.raises(RateLimited, match="budget exhausted"):
        gov.check("post", "post-new")
    gov.close()


def test_budget_ages_out_of_window(tmp_path):
    db = tmp_path / "g.db"
    gov = Governor(db, now=1_000_000.0)
    gov.record("invite", "alice")
    assert gov.budget("invite").used == 1
    gov.close()

    later = Governor(db, now=1_000_000.0 + WEEK + 1)
    assert later.budget("invite").used == 0, "week-old invite should no longer count toward the budget"
    later.check("invite", "bob")  # a *new* target is fine once the old one has aged out of the budget
    later.close()


def test_same_target_stays_blocked_forever_even_after_window_ages_out(tmp_path):
    # Guarantee #2 (never repeat a target) is permanent -- it does not age
    # out the way the rolling budget count does.
    db = tmp_path / "g.db"
    gov = Governor(db, now=1_000_000.0)
    gov.record("invite", "alice")
    gov.close()

    later = Governor(db, now=1_000_000.0 + WEEK + 1)
    with pytest.raises(RateLimited, match="already performed"):
        later.check("invite", "alice")
    later.close()


def test_different_actions_same_target_are_independent(tmp_path):
    gov = Governor(tmp_path / "g.db", now=1_000_000.0)
    gov.record("message", "alice")
    gov.check("referral", "alice")  # different action, no conflict
    gov.close()


def test_context_manager_closes(tmp_path):
    with Governor(tmp_path / "g.db", now=1_000_000.0) as gov:
        gov.record("search", "query-1")
    with pytest.raises(Exception):
        gov._db.execute("SELECT 1")  # connection is closed


def test_remaining_never_negative():
    from linkedin_mcp.governor import Budget

    budget = Budget(action="post", used=99, limit=5, window_seconds=86400)
    assert budget.remaining == 0


def test_demo_runs_clean(capsys):
    demo()
    out = capsys.readouterr().out
    assert "governor self-check OK" in out

"""New coverage closing mutmut gaps in linkedin_mcp/governor.py, added as a
new file per the ownership split with linkedin-mcp-lead -- never editing the
existing test_governor.py/test_governor_boundaries.py/
test_governor_pacing_without_dedupe.py."""

from __future__ import annotations

import pytest

from linkedin_mcp.governor import DEFAULT_DB_PATH, LIMITS, Governor, RateLimited, default_db_path


def test_governor_creates_deeply_nested_parent_directories(tmp_path):
    """__init__ must pass parents=True to mkdir -- a db_path several levels
    below an as-yet-nonexistent directory tree must not raise."""
    db_path = tmp_path / "a" / "b" / "c" / "governor.db"
    gov = Governor(db_path, now=1_000_000.0)
    assert db_path.parent.is_dir()
    gov.close()


def test_default_db_path_no_argument_uses_the_home_default():
    assert default_db_path() == DEFAULT_DB_PATH


def test_check_message_reports_the_exact_hour_count(tmp_path):
    gov = Governor(tmp_path / "g.db", now=1_000_000.0)
    limit, window = LIMITS["message"]  # DAY = 86400 seconds = exactly 24h
    assert window // 3600 == 24
    for i in range(limit):
        gov.record("message", f"t{i}")
    with pytest.raises(RateLimited, match=r"in the last 24h\.$"):
        gov.check("message", "t-new")
    gov.close()


def test_record_replaces_the_same_action_target_pair_instead_of_duplicating(tmp_path):
    """record() uses INSERT OR REPLACE -- recording the exact same
    (action, target) pair twice must count once toward the budget, not
    twice, since the primary key is (action, target)."""
    gov = Governor(tmp_path / "g.db", now=1_000_000.0)
    gov.record("message", "alice")
    gov.record("message", "alice")
    assert gov.budget("message").used == 1
    gov.close()

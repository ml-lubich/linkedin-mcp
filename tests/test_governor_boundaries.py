"""Governor pacing math at exact boundaries, across every configured action:
right at the cap, one over the cap, right at the rolling-window edge, just
past it, and under a skewed/negative clock.
"""

from __future__ import annotations

import pytest

from linkedin_mcp.governor import LIMITS, Governor, RateLimited

ACTIONS = sorted(LIMITS)


@pytest.mark.parametrize("action", ACTIONS)
def test_exactly_at_cap_blocks_next(tmp_path, action):
    limit, _ = LIMITS[action]
    gov = Governor(tmp_path / f"{action}.db", now=1_000_000.0)
    for i in range(limit):
        gov.record(action, f"t{i}")
    with pytest.raises(RateLimited, match="budget exhausted"):
        gov.check(action, "t-new")
    gov.close()


@pytest.mark.parametrize("action", ACTIONS)
def test_one_under_cap_allows(tmp_path, action):
    limit, _ = LIMITS[action]
    gov = Governor(tmp_path / f"{action}.db", now=1_000_000.0)
    for i in range(limit - 1):
        gov.record(action, f"t{i}")
    gov.check(action, "t-new")  # must not raise
    gov.close()


@pytest.mark.parametrize("action", ACTIONS)
def test_one_over_cap_still_blocks(tmp_path, action):
    limit, _ = LIMITS[action]
    gov = Governor(tmp_path / f"{action}.db", now=1_000_000.0)
    for i in range(limit + 1):
        gov.record(action, f"t{i}")
    assert gov.budget(action).used == limit + 1
    assert gov.budget(action).remaining == 0  # never negative
    with pytest.raises(RateLimited):
        gov.check(action, "t-new")
    gov.close()


@pytest.mark.parametrize("action", ACTIONS)
def test_window_edge_still_counts(tmp_path, action):
    """An action at exactly `now - window` is still inside the window
    (the SQL is `at >= cutoff`), so it must still count against the budget."""
    limit, window = LIMITS[action]
    db = tmp_path / f"{action}.db"
    gov = Governor(db, now=1_000_000.0)
    gov.record(action, "edge")
    gov.close()

    at_edge = Governor(db, now=1_000_000.0 + window)  # cutoff == the record's timestamp
    assert at_edge.budget(action).used == 1
    at_edge.close()


@pytest.mark.parametrize("action", ACTIONS)
def test_just_past_window_ages_out_of_budget(tmp_path, action):
    limit, window = LIMITS[action]
    db = tmp_path / f"{action}.db"
    gov = Governor(db, now=1_000_000.0)
    gov.record(action, "old")
    gov.close()

    past = Governor(db, now=1_000_000.0 + window + 0.001)
    assert past.budget(action).used == 0
    past.close()


@pytest.mark.parametrize("action", ACTIONS)
def test_negative_clock_skew_does_not_crash(tmp_path, action):
    """A clock that jumps backwards (skew) must not corrupt the ledger or
    raise -- worst case it just sees the older row as "in the future"
    relative to the cutoff, which SQL's >= handles fine either way."""
    db = tmp_path / f"{action}.db"
    gov = Governor(db, now=1_000_000.0)
    gov.record(action, "a")
    gov.close()

    skewed = Governor(db, now=500_000.0)  # clock jumped backwards 500,000s
    budget = skewed.budget(action)
    assert budget.used >= 0
    assert budget.remaining >= 0
    skewed.close()


@pytest.mark.parametrize("action", ACTIONS)
def test_repeat_target_blocked_regardless_of_budget_headroom(tmp_path, action):
    gov = Governor(tmp_path / f"{action}.db", now=1_000_000.0)
    gov.record(action, "solo-target")
    with pytest.raises(RateLimited, match="already performed"):
        gov.check(action, "solo-target")
    gov.close()


@pytest.mark.parametrize("action", ACTIONS)
def test_budget_used_matches_record_count_up_to_cap(tmp_path, action):
    limit, _ = LIMITS[action]
    gov = Governor(tmp_path / f"{action}.db", now=1_000_000.0)
    n = min(3, limit)
    for i in range(n):
        gov.record(action, f"x{i}")
    assert gov.budget(action).used == n
    gov.close()

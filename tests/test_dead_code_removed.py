"""Cleanup (review C1): messages_actions.READY_JS/ready_expression were
dead -- messaging.py has its own separate _READY_JS and never imports
these. Deleted rather than kept as an unused, confusing second copy."""

from __future__ import annotations


def test_ready_expression_no_longer_exists():
    import linkedin_mcp.messages_actions as messages_actions

    assert not hasattr(messages_actions, "ready_expression")
    assert not hasattr(messages_actions, "READY_JS")


def test_act_js_no_longer_has_unreachable_send_and_tell_branches():
    """act_expression is only ever called with op="select" (see
    messaging.select_thread); the "send"/"tell" branches (typing text,
    clicking Send a second way) were dead code."""
    from linkedin_mcp.messages_actions import ACT_JS

    assert 'op === "send"' not in ACT_JS
    assert "insertText" not in ACT_JS
    assert "send button unavailable" not in ACT_JS

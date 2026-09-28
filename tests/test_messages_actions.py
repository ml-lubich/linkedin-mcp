"""Deterministic LinkedIn messaging action builders. No Chrome.

Ported from own-chrome's actions.py/popups.py/intent.py (tag pre-li-move,
commit 97c1d9a) since own-chrome is dropping its `li` messaging surface and
this package absorbs it. Behavior kept identical; only the import path and
module name changed.
"""

from __future__ import annotations

import json

from linkedin_mcp.messages_actions import (
    ACT_JS,
    COMMANDS,
    act_expression,
    choose_linkedin_tab,
    choose_popup_action,
    on_messaging,
    ready_expression,
    route,
    thread_query_expression,
)


def test_on_messaging_accepts_inbox_and_thread_urls():
    assert on_messaging("https://www.linkedin.com/messaging/")
    assert on_messaging("https://www.linkedin.com/messaging/thread/abc")
    assert not on_messaging("https://www.linkedin.com/feed/")
    assert not on_messaging("https://www.google.com/search?q=linkedin.com/messaging")


def test_ready_expression_is_an_async_iife():
    expr = ready_expression()
    assert expr.startswith("(async")
    assert "/messaging" in expr


def test_act_expression_embeds_escaped_payload():
    expr = act_expression("tell", 'Ann "A"', "hi\nthere", False)
    payload = json.dumps({"op": "tell", "name": 'Ann "A"', "text": "hi\nthere", "send": False}, ensure_ascii=False)
    assert payload in expr


def test_ambiguous_match_returns_before_the_card_click():
    assert ACT_JS.index("matches.length > 1") < ACT_JS.index("(link || card).click()")


def test_choose_linkedin_tab_prefers_messaging_over_an_earlier_feed_tab():
    chosen = choose_linkedin_tab([
        {"id": "feed", "url": "https://www.linkedin.com/feed/", "title": "Feed | LinkedIn"},
        {"id": "msg", "url": "https://www.linkedin.com/messaging/thread/abc/", "title": "(5) Messaging | LinkedIn"},
    ])
    assert chosen is not None
    assert chosen["id"] == "msg"


def test_choose_linkedin_tab_uses_the_feed_when_it_is_the_only_linkedin_tab():
    chosen = choose_linkedin_tab([
        {"id": "google", "url": "https://www.google.com/search?q=linkedin.com/messaging"},
        {"id": "feed", "url": "https://www.linkedin.com/feed/"},
    ])
    assert chosen is not None
    assert chosen["id"] == "feed"


def test_choose_linkedin_tab_returns_none_when_linkedin_is_closed():
    assert choose_linkedin_tab([{"id": "google", "url": "https://www.google.com/"}]) is None


def test_command_catalog_covers_agent_verbs():
    names = [row["name"] for row in COMMANDS]
    assert names == ["open", "threads", "select", "read", "send", "popups", "workflow", "commands"]
    send = next(row for row in COMMANDS if row["name"] == "send")
    assert send["sends"] is True
    threads = next(row for row in COMMANDS if row["name"] == "threads")
    assert threads["sends"] is False


def test_thread_query_expression_embeds_filter_and_limit():
    expr = thread_query_expression("unread", "acme", 5)
    assert '"query": "unread"' in expr
    assert '"filter": "acme"' in expr
    assert '"limit": 5' in expr
    assert expr.startswith("(")


def test_choose_popup_action_declines_by_default():
    action = choose_popup_action(
        "Share your contact info?",
        ["No, don't share", "Yes, please share"],
        {"share_contact": "decline"},
    )
    assert action == "No, don't share"


def test_choose_popup_action_can_be_set_to_share():
    action = choose_popup_action(
        "Share your contact info?",
        ["No, don't share", "Yes, please share"],
        {"share_contact": "share"},
    )
    assert action == "Yes, please share"


def test_choose_popup_action_leaves_unknown_dialogs_alone():
    assert choose_popup_action("Messaging settings", ["Save"], {"share_contact": "decline"}) is None


def test_route_regex_miss_does_not_call_models():
    calls = []

    def complete(model, messages):
        calls.append(model)
        return "{}"

    decision = route(
        "want to grab coffee tomorrow",
        pattern=r"\b(role|hiring|engineer)\b",
        intent_model="gpt-5-nano",
        write_model="gpt-5-mini",
        intent_prompt="job only",
        write_prompt="draft",
        complete=complete,
    )
    assert decision["go"] is False
    assert decision["reason"] == "regex miss"
    assert calls == []


def test_route_nano_go_calls_mini_once():
    calls = []

    def complete(model, messages):
        calls.append(model)
        if model.endswith("nano"):
            return json.dumps({"go": True, "reason": "recruiter asked about a role"})
        return "thanks, I am not looking."

    decision = route(
        "Software engineer role",
        pattern=r"role",
        intent_model="gpt-5-nano",
        write_model="gpt-5-mini",
        intent_prompt="job only",
        write_prompt="draft",
        complete=complete,
    )
    assert decision["draft"] == "thanks, I am not looking."
    assert calls == ["gpt-5-nano", "gpt-5-mini"]

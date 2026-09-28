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
    run_workflow,
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


# ---- route: JSON parsing, empty pattern, go/skip decisions -----------------


def test_route_empty_pattern_still_calls_the_intent_model():
    calls = []

    def complete(model, messages):
        calls.append(model)
        return json.dumps({"go": False, "reason": "not relevant"})

    decision = route(
        "anything at all",
        pattern="",
        intent_model="gpt-5-nano",
        write_model="gpt-5-mini",
        intent_prompt="job only",
        write_prompt="draft",
        complete=complete,
    )
    assert decision == {"go": False, "route": "skip", "reason": "not relevant"}
    assert calls == ["gpt-5-nano"]


def test_route_sends_exact_system_and_user_messages_to_the_intent_model():
    captured = {}

    def complete(model, messages):
        captured[model] = messages
        return json.dumps({"go": False, "reason": "n/a"})

    route(
        "hello there",
        pattern="",
        intent_model="gpt-5-nano",
        write_model="gpt-5-mini",
        intent_prompt="job only",
        write_prompt="draft",
        complete=complete,
    )
    messages = captured["gpt-5-nano"]
    assert messages == [
        {
            "role": "system",
            "content": 'job only Reply with JSON {"go": bool, "reason": string} and nothing else.',
        },
        {"role": "user", "content": "hello there"},
    ]


def test_route_sends_exact_system_and_user_messages_to_the_write_model():
    captured = {}

    def complete(model, messages):
        if model == "gpt-5-nano":
            return json.dumps({"go": True, "reason": "hiring"})
        captured[model] = messages
        return "draft reply"

    route(
        "hello there",
        pattern="",
        intent_model="gpt-5-nano",
        write_model="gpt-5-mini",
        intent_prompt="job only",
        write_prompt="draft this",
        complete=complete,
    )
    assert captured["gpt-5-mini"] == [
        {"role": "system", "content": "draft this"},
        {"role": "user", "content": "hello there"},
    ]


def test_route_go_false_never_calls_the_write_model():
    calls = []

    def complete(model, messages):
        calls.append(model)
        return json.dumps({"go": False, "reason": "not hiring"})

    decision = route(
        "hello",
        pattern="",
        intent_model="gpt-5-nano",
        write_model="gpt-5-mini",
        intent_prompt="job only",
        write_prompt="draft",
        complete=complete,
    )
    assert decision == {"go": False, "route": "skip", "reason": "not hiring"}
    assert calls == ["gpt-5-nano"]


def test_route_go_true_without_reason_key_defaults_reason_to_empty_string():
    def complete(model, messages):
        if model == "gpt-5-nano":
            return json.dumps({"go": True})
        return "the draft"

    decision = route(
        "hello",
        pattern="",
        intent_model="gpt-5-nano",
        write_model="gpt-5-mini",
        intent_prompt="job only",
        write_prompt="draft",
        complete=complete,
    )
    assert decision == {"go": True, "route": "write", "reason": "", "draft": "the draft"}


def test_route_draft_is_stripped_of_surrounding_whitespace():
    def complete(model, messages):
        if model == "gpt-5-nano":
            return json.dumps({"go": True, "reason": "hiring"})
        return "  \n  the draft  \n  "

    decision = route(
        "hello",
        pattern="",
        intent_model="gpt-5-nano",
        write_model="gpt-5-mini",
        intent_prompt="job only",
        write_prompt="draft",
        complete=complete,
    )
    assert decision["draft"] == "the draft"


def test_route_non_json_intent_reply_skips_with_a_fixed_reason():
    decision = route(
        "hello",
        pattern="",
        intent_model="gpt-5-nano",
        write_model="gpt-5-mini",
        intent_prompt="job only",
        write_prompt="draft",
        complete=lambda model, messages: "not json at all",
    )
    assert decision == {"go": False, "route": "skip", "reason": "intent model did not return json"}


def test_route_json_missing_go_key_skips_with_the_same_fixed_reason():
    decision = route(
        "hello",
        pattern="",
        intent_model="gpt-5-nano",
        write_model="gpt-5-mini",
        intent_prompt="job only",
        write_prompt="draft",
        complete=lambda model, messages: json.dumps({"reason": "no go key"}),
    )
    assert decision == {"go": False, "route": "skip", "reason": "intent model did not return json"}


def test_route_json_that_is_not_an_object_skips_with_the_same_fixed_reason():
    decision = route(
        "hello",
        pattern="",
        intent_model="gpt-5-nano",
        write_model="gpt-5-mini",
        intent_prompt="job only",
        write_prompt="draft",
        complete=lambda model, messages: "5",
    )
    assert decision == {"go": False, "route": "skip", "reason": "intent model did not return json"}


# ---- run_workflow: spec defaults, overrides, and the never-sends marker ----


def test_run_workflow_uses_default_models_and_pattern_when_spec_is_empty():
    calls = []

    def complete(model, messages):
        calls.append(model)
        return json.dumps({"go": False, "reason": "n/a"})

    decision = run_workflow({}, "coffee tomorrow?", complete)
    assert decision == {"go": False, "route": "skip", "reason": "n/a", "name": "", "sent": False}
    assert calls == ["gpt-5-nano"]


def test_run_workflow_uses_spec_overrides_for_models_pattern_and_prompts():
    captured = {}

    def complete(model, messages):
        captured.setdefault("models", []).append(model)
        if model == "custom-intent":
            return json.dumps({"go": True, "reason": "hiring"})
        return "custom draft"

    spec = {
        "name": "recruiter-reply",
        "match": r"\brole\b",
        "intent_model": "custom-intent",
        "write_model": "custom-write",
        "intent": "custom intent prompt",
        "write": "custom write prompt",
    }
    decision = run_workflow(spec, "a role opened up", complete)
    assert decision == {
        "go": True,
        "route": "write",
        "reason": "hiring",
        "draft": "custom draft",
        "name": "recruiter-reply",
        "sent": False,
    }
    assert captured["models"] == ["custom-intent", "custom-write"]


def test_run_workflow_regex_miss_from_spec_match_short_circuits():
    calls = []

    def complete(model, messages):
        calls.append(model)
        return json.dumps({"go": True, "reason": "should not run"})

    decision = run_workflow({"match": r"\bhiring\b", "name": "n"}, "just saying hi", complete)
    assert decision == {"go": False, "route": "skip", "reason": "regex miss", "name": "n", "sent": False}
    assert calls == []


def test_run_workflow_sent_is_always_false_regardless_of_dry_run_flag():
    def complete(model, messages):
        return json.dumps({"go": False, "reason": "n/a"})

    assert run_workflow({}, "hi", complete, dry_run=True)["sent"] is False
    assert run_workflow({}, "hi", complete, dry_run=False)["sent"] is False


# ---- _linkedin_host / on_messaging: host matching edge cases --------------


def test_choose_linkedin_tab_matches_bare_and_subdomain_hosts_but_not_lookalikes():
    chosen = choose_linkedin_tab([
        {"id": "evil", "url": "https://linkedin.com.evil.com/messaging/"},
        {"id": "bare", "url": "https://linkedin.com/feed/"},
    ])
    assert chosen is not None
    assert chosen["id"] == "bare"


def test_on_messaging_rejects_lookalike_and_lower_paths():
    assert not on_messaging("https://linkedin.com.evil.com/messaging/")
    assert not on_messaging("https://www.linkedin.com/feed/messaging")
    assert on_messaging("https://mobile.linkedin.com/messaging/thread/1")


def test_choose_linkedin_tab_treats_malformed_url_as_not_linkedin():
    chosen = choose_linkedin_tab([{"id": "bad", "url": "https://[::1"}])
    assert chosen is None


def test_on_messaging_treats_malformed_url_as_false():
    assert not on_messaging("https://[::1")

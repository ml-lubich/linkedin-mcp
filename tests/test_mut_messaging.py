"""New coverage closing mutmut gaps in linkedin_mcp/messaging.py, added
separately from the existing suite (never editing it) since linkedin-mcp-lead
is actively landing correctness/security fixes there. Exercises current
behavior only -- no assumptions about code the lead may still change.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import linkedin_mcp.messaging as messaging


# ---- _allowed_attachment_dir / _validate_attachment_path / SendNotConfirmedError --


def test_allowed_attachment_dir_falls_back_to_home_documents(monkeypatch, config):
    config.attachments_dir = None
    config.referral.resume_path = ""
    result = messaging._allowed_attachment_dir(config)
    assert result == (Path.home() / "Documents").resolve()


def test_validate_attachment_path_rejects_a_directory_with_the_exact_message(config, tmp_path):
    config.attachments_dir = str(tmp_path)
    a_dir = tmp_path / "not_a_file"
    a_dir.mkdir()
    with pytest.raises(ValueError, match=r"^attachment is not a regular file: "):
        messaging._validate_attachment_path(str(a_dir), config)


def test_validate_attachment_path_outside_allowlist_has_the_exact_hint(config, tmp_path):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    config.attachments_dir = str(allowed)
    outside = tmp_path / "outside.pdf"
    outside.write_text("x")
    with pytest.raises(ValueError) as excinfo:
        messaging._validate_attachment_path(str(outside), config)
    assert str(excinfo.value).endswith("set attachments_dir in config.toml to allow it")


def test_send_not_confirmed_error_message_is_passed_through_unchanged():
    err = messaging.SendNotConfirmedError("exact message text", preview={"a": 1})
    assert str(err) == "exact message text"
    assert err.preview == {"a": 1}


def test_send_not_confirmed_error_defaults_preview_to_empty_dict():
    err = messaging.SendNotConfirmedError("no preview given")
    assert err.preview == {}


# NOTE: _fill_compose/_send_button_enabled/_click_send/_last_message_text/
# _compose_is_empty are exactly the low-level helpers the lead is
# mid-refactoring right now (adding a required url_contains pin, see
# test_pinned_tab_targeting.py) -- their signature changed under me twice
# within minutes while writing this file, so direct unit tests against them
# are deliberately skipped here per the "don't write tests against code
# that's about to change" guidance. Their behavior is already exercised
# indirectly through send_message's own tests below, which go through the
# public API and don't care about the private helpers' exact signatures.


# ---- read_thread: defaults, negative limit, non-string payloads -----------


def test_read_thread_default_limit_is_40(config, monkeypatch):
    bodies = [str(i) for i in range(50)]
    payload = json.dumps({"url": "u", "bodies": bodies, "speakers": []})
    monkeypatch.setattr(messaging, "evaluate", lambda *a, **k: payload)
    result = messaging.read_thread(config.cdp_port)
    assert result["bodies"] == bodies[-40:]
    assert len(result["bodies"]) == 40


def test_read_thread_negative_limit_clamps_to_keep_all(config, monkeypatch):
    payload = json.dumps({"url": "u", "bodies": ["a", "b"], "speakers": []})
    monkeypatch.setattr(messaging, "evaluate", lambda *a, **k: payload)
    result = messaging.read_thread(config.cdp_port, limit=-5)
    assert result["bodies"] == ["a", "b"]


def test_read_thread_accepts_an_already_parsed_dict(config, monkeypatch):
    monkeypatch.setattr(messaging, "evaluate", lambda *a, **k: {"url": "u", "bodies": ["a", "b"], "speakers": []})
    result = messaging.read_thread(config.cdp_port, limit=1)
    assert result["bodies"] == ["b"]


def test_read_thread_missing_bodies_key_defaults_to_empty_list(config, monkeypatch):
    monkeypatch.setattr(messaging, "evaluate", lambda *a, **k: {"url": "u"})
    result = messaging.read_thread(config.cdp_port, limit=5)
    assert result["bodies"] == []


# ---- send_message: defaults, port ternary, governor default action --------


def test_send_message_default_verify_attempts_and_wait_seconds(config, monkeypatch):
    sleeps = []
    monkeypatch.setattr(messaging.time, "sleep", lambda s: sleeps.append(s))
    attempts = {"count": 0}

    def fake_evaluate(port, script, **kw):
        if "insertText" in script:
            return True
        if "getAttribute('disabled')" in script:
            return True
        if ".click(); return !!b" in script:
            return True
        if "innerText.trim().length" in script:
            attempts["count"] += 1
            return False
        return ""

    monkeypatch.setattr(messaging, "evaluate", fake_evaluate)
    proof = messaging.send_message("hello", config, confirm=True)
    assert proof["sent"] is False
    assert attempts["count"] == 8
    assert sleeps == [0.75] * 8


def test_send_message_default_attach_wait_seconds(config, monkeypatch):
    sleeps = []
    monkeypatch.setattr(messaging.time, "sleep", lambda s: sleeps.append(s))
    monkeypatch.setattr(messaging, "set_file_input", lambda *a, **k: True)

    def fake_evaluate(port, script, **kw):
        if "insertText" in script:
            return True
        if "getAttribute('disabled')" in script:
            return True
        if ".click(); return !!b" in script:
            return True
        return "hello"

    monkeypatch.setattr(messaging, "evaluate", fake_evaluate)
    messaging.send_message(
        "hello",
        config,
        confirm=True,
        attachment_path=config.referral.resume_path,
        verify_attempts=1,
        verify_wait_seconds=0,
    )
    assert sleeps[0] == 1.5


def test_send_message_uses_explicit_port_over_config_cdp_port(config, monkeypatch):
    ports_seen = []

    def fake_evaluate(port, script, **kw):
        ports_seen.append(port)
        if "insertText" in script:
            return True
        if "getAttribute('disabled')" in script:
            return True
        if ".click(); return !!b" in script:
            return True
        return "hi"

    monkeypatch.setattr(messaging, "evaluate", fake_evaluate)
    messaging.send_message("hi", config, confirm=True, port=5555, verify_attempts=1, verify_wait_seconds=0)
    assert ports_seen and all(p == 5555 for p in ports_seen)
    assert config.cdp_port != 5555


def test_send_message_governor_defaults_action_to_message(config, monkeypatch, tmp_path):
    from linkedin_mcp.governor import Governor

    def fake_evaluate(port, script, **kw):
        if "insertText" in script:
            return True
        if "getAttribute('disabled')" in script:
            return True
        if ".click(); return !!b" in script:
            return True
        return "hi carol"

    monkeypatch.setattr(messaging, "evaluate", fake_evaluate)
    gov = Governor(tmp_path / "gov.db", now=1_000_000.0)
    messaging.send_message(
        "hi carol", config, confirm=True, governor=gov, target="carol", verify_attempts=1, verify_wait_seconds=0
    )
    assert gov.already_done("message", "carol")
    gov.close()


def test_send_message_verifies_against_the_sent_text_when_no_hint_is_given(config, monkeypatch):
    """hint defaults to the sent text itself (not "any non-empty message"),
    so a stale unrelated message already in the thread must not pass."""

    def fake_evaluate(port, script, **kw):
        if "insertText" in script:
            return True
        if "getAttribute('disabled')" in script:
            return True
        if ".click(); return !!b" in script:
            return True
        if "innerText;})()" in script or "innerText : ''" in script:
            return "some unrelated stale message"
        if "innerText.trim().length" in script:
            return True
        return ""

    monkeypatch.setattr(messaging, "evaluate", fake_evaluate)
    proof = messaging.send_message(
        "a distinctive phrase", config, confirm=True, verify_attempts=1, verify_wait_seconds=0
    )
    assert proof["sent"] is False


def test_send_message_not_confirmed_without_an_attachment_has_no_attach_clause(config, monkeypatch):
    monkeypatch.setattr(messaging, "evaluate", lambda *a, **k: True)
    with pytest.raises(messaging.SendNotConfirmedError) as excinfo:
        messaging.send_message("hello", config, confirm=False)
    assert str(excinfo.value) == "send_message requires confirm=True; nothing was sent"
    assert excinfo.value.preview == {"would_attach": None, "compose_filled": True, "sent": False}


# ---- linkedin_tab: collision detection -------------------------------------


def test_linkedin_tab_raises_when_another_open_tab_url_contains_the_chosen_one(monkeypatch):
    chosen_url = "https://www.linkedin.com/messaging/"
    evil = {"id": "evil", "url": f"https://evil.tld/#{chosen_url}"}
    good = {"id": "msg", "url": chosen_url}
    monkeypatch.setattr(messaging, "pages", lambda port: [good, evil])
    with pytest.raises(messaging.ChromeError, match="refusing to target"):
        messaging.linkedin_tab(9222)


def test_linkedin_tab_does_not_flag_itself_as_a_collision(monkeypatch):
    tab = {"id": "msg", "url": "https://www.linkedin.com/messaging/"}
    monkeypatch.setattr(messaging, "pages", lambda port: [tab])
    assert messaging.linkedin_tab(9222)["id"] == "msg"


def test_linkedin_tab_two_unrelated_linkedin_tabs_is_not_a_collision(monkeypatch):
    msg_tab = {"id": "msg", "url": "https://www.linkedin.com/messaging/"}
    other_tab = {"id": "feed", "url": "https://www.linkedin.com/feed/"}
    monkeypatch.setattr(messaging, "pages", lambda port: [msg_tab, other_tab])
    assert messaging.linkedin_tab(9222)["id"] == "msg"


# ---- ensure_messaging / _finish_open ---------------------------------------


def test_ensure_messaging_treats_a_bare_messaging_url_as_already_open(monkeypatch):
    tab = {"id": "msg", "url": "https://www.linkedin.com/messaging", "title": "Messaging"}
    monkeypatch.setattr(messaging, "pages", lambda port: [tab])
    monkeypatch.setattr(messaging, "navigate", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no navigate")))
    info = messaging.ensure_messaging(9222)
    assert info == {"action": "open", "opened": "already", "ok": True, "url": tab["url"], "title": "Messaging"}


def test_ensure_messaging_treats_a_thread_url_as_already_open(monkeypatch):
    tab = {"id": "msg", "url": "https://www.linkedin.com/messaging/thread/abc/", "title": "Thread"}
    monkeypatch.setattr(messaging, "pages", lambda port: [tab])
    monkeypatch.setattr(messaging, "navigate", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no navigate")))
    info = messaging.ensure_messaging(9222)
    assert info["opened"] == "already"


def test_ensure_messaging_missing_title_on_an_already_open_tab_defaults_empty(monkeypatch):
    tab = {"id": "msg", "url": "https://www.linkedin.com/messaging/"}
    monkeypatch.setattr(messaging, "pages", lambda port: [tab])
    info = messaging.ensure_messaging(9222)
    assert info["title"] == ""


def test_ensure_messaging_falls_back_to_MESSAGING_url_and_empty_title_when_open_tab_omits_them(monkeypatch):
    monkeypatch.setattr(messaging, "pages", lambda port: [])
    monkeypatch.setattr(messaging, "open_tab", lambda port, url: {})
    monkeypatch.setattr(
        messaging, "evaluate", lambda port, expr, **kw: json.dumps({"ready": True, "url": messaging.MESSAGING, "title": ""})
    )
    info = messaging.ensure_messaging(9222)
    assert info["url"] == messaging.MESSAGING


def test_ensure_messaging_navigate_passes_the_exact_host_kwarg(monkeypatch):
    captured = {}

    def fake_navigate(port, url, **kw):
        captured["port"] = port
        captured["url"] = url
        captured["kw"] = kw

    monkeypatch.setattr(messaging, "pages", lambda port: [{"id": "feed", "url": "https://www.linkedin.com/feed/"}])
    monkeypatch.setattr(messaging, "navigate", fake_navigate)
    monkeypatch.setattr(
        messaging, "evaluate", lambda port, expr, **kw: json.dumps({"ready": True, "url": messaging.MESSAGING, "title": ""})
    )
    messaging.ensure_messaging(9222)
    assert captured == {"port": 9222, "url": messaging.MESSAGING, "kw": {"host": messaging.TAB}}


def test_finish_open_polls_until_ready_then_stops_sleeping_only_between_tries(monkeypatch):
    responses = [
        json.dumps({"ready": False, "url": "u1", "title": "t1"}),
        json.dumps({"ready": True, "url": "u2", "title": "t2"}),
    ]
    calls = []

    def fake_evaluate(port, expr, **kw):
        calls.append(kw.get("url_contains"))
        return responses.pop(0)

    sleeps = []
    monkeypatch.setattr(messaging, "evaluate", fake_evaluate)
    monkeypatch.setattr(messaging.time, "sleep", lambda s: sleeps.append(s))
    info = messaging._finish_open(9222, {"url": "start-url", "title": "start-title"})
    assert info == {"url": "u2", "title": "t2", "ready": True}
    assert sleeps == [0.1]
    assert calls == ["start-url", "start-url"]


def test_finish_open_keeps_the_original_url_and_title_when_never_ready(monkeypatch):
    monkeypatch.setattr(messaging, "evaluate", lambda *a, **k: json.dumps({"ready": False}))
    times = iter([0.0, 0.5, 1.5])
    monkeypatch.setattr(messaging.time, "time", lambda: next(times, 2.0))
    monkeypatch.setattr(messaging.time, "sleep", lambda s: None)
    info = messaging._finish_open(9222, {"url": "start-url", "title": "start-title"})
    assert info["url"] == "start-url"
    assert info["title"] == "start-title"
    assert info["ready"] is False


# ---- list_threads: defaults, not-ready guard -------------------------------


def test_list_threads_defaults_needle_limit_and_no_navigate(monkeypatch):
    monkeypatch.setattr(messaging, "pages", lambda port: [{"id": "msg", "url": "https://www.linkedin.com/messaging/"}])
    captured = {}

    def fake_eval(port, expr):
        captured["expr"] = expr
        return {"threads": []}

    monkeypatch.setattr(messaging, "_eval_on_linkedin_tab", fake_eval)
    messaging.list_threads(9222)
    assert captured["expr"] == messaging.thread_query_expression("threads", "", 20)


def test_list_threads_raises_when_messaging_tab_never_becomes_ready(monkeypatch):
    monkeypatch.setattr(messaging, "ensure_messaging", lambda port: {"ready": False})
    with pytest.raises(messaging.ChromeError, match="not ready"):
        messaging.list_threads(9222)


def test_list_threads_no_navigate_true_skips_the_readiness_check_entirely(monkeypatch):
    def boom(port):
        raise AssertionError("must not call ensure_messaging when no_navigate=True")

    monkeypatch.setattr(messaging, "ensure_messaging", boom)
    monkeypatch.setattr(messaging, "_eval_on_linkedin_tab", lambda port, expr: {"threads": []})
    result = messaging.list_threads(9222, no_navigate=True)
    assert result["threads"] == []


# ---- select_thread: exact query args, not-ready guard, href passthrough ---


def test_select_thread_queries_all_threads_with_the_exact_expression(monkeypatch):
    monkeypatch.setattr(messaging, "ensure_messaging", lambda port: {"ready": True})
    captured = {}

    def fake_eval(port, expr):
        captured["port"] = port
        captured["expr"] = expr
        return {"threads": []}

    monkeypatch.setattr(messaging, "_eval_on_linkedin_tab", fake_eval)
    messaging.select_thread(9222, "Ada")
    assert captured["port"] == 9222
    assert captured["expr"] == messaging.thread_query_expression("threads", "", 500)


def test_select_thread_raises_when_messaging_tab_never_becomes_ready(monkeypatch):
    monkeypatch.setattr(messaging, "ensure_messaging", lambda port: {"ready": False})
    with pytest.raises(messaging.ChromeError, match="not ready"):
        messaging.select_thread(9222, "Ada")


def test_select_thread_blank_name_raises_the_exact_message():
    with pytest.raises(ValueError) as excinfo:
        messaging.select_thread(9222, "   ")
    assert str(excinfo.value) == "name is required"


def test_select_thread_exact_match_passes_the_disambiguated_href(monkeypatch):
    monkeypatch.setattr(messaging, "ensure_messaging", lambda port: {"ready": True})
    calls = []

    def fake_eval(port, expr):
        calls.append(expr)
        if len(calls) == 1:
            return {"threads": [{"name": "Ada Lovelace", "href": "/t/1/"}]}
        return {"action": "select", "ok": True, "matched": "Ada Lovelace"}

    monkeypatch.setattr(messaging, "_eval_on_linkedin_tab", fake_eval)
    result = messaging.select_thread(9222, "Ada Lovelace")
    assert result["href"] == "/t/1/"
    assert calls[1] == messaging.act_expression("select", "Ada Lovelace", "", False, href="/t/1/")


# ---- popups: default policy, port passthrough -------------------------------


def test_popups_default_policy_declines_and_reaches_the_configured_tab(monkeypatch):
    monkeypatch.setattr(messaging, "pages", lambda port: [{"id": "msg", "url": "https://www.linkedin.com/messaging/"}])
    ports_seen = []

    def fake_evaluate(port, expr, **kw):
        ports_seen.append(port)
        return json.dumps({"title": "Share your contact info?", "buttons": ["No, don't share", "Yes, please share"]})

    monkeypatch.setattr(messaging, "evaluate", fake_evaluate)
    result = messaging.popups(9222)
    assert result["action"] == "No, don't share"
    assert ports_seen == [9222]


def test_popups_apply_without_a_chosen_action_never_clicks(monkeypatch):
    monkeypatch.setattr(messaging, "pages", lambda port: [{"id": "msg", "url": "https://www.linkedin.com/messaging/"}])
    calls = []

    def fake_evaluate(port, expr, **kw):
        calls.append(expr)
        return json.dumps({"title": "Messaging settings", "buttons": ["Save"]})

    monkeypatch.setattr(messaging, "evaluate", fake_evaluate)
    result = messaging.popups(9222, apply=True)
    assert result["action"] is None
    assert result["applied"] is False
    assert len(calls) == 1


# ---- api_key / complete: env stripping, exact keychain cmd, request shape --


def test_api_key_strips_whitespace_from_the_env_value(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "  sk-env-value  \n")
    assert messaging.api_key() == "sk-env-value"


def test_api_key_falls_back_to_keychain_when_env_is_blank(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "   ")
    monkeypatch.setattr(messaging.subprocess, "check_output", lambda *a, **k: "sk-keychain-value\n")
    assert messaging.api_key() == "sk-keychain-value"


def test_api_key_keychain_lookup_uses_the_exact_service_and_account(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    captured = {}

    def fake_check_output(cmd, text=True, stderr=None):
        captured["cmd"] = cmd
        captured["text"] = text
        return "sk-keychain-value"

    monkeypatch.setattr(messaging.subprocess, "check_output", fake_check_output)
    messaging.api_key()
    assert captured["cmd"] == ["security", "find-generic-password", "-s", "openai", "-a", "li", "-w"]
    assert captured["text"] is True


def test_complete_sends_the_exact_request_shape(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    captured = {}

    class _FakeResponse:
        def __init__(self, payload):
            self._payload = payload

        def read(self):
            return self._payload

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def fake_urlopen(request, timeout=30):
        captured["url"] = request.full_url
        captured["method"] = request.get_method()
        captured["headers"] = dict(request.header_items())
        captured["body"] = json.loads(request.data.decode())
        captured["timeout"] = timeout
        return _FakeResponse(json.dumps({"choices": [{"message": {"content": "hi"}}]}).encode())

    monkeypatch.setattr(messaging.urllib.request, "urlopen", fake_urlopen)
    result = messaging.complete("gpt-5-nano", [{"role": "user", "content": "hi"}])
    assert result == "hi"
    assert captured["url"] == "https://api.openai.com/v1/chat/completions"
    assert captured["method"] == "POST"
    assert captured["headers"]["Authorization"] == "Bearer sk-test"
    assert captured["headers"]["Content-type"] == "application/json"
    assert captured["body"] == {"model": "gpt-5-nano", "messages": [{"role": "user", "content": "hi"}]}
    assert captured["timeout"] == 30


def test_complete_truncates_http_error_detail_to_300_chars(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    long_detail = "x" * 500

    class _Resp:
        def read(self):
            return long_detail.encode()

        def close(self):
            pass

    def raise_error(request, timeout=30):
        raise messaging.urllib.error.HTTPError(request.full_url, 500, "boom", {}, _Resp())

    monkeypatch.setattr(messaging.urllib.request, "urlopen", raise_error)
    with pytest.raises(messaging.ChromeError) as excinfo:
        messaging.complete("gpt-5-nano", [])
    msg = str(excinfo.value)
    assert msg.startswith("OpenAI 500: ")
    assert msg[len("OpenAI 500: "):] == "x" * 300


# ---- workflow_run: text vs. reading the open thread, no dry_run kwarg -----


def test_workflow_run_uses_explicit_text_without_reading_the_thread(monkeypatch, tmp_path):
    spec = tmp_path / "spec.json"
    spec.write_text(json.dumps({"intent": "i", "write": "w"}))

    def fake_complete(model, messages):
        if model == "gpt-5-nano":
            return json.dumps({"go": False, "reason": "n/a"})
        return "draft"

    def boom(*a, **k):
        raise AssertionError("must not read the thread when text is given")

    monkeypatch.setattr(messaging, "complete", fake_complete)
    monkeypatch.setattr(messaging, "read_thread", boom)
    result = messaging.workflow_run(str(spec), text="explicit text")
    assert result["go"] is False
    assert result["sent"] is False


def test_workflow_run_reads_the_open_thread_with_limit_4_when_text_is_empty_and_port_given(monkeypatch, tmp_path):
    spec = tmp_path / "spec.json"
    spec.write_text(json.dumps({}))
    captured = {}

    def fake_read_thread(port, limit=40):
        captured["port"] = port
        captured["limit"] = limit
        return {"bodies": ["line one", "line two"]}

    def fake_complete(model, messages):
        captured.setdefault("texts", []).append(messages[-1]["content"])
        return json.dumps({"go": False, "reason": "n/a"})

    monkeypatch.setattr(messaging, "read_thread", fake_read_thread)
    monkeypatch.setattr(messaging, "complete", fake_complete)
    messaging.workflow_run(str(spec), port=9222)
    assert captured["port"] == 9222
    assert captured["limit"] == 4
    assert captured["texts"] == ["line one\n\nline two"]


def test_workflow_run_skips_reading_the_thread_when_no_text_and_no_port(monkeypatch, tmp_path):
    spec = tmp_path / "spec.json"
    spec.write_text(json.dumps({}))

    def boom(*a, **k):
        raise AssertionError("must not read the thread without a port")

    monkeypatch.setattr(messaging, "read_thread", boom)
    monkeypatch.setattr(messaging, "complete", lambda model, messages: json.dumps({"go": False, "reason": "n/a"}))
    result = messaging.workflow_run(str(spec))
    assert result["go"] is False


def test_workflow_run_never_sends_even_when_go_is_true(monkeypatch, tmp_path):
    spec = tmp_path / "spec.json"
    spec.write_text(json.dumps({}))

    def fake_complete(model, messages):
        if model == "gpt-5-nano":
            return json.dumps({"go": True, "reason": "hiring"})
        return "draft reply"

    monkeypatch.setattr(messaging, "complete", fake_complete)
    result = messaging.workflow_run(str(spec), text="hiring for a role")
    assert result["sent"] is False
    assert result["draft"] == "draft reply"

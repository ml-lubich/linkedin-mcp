from __future__ import annotations

import pytest

from linkedin_mcp import auth_capture
from linkedin_mcp.auth_capture import AuthCaptureError


def test_capture_returns_immediately_once_required_cookies_present(monkeypatch, tmp_path):
    cookie_file = tmp_path / "cookies"
    monkeypatch.setattr(auth_capture, "COOKIE_FILE", cookie_file)
    monkeypatch.setattr(auth_capture, "COOKIE_HOME", tmp_path)
    monkeypatch.setattr(
        auth_capture,
        "_fetch_cookies",
        lambda port: [{"name": "li_at", "value": "secret"}, {"name": "JSESSIONID", "value": "sid"}],
    )

    result = auth_capture.capture(port=9333, timeout_seconds=5)

    assert result == {"captured": True, "cookie_count": 2, "path": str(cookie_file)}
    assert cookie_file.read_text() == "li_at=secret; JSESSIONID=sid"


def test_capture_never_returns_cookie_values_in_the_report(monkeypatch, tmp_path):
    monkeypatch.setattr(auth_capture, "COOKIE_FILE", tmp_path / "cookies")
    monkeypatch.setattr(auth_capture, "COOKIE_HOME", tmp_path)
    monkeypatch.setattr(
        auth_capture,
        "_fetch_cookies",
        lambda port: [{"name": "li_at", "value": "top-secret-value"}, {"name": "JSESSIONID", "value": "sid"}],
    )

    result = auth_capture.capture(port=9333, timeout_seconds=5)

    assert "top-secret-value" not in str(result)


def test_capture_times_out_without_a_login(monkeypatch, tmp_path):
    monkeypatch.setattr(auth_capture, "COOKIE_FILE", tmp_path / "cookies")
    monkeypatch.setattr(auth_capture, "_fetch_cookies", lambda port: [])

    result = auth_capture.capture(port=9333, timeout_seconds=0)

    assert result["captured"] is False
    assert result["cookie_count"] == 0
    assert "error" in result


def test_capture_tolerates_chrome_errors_and_keeps_polling(monkeypatch, tmp_path):
    from own_chrome.cdp import ChromeError

    monkeypatch.setattr(auth_capture, "COOKIE_FILE", tmp_path / "cookies")
    monkeypatch.setattr(auth_capture.time, "sleep", lambda s: None)

    def boom(port):
        raise ChromeError("no chrome")

    monkeypatch.setattr(auth_capture, "_fetch_cookies", boom)
    result = auth_capture.capture(port=9333, timeout_seconds=0.01, poll_seconds=0)
    assert result["captured"] is False


def test_capture_polls_again_when_cookies_incomplete_then_succeeds(monkeypatch, tmp_path):
    cookie_file = tmp_path / "cookies"
    monkeypatch.setattr(auth_capture, "COOKIE_FILE", cookie_file)
    monkeypatch.setattr(auth_capture, "COOKIE_HOME", tmp_path)
    monkeypatch.setattr(auth_capture.time, "sleep", lambda s: None)

    calls = {"n": 0}

    def fetch(port):
        calls["n"] += 1
        if calls["n"] == 1:
            return [{"name": "li_at", "value": "x"}]  # missing JSESSIONID -- not yet logged in
        return [{"name": "li_at", "value": "x"}, {"name": "JSESSIONID", "value": "y"}]

    monkeypatch.setattr(auth_capture, "_fetch_cookies", fetch)
    result = auth_capture.capture(port=9333, timeout_seconds=5, poll_seconds=0)
    assert result["captured"] is True
    assert calls["n"] == 2


def test_fetch_cookies_raises_when_no_linkedin_tab(monkeypatch):
    from own_chrome.cdp import ChromeError

    monkeypatch.setattr(auth_capture, "pages", lambda port: [])
    monkeypatch.setattr(auth_capture, "filter_pages", lambda tabs, needle, limit: [])
    with pytest.raises(ChromeError):
        auth_capture._fetch_cookies(9333)


def test_fetch_cookies_uses_cdp_session(monkeypatch):
    calls = {}

    class FakeSession:
        def __init__(self, port, tab):
            calls["port"] = port
            calls["tab"] = tab

        def call(self, method, params):
            calls["method"] = method
            calls["params"] = params
            return {"cookies": [{"name": "li_at", "value": "x"}]}

        def __enter__(self):
            return self

        def __exit__(self, *exc_info):
            return None

    monkeypatch.setattr(auth_capture, "pages", lambda port: [{"url": "https://www.linkedin.com/feed/"}])
    monkeypatch.setattr(auth_capture, "filter_pages", lambda tabs, needle, limit: tabs)
    monkeypatch.setattr(auth_capture, "CdpSession", FakeSession)

    cookies = auth_capture._fetch_cookies(9333)

    assert cookies == [{"name": "li_at", "value": "x"}]
    assert calls["method"] == "Network.getCookies"
    assert calls["tab"] == auth_capture.TAB


def test_env_line_reads_saved_cookie_and_formats_export(monkeypatch, tmp_path):
    cookie_file = tmp_path / "cookies"
    cookie_file.write_text("li_at=abc; JSESSIONID=xyz")
    monkeypatch.setattr(auth_capture, "COOKIE_FILE", cookie_file)

    line = auth_capture.env_line()

    assert line == 'export LINKEDIN_COOKIE_HEADER="li_at=abc; JSESSIONID=xyz"'


def test_env_line_without_a_saved_session_raises(monkeypatch, tmp_path):
    monkeypatch.setattr(auth_capture, "COOKIE_FILE", tmp_path / "missing-cookies")
    with pytest.raises(AuthCaptureError):
        auth_capture.env_line()

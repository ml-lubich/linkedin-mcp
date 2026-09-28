"""Security fix (review A5): the cookie file must be created with 0600 mode
atomically (os.open with O_CREAT|O_WRONLY|O_TRUNC, 0o600), not
write_text()-then-chmod(), which leaves a window where the file is
world/group-readable under the default umask before chmod tightens it. The
parent config directory must be 0700 for the same reason."""

from __future__ import annotations

import stat

from linkedin_mcp import auth_capture


def test_capture_creates_the_cookie_file_with_0600_without_a_separate_chmod(monkeypatch, tmp_path):
    cookie_home = tmp_path / "linkedin-mcp"
    cookie_file = cookie_home / "cookies"
    monkeypatch.setattr(auth_capture, "COOKIE_HOME", cookie_home)
    monkeypatch.setattr(auth_capture, "COOKIE_FILE", cookie_file)
    monkeypatch.setattr(
        auth_capture,
        "_fetch_cookies",
        lambda port: [{"name": "li_at", "value": "secret"}, {"name": "JSESSIONID", "value": "sid"}],
    )

    real_chmod = auth_capture.os.chmod

    def no_chmod_on_the_cookie_file(path, mode):
        if str(path) == str(cookie_file):
            raise AssertionError("must not rely on a separate os.chmod call for the cookie file")
        return real_chmod(path, mode)

    monkeypatch.setattr(auth_capture.os, "chmod", no_chmod_on_the_cookie_file)

    result = auth_capture.capture(port=9333, timeout_seconds=5)

    assert result["captured"] is True
    mode = stat.S_IMODE(cookie_file.stat().st_mode)
    assert mode == 0o600
    assert cookie_file.read_text() == "li_at=secret; JSESSIONID=sid"


def test_capture_creates_the_config_dir_with_0700(monkeypatch, tmp_path):
    cookie_home = tmp_path / "linkedin-mcp"
    cookie_file = cookie_home / "cookies"
    monkeypatch.setattr(auth_capture, "COOKIE_HOME", cookie_home)
    monkeypatch.setattr(auth_capture, "COOKIE_FILE", cookie_file)
    monkeypatch.setattr(
        auth_capture,
        "_fetch_cookies",
        lambda port: [{"name": "li_at", "value": "x"}, {"name": "JSESSIONID", "value": "y"}],
    )

    auth_capture.capture(port=9333, timeout_seconds=5)

    assert stat.S_IMODE(cookie_home.stat().st_mode) == 0o700

"""Security fix (review A3): auth_capture.env_line() used naive double-quote
interpolation (`f'export X="{header}"'`), which lets a cookie value
containing a `"` break out of the quoting and inject shell commands when the
printed line is eval'd. shlex.quote closes that."""

from __future__ import annotations

import subprocess

from linkedin_mcp import auth_capture


def test_env_line_shell_quotes_a_value_containing_a_double_quote_and_command_injection(monkeypatch, tmp_path):
    cookie_file = tmp_path / "cookies"
    payload_marker = tmp_path / "pwned"
    header = f'li_at=abc"; touch {payload_marker}; JSESSIONID=xyz'
    cookie_file.write_text(header)
    monkeypatch.setattr(auth_capture, "COOKIE_FILE", cookie_file)

    line = auth_capture.env_line()

    result = subprocess.run(
        ["sh", "-c", f"{line}; printf '%s' \"$LINKEDIN_COOKIE_HEADER\""],
        capture_output=True,
        text=True,
        check=True,
    )

    assert result.stdout == header
    assert not payload_marker.exists()


def test_env_line_uses_shlex_quote() -> None:
    import inspect

    source = inspect.getsource(auth_capture.env_line)
    assert "shlex.quote" in source

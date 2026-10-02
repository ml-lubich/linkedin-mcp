"""Token-minimal output: compact JSON, fields, limit, truncation, one-line errors."""

from __future__ import annotations

import json

from typer.testing import CliRunner

import linkedin_mcp.core as core
from linkedin_mcp import compact
from linkedin_mcp.cli import app

runner = CliRunner()


def test_dumps_is_single_line_without_spaces() -> None:
    assert compact.dumps({"a": [1, 2], "b": "é"}) == '{"a":[1,2],"b":"é"}'


def test_trim_cuts_strings_and_drops_empties() -> None:
    out = compact.trim({"a": "x" * 10, "b": None, "c": "", "d": [], "e": False}, 4)
    assert out == {"a": "xxxx…", "e": False}


def test_trim_zero_means_no_cut() -> None:
    assert compact.trim("x" * 1000, 0) == "x" * 1000


def test_shape_list_limit_adds_more_row_and_fields_pick() -> None:
    rows = [{"name": "a", "url": "u", "x": 1}, {"name": "b", "url": "v"}, {"name": "c"}]
    out = compact.shape(rows, fields=["name", "url"], limit=2)
    assert out == [{"name": "a", "url": "u"}, {"name": "b", "url": "v"}, {"more": 1}]


def test_shape_dict_with_list_counts_rows() -> None:
    out = compact.shape({"threads": [{"name": "a"}, {"name": "b"}], "url": "u"}, limit=1)
    assert out == {"threads": [{"name": "a"}], "n": 2, "more": 1, "url": "u"}


def test_shape_plain_dict_fields_select_keys() -> None:
    assert compact.shape({"a": 1, "b": 2}, fields=["b", "zzz"]) == {"b": 2}


def test_shape_empty_and_unicode() -> None:
    assert compact.shape([]) == []
    assert compact.shape({"t": "日本語" * 5}, max_chars=3) == {"t": "日本語…"}


def test_parse_fields_handles_blanks_and_spaces() -> None:
    assert compact.parse_fields(" a, b ,,c") == ["a", "b", "c"]
    assert compact.parse_fields(None) == []


def test_error_line_has_one_line_and_next_step() -> None:
    line = compact.error_line(ValueError("bad\n\nthing"))
    assert "\n" not in line and line.startswith("error: bad thing | next: ")


def test_error_line_chrome_and_confirm_hints() -> None:
    class ChromeError(Exception): ...

    class SendNotConfirmedError(Exception): ...

    assert "li login" in compact.error_line(ChromeError("down"))
    assert "--confirm" in compact.error_line(SendNotConfirmedError("x"))


# ---- CLI wiring (core mocked, no browser) ---------------------------------

SCAN = {
    "Ada": {"name": "Ada", "url": "https://l/ada", "unread": True, "text": "old " * 200 + "NEWEST python ai role"},
    "Bob": {"name": "Bob", "url": "https://l/bob", "unread": False, "text": "hi"},
}


def _scan(monkeypatch):
    monkeypatch.setattr(core, "scan", lambda port=None, config_path=None: SCAN)


def test_scan_default_is_one_line_compact_json_with_fit_and_tail_text(monkeypatch) -> None:
    _scan(monkeypatch)
    result = runner.invoke(app, ["scan"])
    assert result.exit_code == 0
    assert result.output.count("\n") == 1
    rows = json.loads(result.output)
    assert [r["name"] for r in rows] == ["Ada", "Bob"]
    assert rows[0]["fit"]["level"] == "strong"
    assert len(rows[0]["text"]) == 300 and rows[0]["text"].endswith("NEWEST python ai role")


def test_scan_json_flag_still_accepted(monkeypatch) -> None:
    _scan(monkeypatch)
    assert runner.invoke(app, ["scan", "--json"]).exit_code == 0


def test_scan_fields_limit_max_chars_before_and_after_subcommand(monkeypatch) -> None:
    _scan(monkeypatch)
    for argv in (
        ["--fields", "name,fit", "--limit", "1", "scan"],
        ["--limit", "1", "scan", "--fields", "name,fit"],
        ["--limit", "1", "scan", "--fields=name,fit"],
    ):
        result = runner.invoke(app, argv)
        assert result.exit_code == 0, result.output
        rows = json.loads(result.output)
        assert set(rows[0]) == {"name", "fit"} and rows[1] == {"more": 1}


def test_scan_max_chars_option(monkeypatch) -> None:
    _scan(monkeypatch)
    rows = json.loads(runner.invoke(app, ["scan", "--max-chars", "10"]).output)
    assert len(rows[0]["text"]) == 10


def test_scan_empty_is_empty_list(monkeypatch) -> None:
    monkeypatch.setattr(core, "scan", lambda port=None, config_path=None: {})
    assert runner.invoke(app, ["scan"]).output.strip() == "[]"


def test_messages_read_truncates_bodies_and_counts(monkeypatch) -> None:
    monkeypatch.setattr(core, "messages_read", lambda **k: {"url": "u", "bodies": ["x" * 500, "y"], "speakers": ["a", "b"]})
    data = json.loads(runner.invoke(app, ["messages", "read", "--max-chars", "20"]).output)
    assert data["n"] == 2 and data["bodies"][0] == "x" * 20 + "…"


def test_error_is_one_line_with_next_step(monkeypatch) -> None:
    monkeypatch.setattr(core, "scan", lambda **k: (_ for _ in ()).throw(RuntimeError("boom")))
    result = runner.invoke(app, ["scan"])
    assert result.exit_code == 1
    assert result.output.strip() == "error: boom | next: run `li doctor`"


def test_help_works_on_root_and_nested() -> None:
    for argv in (["-h"], ["--help"], ["scan", "-h"], ["messages", "read", "-h"], ["referral", "queue", "-h"]):
        assert runner.invoke(app, argv).exit_code == 0, argv

from typer.testing import CliRunner

from linkedin_mcp.cli import app

runner = CliRunner()


def test_help_short_flag_on_root_groups_and_leaves():
    invocations = (
        ["-h"],
        ["--help"],
        ["auth", "-h"],
        ["auth", "env", "-h"],
        ["messages", "-h"],
        ["messages", "read", "-h"],
        ["post-cdp", "-h"],
        ["referral", "draft", "-h"],
    )
    for args in invocations:
        result = runner.invoke(app, args)
        assert result.exit_code == 0, (args, result.output)
        assert "Usage" in result.output
    read_help = runner.invoke(app, ["messages", "read", "-h"])
    assert "-j" in read_help.output and "--json" in read_help.output


def test_root_help_uses_shared_surface_and_version_shortcut():
    result = runner.invoke(app, ["-h"])
    assert result.exit_code == 0
    assert "-V" in result.output and "--version" in result.output
    assert "--install-completion" not in result.output
    assert "--show-completion" not in result.output
    options_panel = result.output.split("╭─ Options", 1)[1].split("╭─ Commands", 1)[0]
    for legacy in ("--config", "--fields", "--limit", "--max-chars"):
        assert legacy not in options_panel

    result = runner.invoke(app, ["-V"])
    assert result.exit_code == 0
    assert result.output.strip()


def test_root_without_command_shows_help():
    result = runner.invoke(app, [])
    assert result.exit_code == 2
    assert "Usage" in result.output
    assert "auth" in result.output
    assert "Error" not in result.output

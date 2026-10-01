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

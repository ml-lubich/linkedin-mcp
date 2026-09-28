"""Regression guard: the `li` binary shell-out (own-chrome's old messaging
CLI, on its way out per the team lead) must not exist anywhere in this
package. own-chrome's own messaging code lands in a later phase through
messaging.py directly, not through a `li` subprocess call."""

from __future__ import annotations

import pathlib

import pytest

import linkedin_mcp

PACKAGE_DIR = pathlib.Path(linkedin_mcp.__file__).parent


def test_li_cli_module_does_not_exist() -> None:
    with pytest.raises(ModuleNotFoundError):
        import linkedin_mcp.li_cli  # noqa: F401


def test_no_source_file_shells_out_to_the_li_binary() -> None:
    offenders = []
    for py_file in PACKAGE_DIR.glob("*.py"):
        text = py_file.read_text()
        if 'which("li")' in text or '["li",' in text or "'li_cli'" in text or '"li_cli"' in text:
            offenders.append(py_file.name)
    assert offenders == []


def test_doctor_does_not_check_for_li_installed() -> None:
    from linkedin_mcp import doctor as doctor_mod

    source = pathlib.Path(doctor_mod.__file__).read_text()
    assert "li installed" not in source

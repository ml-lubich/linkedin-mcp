"""Both console scripts must exist and point at the same Typer app, so
`linkedin` and `linkedin-mcp` are interchangeable everywhere."""

from __future__ import annotations

import tomllib
from pathlib import Path

PYPROJECT = Path(__file__).resolve().parent.parent / "pyproject.toml"


def _scripts() -> dict[str, str]:
    data = tomllib.loads(PYPROJECT.read_text())
    return data["project"]["scripts"]


def test_both_entry_points_exist_and_point_at_the_same_app() -> None:
    scripts = _scripts()
    assert "linkedin" in scripts
    assert "linkedin-mcp" in scripts
    assert scripts["linkedin"] == scripts["linkedin-mcp"] == "linkedin_mcp.cli:app"


def test_entry_point_target_is_importable_and_callable() -> None:
    from linkedin_mcp.cli import app

    assert callable(app)

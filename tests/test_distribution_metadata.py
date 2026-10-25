"""Keep the published distribution and installed command names in sync."""

from __future__ import annotations

import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_distribution_metadata_matches_lockfile_and_preserves_commands() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    lock = tomllib.loads((ROOT / "uv.lock").read_text())
    package = next(
        item
        for item in lock["package"]
        if item.get("source") == {"editable": "."}
    )

    assert project["name"] == "linkedin-cli-mcp"
    assert project["version"] == "0.3.0"
    assert package["name"] == project["name"]
    assert package["version"] == project["version"]
    assert set(project["scripts"]) == {"li", "linkedin", "linkedin-mcp"}

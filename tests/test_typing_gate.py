"""The package must stay mypy --strict clean (config in pyproject.toml)."""

from pathlib import Path

from mypy import api

ROOT = Path(__file__).resolve().parent.parent


def test_mypy_strict_clean() -> None:
    out, err, code = api.run(["--config-file", str(ROOT / "pyproject.toml"), str(ROOT / "linkedin_mcp")])
    assert code == 0, out + err


def test_py_typed_marker_present() -> None:
    assert (ROOT / "linkedin_mcp" / "py.typed").is_file()


def test_no_type_ignore_in_package() -> None:
    offenders = [
        str(p) for p in (ROOT / "linkedin_mcp").rglob("*.py") if "type: ignore" in p.read_text()
    ]
    assert not offenders, offenders

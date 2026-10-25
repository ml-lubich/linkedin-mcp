"""Machine-readable CLI schema for agent integrations."""

from __future__ import annotations

import typer

from . import __version__


def build_schema(app: typer.Typer) -> dict[str, object]:
    """Return the registered command tree as a compact, stable JSON shape."""
    root = typer.main.get_command(app)
    commands: list[dict[str, object]] = []

    def visit(command: object, prefix: str) -> None:
        subcommands = getattr(command, "commands", None)
        if subcommands:
            for name, child in subcommands.items():
                visit(child, f"{prefix} {name}".strip())
            return

        params: list[dict[str, object]] = []
        for param in getattr(command, "params", []):
            if param.name == "help":
                continue
            params.append(
                {
                    "name": param.name,
                    "type": getattr(param.type, "name", str(param.type)),
                    "required": bool(param.required),
                    "flags": list(getattr(param, "opts", [])),
                }
            )
        commands.append(
            {
                "name": prefix,
                "help": (getattr(command, "help", None) or "").strip(),
                "params": params,
            }
        )

    visit(root, "")
    return {
        "version": __version__,
        "tool": "linkedin",
        "mcp": "linkedin-mcp",
        "help": "linkedin --help | linkedin <command> --help | linkedin-mcp serve",
        "commands": commands,
    }

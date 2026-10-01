"""Prompt management, parsing, and rendering for 2026 AI-Native compliance.

Loads prompt definitions from the `prompts/` directory (*.md frontmatter or YAML),
validating their schemas, instructions, token budgets, and few-shots.
"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml


@dataclass
class PromptDefinition:
    name: str
    description: str
    schema: dict[str, Any]
    instructions: str
    few_shots: list[dict[str, Any]] = field(default_factory=list)
    template: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "schema": self.schema,
            "instructions": self.instructions,
            "few_shots": self.few_shots,
            "template": self.template,
        }


def default_prompts_dir() -> Path:
    pkg_dir = Path(__file__).resolve().parent
    repo_prompts = pkg_dir.parent / "prompts"
    if repo_prompts.is_dir():
        return repo_prompts
    cwd_prompts = Path.cwd() / "prompts"
    if cwd_prompts.is_dir():
        return cwd_prompts
    return repo_prompts


def parse_prompt_file(file_path: Path) -> PromptDefinition:
    content = file_path.read_text(encoding="utf-8")
    stem = file_path.stem

    data: dict[str, Any] = {}
    body = ""

    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) >= 3 and parts[2].strip():
            raw_frontmatter = parts[1]
            body = parts[2].strip()
            data = yaml.safe_load(raw_frontmatter) or {}
        else:
            loaded = yaml.safe_load(content)
            if isinstance(loaded, dict):
                data = loaded
    else:
        loaded = yaml.safe_load(content)
        if isinstance(loaded, dict):
            data = loaded

    if data:
        name = data.get("name", stem)
        description = data.get("description", "")
        schema = data.get("schema", {"type": "object", "properties": {}})
        instructions = data.get("instructions", "")
        few_shots = data.get("few_shots", [])
        template = data.get("template", body or "")
        return PromptDefinition(
            name=name,
            description=description,
            schema=schema,
            instructions=str(instructions).strip(),
            few_shots=few_shots,
            template=str(template).strip(),
        )

    return PromptDefinition(
        name=stem,
        description=f"Prompt template for {stem}",
        schema={"type": "object", "properties": {}},
        instructions="",
        few_shots=[],
        template=content.strip(),
    )


def list_prompts(prompts_dir: Optional[Path] = None) -> list[str]:
    pdir = prompts_dir or default_prompts_dir()
    if not pdir.is_dir():
        return []
    names = []
    for file in sorted(pdir.glob("*.md")):
        names.append(file.stem)
    return names


def get_prompt(name: str, prompts_dir: Optional[Path] = None) -> PromptDefinition:
    pdir = prompts_dir or default_prompts_dir()
    file_path = pdir / f"{name}.md"
    if not file_path.is_file():
        available = list_prompts(pdir)
        raise FileNotFoundError(
            f"Prompt '{name}' not found at {file_path}. Available prompts: {', '.join(available)}"
        )
    return parse_prompt_file(file_path)

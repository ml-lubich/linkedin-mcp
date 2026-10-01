"""Automated prompt evaluation tests asserting template parsing, token budgets,
character constraints, and CLI subcommand behavior with --json.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from linkedin_mcp import prompt_manager
from linkedin_mcp.cli import app

runner = CliRunner()

REQUIRED_PROMPTS = [
    "cold-outreach",
    "triage-inbox",
    "connection-invite",
]


def test_required_prompts_exist_in_directory():
    pdir = prompt_manager.default_prompts_dir()
    assert pdir.is_dir(), f"Prompts directory not found at {pdir}"
    available = prompt_manager.list_prompts(pdir)
    for req in REQUIRED_PROMPTS:
        assert req in available, f"Missing required prompt {req} in {available}"


@pytest.mark.parametrize("prompt_name", REQUIRED_PROMPTS)
def test_prompt_definitions_parse_correctly(prompt_name):
    prompt_def = prompt_manager.get_prompt(prompt_name)
    assert prompt_def.name == prompt_name
    assert prompt_def.description, f"Prompt {prompt_name} missing description"
    assert isinstance(prompt_def.schema, dict)
    assert prompt_def.schema.get("type") == "object"
    assert "properties" in prompt_def.schema
    assert prompt_def.instructions, f"Prompt {prompt_name} missing instructions"
    assert len(prompt_def.few_shots) >= 1, f"Prompt {prompt_name} should have few-shots"


def test_connection_invite_complies_with_character_budget():
    """LinkedIn connection notes have a strict hard limit of 300 characters."""
    prompt_def = prompt_manager.get_prompt("connection-invite")
    # All few-shot outputs must strictly be <= 300 characters
    for shot in prompt_def.few_shots:
        output_text = shot.get("output", "")
        assert len(output_text) <= 300, (
            f"Few-shot output exceeds 300 characters ({len(output_text)} chars): {output_text}"
        )
        assert len(output_text) >= 100, f"Few-shot note seems too short: {output_text}"


def test_cold_outreach_complies_with_character_budget():
    """Cold outreach notes should adhere to a strict character budget (under 600 chars)."""
    prompt_def = prompt_manager.get_prompt("cold-outreach")
    for shot in prompt_def.few_shots:
        output_text = shot.get("output", "").strip()
        assert len(output_text) <= 600, (
            f"Cold outreach few-shot exceeds 600 characters ({len(output_text)} chars)"
        )


def test_triage_inbox_schema_and_few_shot_structure():
    """Triage inbox few shots must emit valid structured categorization matching instructions."""
    prompt_def = prompt_manager.get_prompt("triage-inbox")
    for shot in prompt_def.few_shots:
        output_text = shot.get("output", "").strip()
        parsed = json.loads(output_text)
        assert "category" in parsed
        assert "intent" in parsed
        assert "priority" in parsed
        assert parsed["priority"] in ["high", "medium", "low"]
        assert "suggested_action" in parsed


def test_cli_prompt_list_json():
    result = runner.invoke(app, ["prompt", "--list", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert "prompts" in data
    for req in REQUIRED_PROMPTS:
        assert req in data["prompts"]


@pytest.mark.parametrize("prompt_name", REQUIRED_PROMPTS)
def test_cli_prompt_get_json(prompt_name):
    result = runner.invoke(app, ["prompt", prompt_name, "--json"])
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["name"] == prompt_name
    assert "description" in data
    assert "schema" in data
    assert "instructions" in data
    assert "few_shots" in data
    assert "template" in data


def test_cli_prompt_not_found():
    result = runner.invoke(app, ["prompt", "nonexistent-prompt", "--json"])
    assert result.exit_code != 0

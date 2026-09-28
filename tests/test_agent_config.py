from __future__ import annotations

from pathlib import Path

from linkedin_mcp.agent_config import PitchRule, load_config


def test_defaults_with_no_file(tmp_path: Path):
    cfg = load_config(path=tmp_path / "missing.toml", env={})
    assert cfg.cdp_port == 9222
    assert cfg.referral.enabled is False
    assert cfg.reserved_for_self == []


def test_loads_from_toml(tmp_path: Path):
    toml_path = tmp_path / "config.toml"
    toml_path.write_text(
        """
[chrome]
port = 9333

[user]
self_name = "Me"

[referral]
enabled = true
name = "Ref Person"
email = "ref@example.com"
linkedin_url = "https://www.linkedin.com/in/ref/"
resume_path = "/tmp/r.pdf"

[[referral.pitch]]
keywords = ["ai"]
text = "does ai things"

[[referral.pitch]]
keywords = ["default"]
text = "generalist"

[exclusions]
reserved_for_self = ["Acme"]
never_contact = ["Bad Actor"]

[popups]
share_contact = "share"
"""
    )
    cfg = load_config(path=toml_path, env={})
    assert cfg.cdp_port == 9333
    assert cfg.self_name == "Me"
    assert cfg.referral.enabled is True
    assert cfg.referral.name == "Ref Person"
    assert cfg.reserved_for_self == ["Acme"]
    assert cfg.never_contact == ["Bad Actor"]
    assert cfg.share_contact == "share"
    assert cfg.referral.pitch_for("an ai role") == "does ai things"
    assert cfg.referral.pitch_for("something else") == "generalist"


def test_env_overrides_file(tmp_path: Path):
    toml_path = tmp_path / "config.toml"
    toml_path.write_text('[chrome]\nport = 1111\n')
    env = {
        "LINKEDIN_AGENT_CDP_PORT": "2222",
        "LINKEDIN_AGENT_SELF_NAME": "Env Name",
        "LINKEDIN_AGENT_REFEREE_NAME": "Env Referee",
        "LINKEDIN_AGENT_REFEREE_EMAIL": "env@example.com",
        "LINKEDIN_AGENT_REFEREE_LINKEDIN": "https://www.linkedin.com/in/env/",
        "LINKEDIN_AGENT_REFEREE_RESUME": "/tmp/env.pdf",
        "LINKEDIN_AGENT_RESERVED_COMPANIES": "A, B ,C",
        "LINKEDIN_AGENT_NEVER_CONTACT": "X,Y",
    }
    cfg = load_config(path=toml_path, env=env)
    assert cfg.cdp_port == 2222
    assert cfg.self_name == "Env Name"
    assert cfg.referral.enabled is True
    assert cfg.referral.name == "Env Referee"
    assert cfg.referral.email == "env@example.com"
    assert cfg.referral.linkedin_url == "https://www.linkedin.com/in/env/"
    assert cfg.referral.resume_path == "/tmp/env.pdf"
    assert cfg.reserved_for_self == ["A", "B", "C"]
    assert cfg.never_contact == ["X", "Y"]


def test_pitch_rule_matches_is_case_insensitive():
    rule = PitchRule(keywords=["Data", "MLOps"], text="x")
    assert rule.matches("this role touches DATA pipelines")
    assert not rule.matches("frontend design work")


def test_pitch_for_with_no_rules_falls_back():
    from linkedin_mcp.agent_config import ReferralConfig

    referral = ReferralConfig()
    assert referral.pitch_for("anything") == "is a strong candidate worth a look"


def test_pitch_rule_default_keyword_matches_directly():
    rule = PitchRule(keywords=["default"], text="fallback text")
    assert rule.matches("literally anything at all") is True
    assert rule.matches("") is True


def test_env_overrides_cdp_port_alone(tmp_path):
    cfg = load_config(path=tmp_path / "missing.toml", env={"LINKEDIN_AGENT_CDP_PORT": "5555"})
    assert cfg.cdp_port == 5555


def test_env_overrides_governor_db_path_alone(tmp_path):
    cfg = load_config(
        path=tmp_path / "missing.toml", env={"LINKEDIN_AGENT_GOVERNOR_DB": "/tmp/custom-governor.db"}
    )
    assert cfg.governor_db_path == "/tmp/custom-governor.db"

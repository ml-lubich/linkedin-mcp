"""Load linkedin-agent config from ~/.config/linkedin-agent/config.toml, with
environment variables overriding file values. No personal defaults live in
code -- every identity/PII field must come from the file or an env var.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

CONFIG_PATH = Path.home() / ".config" / "linkedin-agent" / "config.toml"


def _split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


@dataclass
class PitchRule:
    keywords: list[str]
    text: str

    def matches(self, blob: str) -> bool:
        if self.keywords == ["default"]:
            return True
        lowered = blob.lower()
        return any(keyword.lower() in lowered for keyword in self.keywords)


@dataclass
class ReferralConfig:
    enabled: bool = False
    name: str = ""
    email: str = ""
    linkedin_url: str = ""
    resume_path: str = ""
    attachment_name: str = "resume.pdf"
    pitch: list[PitchRule] = field(default_factory=list)

    def pitch_for(self, blob: str) -> str:
        for rule in self.pitch:
            if rule.keywords != ["default"] and rule.matches(blob):
                return rule.text
        for rule in self.pitch:
            if rule.keywords == ["default"]:
                return rule.text
        return "is a strong candidate worth a look"


@dataclass
class Config:
    cdp_port: int = 9222
    self_name: str = ""
    referral: ReferralConfig = field(default_factory=ReferralConfig)
    reserved_for_self: list[str] = field(default_factory=list)
    never_contact: list[str] = field(default_factory=list)
    share_contact: str = "decline"
    governor_db_path: str = ""


def _load_toml(path: Path) -> dict:
    if not path.exists():
        return {}
    with path.open("rb") as handle:
        return tomllib.load(handle)


def load_config(path: Path | None = None, env: dict | None = None) -> Config:
    """Read config.toml (if present) then apply LINKEDIN_AGENT_* env overrides."""
    raw = _load_toml(path or CONFIG_PATH)
    env = os.environ if env is None else env

    chrome = raw.get("chrome") or {}
    user = raw.get("user") or {}
    referral_raw = raw.get("referral") or {}
    exclusions = raw.get("exclusions") or {}
    popups = raw.get("popups") or {}
    governor_raw = raw.get("governor") or {}

    pitch_rules = [
        PitchRule(keywords=list(entry.get("keywords") or []), text=str(entry.get("text") or ""))
        for entry in referral_raw.get("pitch") or []
    ]

    referral = ReferralConfig(
        enabled=bool(referral_raw.get("enabled", False)),
        name=str(referral_raw.get("name") or ""),
        email=str(referral_raw.get("email") or ""),
        linkedin_url=str(referral_raw.get("linkedin_url") or ""),
        resume_path=str(referral_raw.get("resume_path") or ""),
        attachment_name=str(referral_raw.get("attachment_name") or "resume.pdf"),
        pitch=pitch_rules,
    )

    cfg = Config(
        cdp_port=int(chrome.get("port", 9222)),
        self_name=str(user.get("self_name") or ""),
        referral=referral,
        reserved_for_self=list(exclusions.get("reserved_for_self") or []),
        never_contact=list(exclusions.get("never_contact") or []),
        share_contact=str(popups.get("share_contact") or "decline"),
        governor_db_path=str(governor_raw.get("db_path") or ""),
    )

    if env.get("LINKEDIN_AGENT_GOVERNOR_DB"):
        cfg.governor_db_path = env["LINKEDIN_AGENT_GOVERNOR_DB"]
    if env.get("LINKEDIN_AGENT_CDP_PORT"):
        cfg.cdp_port = int(env["LINKEDIN_AGENT_CDP_PORT"])
    if env.get("LINKEDIN_AGENT_SELF_NAME"):
        cfg.self_name = env["LINKEDIN_AGENT_SELF_NAME"]
    if env.get("LINKEDIN_AGENT_REFEREE_NAME"):
        cfg.referral.name = env["LINKEDIN_AGENT_REFEREE_NAME"]
        cfg.referral.enabled = True
    if env.get("LINKEDIN_AGENT_REFEREE_EMAIL"):
        cfg.referral.email = env["LINKEDIN_AGENT_REFEREE_EMAIL"]
    if env.get("LINKEDIN_AGENT_REFEREE_LINKEDIN"):
        cfg.referral.linkedin_url = env["LINKEDIN_AGENT_REFEREE_LINKEDIN"]
    if env.get("LINKEDIN_AGENT_REFEREE_RESUME"):
        cfg.referral.resume_path = env["LINKEDIN_AGENT_REFEREE_RESUME"]
    if env.get("LINKEDIN_AGENT_RESERVED_COMPANIES"):
        cfg.reserved_for_self = _split_csv(env["LINKEDIN_AGENT_RESERVED_COMPANIES"])
    if env.get("LINKEDIN_AGENT_NEVER_CONTACT"):
        cfg.never_contact = _split_csv(env["LINKEDIN_AGENT_NEVER_CONTACT"])

    return cfg

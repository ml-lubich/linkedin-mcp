"""Load linkedin-agent config from ~/.config/linkedin-agent/config.toml, with
environment variables overriding file values. No personal defaults live in
code -- every identity/PII field must come from the file or an env var.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

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
    # Directory a message/referral attachment must resolve inside (see
    # messaging._validate_attachment_path). Empty means: fall back to
    # referral.resume_path's directory, else ~/Documents.
    attachments_dir: str = ""
    # How long an identical `messages send --to NAME` text is refused as a
    # likely double-send before it's allowed again (see core.messages_send
    # and Governor.check_windowed). Default 24h.
    to_dedupe_window_seconds: int = 86400


def _load_toml(path: Path) -> dict[str, Any]:  # TOML boundary
    if not path.exists():
        return {}
    with path.open("rb") as handle:
        return tomllib.load(handle)


def load_config(path: Path | None = None, env: Mapping[str, str] | None = None) -> Config:
    """Read config.toml (if present) then apply LINKEDIN_AGENT_* env overrides."""
    raw = _load_toml(path or CONFIG_PATH)
    environ: Mapping[str, str] = os.environ if env is None else env

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
        attachments_dir=str(raw.get("attachments_dir") or ""),
        to_dedupe_window_seconds=int(raw.get("to_dedupe_window_seconds") or 86400),
    )

    if environ.get("LINKEDIN_AGENT_GOVERNOR_DB"):
        cfg.governor_db_path = environ["LINKEDIN_AGENT_GOVERNOR_DB"]
    if environ.get("LINKEDIN_AGENT_CDP_PORT"):
        cfg.cdp_port = int(environ["LINKEDIN_AGENT_CDP_PORT"])
    if environ.get("LINKEDIN_AGENT_SELF_NAME"):
        cfg.self_name = environ["LINKEDIN_AGENT_SELF_NAME"]
    if environ.get("LINKEDIN_AGENT_REFEREE_NAME"):
        cfg.referral.name = environ["LINKEDIN_AGENT_REFEREE_NAME"]
        cfg.referral.enabled = True
    if environ.get("LINKEDIN_AGENT_REFEREE_EMAIL"):
        cfg.referral.email = environ["LINKEDIN_AGENT_REFEREE_EMAIL"]
    if environ.get("LINKEDIN_AGENT_REFEREE_LINKEDIN"):
        cfg.referral.linkedin_url = environ["LINKEDIN_AGENT_REFEREE_LINKEDIN"]
    if environ.get("LINKEDIN_AGENT_REFEREE_RESUME"):
        cfg.referral.resume_path = environ["LINKEDIN_AGENT_REFEREE_RESUME"]
    if environ.get("LINKEDIN_AGENT_RESERVED_COMPANIES"):
        cfg.reserved_for_self = _split_csv(environ["LINKEDIN_AGENT_RESERVED_COMPANIES"])
    if environ.get("LINKEDIN_AGENT_NEVER_CONTACT"):
        cfg.never_contact = _split_csv(environ["LINKEDIN_AGENT_NEVER_CONTACT"])
    if environ.get("LINKEDIN_AGENT_ATTACHMENTS_DIR"):
        cfg.attachments_dir = environ["LINKEDIN_AGENT_ATTACHMENTS_DIR"]
    if environ.get("LINKEDIN_AGENT_TO_DEDUPE_WINDOW"):
        cfg.to_dedupe_window_seconds = int(environ["LINKEDIN_AGENT_TO_DEDUPE_WINDOW"])

    return cfg

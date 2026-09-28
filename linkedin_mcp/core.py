"""Shared core: every CLI command and every MCP tool calls one of these
functions, never each other's plumbing directly. That is what keeps the two
surfaces from drifting apart (see tests/test_mcp_parity.py).

Two families of write action live here, gated two different ways:

* Voyager/browser writes (publish_post, react, unreact, save_activity,
  unsave_activity, comment) had no confirm gate at all upstream -- they gain
  one here, via guard.require_confirm, applied once instead of six times.
* CDP-driven agent writes (messages_send, post_cdp_publish, referral_send)
  already had a confirm gate (SendNotConfirmedError, from messaging.py) --
  `confirm` is passed straight through to it rather than gated twice.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from . import auth_capture as auth_capture_mod
from . import classify as classify_mod
from . import copywriter as copywriter_mod
from . import doctor as doctor_mod
from . import messaging as messaging_mod
from . import messages_actions as messages_actions_mod
from . import post_cdp as post_cdp_mod
from . import referral as referral_mod
from . import scan as scan_mod
from .agent_config import Config as AgentConfig
from .agent_config import load_config as load_agent_config
from .governor import Governor, default_db_path
from .auth import collect_auth_diagnostics
from .client import LinkedInClient
from .guard import require_confirm
from .models import Post, Profile, SearchResult
from .voyager_config import AppConfig, load_config as load_voyager_config


def _voyager_config(config_path: Optional[str] = None) -> AppConfig:
    return load_voyager_config(Path(config_path) if config_path else None)


def _voyager_client(config_path: Optional[str] = None) -> LinkedInClient:
    return LinkedInClient(_voyager_config(config_path))


def _agent_config(config_path: Optional[str] = None) -> AgentConfig:
    return load_agent_config(Path(config_path) if config_path else None)


# ---- Voyager API surface (read-only) ----------------------------------


def auth_status(config_path: Optional[str] = None) -> dict:
    return _voyager_client(config_path).auth_status()


def auth_diagnostics(config_path: Optional[str] = None) -> dict:
    return collect_auth_diagnostics(_voyager_config(config_path))


def feed(limit: Optional[int] = None, config_path: Optional[str] = None) -> list[Post]:
    return _voyager_client(config_path).feed(limit=limit)


def search(query: str, limit: Optional[int] = None, config_path: Optional[str] = None) -> list[SearchResult]:
    return _voyager_client(config_path).search(query, limit=limit)


def get_profile(identifier: str, config_path: Optional[str] = None) -> Profile:
    return _voyager_client(config_path).get_profile(identifier)


def get_profile_posts(
    identifier: str, limit: Optional[int] = None, config_path: Optional[str] = None
) -> list[Post]:
    return _voyager_client(config_path).get_profile_posts(identifier, limit=limit)


def get_activity(identifier: str, config_path: Optional[str] = None) -> Post:
    return _voyager_client(config_path).get_activity(identifier)


# ---- Voyager/browser write surface (newly confirm-gated) ---------------


def publish_post(
    text: str, visibility: str = "connections", confirm: bool = False, config_path: Optional[str] = None
) -> str:
    require_confirm(confirm, "post")
    return _voyager_client(config_path).post(text, visibility=visibility)


def react(
    identifier: str, reaction_type: str = "like", confirm: bool = False, config_path: Optional[str] = None
) -> str:
    require_confirm(confirm, "react")
    return _voyager_client(config_path).react(identifier, reaction_type)


def unreact(identifier: str, confirm: bool = False, config_path: Optional[str] = None) -> str:
    require_confirm(confirm, "unreact")
    return _voyager_client(config_path).unreact(identifier)


def save_activity(identifier: str, confirm: bool = False, config_path: Optional[str] = None) -> str:
    require_confirm(confirm, "save")
    return _voyager_client(config_path).save(identifier)


def unsave_activity(identifier: str, confirm: bool = False, config_path: Optional[str] = None) -> str:
    require_confirm(confirm, "unsave")
    return _voyager_client(config_path).unsave(identifier)


def comment(identifier: str, text: str, confirm: bool = False, config_path: Optional[str] = None) -> str:
    require_confirm(confirm, "comment")
    return _voyager_client(config_path).comment(identifier, text)


# ---- CDP agent surface: drives the user's own logged-in Chrome ---------


def doctor(config_path: Optional[str] = None) -> dict:
    return doctor_mod.check(_agent_config(config_path))


def classify_message(text: str, name: str = "", headline: str = "", config_path: Optional[str] = None) -> dict:
    config = _agent_config(config_path)
    reason = classify_mod.exclude_reason(name, headline, text, config)
    return {
        "hiring": classify_mod.looks_like_hiring(text),
        "excluded": bool(reason),
        "exclude_reason": reason,
        "already_referred": classify_mod.already_referred(text, config),
    }


def post_cdp_draft(text: str) -> dict:
    """Lint post text against the anti-cringe rules. Never touches the browser."""
    return {"text": text, "problems": post_cdp_mod.lint_post(text)}


def post_cdp_publish(
    text: str,
    image: Optional[str] = None,
    confirm: bool = False,
    port: Optional[int] = None,
    config_path: Optional[str] = None,
) -> dict:
    """Fill the composer and, only with confirm=True, publish (own logged-in
    Chrome via CDP). Without confirm, raises SendNotConfirmedError after
    filling the box -- the browser-side preview, not the CLI confirm gate."""
    config = _agent_config(config_path)
    return post_cdp_mod.publish_post(text=text, config=config, confirm=confirm, image_path=image, port=port)


def messages_read(
    url: str = "", limit: int = 40, port: Optional[int] = None, config_path: Optional[str] = None
) -> dict:
    config = _agent_config(config_path)
    cdp_port = port if port is not None else config.cdp_port
    if url:
        messaging_mod.open_thread(url, cdp_port)
    return messaging_mod.read_thread(cdp_port, limit=limit)


def messages_send(
    text: str,
    to: str = "",
    attach: Optional[str] = None,
    attach_name: Optional[str] = None,
    target: str = "",
    confirm: bool = False,
    port: Optional[int] = None,
    config_path: Optional[str] = None,
) -> dict:
    """Type `text` into the compose box and, only with confirm=True, send.
    With `to`, selects that thread by name first (absorbed from `li tell`);
    without it, types into whatever thread is already open (the original
    linkedin-agent behavior)."""
    config = _agent_config(config_path)
    if to:
        cdp_port = port if port is not None else config.cdp_port
        selection = messaging_mod.select_thread(cdp_port, to)
        if selection.get("ambiguous"):
            raise ValueError(f"'{to}' is ambiguous; matches: {selection.get('matches')}")
        if not selection.get("ok"):
            raise ValueError(f"no thread matched '{to}'")
    # Pace/dedupe through a real Governor whenever there's an identity to pace
    # against -- `target`, or `to` when target wasn't given explicitly --
    # otherwise send_message's own governor check is silently a no-op.
    # Explicit `target` gets permanent dedupe (a repeat is a bug -- the same
    # resume/post/thread-id being sent twice). `to`-only is paced by the
    # rolling budget but never permanently blocked -- replying to the same
    # person again next week is normal, not a repeat to refuse forever.
    identity = target or to
    dedupe = bool(target)
    governor = Governor(default_db_path(getattr(config, "governor_db_path", ""))) if identity else None
    try:
        return messaging_mod.send_message(
            text=text,
            config=config,
            confirm=confirm,
            attachment_path=attach,
            attachment_name_hint=attach_name,
            port=port,
            governor=governor,
            target=identity,
            dedupe=dedupe,
        )
    finally:
        if governor is not None:
            governor.close()


def messages_threads(
    needle: str = "",
    limit: int = 20,
    unread: bool = False,
    no_navigate: bool = False,
    port: Optional[int] = None,
    config_path: Optional[str] = None,
) -> dict:
    config = _agent_config(config_path)
    cdp_port = port if port is not None else config.cdp_port
    return messaging_mod.list_threads(cdp_port, kind="unread" if unread else "threads", needle=needle, limit=limit, no_navigate=no_navigate)


def messages_select(name: str, port: Optional[int] = None, config_path: Optional[str] = None) -> dict:
    config = _agent_config(config_path)
    cdp_port = port if port is not None else config.cdp_port
    return messaging_mod.select_thread(cdp_port, name)


def messages_open(port: Optional[int] = None, config_path: Optional[str] = None) -> dict:
    config = _agent_config(config_path)
    cdp_port = port if port is not None else config.cdp_port
    return messaging_mod.ensure_messaging(cdp_port)


def messages_popups(
    apply: bool = False, port: Optional[int] = None, config_path: Optional[str] = None
) -> dict:
    config = _agent_config(config_path)
    cdp_port = port if port is not None else config.cdp_port
    return messaging_mod.popups(cdp_port, apply=apply, policy=None)


def messages_workflow(spec_path: str, text: str = "", port: Optional[int] = None, config_path: Optional[str] = None) -> dict:
    """Classify the open thread (or `text`) and draft a reply. Never sends."""
    config = _agent_config(config_path)
    cdp_port = port if port is not None else config.cdp_port
    return messaging_mod.workflow_run(spec_path, text=text, port=cdp_port)


def messages_commands() -> dict:
    """List the `messages` agent verbs. No browser."""
    return {"commands": [dict(row) for row in messages_actions_mod.COMMANDS]}


def scan(port: Optional[int] = None, config_path: Optional[str] = None) -> dict:
    """Find threads that still need a reply/referral. Converts each
    Candidate to a plain dict here, once, so the CLI and the MCP tool can
    just emit the result instead of each doing their own asdict()."""
    import dataclasses

    config = _agent_config(config_path)
    candidates = scan_mod.find_referral_candidates(config, port=port)
    return {name: (dataclasses.asdict(c) if dataclasses.is_dataclass(c) else c) for name, c in candidates.items()}


def referral_draft(
    name: str,
    text: str,
    headline: str = "",
    reengage: bool = False,
    stale_days: int = 0,
    config_path: Optional[str] = None,
) -> dict:
    config = _agent_config(config_path)
    if not config.referral.enabled:
        raise RuntimeError("referral is disabled in config; set referral.enabled = true")
    draft = copywriter_mod.draft_referral(
        name=name, headline=headline, message=text, config=config, reengage=reengage, stale_days=stale_days
    )
    return {"draft": draft, "problems": copywriter_mod.assert_human_copy(draft, config)}


def referral_send(
    name: str,
    url: str,
    text: str = "",
    stamp: str = "",
    confirm: bool = False,
    port: Optional[int] = None,
    config_path: Optional[str] = None,
) -> dict:
    config = _agent_config(config_path)
    result = referral_mod.send_referral_for_candidate(
        name=name, url=url, thread_text=text, config=config, confirm=confirm, stamp=stamp, port=port
    )
    return {"name": result.name, "skipped": result.skipped, "draft": result.draft, "proof": result.proof}


# ---- Session cookie capture (CDP) --------------------------------------


def auth_capture(port: int = auth_capture_mod.DEFAULT_PORT, timeout: float = 600.0) -> dict:
    return auth_capture_mod.capture(port=port, timeout_seconds=timeout)


def auth_env() -> str:
    return auth_capture_mod.env_line()

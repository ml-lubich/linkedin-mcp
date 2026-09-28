"""Draft and, only with explicit confirmation, publish a LinkedIn feed post.

Ported from the linkedin-post SKILL.md workflow.
"""

from __future__ import annotations

import hashlib
import json
import time

from own_chrome.cdp import ChromeError, evaluate, navigate

from linkedin_mcp.cdp_session import set_file_input
from linkedin_mcp.agent_config import Config
from linkedin_mcp.governor import Governor, default_db_path
from linkedin_mcp.messaging import SendNotConfirmedError, _validate_attachment_path

TAB = "linkedin.com"
FEED_URL = "https://www.linkedin.com/feed/"
START_POST_SELECTOR = "button[aria-label*='Start a post' i]"
EDITOR_SELECTOR = ".ql-editor[contenteditable='true']"
POST_BUTTON_SELECTOR = "button.share-actions__primary-action"
IMAGE_INPUT_SELECTOR = "input[type='file'][accept*='image']"

BANNED_PHRASES = (
    "excited to announce",
    "thrilled to share",
    "in today's fast-paced world",
    "game-changer",
    "leveraging",
    "testament to",
    "delve",
    "embark",
)


def lint_post(text: str) -> list[str]:
    """Cheap guardrail against the cringe patterns the linkedin-post skill bans."""
    lowered = text.lower()
    problems = [phrase for phrase in BANNED_PHRASES if phrase in lowered]
    if len([w for w in text.split() if w.startswith("#")]) > 2:
        problems.append("too-many-hashtags")
    return problems


def open_composer(port: int) -> None:
    navigate(port, FEED_URL, host=TAB)
    script = (
        f"(() => {{const b = document.querySelector({json.dumps(START_POST_SELECTOR)}); if (b) b.click(); return !!b;}})()"
    )
    ok = evaluate(port, script, host=TAB)
    if not ok:
        raise ChromeError("could not find the 'Start a post' button")


def publish_post(
    text: str,
    config: Config,
    confirm: bool,
    image_path: str | None = None,
    port: int | None = None,
    governor: Governor | None = None,
) -> dict:
    """Publishing is a bulk/loop-shaped risk (a script that posts repeatedly),
    so it is always paced and deduped through Governor -- target is a hash of
    the exact text, so posting the same content twice is refused even if the
    caller forgot to dedupe upstream."""
    cdp_port = port if port is not None else config.cdp_port

    # Same allowlist check as messaging.send_message's attachment_path (see
    # review A1/H3): validated before anything is touched, confirmed or not.
    validated_image = _validate_attachment_path(image_path, config) if image_path else None

    open_composer(cdp_port)
    time.sleep(0.5)

    fill_script = (
        f"((t) => {{const box = document.querySelector({json.dumps(EDITOR_SELECTOR)});"
        "if (!box) return false; box.focus(); document.execCommand('insertText', false, t); return true;})("
        + json.dumps(text)
        + ")"
    )
    if not evaluate(cdp_port, fill_script, host=TAB):
        raise ChromeError("post editor not found")

    if not confirm:
        raise SendNotConfirmedError("publish_post requires confirm=True; nothing was posted")

    attached = False
    if validated_image is not None:
        attached = set_file_input(cdp_port, IMAGE_INPUT_SELECTOR, str(validated_image), host=TAB)
        time.sleep(1.0)

    target = hashlib.sha256(text.encode()).hexdigest()[:16]
    owns_governor = governor is None
    gov = governor or Governor(default_db_path(config.governor_db_path))
    try:
        gov.check("post", target)
        click_script = (
            f"(() => {{const b = document.querySelector({json.dumps(POST_BUTTON_SELECTOR)}); if (b) b.click(); return !!b;}})()"
        )
        clicked = evaluate(cdp_port, click_script, host=TAB)
        if clicked:
            gov.record("post", target)
    finally:
        if owns_governor:
            gov.close()
    return {"clicked_post": bool(clicked), "attached_image": attached}

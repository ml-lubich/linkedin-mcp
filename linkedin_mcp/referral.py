"""Send a referral message (text + attached resume) for one candidate thread.

Ties together scan.Candidate, copywriter.draft_referral, and
messaging.send_message. Sending only happens with confirm=True.
"""

from __future__ import annotations

from dataclasses import dataclass

from linkedin_mcp.classify import already_referred
from linkedin_mcp.agent_config import Config
from linkedin_mcp.copywriter import draft_referral, stale_days_from
from linkedin_mcp.governor import Governor, RateLimited, default_db_path
from linkedin_mcp.messaging import open_thread, read_thread, send_message


@dataclass
class ReferralResult:
    name: str
    skipped: str = ""
    draft: str = ""
    proof: dict | None = None


def send_referral_for_candidate(
    name: str,
    url: str,
    thread_text: str,
    config: Config,
    confirm: bool,
    stamp: str = "",
    port: int | None = None,
    governor: Governor | None = None,
) -> ReferralResult:
    """Referral sends are the bulk/loop-shaped case (one call per candidate
    thread from scan.find_referral_candidates), so this always paces and
    dedupes through Governor -- pass one in for a shared ledger across many
    calls, or leave it None to open+close one against config.governor_db_path
    for just this call."""
    if not config.referral.enabled or not config.referral.resume_path:
        return ReferralResult(name=name, skipped="referral disabled or resume_path not configured")

    cdp_port = port if port is not None else config.cdp_port
    open_thread(url, cdp_port)
    live = read_thread(cdp_port)
    blob = "\n".join([live.get("bodies") and live["bodies"][-1] or "", thread_text])
    if already_referred(blob, config):
        return ReferralResult(name=name, skipped="already referred")

    reengage = bool(config.self_name) and bool(live.get("speakers")) and live["speakers"][-1] == config.self_name
    draft = draft_referral(
        name=name,
        headline="",
        message=blob,
        config=config,
        reengage=reengage,
        stale_days=stale_days_from(stamp),
    )

    owns_governor = governor is None
    gov = governor or Governor(default_db_path(config.governor_db_path))
    try:
        proof = send_message(
            text=draft,
            config=config,
            confirm=confirm,
            attachment_path=config.referral.resume_path,
            attachment_name_hint=config.referral.attachment_name,
            port=cdp_port,
            governor=gov,
            target=url,
            action="referral",
        )
    except RateLimited as exc:
        return ReferralResult(name=name, draft=draft, skipped=f"rate-limited: {exc}")
    finally:
        if owns_governor:
            gov.close()
    return ReferralResult(name=name, draft=draft, proof=proof)

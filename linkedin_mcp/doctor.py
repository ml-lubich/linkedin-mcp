"""`linkedin doctor` -- checks the environment before anything tries to click
a real button: is Chrome's CDP port reachable, is own-chrome installed, is
LinkedIn open and logged in.
"""

from __future__ import annotations

import shutil

from own_chrome.cdp import ChromeError, describe, filter_pages, pages

from linkedin_mcp.agent_config import Config
from linkedin_mcp.cdp_session import JSON

TAB = "linkedin.com"


def check(config: Config) -> JSON:
    report: JSON = {"port": config.cdp_port, "checks": []}

    def add(name: str, ok: bool, detail: str = "") -> None:
        report["checks"].append({"name": name, "ok": ok, "detail": detail})

    own_chrome_installed = shutil.which("own-chrome") is not None
    add("own-chrome installed", own_chrome_installed, "" if own_chrome_installed else "run: uv tool install git+https://github.com/ml-lubich/own-chrome")

    try:
        info = describe(config.cdp_port)
        add("chrome cdp reachable", True, f"pid {info.get('pid')} on port {config.cdp_port}")
    except ChromeError as exc:
        add("chrome cdp reachable", False, str(exc))
        report["ok"] = False
        return report

    try:
        linkedin_tabs = filter_pages(pages(config.cdp_port), TAB, 5)
        add("linkedin.com tab open", bool(linkedin_tabs), f"{len(linkedin_tabs)} tab(s)")
    except ChromeError as exc:
        add("linkedin.com tab open", False, str(exc))
        linkedin_tabs = []

    logged_in = any("/login" not in (t.get("url") or "") and "uas/login" not in (t.get("url") or "") for t in linkedin_tabs)
    add("logged in (no /login tab)", logged_in or not linkedin_tabs, "" if logged_in else "a LinkedIn tab is on a login page")

    if not config.referral.enabled:
        add("referral config", True, "disabled (fine if you don't use send-referral)")
    else:
        missing = [
            field
            for field in ("name", "email", "linkedin_url", "resume_path")
            if not getattr(config.referral, field)
        ]
        add("referral config", not missing, f"missing: {', '.join(missing)}" if missing else "")

    report["ok"] = all(c["ok"] for c in report["checks"])
    return report

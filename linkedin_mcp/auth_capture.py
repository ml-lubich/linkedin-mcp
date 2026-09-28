"""LinkedIn session cookie capture over CDP, for LINKEDIN_COOKIE_HEADER.

Chrome 127+ encrypts its Cookies DB with an app-bound key, so reading the
SQLite file directly (browser-cookie3's approach, used by `linkedin
auth-status`) does not always work. This asks Chrome for its own cookies
over the DevTools Protocol instead -- the same CDP connection linkedin_mcp
already uses for messaging/posting (see cdp_session.py).

Cookie values are written to a 0600 file and are never printed, except by
the explicit `env` command / `env_line()` call, which is the one place a
value is meant to leave the machine (into a shell export).
"""

from __future__ import annotations

import os
import shlex
import time
from pathlib import Path

from own_chrome.cdp import ChromeError, filter_pages, pages

from linkedin_mcp.cdp_session import CdpSession

DEFAULT_PORT = 9333
TAB = "linkedin.com"
COOKIE_HOME = Path.home() / ".config" / "linkedin-mcp"
COOKIE_FILE = COOKIE_HOME / "cookies"
REQUIRED_COOKIE_NAMES = ("li_at", "JSESSIONID")


class AuthCaptureError(RuntimeError):
    """Raised when session capture/read fails."""


def _fetch_cookies(port: int) -> list[dict]:
    if not filter_pages(pages(port), TAB, 5):
        raise ChromeError(f"no linkedin.com tab open on CDP port {port}")
    with CdpSession(port, host=TAB) as session:
        result = session.call("Network.getCookies", {"urls": ["https://www.linkedin.com/"]})
    return list(result.get("cookies") or [])


def capture(port: int = DEFAULT_PORT, timeout_seconds: float = 600.0, poll_seconds: float = 3.0) -> dict:
    """Poll a CDP-attached Chrome until the user is logged in to LinkedIn,
    then persist the cookie header. Returns a report dict; never returns
    cookie values."""
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        try:
            cookies = _fetch_cookies(port)
        except ChromeError:
            cookies = []
        names = {c.get("name") for c in cookies}
        if all(name in names for name in REQUIRED_COOKIE_NAMES):
            header = "; ".join(f"{c['name']}={c['value']}" for c in cookies)
            COOKIE_HOME.mkdir(parents=True, exist_ok=True, mode=0o700)
            os.chmod(COOKIE_HOME, 0o700)  # mkdir's mode is weakened by umask; enforce it directly
            # Create with 0600 from the first byte -- no write-then-chmod window
            # where the file is briefly group/world-readable under the default umask.
            fd = os.open(COOKIE_FILE, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
            try:
                os.write(fd, header.encode("utf-8"))
            finally:
                os.close(fd)
            return {"captured": True, "cookie_count": len(cookies), "path": str(COOKIE_FILE)}
        time.sleep(poll_seconds)
    return {
        "captured": False,
        "cookie_count": 0,
        "path": str(COOKIE_FILE),
        "error": f"no LinkedIn session after {timeout_seconds:.0f}s",
    }


def env_line() -> str:
    """Return the `export LINKEDIN_COOKIE_HEADER=...` line for the saved session."""
    if not COOKIE_FILE.is_file():
        raise AuthCaptureError(f"no saved session at {COOKIE_FILE}; run `linkedin auth capture` first")
    header = COOKIE_FILE.read_text(encoding="utf-8").strip()
    return f"export LINKEDIN_COOKIE_HEADER={shlex.quote(header)}"

"""Confirm guard for the Voyager/browser write actions (post, react, unreact,
save, unsave, comment). Every one of those routes through here, so "nothing
happens without confirm=True" is enforced once, in the shared core, instead of
separately in each CLI command and each MCP tool.

The CDP-driven agent actions (messages send, post-cdp publish, referral send)
have their own long-established guard (`SendNotConfirmedError` in
messaging.py) which this does not duplicate -- core.py passes `confirm`
straight through to those instead.
"""

from __future__ import annotations


class ConfirmRequiredError(RuntimeError):
    """Raised when a write action is attempted without confirm=True."""

    def __init__(self, action: str) -> None:
        self.action = action
        super().__init__(f"{action} requires confirm=True; nothing was done.")


def require_confirm(confirm: bool, action: str) -> None:
    """Raise ConfirmRequiredError unless confirm is True."""
    if not confirm:
        raise ConfirmRequiredError(action)

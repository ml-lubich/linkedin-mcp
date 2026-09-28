from __future__ import annotations

import pytest

from linkedin_mcp.guard import ConfirmRequiredError, require_confirm


def test_require_confirm_passes_when_true() -> None:
    require_confirm(True, "post")  # must not raise


@pytest.mark.parametrize("falsy", [False, 0, None, "", [], {}])
def test_require_confirm_raises_for_every_falsy_value(falsy) -> None:
    with pytest.raises(ConfirmRequiredError) as excinfo:
        require_confirm(falsy, "react")
    assert excinfo.value.action == "react"
    assert "react" in str(excinfo.value)
    assert "confirm=True" in str(excinfo.value)

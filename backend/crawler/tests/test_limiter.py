import pytest


@pytest.mark.skip(reason="Phase 1")
def test_acquire_stays_under_80_percent_and_spreads_evenly() -> None:
    """Will check: acquire never exceeds 80% of any rule and spaces requests evenly."""


@pytest.mark.skip(reason="Phase 1")
def test_follows_live_headers_and_429() -> None:
    """Will check: update_from_headers and on_rate_limited change the allowed pace."""

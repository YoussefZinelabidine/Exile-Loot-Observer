import pytest


@pytest.mark.skip(reason="Phase 1")
def test_parse_rate_limit_headers() -> None:
    """Will check: recorded headers parse into the expected PolicySnapshot; none -> None."""


@pytest.mark.skip(reason="Phase 1")
def test_parse_retry_after() -> None:
    """Will check: Retry-After is returned as seconds; absent -> None."""

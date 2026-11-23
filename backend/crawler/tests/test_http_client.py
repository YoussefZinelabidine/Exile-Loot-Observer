import pytest


@pytest.mark.skip(reason="Phase 1")
def test_check_order() -> None:
    """Will check: breaker, then budget, then limiter, then request, using a mocked transport."""


@pytest.mark.skip(reason="Phase 1")
def test_429_trips_breaker() -> None:
    """Will check: a 429 response trips the breaker and raises RateLimitedError."""

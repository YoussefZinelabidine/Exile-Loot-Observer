import pytest


@pytest.mark.skip(reason="Phase 1")
def test_trip_opens_for_retry_after_and_alerts() -> None:
    """Will check: trip opens the breaker for >= Retry-After (default 1 h) and sends an alert."""


@pytest.mark.skip(reason="Phase 1")
def test_check_raises_when_open() -> None:
    """Will check: check raises CircuitOpenError with retry_at while open."""

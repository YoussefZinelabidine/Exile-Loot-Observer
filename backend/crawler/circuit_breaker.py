"""Circuit breaker: any 429 stops all jobs."""

from datetime import datetime


class CircuitBreaker:
    """Stops all crawler jobs after a 429."""

    def trip(self, retry_after_seconds: float | None, reason: str) -> None:
        """Open the breaker and stop all jobs for at least Retry-After (default 1 h).

        Also calls `backend.common.alerts.send_alert`.
        """
        raise NotImplementedError("Phase 1")

    def is_open(self) -> bool:
        """Return True while the breaker is open."""
        raise NotImplementedError("Phase 1")

    def retry_at(self) -> datetime | None:
        """Return when the breaker may close, or None if it is closed."""
        raise NotImplementedError("Phase 1")

    def check(self) -> None:
        """Raise CircuitOpenError if the breaker is open."""
        raise NotImplementedError("Phase 1")

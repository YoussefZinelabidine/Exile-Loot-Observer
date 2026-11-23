"""Crawler exceptions."""

from datetime import datetime


class CrawlerError(Exception):
    """Base class for all crawler errors."""


class CircuitOpenError(CrawlerError):
    """Raised when a request is attempted while the circuit breaker is open."""

    def __init__(self, retry_at: datetime | None, message: str = "Circuit breaker is open") -> None:
        super().__init__(message)
        self.retry_at = retry_at


class DailyBudgetExceededError(CrawlerError):
    """Raised when the daily character budget is exhausted."""


class RateLimitedError(CrawlerError):
    """Raised on an HTTP 429 response."""

    def __init__(
        self, retry_after_seconds: float | None, message: str = "Rate limited (429)"
    ) -> None:
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds

"""Crawler exceptions."""

from datetime import datetime


class CrawlerError(Exception):
    """Base class for all crawler errors."""


class CircuitOpenError(CrawlerError):
    """Raised when a request is attempted while the circuit breaker is open."""

    def __init__(self, retry_at: datetime | None, message: str = "Circuit breaker is open") -> None:
        super().__init__(message)
        self.retry_at = retry_at


class MissingContactInfoError(CrawlerError):
    """Raised when the contact email or project URL is missing: no GGG request may be sent."""


class DailyBudgetExceededError(CrawlerError):
    """Raised when the daily character budget is exhausted."""


class RateLimitedError(CrawlerError):
    """Raised on an HTTP 429 response."""

    def __init__(
        self, retry_after_seconds: float | None, message: str = "Rate limited (429)"
    ) -> None:
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


class EndpointNotAllowedError(CrawlerError):
    """Raised when a URL is not in the hard-coded GGG endpoint table. Nothing is sent."""


class HistoryRetentionError(CrawlerError):
    """Raised when a live rule's period is longer than the history the stores keep."""

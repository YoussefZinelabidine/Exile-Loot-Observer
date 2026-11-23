"""The shared rate limiter."""

from backend.crawler.rate_limit_headers import PolicySnapshot


class SharedRateLimiter:
    """The single rate limiter for every crawler and validation job.

    There is exactly one instance shared by every crawler and validation job.
    How it is shared across processes is an open question for Phase 1; no
    mechanism is chosen here.
    """

    def acquire(self, policy: str) -> None:
        """Block until a request is allowed at <= 80% of every rule, spread evenly."""
        raise NotImplementedError("Phase 1")

    def update_from_headers(self, snapshot: PolicySnapshot) -> None:
        """Update the limiter's view of a policy from live response headers."""
        raise NotImplementedError("Phase 1")

    def on_rate_limited(self, retry_after_seconds: float | None) -> None:
        """Record a 429 so no further requests are allowed for the penalty period."""
        raise NotImplementedError("Phase 1")

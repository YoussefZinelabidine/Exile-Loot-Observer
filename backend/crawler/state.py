"""Crawler state: the store protocol and its in-memory implementation.

All limiter, budget, breaker and hard-stop state goes through `CrawlerStateStore`, so it can
be shared by several processes (the Postgres store comes in job P1-C1b). The in-memory
store is used by every test and is only safe within one process.

Contract for implementations (written for the Postgres store):
- `with_lock()` is one transaction on the store's own connection that holds
  `pg_advisory_xact_lock`. Every store call made inside it uses that same transaction.
  A nested `with_lock()` on the same store is a no-op (it joins the outer one).
- Calls made outside `with_lock()` run on their own (autocommit) and are individually atomic.
- `trip_breaker` and `set_hard_stop` never shorten or overwrite an existing hold
  (Postgres: `GREATEST(open_until, ...)`, `INSERT ... ON CONFLICT DO NOTHING`).
- Request and outside-hit history older than HISTORY_RETENTION (24 h) may be dropped.
- All datetimes are timezone-aware UTC.
"""

import threading
from collections import defaultdict
from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Final, Protocol

from backend.crawler.rate_limit_headers import RateLimitRule

# Request and outside-hit history is kept this long by every store. The limiter refuses any
# live rule with a longer period, because it could not count its window.
HISTORY_RETENTION: Final[timedelta] = timedelta(hours=24)


@dataclass(frozen=True)
class BreakerState:
    """The circuit breaker is open until `open_until`."""

    open_until: datetime
    reason: str


@dataclass(frozen=True)
class HardStopState:
    """The crawler is stopped until a human clears it (never expires on its own)."""

    reason: str
    since: datetime


class CrawlerStateStore(Protocol):
    """Storage behind the limiter, budget, breaker and hard stop. See the module docstring."""

    def with_lock(self) -> AbstractContextManager[None]:
        """Serialise critical sections across processes (see the module contract)."""
        ...

    def record_request(self, policy: str, sent_at: datetime) -> None:
        """Remember that a request under `policy` was sent at `sent_at`."""
        ...

    def request_times(self, policy: str, since: datetime) -> list[datetime]:
        """Return send times of `policy` requests after `since` (exclusive), ascending."""
        ...

    def record_outside_hits(self, policy: str, period_seconds: int, n: int, at: datetime) -> None:
        """Record `n` hits in the `period_seconds` window that we did not send ourselves."""
        ...

    def outside_hits(
        self, policy: str, period_seconds: int, since: datetime
    ) -> list[tuple[datetime, int]]:
        """Return `(at, n)` outside-hit records for that window after `since`, ascending."""
        ...

    def get_live_limits(self, policy: str) -> dict[str, list[RateLimitRule]] | None:
        """Return the last limits seen in response headers (rule name -> rules), or None."""
        ...

    def set_live_limits(self, policy: str, rules: dict[str, list[RateLimitRule]]) -> None:
        """Store the limits seen in response headers for `policy`."""
        ...

    def budget_used(self, day: date) -> int:
        """Return the units consumed on the UTC calendar day `day`."""
        ...

    def budget_consume(self, day: date, n: int) -> None:
        """Add `n` units to the day's usage (no cap check: the budget class does that)."""
        ...

    def breaker_state(self) -> BreakerState | None:
        """Return the stored breaker state, or None if it was never tripped."""
        ...

    def trip_breaker(self, open_until: datetime, reason: str) -> None:
        """Open the breaker until `open_until` (never shortens an existing, later hold)."""
        ...

    def hard_stop_state(self) -> HardStopState | None:
        """Return the hard-stop flag, or None if the crawler is not hard-stopped."""
        ...

    def set_hard_stop(self, reason: str, at: datetime) -> bool:
        """Set the hard-stop flag. Return True if newly set, False if it already was set."""
        ...

    def clear_hard_stop(self) -> None:
        """Clear the hard-stop flag. Only the manual reset tool may call this."""
        ...


class InMemoryStateStore:
    """Process-local `CrawlerStateStore` for tests and single-process use."""

    _KEEP = HISTORY_RETENTION

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._requests: dict[str, list[datetime]] = defaultdict(list)
        self._outside: dict[tuple[str, int], list[tuple[datetime, int]]] = defaultdict(list)
        self._live: dict[str, dict[str, list[RateLimitRule]]] = {}
        self._budget: dict[date, int] = defaultdict(int)
        self._breaker: BreakerState | None = None
        self._hard_stop: HardStopState | None = None

    @contextmanager
    def with_lock(self) -> Iterator[None]:
        with self._lock:  # RLock: nested use on the same thread is a no-op
            yield

    def record_request(self, policy: str, sent_at: datetime) -> None:
        times = self._requests[policy]
        times.append(sent_at)
        times.sort()
        cutoff = sent_at - self._KEEP
        self._requests[policy] = [t for t in times if t > cutoff]

    def request_times(self, policy: str, since: datetime) -> list[datetime]:
        return [t for t in self._requests.get(policy, []) if t > since]

    def record_outside_hits(self, policy: str, period_seconds: int, n: int, at: datetime) -> None:
        records = self._outside[(policy, period_seconds)]
        records.append((at, n))
        records.sort()
        cutoff = at - self._KEEP
        self._outside[(policy, period_seconds)] = [r for r in records if r[0] > cutoff]

    def outside_hits(
        self, policy: str, period_seconds: int, since: datetime
    ) -> list[tuple[datetime, int]]:
        return [r for r in self._outside.get((policy, period_seconds), []) if r[0] > since]

    def get_live_limits(self, policy: str) -> dict[str, list[RateLimitRule]] | None:
        live = self._live.get(policy)
        return None if live is None else {k: list(v) for k, v in live.items()}

    def set_live_limits(self, policy: str, rules: dict[str, list[RateLimitRule]]) -> None:
        self._live[policy] = {k: list(v) for k, v in rules.items()}

    def budget_used(self, day: date) -> int:
        return self._budget.get(day, 0)

    def budget_consume(self, day: date, n: int) -> None:
        self._budget[day] += n

    def breaker_state(self) -> BreakerState | None:
        return self._breaker

    def trip_breaker(self, open_until: datetime, reason: str) -> None:
        if self._breaker is None or open_until > self._breaker.open_until:
            self._breaker = BreakerState(open_until, reason)

    def hard_stop_state(self) -> HardStopState | None:
        return self._hard_stop

    def set_hard_stop(self, reason: str, at: datetime) -> bool:
        if self._hard_stop is not None:
            return False
        self._hard_stop = HardStopState(reason, at)
        return True

    def clear_hard_stop(self) -> None:
        self._hard_stop = None

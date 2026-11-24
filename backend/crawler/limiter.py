"""The shared rate limiter."""

import math
from dataclasses import dataclass
from datetime import datetime, timedelta

from backend.crawler.budget import DailyCharacterBudget
from backend.crawler.clock import Clock, SleepFn, system_clock, system_sleep
from backend.crawler.constants import MEASURED_LIMITS, RATE_LIMIT_CAP_FRACTION
from backend.crawler.errors import (
    CircuitOpenError,
    CrawlerError,
    DailyBudgetExceededError,
    HistoryRetentionError,
)
from backend.crawler.rate_limit_headers import PolicySnapshot, hold_seconds
from backend.crawler.state import HISTORY_RETENTION, CrawlerStateStore


@dataclass(frozen=True)
class PeriodLimit:
    """Effective limit for one period: window cap and minimum spacing between requests."""

    max_hits: int  # the real limit, min(live, measured)
    cap: int  # most requests allowed in any window of the period
    spacing_seconds: float  # minimum gap between two of our requests


class SharedRateLimiter:
    """The single rate limiter for every crawler and validation job.

    There is exactly one logical limiter, shared by every crawler and validation job: all
    its state lives in the `CrawlerStateStore`, and the check-and-record step runs under
    `store.with_lock()` so several processes can share it once the Postgres store exists
    (P1-C1b). The lock is never held while sleeping: `acquire` computes the wait under the
    lock, releases it, sleeps, and re-checks everything (breaker, hard stop, limits).

    Per policy and per period the limit is `min(live header limit, measured limit)`, and we
    stay at 80% of it: window cap `max(1, floor(0.8 * limit))`, spacing
    `period / floor(0.8 * limit)`, or `period / (0.8 * limit)` when the floor is below 1.
    A limit or period that is not positive is refused. Hits reported by GGG's headers that we
    did not record ourselves count as outside hits, so the effective count per window is
    `max(own recorded, header hits)` and can only slow us down. Live limits are read on every
    call, so tightened limits apply immediately. A policy with neither a live nor a measured
    limit is refused.
    """

    def __init__(
        self,
        store: CrawlerStateStore,
        *,
        clock: Clock = system_clock,
        sleep: SleepFn = system_sleep,
    ) -> None:
        self._store = store
        self._clock = clock
        self._sleep = sleep

    @property
    def store(self) -> CrawlerStateStore:
        return self._store

    def period_limits(self, policy: str) -> dict[int, PeriodLimit]:
        """Return the effective limit per period after applying the 80% cap."""
        max_by_period: dict[int, int] = {}

        def merge(max_hits: int, period: int) -> None:
            if max_hits <= 0 or period <= 0:
                raise CrawlerError(
                    f"Invalid rate limit {max_hits}:{period} for {policy!r}; refusing to send"
                )
            if period > HISTORY_RETENTION.total_seconds():
                raise HistoryRetentionError(
                    f"Rate-limit period {period} s for {policy!r} is longer than the "
                    f"{int(HISTORY_RETENTION.total_seconds())} s of history kept; refusing to send"
                )
            max_by_period[period] = min(max_hits, max_by_period.get(period, max_hits))

        for max_hits, period in MEASURED_LIMITS.get(policy, ()):
            merge(max_hits, period)
        live = self._store.get_live_limits(policy)
        if live:
            for rules in live.values():
                for rule in rules:
                    merge(rule.max_hits, rule.period_seconds)
        if not max_by_period:
            raise CrawlerError(f"No known rate limit for policy {policy!r}; refusing to send")
        result = {}
        for period, max_hits in max_by_period.items():
            target = RATE_LIMIT_CAP_FRACTION * max_hits
            floored = math.floor(target)
            if floored >= 1:
                result[period] = PeriodLimit(max_hits, floored, period / floored)
            else:
                result[period] = PeriodLimit(max_hits, 1, period / target)
        return result

    def allowed_hits(self, policy: str) -> dict[int, int]:
        """Return `{period_seconds: window cap}`."""
        return {p: lim.cap for p, lim in self.period_limits(policy).items()}

    def _required_wait(self, policy: str, now: datetime) -> float:
        limits = self.period_limits(policy)
        longest = timedelta(seconds=max(limits))
        times = self._store.request_times(policy, now - longest)
        wait = 0.0
        for period, lim in limits.items():
            since = now - timedelta(seconds=period)
            if times:
                wait = max(wait, (times[-1] - now).total_seconds() + lim.spacing_seconds)
            events = [(t, 1) for t in times if t > since]
            events += self._store.outside_hits(policy, period, since)
            events.sort()
            total = sum(n for _, n in events)
            if total >= lim.cap:
                removed = 0
                for t, n in events:
                    removed += n
                    if total - removed < lim.cap:
                        wait = max(wait, (t + timedelta(seconds=period) - now).total_seconds())
                        break
        return wait

    def acquire(self, policy: str, *, budget: DailyCharacterBudget | None = None) -> None:
        """Block until a request is allowed at <= 80% of every rule, spread evenly.

        The wait is computed under the store lock; the lock is released while sleeping and
        everything is re-checked afterwards. When the wait is zero, in the same locked step
        and with the same clock value: the breaker and hard stop are re-checked, the budget
        is charged (if `budget` is given; raises DailyBudgetExceededError when exhausted) and
        the request is recorded. Raises CircuitOpenError while the breaker or the hard stop is
        active, CrawlerError for a policy with no known limit.
        """
        while True:
            with self._store.with_lock():
                now = self._clock()
                self._raise_if_stopped(now)
                wait = self._required_wait(policy, now)
                if wait <= 0:
                    if budget is not None and not budget.try_consume(1, at=now):
                        raise DailyBudgetExceededError("Daily character budget exhausted")
                    self._store.record_request(policy, now)
                    return
            self._sleep(wait)

    def _raise_if_stopped(self, now: datetime) -> None:
        if self._store.hard_stop_state() is not None:
            raise CircuitOpenError(None, "Crawler is hard-stopped (reset by hand)")
        state = self._store.breaker_state()
        if state is not None and now < state.open_until:
            raise CircuitOpenError(state.open_until)

    def record_extra_hit(self, policy: str, at: datetime) -> None:
        """Record one request under another policy (used when GGG names a different policy)."""
        with self._store.with_lock():
            self._store.record_request(policy, at)

    def update_from_headers(self, snapshot: PolicySnapshot, *, at: datetime | None = None) -> None:
        """Store the live limits and any header hits we had not counted ourselves.

        For every period, if the highest `hits` reported by any rule exceeds our own recorded
        requests plus earlier outside hits in that window, the difference is recorded as
        outside hits at `at` (default: now), so the count is `max(own, header)`.
        """
        with self._store.with_lock():
            at = at if at is not None else self._clock()
            policy = snapshot.policy
            self._store.set_live_limits(
                policy,
                {name: [p.rule for p in pairs] for name, pairs in snapshot.rules.items()},
            )
            header_hits: dict[int, int] = {}
            for pairs in snapshot.rules.values():
                for pair in pairs:
                    p = pair.state.period_seconds
                    header_hits[p] = max(header_hits.get(p, 0), pair.state.hits)
            for period, hits in header_hits.items():
                since = at - timedelta(seconds=period)
                counted = len(self._store.request_times(policy, since))
                counted += sum(n for _, n in self._store.outside_hits(policy, period, since))
                if hits > counted:
                    self._store.record_outside_hits(policy, period, hits - counted, at)

    def on_rate_limited(self, retry_after_seconds: float | None) -> None:
        """Make sure the stored breaker is open for at least Retry-After (default 1 h).

        Sends no alert (that is the circuit breaker's job); it only guarantees the limiter
        itself refuses to send while a 429 hold is active. Missing, non-finite or
        non-positive values mean the default; huge values are clamped to 30 days.
        """
        seconds = hold_seconds(retry_after_seconds)
        with self._store.with_lock():
            self._store.trip_breaker(self._clock() + timedelta(seconds=seconds), "rate limited")

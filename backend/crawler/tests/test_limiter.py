from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

import pytest

from backend.crawler.budget import DailyCharacterBudget
from backend.crawler.constants import (
    MEASURED_LIMITS,
    POLICY_CHARACTER,
    POLICY_ITEMS,
    POLICY_LADDER_VIEW,
)
from backend.crawler.errors import CircuitOpenError, CrawlerError, DailyBudgetExceededError
from backend.crawler.limiter import SharedRateLimiter
from backend.crawler.rate_limit_headers import (
    PolicySnapshot,
    RateLimitRule,
    RateLimitState,
    RulePair,
)
from backend.crawler.state import InMemoryStateStore

from .conftest import FakeClock


def make(store, clock: FakeClock) -> SharedRateLimiter:
    return SharedRateLimiter(store, clock=clock, sleep=clock.sleep)


def snapshot(policy: str, *rules: tuple[int, int], hits: int = 0) -> PolicySnapshot:
    pairs = [RulePair(RateLimitRule(m, p, 60), RateLimitState(hits, p, 0)) for m, p in rules]
    return PolicySnapshot(policy, {"ip": pairs})


class TrackingStore(InMemoryStateStore):
    """Counts how deep the caller is inside with_lock()."""

    def __init__(self) -> None:
        super().__init__()
        self.depth = 0

    @contextmanager
    def with_lock(self):
        with super().with_lock():
            self.depth += 1
            try:
                yield
            finally:
                self.depth -= 1


@pytest.mark.parametrize("policy", [POLICY_LADDER_VIEW, POLICY_CHARACTER, POLICY_ITEMS])
def test_never_exceeds_80_percent_and_spreads_evenly(store, clock, policy) -> None:
    limiter = make(store, clock)
    sent = []
    for _ in range(300):
        limiter.acquire(policy)
        sent.append(clock.now)
    for max_hits, period in MEASURED_LIMITS[policy]:
        cap = int(0.8 * max_hits)
        for i, end in enumerate(sent):
            start = end - timedelta(seconds=period)
            assert len([t for t in sent[: i + 1] if t > start]) <= cap
    gaps = [(b - a).total_seconds() for a, b in zip(sent, sent[1:], strict=False)]
    assert max(gaps) - min(gaps) < 1e-6
    assert min(gaps) > 0


def test_first_request_does_not_wait(store, clock) -> None:
    make(store, clock).acquire(POLICY_CHARACTER)
    assert clock.sleeps == []


def test_follows_tightened_live_limits_immediately(store, clock) -> None:
    limiter = make(store, clock)
    limiter.acquire(POLICY_LADDER_VIEW)
    limiter.acquire(POLICY_LADDER_VIEW)
    assert limiter.allowed_hits(POLICY_LADDER_VIEW) == {5: 4, 10: 8}
    limiter.update_from_headers(snapshot(POLICY_LADDER_VIEW, (2, 5), (4, 10)))
    assert limiter.allowed_hits(POLICY_LADDER_VIEW) == {5: 1, 10: 3}
    limiter.acquire(POLICY_LADDER_VIEW)
    prev = clock.now
    limiter.acquire(POLICY_LADDER_VIEW)
    assert (clock.now - prev).total_seconds() >= 5


def test_single_period_live_tightening(store, clock) -> None:
    limiter = make(store, clock)
    limiter.update_from_headers(snapshot(POLICY_LADDER_VIEW, (2, 5)))
    assert limiter.allowed_hits(POLICY_LADDER_VIEW) == {5: 1, 10: 8}


def test_never_speeds_up_when_live_limit_is_higher(store, clock) -> None:
    limiter = make(store, clock)
    limiter.update_from_headers(snapshot(POLICY_CHARACTER, (100, 60), (900, 1800)))
    assert limiter.allowed_hits(POLICY_CHARACTER) == {60: 12, 1800: 72, 7200: 144}


def test_live_period_unknown_to_measured_is_applied(store, clock) -> None:
    limiter = make(store, clock)
    limiter.update_from_headers(snapshot(POLICY_LADDER_VIEW, (10, 60)))
    assert limiter.allowed_hits(POLICY_LADDER_VIEW)[60] == 8


def test_small_limit_spacing_is_period_over_80_percent(store, clock) -> None:
    limiter = make(store, clock)
    # 1 hit per 60 s: floor(0.8) = 0, so spacing must be 60 / 0.8 = 75 s, not 60 s.
    limiter.update_from_headers(snapshot(POLICY_LADDER_VIEW, (1, 60)))
    limits = limiter.period_limits(POLICY_LADDER_VIEW)
    assert limits[60].cap == 1
    assert limits[60].spacing_seconds == pytest.approx(75.0)
    limiter.acquire(POLICY_LADDER_VIEW)
    start = clock.now
    limiter.acquire(POLICY_LADDER_VIEW)
    assert (clock.now - start).total_seconds() >= 75.0


@pytest.mark.parametrize("rule", [(0, 60), (-3, 60), (5, 0), (5, -1)])
def test_non_positive_limit_or_period_is_refused(store, clock, rule) -> None:
    store.set_live_limits(POLICY_LADDER_VIEW, {"ip": [RateLimitRule(rule[0], rule[1], 0)]})
    limiter = make(store, clock)
    with pytest.raises(CrawlerError):
        limiter.acquire(POLICY_LADDER_VIEW)
    assert store.request_times(POLICY_LADDER_VIEW, clock.now - timedelta(days=1)) == []


def test_burst_from_other_process_is_waited_out(store, clock) -> None:
    for _ in range(4):
        store.record_request(POLICY_LADDER_VIEW, clock.now)
    start = clock.now
    make(store, clock).acquire(POLICY_LADDER_VIEW)
    assert (clock.now - start).total_seconds() >= 5


def test_burst_at_two_hour_window_edge(store, clock) -> None:
    t0 = clock.now - timedelta(seconds=7199)
    for _ in range(144):  # the 2 h cap, all just inside the window
        store.record_request(POLICY_CHARACTER, t0)
    make(store, clock).acquire(POLICY_CHARACTER)
    assert clock.sleeps == [pytest.approx(1.0)]
    assert clock.now == t0 + timedelta(seconds=7200)


def test_burst_just_outside_two_hour_window_does_not_wait(store, clock) -> None:
    t0 = clock.now - timedelta(seconds=7200)
    for _ in range(144):
        store.record_request(POLICY_CHARACTER, t0)
    make(store, clock).acquire(POLICY_CHARACTER)
    assert clock.sleeps == []


def test_unknown_policy_is_refused(store, clock) -> None:
    with pytest.raises(CrawlerError):
        make(store, clock).acquire("mystery-policy")
    assert store.request_times("mystery-policy", clock.now - timedelta(days=1)) == []


def test_refuses_while_breaker_open(store, clock) -> None:
    store.trip_breaker(clock.now + timedelta(seconds=60), "test")
    with pytest.raises(CircuitOpenError):
        make(store, clock).acquire(POLICY_LADDER_VIEW)


def test_refuses_while_hard_stopped(store, clock) -> None:
    store.set_hard_stop("penalty", clock.now)
    with pytest.raises(CircuitOpenError) as exc:
        make(store, clock).acquire(POLICY_LADDER_VIEW)
    assert exc.value.retry_at is None


def test_lock_is_not_held_while_sleeping(clock) -> None:
    store = TrackingStore()
    depths = []

    def sleep(seconds: float) -> None:
        depths.append(store.depth)
        clock.sleep(seconds)

    limiter = SharedRateLimiter(store, clock=clock, sleep=sleep)
    limiter.acquire(POLICY_CHARACTER)
    limiter.acquire(POLICY_CHARACTER)
    assert depths and all(d == 0 for d in depths)


def test_breaker_tripped_during_wait_prevents_send(store, clock) -> None:
    def sleep(seconds: float) -> None:
        clock.sleep(seconds)
        # another process gets a 429 while we wait
        store.trip_breaker(clock.now + timedelta(seconds=3600), "other process 429")

    limiter = SharedRateLimiter(store, clock=clock, sleep=sleep)
    limiter.acquire(POLICY_CHARACTER)
    before = store.request_times(POLICY_CHARACTER, clock.now - timedelta(days=1))
    with pytest.raises(CircuitOpenError):
        limiter.acquire(POLICY_CHARACTER)
    assert store.request_times(POLICY_CHARACTER, clock.now - timedelta(days=1)) == before


def test_hard_stop_during_wait_prevents_send(store, clock) -> None:
    def sleep(seconds: float) -> None:
        clock.sleep(seconds)
        store.set_hard_stop("penalty elsewhere", clock.now)

    limiter = SharedRateLimiter(store, clock=clock, sleep=sleep)
    limiter.acquire(POLICY_CHARACTER)
    with pytest.raises(CircuitOpenError):
        limiter.acquire(POLICY_CHARACTER)
    assert len(store.request_times(POLICY_CHARACTER, clock.now - timedelta(days=1))) == 1


def test_budget_is_charged_with_the_request_on_the_same_day(store) -> None:
    start = datetime(2026, 11, 24, 23, 59, 30, tzinfo=UTC)
    clock = FakeClock(start)
    budget = DailyCharacterBudget(store, clock=clock)
    limiter = make(store, clock)
    store.record_request(POLICY_ITEMS, start)  # forces a ~50 s wait, across UTC midnight
    limiter.acquire(POLICY_ITEMS, budget=budget)
    assert clock.now.date() != start.date()
    assert store.budget_used(start.date()) == 0
    assert store.budget_used(clock.now.date()) == 1


def test_budget_refusal_records_no_request(store, clock) -> None:
    budget = DailyCharacterBudget(store, clock=clock, max_per_day=1)
    limiter = make(store, clock)
    limiter.acquire(POLICY_ITEMS, budget=budget)
    with pytest.raises(DailyBudgetExceededError):
        limiter.acquire(POLICY_ITEMS, budget=budget)
    assert len(store.request_times(POLICY_ITEMS, clock.now - timedelta(days=1))) == 1


def test_header_hits_above_own_count_slow_us_down(store, clock) -> None:
    limiter = make(store, clock)
    limiter.acquire(POLICY_LADDER_VIEW)
    # GGG says 4 hits in the 5 s window (cap is 4), we only recorded 1.
    limiter.update_from_headers(
        snapshot(POLICY_LADDER_VIEW, (5, 5), (10, 10), hits=4), at=clock.now
    )
    assert store.outside_hits(POLICY_LADDER_VIEW, 5, clock.now - timedelta(seconds=5)) == [
        (clock.now, 3)
    ]
    start = clock.now
    limiter.acquire(POLICY_LADDER_VIEW)
    assert (clock.now - start).total_seconds() >= 5  # waits for the window, not just spacing


def test_header_hits_not_double_counted(store, clock) -> None:
    limiter = make(store, clock)
    limiter.acquire(POLICY_LADDER_VIEW)
    snap = snapshot(POLICY_LADDER_VIEW, (5, 5), (10, 10), hits=3)
    limiter.update_from_headers(snap, at=clock.now)
    limiter.update_from_headers(snap, at=clock.now)
    hits = store.outside_hits(POLICY_LADDER_VIEW, 5, clock.now - timedelta(seconds=5))
    assert sum(n for _, n in hits) == 2


def test_header_hits_not_above_own_count_change_nothing(store, clock) -> None:
    limiter = make(store, clock)
    limiter.acquire(POLICY_LADDER_VIEW)
    limiter.update_from_headers(snapshot(POLICY_LADDER_VIEW, (5, 5), hits=1), at=clock.now)
    assert store.outside_hits(POLICY_LADDER_VIEW, 5, clock.now - timedelta(days=1)) == []


def test_on_rate_limited_holds_for_retry_after_or_default(store, clock) -> None:
    limiter = make(store, clock)
    limiter.on_rate_limited(120)
    state = store.breaker_state()
    assert state is not None and (state.open_until - clock.now).total_seconds() == 120
    limiter.on_rate_limited(None)
    state = store.breaker_state()
    assert state is not None and (state.open_until - clock.now).total_seconds() == 3600


@pytest.mark.parametrize("bad", [float("inf"), float("nan"), -1.0, 1e300])
def test_on_rate_limited_survives_bad_values(store, clock, bad) -> None:
    make(store, clock).on_rate_limited(bad)
    state = store.breaker_state()
    assert state is not None
    seconds = (state.open_until - clock.now).total_seconds()
    assert 0 < seconds <= 30 * 24 * 3600


def test_live_rule_longer_than_retention_is_refused(store, clock) -> None:
    from backend.crawler.errors import HistoryRetentionError

    limiter = make(store, clock)
    store.set_live_limits(POLICY_LADDER_VIEW, {"ip": [RateLimitRule(100, 24 * 3600 + 1, 60)]})
    with pytest.raises(HistoryRetentionError):
        limiter.acquire(POLICY_LADDER_VIEW)
    assert store.request_times(POLICY_LADDER_VIEW, clock.now - timedelta(days=2)) == []
    # exactly 24 h is still countable
    store.set_live_limits(POLICY_LADDER_VIEW, {"ip": [RateLimitRule(100, 24 * 3600, 60)]})
    limiter.acquire(POLICY_LADDER_VIEW)

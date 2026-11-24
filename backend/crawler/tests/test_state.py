"""CrawlerStateStore contract tests, run against the in-memory and the PostgreSQL store.

The PostgreSQL runs use the throwaway `elo_test` database (fixture from backend/tests) and are
skipped when it is unavailable.
"""

from datetime import timedelta

import pytest

from backend.crawler.rate_limit_headers import RateLimitRule
from backend.crawler.state import InMemoryStateStore


@pytest.fixture(params=["memory", pytest.param("postgres", marks=pytest.mark.db)])
def store(request):
    if request.param == "memory":
        return InMemoryStateStore()
    return request.getfixturevalue("pg_store")


def test_nested_with_lock_is_a_noop(store, clock) -> None:
    with store.with_lock():
        with store.with_lock():
            store.record_request("p", clock.now)
        store.record_request("p", clock.now + timedelta(seconds=1))
    assert len(store.request_times("p", clock.now - timedelta(seconds=1))) == 2


def test_request_times_exclusive_since_and_sorted(store, clock) -> None:
    a, b, c = (clock.now + timedelta(seconds=s) for s in (0, 10, 5))
    for t in (a, b, c):
        store.record_request("p", t)
    assert store.request_times("p", a) == [c, b]
    assert store.request_times("other", a - timedelta(days=1)) == []


def test_live_limits_roundtrip_is_a_copy_and_replaced(store) -> None:
    rules = {"ip": [RateLimitRule(5, 5, 10)]}
    assert store.get_live_limits("p") is None
    store.set_live_limits("p", rules)
    rules["ip"].clear()
    assert store.get_live_limits("p") == {"ip": [RateLimitRule(5, 5, 10)]}
    store.set_live_limits("p", {"acc": [RateLimitRule(7, 10, 20), RateLimitRule(9, 60, 30)]})
    assert store.get_live_limits("p") == {
        "acc": [RateLimitRule(7, 10, 20), RateLimitRule(9, 60, 30)]
    }
    assert store.get_live_limits("other") is None


def test_budget_upsert_accumulates_per_day(store, clock) -> None:
    day = clock.now.date()
    assert store.budget_used(day) == 0
    store.budget_consume(day, 2)
    store.budget_consume(day, 3)
    assert store.budget_used(day) == 5
    assert store.budget_used(day + timedelta(days=1)) == 0


def test_trip_breaker_never_shortens(store, clock) -> None:
    assert store.breaker_state() is None
    later = clock.now + timedelta(seconds=100)
    store.trip_breaker(later, "long")
    store.trip_breaker(clock.now + timedelta(seconds=10), "short")
    state = store.breaker_state()
    assert state is not None and state.open_until == later and state.reason == "long"
    longer = clock.now + timedelta(seconds=500)
    store.trip_breaker(longer, "longer")
    state = store.breaker_state()
    assert state is not None and state.open_until == longer and state.reason == "longer"


def test_state_survives_a_new_store_object_on_the_same_data(store, clock) -> None:
    store.trip_breaker(clock.now + timedelta(seconds=60), "persisted")
    store.budget_consume(clock.now.date(), 7)
    if isinstance(store, InMemoryStateStore):
        same = store  # in-memory data lives in the object itself
    else:
        import psycopg

        from backend.crawler.pg_store import PostgresStateStore

        same = PostgresStateStore(psycopg.connect(**_conninfo(store)))
    try:
        state = same.breaker_state()
        assert state is not None and state.reason == "persisted"
        assert same.budget_used(clock.now.date()) == 7
    finally:
        if same is not store:
            same.close()


def _conninfo(store) -> dict:
    info = store._conn.info
    return {
        "host": info.host,
        "port": info.port,
        "dbname": info.dbname,
        "user": info.user,
        "password": info.password,
    }


# ---- outside hits and hard stop (both stores) ---------------------------------------------


def test_outside_hits_are_per_policy_and_period(store, clock) -> None:
    store.record_outside_hits("p", 5, 3, clock.now)
    assert store.outside_hits("p", 5, clock.now - timedelta(seconds=1)) == [(clock.now, 3)]
    assert store.outside_hits("p", 10, clock.now - timedelta(seconds=1)) == []
    assert store.outside_hits("p", 5, clock.now) == []


def test_hard_stop_set_once_and_cleared(store, clock) -> None:
    assert store.hard_stop_state() is None
    assert store.set_hard_stop("first", clock.now) is True
    assert store.set_hard_stop("second", clock.now + timedelta(seconds=1)) is False
    state = store.hard_stop_state()
    assert state is not None and state.reason == "first" and state.since == clock.now
    store.clear_hard_stop()
    assert store.hard_stop_state() is None


def test_memory_history_is_pruned_after_24_hours() -> None:
    from datetime import UTC, datetime

    s = InMemoryStateStore()
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    s.record_request("p", t0)
    s.record_request("p", t0 + timedelta(hours=25))
    assert s.request_times("p", t0 - timedelta(days=1)) == [t0 + timedelta(hours=25)]


# ---- PostgreSQL only -------------------------------------------------------------------------


@pytest.mark.db
def test_pg_prunes_requests_older_than_24_hours(pg_store, clock) -> None:
    pg_store.record_request("p", clock.now - timedelta(hours=25))
    pg_store.record_request("p", clock.now - timedelta(hours=23))
    pg_store.record_request("p", clock.now)
    got = pg_store.request_times("p", clock.now - timedelta(days=2))
    assert got == [clock.now - timedelta(hours=23), clock.now]


@pytest.mark.db
def test_pg_with_lock_holds_the_advisory_lock(pg_store) -> None:
    import psycopg

    from backend.crawler.pg_store import ADVISORY_LOCK_KEY

    def other_can_lock() -> bool:
        with psycopg.connect(**_conninfo(pg_store), autocommit=True) as other:
            with other.transaction():
                row = other.execute("SELECT pg_try_advisory_xact_lock(%s)", (ADVISORY_LOCK_KEY,))
                return bool(row.fetchone()[0])

    assert other_can_lock() is True  # free outside with_lock
    with pg_store.with_lock():
        with pg_store.with_lock():  # nested: no deadlock
            assert other_can_lock() is False
        assert other_can_lock() is False
    assert other_can_lock() is True  # released at commit


@pytest.mark.db
def test_pg_with_lock_rolls_back_on_error(pg_store, clock) -> None:
    with pytest.raises(RuntimeError):
        with pg_store.with_lock():
            pg_store.record_request("p", clock.now)
            raise RuntimeError("boom")
    assert pg_store.request_times("p", clock.now - timedelta(days=1)) == []


@pytest.mark.db
def test_pg_prunes_outside_hits_older_than_24_hours(pg_store, clock) -> None:
    pg_store.record_outside_hits("p", 5, 2, clock.now - timedelta(hours=25))
    pg_store.record_outside_hits("p", 5, 1, clock.now)
    assert pg_store.outside_hits("p", 5, clock.now - timedelta(days=2)) == [(clock.now, 1)]


@pytest.mark.db
def test_pg_outside_hits_reject_non_positive(pg_store, clock) -> None:
    with pytest.raises(ValueError):
        pg_store.record_outside_hits("p", 5, 0, clock.now)


@pytest.mark.db
def test_pg_hard_stop_is_independent_of_the_breaker(pg_store, clock) -> None:
    pg_store.trip_breaker(clock.now + timedelta(seconds=60), "429")
    assert pg_store.hard_stop_state() is None
    assert pg_store.set_hard_stop("penalty", clock.now) is True
    state = pg_store.breaker_state()
    assert state is not None and state.reason == "429"
    pg_store.clear_hard_stop()
    assert pg_store.breaker_state() is not None


def test_retention_is_24_hours_in_both_stores() -> None:
    from backend.crawler import pg_store
    from backend.crawler.state import HISTORY_RETENTION

    assert HISTORY_RETENTION == timedelta(hours=24)
    assert pg_store.REQUEST_RETENTION == HISTORY_RETENTION
    assert InMemoryStateStore._KEEP == HISTORY_RETENTION


def test_pg_helpers_reject_naive_datetimes() -> None:
    from datetime import datetime

    from backend.crawler.pg_store import _utc

    with pytest.raises(ValueError):
        _utc(datetime(2026, 11, 24, 12, 0))

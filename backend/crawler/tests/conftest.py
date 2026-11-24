"""Shared test helpers: fake clock, fake sleep, recorded header sets."""

from datetime import UTC, datetime, timedelta

import pytest

from backend.crawler.state import InMemoryStateStore


class FakeClock:
    """A controllable clock; `sleep` advances it instantly (no real waiting)."""

    def __init__(self, start: datetime | None = None) -> None:
        self.now = start or datetime(2026, 11, 24, 12, 0, 0, tzinfo=UTC)
        self.sleeps: list[float] = []

    def __call__(self) -> datetime:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += timedelta(seconds=seconds)

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def store() -> InMemoryStateStore:
    return InMemoryStateStore()


# Recorded-style header sets, with values taken from MEASURED_LIMITS (penalties are examples).
LADDER_HEADERS = {
    "X-Rate-Limit-Policy": "ladder-view",
    "X-Rate-Limit-Rules": "Ip",
    "X-Rate-Limit-Ip": "5:5:10,10:10:60",
    "X-Rate-Limit-Ip-State": "1:5:0,1:10:0",
}
CHARACTER_HEADERS = {
    "X-Rate-Limit-Policy": "backend-character-request-limit",
    "X-Rate-Limit-Rules": "Ip,Account",
    "X-Rate-Limit-Ip": "15:60:60,90:1800:300,180:7200:1800",
    "X-Rate-Limit-Ip-State": "1:60:0,1:1800:0,1:7200:0",
    "X-Rate-Limit-Account": "15:60:60,90:1800:300,180:7200:1800",
    "X-Rate-Limit-Account-State": "2:60:0,2:1800:0,2:7200:0",
}
ITEMS_HEADERS = {
    "X-Rate-Limit-Policy": "backend-item-request-limit",
    "X-Rate-Limit-Rules": "Ip",
    "X-Rate-Limit-Ip": "30:60:60,90:1800:300,180:7200:1800",
    "X-Rate-Limit-Ip-State": "1:60:0,1:1800:0,1:7200:0",
}


# ---- PostgreSQL (elo_test only) ----------------------------------------------------------
# The `test_engine` fixture lives in backend/conftest.py (P1-B1). It skips when the
# database settings or server are unavailable, and it only ever migrates the throwaway elo_test.


@pytest.fixture
def pg_store(test_engine):
    import psycopg

    from backend.crawler.pg_store import PostgresStateStore

    url = test_engine.url
    assert url.database == "elo_test"  # never touch any other database
    conn = psycopg.connect(
        host=url.host,
        port=url.port,
        dbname=url.database,
        user=url.username,
        password=url.password,
    )
    store = PostgresStateStore(conn)
    conn.execute(
        "TRUNCATE crawler_requests, crawler_live_limits, crawler_budget, crawler_breaker, "
        "crawler_outside_hits, crawler_hard_stop"
    )
    try:
        yield store
    finally:
        store.close()

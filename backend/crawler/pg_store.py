"""PostgreSQL implementation of `CrawlerStateStore`.

Follows the contract in `backend.crawler.state`:
- one connection; `with_lock()` is one transaction on it that first takes
  `pg_advisory_xact_lock(ADVISORY_LOCK_KEY)`; every call inside uses that transaction;
  a nested `with_lock()` joins the outer one (no-op);
- calls outside `with_lock()` run in autocommit mode, one atomic statement (or one short
  transaction) each;
- `trip_breaker` never shortens an existing hold (`GREATEST`);
- `budget_consume` is an atomic upsert.

Tables come from migration 0001 (`crawler_requests`, `crawler_live_limits`, `crawler_budget`,
`crawler_breaker`, `crawler_outside_hits`, `crawler_hard_stop`). The hard stop has its own
single-row table so it can never be overwritten by the breaker.

Connection failures: the store never reconnects. If the connection drops, every call raises
and the crawler fails closed (it cannot send) until the process is restarted.

One store object is meant for one thread at a time; an internal re-entrant mutex keeps the
single psycopg connection safe if it is shared anyway.
"""

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING, Final

import psycopg

from backend.crawler.rate_limit_headers import RateLimitRule
from backend.crawler.state import HISTORY_RETENTION, BreakerState, HardStopState

if TYPE_CHECKING:
    from backend.common.config import Settings

# Fixed advisory-lock key shared by every crawler process ("ELOC" in ASCII).
ADVISORY_LOCK_KEY: Final[int] = 0x454C4F43

# crawler_requests and crawler_outside_hits rows older than this are deleted (24 h, the same as
# the in-memory store); the limiter refuses live rules with a longer period.
REQUEST_RETENTION: Final[timedelta] = HISTORY_RETENTION


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("naive datetime: an aware datetime is required")
    return value.astimezone(UTC)


class PostgresStateStore:
    """`CrawlerStateStore` backed by PostgreSQL."""

    def __init__(self, conn: psycopg.Connection) -> None:
        conn.autocommit = True
        self._conn = conn
        self._mutex = threading.RLock()
        self._depth = 0

    @classmethod
    def from_settings(cls, settings: "Settings | None" = None) -> "PostgresStateStore":
        """Connect with the server settings (the database named in them)."""
        if settings is None:
            from backend.common.config import get_settings

            settings = get_settings()
        conn = psycopg.connect(
            host=settings.db_host,
            port=settings.db_port,
            dbname=settings.db_name,
            user=settings.db_user,
            password=settings.db_pass.get_secret_value(),
            autocommit=True,
            connect_timeout=10,
        )
        return cls(conn)

    def close(self) -> None:
        self._conn.close()

    # ---- locking -------------------------------------------------------------------------

    @contextmanager
    def with_lock(self) -> Iterator[None]:
        with self._mutex:
            if self._depth > 0:
                self._depth += 1
                try:
                    yield
                finally:
                    self._depth -= 1
                return
            with self._conn.transaction():
                self._conn.execute("SELECT pg_advisory_xact_lock(%s)", (ADVISORY_LOCK_KEY,))
                self._depth = 1
                try:
                    yield
                finally:
                    self._depth = 0

    @contextmanager
    def _atomic(self) -> Iterator[None]:
        """Join the lock's transaction if there is one, else open a short one."""
        with self._mutex:
            if self._depth > 0:
                yield
            else:
                with self._conn.transaction():
                    yield

    # ---- requests ------------------------------------------------------------------------

    def record_request(self, policy: str, sent_at: datetime) -> None:
        with self._atomic():
            self._conn.execute(
                "INSERT INTO crawler_requests (policy, sent_at) VALUES (%s, %s)",
                (policy, _utc(sent_at)),
            )
            self._conn.execute(
                "DELETE FROM crawler_requests WHERE sent_at < %s",
                (_utc(sent_at) - REQUEST_RETENTION,),
            )

    def request_times(self, policy: str, since: datetime) -> list[datetime]:
        with self._mutex:
            rows = self._conn.execute(
                "SELECT sent_at FROM crawler_requests WHERE policy = %s AND sent_at > %s "
                "ORDER BY sent_at",
                (policy, _utc(since)),
            ).fetchall()
        return [_utc(r[0]) for r in rows]

    # ---- outside hits ----------------------------------------------------------------------

    def record_outside_hits(self, policy: str, period_seconds: int, n: int, at: datetime) -> None:
        if n <= 0:
            raise ValueError(f"n must be positive, got {n}")
        with self._atomic():
            self._conn.execute(
                "INSERT INTO crawler_outside_hits (policy, period_s, hits, at) "
                "VALUES (%s, %s, %s, %s)",
                (policy, period_seconds, n, _utc(at)),
            )
            self._conn.execute(
                "DELETE FROM crawler_outside_hits WHERE at < %s",
                (_utc(at) - REQUEST_RETENTION,),
            )

    def outside_hits(
        self, policy: str, period_seconds: int, since: datetime
    ) -> list[tuple[datetime, int]]:
        with self._mutex:
            rows = self._conn.execute(
                "SELECT at, hits FROM crawler_outside_hits "
                "WHERE policy = %s AND period_s = %s AND at > %s ORDER BY at, id",
                (policy, period_seconds, _utc(since)),
            ).fetchall()
        return [(_utc(at), int(hits)) for at, hits in rows]

    # ---- hard stop -------------------------------------------------------------------------

    def hard_stop_state(self) -> HardStopState | None:
        with self._mutex:
            row = self._conn.execute(
                "SELECT reason, since FROM crawler_hard_stop WHERE id = 1"
            ).fetchone()
        return None if row is None else HardStopState(row[0], _utc(row[1]))

    def set_hard_stop(self, reason: str, at: datetime) -> bool:
        with self._mutex:
            cur = self._conn.execute(
                "INSERT INTO crawler_hard_stop (id, reason, since) VALUES (1, %s, %s) "
                "ON CONFLICT (id) DO NOTHING",
                (reason, _utc(at)),
            )
            return cur.rowcount == 1

    def clear_hard_stop(self) -> None:
        with self._mutex:
            self._conn.execute("DELETE FROM crawler_hard_stop WHERE id = 1")

    # ---- live limits -----------------------------------------------------------------------

    def get_live_limits(self, policy: str) -> dict[str, list[RateLimitRule]] | None:
        with self._mutex:
            rows = self._conn.execute(
                "SELECT rule, max_hits, period_s, penalty_s FROM crawler_live_limits "
                "WHERE policy = %s ORDER BY rule, period_s",
                (policy,),
            ).fetchall()
        if not rows:
            return None
        result: dict[str, list[RateLimitRule]] = {}
        for rule, max_hits, period_s, penalty_s in rows:
            result.setdefault(rule, []).append(RateLimitRule(max_hits, period_s, penalty_s))
        return result

    def set_live_limits(self, policy: str, rules: dict[str, list[RateLimitRule]]) -> None:
        with self._atomic():
            self._conn.execute("DELETE FROM crawler_live_limits WHERE policy = %s", (policy,))
            for name, rule_list in rules.items():
                for rule in rule_list:
                    self._conn.execute(
                        "INSERT INTO crawler_live_limits "
                        "(policy, rule, max_hits, period_s, penalty_s, updated_at) "
                        "VALUES (%s, %s, %s, %s, %s, now()) "
                        "ON CONFLICT (policy, rule, period_s) DO UPDATE SET "
                        "max_hits = LEAST(crawler_live_limits.max_hits, EXCLUDED.max_hits), "
                        "penalty_s = EXCLUDED.penalty_s, updated_at = now()",
                        (policy, name, rule.max_hits, rule.period_seconds, rule.penalty_seconds),
                    )

    # ---- budget ----------------------------------------------------------------------------

    def budget_used(self, day: date) -> int:
        with self._mutex:
            row = self._conn.execute(
                "SELECT characters_used FROM crawler_budget WHERE day = %s", (day,)
            ).fetchone()
        return 0 if row is None else int(row[0])

    def budget_consume(self, day: date, n: int) -> None:
        with self._mutex:
            self._conn.execute(
                "INSERT INTO crawler_budget (day, characters_used) VALUES (%s, %s) "
                "ON CONFLICT (day) DO UPDATE SET "
                "characters_used = crawler_budget.characters_used + EXCLUDED.characters_used",
                (day, n),
            )

    # ---- breaker ---------------------------------------------------------------------------

    def breaker_state(self) -> BreakerState | None:
        with self._mutex:
            row = self._conn.execute(
                "SELECT open_until, reason FROM crawler_breaker "
                "WHERE id = 1 AND open_until IS NOT NULL"
            ).fetchone()
        if row is None:
            return None
        return BreakerState(_utc(row[0]), row[1] or "")

    def trip_breaker(self, open_until: datetime, reason: str) -> None:
        with self._mutex:
            self._conn.execute(
                "INSERT INTO crawler_breaker (id, open_until, reason, tripped_at) "
                "VALUES (1, %s, %s, now()) "
                "ON CONFLICT (id) DO UPDATE SET "
                "reason = CASE WHEN crawler_breaker.open_until IS NULL "
                "OR EXCLUDED.open_until > crawler_breaker.open_until "
                "THEN EXCLUDED.reason ELSE crawler_breaker.reason END, "
                "tripped_at = CASE WHEN crawler_breaker.open_until IS NULL "
                "OR EXCLUDED.open_until > crawler_breaker.open_until "
                "THEN now() ELSE crawler_breaker.tripped_at END, "
                "open_until = GREATEST(crawler_breaker.open_until, EXCLUDED.open_until)",
                (_utc(open_until), reason),
            )

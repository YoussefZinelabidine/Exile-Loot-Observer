"""Daily character budget (items + tree)."""

from datetime import UTC, date, datetime

from backend.crawler.clock import Clock, system_clock
from backend.crawler.constants import DAILY_CHARACTER_MAX
from backend.crawler.state import CrawlerStateStore


def utc_day(at: datetime) -> date:
    """Return the UTC calendar day of an aware datetime; naive datetimes are rejected."""
    if at.tzinfo is None or at.utcoffset() is None:
        raise ValueError("naive datetime: an aware datetime is required")
    return at.astimezone(UTC).date()


class DailyCharacterBudget:
    """Counts characters fetched per UTC calendar day against a hard cap.

    One unit = one character (items + tree), charged when its items request is sent.
    The cap can be lowered but never raised above DAILY_CHARACTER_MAX.
    """

    def __init__(
        self,
        store: CrawlerStateStore,
        *,
        clock: Clock = system_clock,
        max_per_day: int = DAILY_CHARACTER_MAX,
    ) -> None:
        if isinstance(max_per_day, bool) or not isinstance(max_per_day, int):
            raise TypeError(f"max_per_day must be an int, got {type(max_per_day).__name__}")
        if max_per_day <= 0:
            raise ValueError(f"max_per_day must be positive, got {max_per_day}")
        if max_per_day > DAILY_CHARACTER_MAX:
            raise ValueError(
                f"max_per_day {max_per_day} exceeds the hard maximum {DAILY_CHARACTER_MAX}"
            )
        self._store = store
        self._clock = clock
        self._max_per_day = max_per_day

    @property
    def store(self) -> CrawlerStateStore:
        return self._store

    def try_consume(self, n: int = 1, *, at: datetime | None = None) -> bool:
        """Consume n characters if available; return False (consuming nothing) otherwise.

        The UTC day is taken from `at` (default: the clock). Pass the same value used to
        record the request so both land on the same day.
        """
        if isinstance(n, bool) or not isinstance(n, int) or n <= 0:
            raise ValueError(f"n must be a positive int, got {n!r}")
        day = utc_day(at if at is not None else self._clock())
        with self._store.with_lock():
            if self._store.budget_used(day) + n > self._max_per_day:
                return False
            self._store.budget_consume(day, n)
            return True

    def remaining(self, *, at: datetime | None = None) -> int:
        """Return how many characters can still be fetched on the UTC day of `at` (now)."""
        used = self._store.budget_used(utc_day(at if at is not None else self._clock()))
        return max(0, self._max_per_day - used)

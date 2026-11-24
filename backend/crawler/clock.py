"""Injectable clock and sleep, so tests never wait in real time."""

import time
from collections.abc import Callable
from datetime import UTC, datetime

Clock = Callable[[], datetime]
SleepFn = Callable[[float], None]


def system_clock() -> datetime:
    """Return the current time as a timezone-aware UTC datetime."""
    return datetime.now(UTC)


def system_sleep(seconds: float) -> None:
    """Really sleep (default for production use only)."""
    time.sleep(seconds)

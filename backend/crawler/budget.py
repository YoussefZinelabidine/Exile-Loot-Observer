"""Daily character budget (items + tree)."""

from backend.crawler.constants import DAILY_CHARACTER_MAX


class DailyCharacterBudget:
    """Counts characters fetched per day against a hard cap.

    The cap can be lowered but never raised above DAILY_CHARACTER_MAX.
    """

    def __init__(self, max_per_day: int = DAILY_CHARACTER_MAX) -> None:
        if isinstance(max_per_day, bool) or not isinstance(max_per_day, int):
            raise TypeError(f"max_per_day must be an int, got {type(max_per_day).__name__}")
        if max_per_day <= 0:
            raise ValueError(f"max_per_day must be positive, got {max_per_day}")
        if max_per_day > DAILY_CHARACTER_MAX:
            raise ValueError(
                f"max_per_day {max_per_day} exceeds the hard maximum {DAILY_CHARACTER_MAX}"
            )
        self._max_per_day = max_per_day

    def try_consume(self, n: int = 1) -> bool:
        """Consume n characters if available; return False (consuming nothing) otherwise."""
        raise NotImplementedError("Phase 1")

    def remaining(self) -> int:
        """Return how many characters can still be fetched today."""
        raise NotImplementedError("Phase 1")

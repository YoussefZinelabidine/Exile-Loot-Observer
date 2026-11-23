"""Crawler safety constants. Plain module constants, never read from config or env."""

from collections.abc import Mapping
from types import MappingProxyType
from typing import Final

RATE_LIMIT_CAP_FRACTION: Final[float] = 0.8

# Hard-coded: no setting can raise it.
DAILY_CHARACTER_MAX: Final[int] = 1700  # items + tree

DEFAULT_RETRY_AFTER_SECONDS: Final[int] = 3600

POLICY_LADDER_VIEW: Final[str] = "ladder-view"
POLICY_CHARACTER: Final[str] = "backend-character-request-limit"
POLICY_ITEMS: Final[str] = "backend-item-request-limit"

# Measurements of 19 Nov 2026: per policy, a list of (max_hits, period_seconds).
# Reference values only: the limiter always follows the live headers. The ladder
# 15:10 rule mentioned in HANDOFF is unconfirmed (open question).
MEASURED_LIMITS: Final[Mapping[str, tuple[tuple[int, int], ...]]] = MappingProxyType(
    {
        POLICY_LADDER_VIEW: ((5, 5), (10, 10)),
        POLICY_CHARACTER: ((15, 60), (90, 1800), (180, 7200)),
        POLICY_ITEMS: ((30, 60), (90, 1800), (180, 7200)),
    }
)

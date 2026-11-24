"""Crawler: the only code allowed to send requests to GGG, with its safety layer."""

from backend.crawler.budget import DailyCharacterBudget
from backend.crawler.circuit_breaker import CircuitBreaker
from backend.crawler.clock import Clock, SleepFn, system_clock, system_sleep
from backend.crawler.constants import (
    DAILY_CHARACTER_MAX,
    DEFAULT_RETRY_AFTER_SECONDS,
    MAX_RETRY_AFTER_SECONDS,
    MEASURED_LIMITS,
    POLICY_CHARACTER,
    POLICY_ITEMS,
    POLICY_LADDER_VIEW,
    RATE_LIMIT_CAP_FRACTION,
)
from backend.crawler.endpoints import ENDPOINTS, Endpoint, resolve_endpoint
from backend.crawler.errors import (
    CircuitOpenError,
    CrawlerError,
    DailyBudgetExceededError,
    EndpointNotAllowedError,
    MissingContactInfoError,
    RateLimitedError,
)
from backend.crawler.http_client import SafeHttpClient
from backend.crawler.limiter import SharedRateLimiter
from backend.crawler.rate_limit_headers import (
    PolicySnapshot,
    RateLimitRule,
    RateLimitState,
    RulePair,
    parse_rate_limit_headers,
    parse_retry_after,
)
from backend.crawler.state import BreakerState, CrawlerStateStore, HardStopState, InMemoryStateStore
from backend.crawler.user_agent import build_user_agent

__all__ = [
    "ENDPOINTS",
    "MAX_RETRY_AFTER_SECONDS",
    "Endpoint",
    "EndpointNotAllowedError",
    "HardStopState",
    "resolve_endpoint",
    "BreakerState",
    "Clock",
    "CrawlerStateStore",
    "InMemoryStateStore",
    "MissingContactInfoError",
    "SleepFn",
    "system_clock",
    "system_sleep",
    "DAILY_CHARACTER_MAX",
    "DEFAULT_RETRY_AFTER_SECONDS",
    "MEASURED_LIMITS",
    "POLICY_CHARACTER",
    "POLICY_ITEMS",
    "POLICY_LADDER_VIEW",
    "RATE_LIMIT_CAP_FRACTION",
    "CircuitBreaker",
    "CircuitOpenError",
    "CrawlerError",
    "DailyBudgetExceededError",
    "DailyCharacterBudget",
    "PolicySnapshot",
    "RateLimitRule",
    "RateLimitState",
    "RateLimitedError",
    "RulePair",
    "SafeHttpClient",
    "SharedRateLimiter",
    "build_user_agent",
    "parse_rate_limit_headers",
    "parse_retry_after",
]

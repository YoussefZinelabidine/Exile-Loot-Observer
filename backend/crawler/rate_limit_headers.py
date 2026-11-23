"""Types and parsers for GGG rate-limit response headers."""

from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class RateLimitRule:
    """One limit: at most `max_hits` per `period_seconds`; breaking it costs `penalty_seconds`."""

    max_hits: int
    period_seconds: int
    penalty_seconds: int


@dataclass(frozen=True)
class RateLimitState:
    """Current usage: `hits` in a window of `period_seconds`; penalty seconds if restricted."""

    hits: int
    period_seconds: int
    active_penalty_seconds: int


@dataclass(frozen=True)
class RulePair:
    """A rule together with its current state."""

    rule: RateLimitRule
    state: RateLimitState


@dataclass(frozen=True)
class PolicySnapshot:
    """All rules of one policy. Key = rule name such as `ip`, `account`, `client`."""

    policy: str
    rules: dict[str, list[RulePair]]


def parse_rate_limit_headers(headers: Mapping[str, str]) -> PolicySnapshot | None:
    """Parse rate-limit headers into a PolicySnapshot, or None if absent.

    Header format:
    - `X-Rate-Limit-Policy`: policy name.
    - `X-Rate-Limit-Rules`: comma-separated rule names (e.g. `ip,account`).
    - `X-Rate-Limit-<Rule>`: `hits:period:penalty,...` (the rule's limits).
    - `X-Rate-Limit-<Rule>-State`: `hits:period:active_penalty,...` (current state).
    - `Retry-After`: seconds to wait, sent with a 429 (see `parse_retry_after`).
    """
    raise NotImplementedError("Phase 1")


def parse_retry_after(headers: Mapping[str, str]) -> float | None:
    """Return the `Retry-After` value in seconds, or None if absent."""
    raise NotImplementedError("Phase 1")

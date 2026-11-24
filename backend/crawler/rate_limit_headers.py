"""Types and parsers for GGG rate-limit response headers."""

import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

from backend.crawler.constants import DEFAULT_RETRY_AFTER_SECONDS, MAX_RETRY_AFTER_SECONDS


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


def _lower(headers: Mapping[str, str]) -> dict[str, str]:
    return {k.lower(): v for k, v in headers.items()}


def _triples(value: str) -> list[tuple[int, int, int]]:
    out = []
    for part in value.split(","):
        a, b, c = part.strip().split(":")
        out.append((int(a), int(b), int(c)))
    return out


def policy_header(headers: Mapping[str, str]) -> str | None:
    """Return the `X-Rate-Limit-Policy` value, or None if absent or blank."""
    value = _lower(headers).get("x-rate-limit-policy", "").strip()
    return value or None


def parse_rate_limit_headers(headers: Mapping[str, str]) -> PolicySnapshot | None:
    """Parse rate-limit headers into a PolicySnapshot, or None if absent or malformed.

    Header names are matched case-insensitively. Format:
    - `X-Rate-Limit-Policy`: policy name.
    - `X-Rate-Limit-Rules`: comma-separated rule names (e.g. `ip,account`).
    - `X-Rate-Limit-<Rule>`: `hits:period:penalty,...` (the rule's limits).
    - `X-Rate-Limit-<Rule>-State`: `hits:period:active_penalty,...` (current state).
    - `Retry-After`: seconds to wait, sent with a 429 (see `parse_retry_after`).

    If a rule's `-State` header is missing, its state is taken as zero hits and no penalty.
    A rule whose limit header is missing, any malformed value, a negative `max_hits`, a
    `period <= 0`, or a negative hit count or penalty makes the whole result None (a
    half-understood limit is never trusted). A limit of `max_hits == 0` is kept: it means
    "nothing allowed" and callers treat it as a hard stop (see `has_zero_limit`).
    """
    h = _lower(headers)
    policy = h.get("x-rate-limit-policy", "").strip()
    names_raw = h.get("x-rate-limit-rules", "").strip()
    if not policy or not names_raw:
        return None
    rules: dict[str, list[RulePair]] = {}
    try:
        for name in (n.strip() for n in names_raw.split(",") if n.strip()):
            limit_raw = h.get(f"x-rate-limit-{name.lower()}")
            if limit_raw is None:
                return None
            limits = _triples(limit_raw)
            state_raw = h.get(f"x-rate-limit-{name.lower()}-state")
            if state_raw is None:
                states = [(0, period, 0) for _, period, _ in limits]
            else:
                states = _triples(state_raw)
            if len(states) != len(limits):
                return None
            for max_hits, period, penalty in limits:
                if max_hits < 0 or period <= 0 or penalty < 0:
                    return None
            for hits, period, active in states:
                if hits < 0 or period <= 0 or active < 0:
                    return None
            rules[name] = [
                RulePair(RateLimitRule(*lim), RateLimitState(*st))
                for lim, st in zip(limits, states, strict=True)
            ]
    except ValueError:
        return None
    return PolicySnapshot(policy, rules) if rules else None


def has_zero_limit(snapshot: PolicySnapshot) -> bool:
    """Return True if any rule allows 0 hits (GGG saying "nothing is allowed")."""
    return any(pair.rule.max_hits <= 0 for pairs in snapshot.rules.values() for pair in pairs)


def has_rate_limit_headers(headers: Mapping[str, str]) -> bool:
    """Return True if the response carries any `X-Rate-Limit-*` header."""
    return any(k.lower().startswith("x-rate-limit-") for k in headers)


def find_active_penalty(headers: Mapping[str, str]) -> str | None:
    """Scan every `X-Rate-Limit-*-State` header on its own and look for an active penalty.

    Independent of the strict parser: entries are split on "," then ":", and any entry with
    3 or more fields whose third field is an integer > 0 counts (so a 4-field entry, or a
    missing sibling header, cannot hide a penalty). Returns the header name, or None.
    """
    for name, value in headers.items():
        lowered = name.lower()
        if not (lowered.startswith("x-rate-limit-") and lowered.endswith("-state")):
            continue
        for entry in value.split(","):
            fields = entry.split(":")
            if len(fields) >= 3:
                try:
                    if int(fields[2].strip()) > 0:
                        return name
                except ValueError:
                    continue
    return None


def find_zero_limit(headers: Mapping[str, str]) -> str | None:
    """Scan every `X-Rate-Limit-<rule>` limit header on its own for a limit of 0 (or less) hits.

    Independent of the strict parser: the first field of each comma-separated entry is
    checked; an integer <= 0 counts (negative too). Policy, rules and `-State` headers are
    skipped. Returns the header name, or None.
    """
    for name, value in headers.items():
        lowered = name.lower()
        if (
            not lowered.startswith("x-rate-limit-")
            or lowered.endswith("-state")
            or lowered in ("x-rate-limit-policy", "x-rate-limit-rules")
        ):
            continue
        for entry in value.split(","):
            try:
                if int(entry.split(":")[0].strip()) <= 0:
                    return name
            except ValueError:
                continue
    return None


def has_active_penalty(snapshot: PolicySnapshot) -> bool:
    """Return True if any rule state reports an active penalty (> 0 seconds)."""
    return any(
        pair.state.active_penalty_seconds > 0 for pairs in snapshot.rules.values() for pair in pairs
    )


def parse_retry_after(headers: Mapping[str, str], now: datetime | None = None) -> float | None:
    """Return the `Retry-After` value in seconds, or None if absent or unusable.

    Accepts a number of seconds, or an HTTP date (then `now`, default current UTC time, is
    used to turn it into seconds). Non-finite values (nan, inf, overflow) give None. Negative
    values give 0.0; values above MAX_RETRY_AFTER_SECONDS (30 days) are clamped to it.
    """
    raw = _lower(headers).get("retry-after")
    if raw is None:
        return None
    raw = raw.strip()
    try:
        seconds = float(raw)
    except ValueError:
        seconds = None
    if seconds is not None:
        if not math.isfinite(seconds):
            return None
        return min(max(0.0, seconds), float(MAX_RETRY_AFTER_SECONDS))
    try:
        when = parsedate_to_datetime(raw)
        if when.tzinfo is None:
            when = when.replace(tzinfo=UTC)
        seconds = (when - (now or datetime.now(UTC))).total_seconds()
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(seconds):
        return None
    return min(max(0.0, seconds), float(MAX_RETRY_AFTER_SECONDS))


def hold_seconds(retry_after_seconds: float | None) -> float:
    """Turn a (possibly missing or bad) Retry-After into a safe hold in seconds.

    None, non-finite, non-numeric or non-positive values give DEFAULT_RETRY_AFTER_SECONDS;
    anything above MAX_RETRY_AFTER_SECONDS is clamped.
    """
    try:
        value = float(retry_after_seconds)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return float(DEFAULT_RETRY_AFTER_SECONDS)
    if not math.isfinite(value) or value <= 0:
        return float(DEFAULT_RETRY_AFTER_SECONDS)
    return min(value, float(MAX_RETRY_AFTER_SECONDS))

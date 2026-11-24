from datetime import UTC, datetime

import pytest

from backend.crawler.rate_limit_headers import (
    RateLimitRule,
    RateLimitState,
    find_active_penalty,
    find_zero_limit,
    has_active_penalty,
    has_rate_limit_headers,
    has_zero_limit,
    hold_seconds,
    parse_rate_limit_headers,
    parse_retry_after,
    policy_header,
)

from .conftest import CHARACTER_HEADERS, ITEMS_HEADERS, LADDER_HEADERS


def test_ladder_policy() -> None:
    snap = parse_rate_limit_headers(LADDER_HEADERS)
    assert snap is not None
    assert snap.policy == "ladder-view"
    pairs = snap.rules["Ip"]
    assert [p.rule for p in pairs] == [RateLimitRule(5, 5, 10), RateLimitRule(10, 10, 60)]
    assert pairs[0].state == RateLimitState(1, 5, 0)


def test_multiple_rules_character_and_items() -> None:
    snap = parse_rate_limit_headers(CHARACTER_HEADERS)
    assert snap is not None
    assert set(snap.rules) == {"Ip", "Account"}
    assert len(snap.rules["Account"]) == 3
    assert snap.rules["Account"][1].state == RateLimitState(2, 1800, 0)
    items = parse_rate_limit_headers(ITEMS_HEADERS)
    assert items is not None
    assert items.rules["Ip"][0].rule == RateLimitRule(30, 60, 60)


def test_active_penalty() -> None:
    headers = dict(LADDER_HEADERS)
    headers["X-Rate-Limit-Ip-State"] = "6:5:10,6:10:0"
    snap = parse_rate_limit_headers(headers)
    assert snap is not None
    assert snap.rules["Ip"][0].state == RateLimitState(6, 5, 10)


def test_case_insensitive_names() -> None:
    lowered = {k.lower(): v for k, v in LADDER_HEADERS.items()}
    assert parse_rate_limit_headers(lowered) == parse_rate_limit_headers(LADDER_HEADERS)


def test_missing_state_header_means_zero_hits() -> None:
    headers = {k: v for k, v in LADDER_HEADERS.items() if not k.endswith("-State")}
    snap = parse_rate_limit_headers(headers)
    assert snap is not None
    assert snap.rules["Ip"][1].state == RateLimitState(0, 10, 0)


def test_missing_or_malformed_headers_give_none() -> None:
    assert parse_rate_limit_headers({}) is None
    no_policy = {k: v for k, v in LADDER_HEADERS.items() if k != "X-Rate-Limit-Policy"}
    assert parse_rate_limit_headers(no_policy) is None
    no_rules = {k: v for k, v in LADDER_HEADERS.items() if k != "X-Rate-Limit-Rules"}
    assert parse_rate_limit_headers(no_rules) is None
    no_limit = {k: v for k, v in LADDER_HEADERS.items() if k != "X-Rate-Limit-Ip"}
    assert parse_rate_limit_headers(no_limit) is None
    assert parse_rate_limit_headers({**LADDER_HEADERS, "X-Rate-Limit-Ip": "5:5"}) is None
    assert parse_rate_limit_headers({**LADDER_HEADERS, "X-Rate-Limit-Ip": "a:b:c"}) is None
    assert parse_rate_limit_headers({**LADDER_HEADERS, "X-Rate-Limit-Ip-State": "1:5:0"}) is None


def test_retry_after_seconds() -> None:
    assert parse_retry_after({"Retry-After": "120"}) == 120.0
    assert parse_retry_after({"retry-after": "1.5"}) == 1.5
    assert parse_retry_after({}) is None
    assert parse_retry_after({"Retry-After": "soon"}) is None
    assert parse_retry_after({"Retry-After": "-5"}) == 0.0


def test_retry_after_http_date() -> None:
    now = datetime(2026, 11, 24, 12, 0, 0, tzinfo=UTC)
    headers = {"Retry-After": "Tue, 24 Nov 2026 12:01:00 GMT"}
    assert parse_retry_after(headers, now) == 60.0


@pytest.mark.parametrize("raw", ["inf", "-inf", "nan", "Infinity", "1e999"])
def test_retry_after_non_finite_is_none(raw) -> None:
    assert parse_retry_after({"Retry-After": raw}) is None


def test_retry_after_is_clamped_to_30_days() -> None:
    assert parse_retry_after({"Retry-After": "99999999999"}) == 30 * 24 * 3600
    far = {"Retry-After": "Fri, 31 Dec 9999 23:59:59 GMT"}
    assert parse_retry_after(far, datetime(2026, 11, 24, tzinfo=UTC)) == 30 * 24 * 3600


@pytest.mark.parametrize("raw", ["", "tomorrow", "Mon, 99 Foo 2026 99:99:99 GMT"])
def test_retry_after_garbage_is_none(raw) -> None:
    assert parse_retry_after({"Retry-After": raw}) is None


@pytest.mark.parametrize("bad", [None, float("inf"), float("nan"), -1.0, 0.0, "x"])
def test_hold_seconds_falls_back_to_default(bad) -> None:
    assert hold_seconds(bad) == 3600.0


def test_hold_seconds_values() -> None:
    assert hold_seconds(120) == 120.0
    assert hold_seconds(1e300) == 30 * 24 * 3600


@pytest.mark.parametrize("limit", ["5:0:10", "-5:5:10", "5:-5:10", "5:5:-1", "5:5:10,5:0:60"])
def test_non_positive_limits_are_malformed(limit) -> None:
    assert parse_rate_limit_headers({**LADDER_HEADERS, "X-Rate-Limit-Ip": limit}) is None


@pytest.mark.parametrize("state", ["-1:5:0,1:10:0", "1:5:-1,1:10:0", "1:0:0,1:10:0"])
def test_negative_state_values_are_malformed(state) -> None:
    assert parse_rate_limit_headers({**LADDER_HEADERS, "X-Rate-Limit-Ip-State": state}) is None


def test_active_penalty_detection() -> None:
    quiet = parse_rate_limit_headers(LADDER_HEADERS)
    assert quiet is not None and not has_active_penalty(quiet)
    hot = parse_rate_limit_headers({**LADDER_HEADERS, "X-Rate-Limit-Ip-State": "1:5:0,11:10:60"})
    assert hot is not None and has_active_penalty(hot)


def test_policy_header() -> None:
    assert policy_header(LADDER_HEADERS) == "ladder-view"
    assert policy_header({"x-rate-limit-policy": "  "}) is None
    assert policy_header({}) is None


def test_zero_limit_is_kept_and_detected() -> None:
    snap = parse_rate_limit_headers({**LADDER_HEADERS, "X-Rate-Limit-Ip": "5:5:10,0:10:60"})
    assert snap is not None and has_zero_limit(snap)
    ok = parse_rate_limit_headers(LADDER_HEADERS)
    assert ok is not None and not has_zero_limit(ok)


def test_lenient_penalty_scan_ignores_strict_parse() -> None:
    assert find_active_penalty({}) is None
    assert find_active_penalty(LADDER_HEADERS) is None
    assert find_active_penalty({"X-Rate-Limit-Account-State": "1:5:0,3:10:60"}) is not None
    assert find_active_penalty({"x-rate-limit-ip-state": "1:5:0:99,1:10:7:99"}) is not None
    assert find_active_penalty({"X-Rate-Limit-Ip-State": "1:5:oops,1:10:0"}) is None
    assert find_active_penalty({"X-Rate-Limit-Ip-State": "1:5"}) is None
    assert find_active_penalty({"X-Rate-Limit-Ip": "1:5:60"}) is None  # not a -State header


def test_has_rate_limit_headers() -> None:
    assert has_rate_limit_headers({"x-rate-limit-foo": "1"})
    assert not has_rate_limit_headers({"Retry-After": "1"})


def test_lenient_zero_limit_scan() -> None:
    assert find_zero_limit(LADDER_HEADERS) is None
    assert find_zero_limit({"X-Rate-Limit-Account": "5:5:10,0:10:60"}) is not None
    assert find_zero_limit({"x-rate-limit-ip": "0:5:10:99"}) is not None
    assert find_zero_limit({"X-Rate-Limit-Ip": "oops,5:5:10"}) is None
    assert find_zero_limit({"X-Rate-Limit-Ip-State": "0:5:0"}) is None  # state, not a limit
    assert find_zero_limit({"X-Rate-Limit-Policy": "0", "X-Rate-Limit-Rules": "0"}) is None


def test_negative_limits_count_as_zero_limit() -> None:
    assert find_zero_limit({"X-Rate-Limit-Ip": "5:5:10,-1:10:60"}) is not None
    assert find_zero_limit({"X-Rate-Limit-Ip": "-0:5:10"}) is not None

import logging
from datetime import timedelta

import httpx
import pytest

from backend.crawler.budget import DailyCharacterBudget
from backend.crawler.circuit_breaker import CircuitBreaker
from backend.crawler.constants import POLICY_CHARACTER, POLICY_ITEMS, POLICY_LADDER_VIEW
from backend.crawler.errors import (
    CircuitOpenError,
    CrawlerError,
    DailyBudgetExceededError,
    MissingContactInfoError,
    RateLimitedError,
)
from backend.crawler.http_client import SafeHttpClient
from backend.crawler.limiter import SharedRateLimiter
from backend.crawler.state import InMemoryStateStore

from .conftest import CHARACTER_HEADERS, ITEMS_HEADERS, LADDER_HEADERS

BASE = "https://www.pathofexile.com"
LADDER = BASE + "/api/ladders"
LEAGUES = BASE + "/api/leagues"
CHARS = BASE + "/character-window/get-characters"
ITEMS = BASE + "/character-window/get-items"
UA = "ELO/9.9 (+https://example.org/elo; contact: project@example.org)"


class Harness:
    def __init__(self, store, clock, handler=None, *, email="project@example.org") -> None:
        self.requests: list[httpx.Request] = []
        self.alerts: list[str] = []
        self.handler = handler or (lambda req: httpx.Response(200))
        self.store = store
        self.clock = clock
        self.breaker = CircuitBreaker(
            store, clock=clock, alert=lambda msg, **kw: self.alerts.append(msg)
        )
        self.budget = DailyCharacterBudget(store, clock=clock)
        self.limiter = SharedRateLimiter(store, clock=clock, sleep=clock.sleep)
        self.client = SafeHttpClient(
            limiter=self.limiter,
            breaker=self.breaker,
            budget=self.budget,
            version="9.9",
            contact_email=email,
            project_url="https://example.org/elo",
            transport=httpx.MockTransport(self._handle),
            clock=clock,
        )

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self.handler(request)


def test_sends_exact_user_agent_and_params(store, clock) -> None:
    h = Harness(store, clock, lambda r: httpx.Response(200, headers=LADDER_HEADERS))
    response = h.client.get(LADDER, params={"a": "b"})
    assert response.status_code == 200
    assert h.requests[0].headers["user-agent"] == UA
    assert h.requests[0].url.params["a"] == "b"


@pytest.mark.parametrize("email", [None, ""])
def test_refuses_without_contact_email(store, clock, email) -> None:
    h = Harness(store, clock, email=email)
    with pytest.raises(MissingContactInfoError):
        h.client.get(ITEMS)
    assert h.requests == []
    assert h.budget.remaining() == 1700


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/api/leagues",
        BASE + "/api/something-else",
        "http://www.pathofexile.com/api/leagues",
        BASE + "/character-window/get-items/",
    ],
)
def test_unknown_endpoints_are_refused_and_nothing_is_sent(store, clock, url) -> None:
    h = Harness(store, clock)
    with pytest.raises(CrawlerError):
        h.client.get(url)
    assert h.requests == []
    assert h.budget.remaining() == 1700
    assert store.request_times(POLICY_ITEMS, clock.now - timedelta(days=1)) == []


def test_policy_comes_from_the_endpoint_table(store, clock) -> None:
    h = Harness(store, clock)
    h.client.get(LEAGUES)
    h.client.get(CHARS)
    h.client.get(ITEMS)
    day = clock.now - timedelta(days=1)
    assert len(store.request_times(POLICY_LADDER_VIEW, day)) == 1
    assert len(store.request_times(POLICY_CHARACTER, day)) == 1
    assert len(store.request_times(POLICY_ITEMS, day)) == 1


def test_updates_limiter_from_response_headers(store, clock) -> None:
    h = Harness(store, clock, lambda r: httpx.Response(200, headers=ITEMS_HEADERS))
    h.client.get(ITEMS)
    live = store.get_live_limits(POLICY_ITEMS)
    assert live is not None and live["Ip"][0].max_hits == 30


def test_response_without_headers_is_fine(store, clock) -> None:
    h = Harness(store, clock)
    assert h.client.get(CHARS).status_code == 200


def test_requests_are_paced(store, clock) -> None:
    h = Harness(store, clock)
    h.client.get(LADDER)
    start = clock.now
    h.client.get(LADDER)
    assert (clock.now - start).total_seconds() >= 1.25


def test_only_items_endpoint_charges_budget(store, clock) -> None:
    h = Harness(store, clock)
    h.client.get(CHARS)
    h.client.get(LADDER)
    assert h.budget.remaining() == 1700
    h.client.get(ITEMS)
    assert h.budget.remaining() == 1699


def test_budget_exhausted_blocks_items_only(store, clock) -> None:
    h = Harness(store, clock)
    store.budget_consume(clock.now.date(), 1700)
    with pytest.raises(DailyBudgetExceededError):
        h.client.get(ITEMS)
    assert h.requests == []
    h.client.get(CHARS)


def test_429_trips_breaker_alerts_once_and_blocks(store, clock) -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"Retry-After": "120", **LADDER_HEADERS})

    h = Harness(store, clock, handler)
    with pytest.raises(RateLimitedError) as exc:
        h.client.get(LADDER)
    assert exc.value.retry_after_seconds == 120
    assert len(h.alerts) == 1 and len(h.requests) == 1
    for url in (LADDER, CHARS, ITEMS):
        with pytest.raises(CircuitOpenError):
            h.client.get(url)
    assert len(h.requests) == 1 and len(h.alerts) == 1
    clock.advance(119)
    with pytest.raises(CircuitOpenError):
        h.client.get(LADDER)
    clock.advance(1)
    h.handler = lambda r: httpx.Response(200)
    assert h.client.get(LADDER).status_code == 200


def test_429_without_retry_after_holds_one_hour(store, clock) -> None:
    h = Harness(store, clock, lambda r: httpx.Response(429))
    with pytest.raises(RateLimitedError):
        h.client.get(LADDER)
    assert h.breaker.retry_at() == clock.now + timedelta(seconds=3600)


def test_429_with_http_date_retry_after(store, clock) -> None:
    date = "Tue, 24 Nov 2026 12:02:00 GMT"  # the fake clock starts at 12:00:00 UTC
    h = Harness(store, clock, lambda r: httpx.Response(429, headers={"Retry-After": date}))
    with pytest.raises(RateLimitedError) as exc:
        h.client.get(LADDER)
    assert exc.value.retry_after_seconds == 120
    assert h.breaker.retry_at() == clock.now + timedelta(seconds=120)


@pytest.mark.parametrize("raw", ["inf", "nan", "1e999", "-7", "garbage", "99999999999999999"])
def test_429_with_hostile_retry_after_still_trips_breaker(store, clock, raw) -> None:
    h = Harness(store, clock, lambda r: httpx.Response(429, headers={"Retry-After": raw}))
    with pytest.raises(RateLimitedError):
        h.client.get(LADDER)
    assert h.breaker.is_open()
    assert len(h.alerts) == 1
    with pytest.raises(CircuitOpenError):
        h.client.get(LADDER)
    until = h.breaker.retry_at()
    assert until is not None
    assert timedelta(0) < until - clock.now <= timedelta(days=30)


def test_429_blocks_locally_even_if_store_writes_fail(store, clock, caplog) -> None:
    class BrokenStore(InMemoryStateStore):
        broken = False

        def trip_breaker(self, open_until, reason):
            if self.broken:
                raise RuntimeError("db down")
            super().trip_breaker(open_until, reason)

    broken = BrokenStore()
    h = Harness(broken, clock, lambda r: httpx.Response(429, headers={"Retry-After": "300"}))
    broken.broken = True
    with caplog.at_level(logging.ERROR):
        with pytest.raises(RateLimitedError):
            h.client.get(LADDER)
    assert broken.breaker_state() is None  # the store never got it
    with pytest.raises(CircuitOpenError):
        h.client.get(LADDER)
    assert len(h.requests) == 1
    clock.advance(300)
    h.handler = lambda r: httpx.Response(200)
    assert h.client.get(LADDER).status_code == 200


def test_breaker_checked_before_budget(store, clock) -> None:
    h = Harness(store, clock)
    h.breaker.trip(60, "manual")
    with pytest.raises(CircuitOpenError):
        h.client.get(ITEMS)
    assert h.budget.remaining() == 1700


def test_other_status_codes_are_returned(store, clock) -> None:
    h = Harness(store, clock, lambda r: httpx.Response(404))
    assert h.client.get(CHARS).status_code == 404
    assert h.breaker.is_open() is False


def test_policy_mismatch_trips_breaker_records_hit_and_alerts(store, clock) -> None:
    # The table says ladder-view, GGG answers with the character policy.
    h = Harness(store, clock, lambda r: httpx.Response(200, headers=CHARACTER_HEADERS))
    assert h.client.get(LADDER).status_code == 200
    assert len(h.alerts) == 1 and "mismatch" in h.alerts[0]
    assert len(store.request_times(POLICY_CHARACTER, clock.now - timedelta(days=1))) == 1
    assert h.breaker.is_open()
    with pytest.raises(CircuitOpenError):
        h.client.get(LADDER)
    assert len(h.requests) == 1


def test_matching_policy_header_does_not_trip(store, clock) -> None:
    h = Harness(store, clock, lambda r: httpx.Response(200, headers=LADDER_HEADERS))
    h.client.get(LADDER)
    assert not h.breaker.is_open() and h.alerts == []


def _penalty_headers() -> dict[str, str]:
    return {**LADDER_HEADERS, "X-Rate-Limit-Ip-State": "6:5:10,6:10:0"}


def test_active_penalty_is_a_hard_stop_in_every_process(store, clock) -> None:
    h = Harness(store, clock, lambda r: httpx.Response(200, headers=_penalty_headers()))
    assert h.client.get(LADDER).status_code == 200
    assert len(h.alerts) == 1 and "restart by hand" in h.alerts[0]
    assert store.hard_stop_state() is not None
    clock.advance(10 * 24 * 3600)  # never expires on its own
    with pytest.raises(CircuitOpenError) as exc:
        h.client.get(LADDER)
    assert exc.value.retry_at is None
    # a different process (new objects, same store) is refused too
    other = Harness(store, clock)
    with pytest.raises(CircuitOpenError):
        other.client.get(CHARS)
    assert len(h.requests) == 1 and other.requests == []


def test_hard_stop_stays_locally_even_after_manual_reset_until_restart(store, clock) -> None:
    h = Harness(store, clock, lambda r: httpx.Response(200, headers=_penalty_headers()))
    h.client.get(LADDER)
    store.clear_hard_stop()
    with pytest.raises(CircuitOpenError):
        h.client.get(LADDER)  # this process stays stopped; restart it by hand
    fresh = Harness(store, clock)
    assert fresh.client.get(LADDER).status_code == 200


def test_429_with_penalty_stops_hard_and_alerts_once(store, clock) -> None:
    headers = {"Retry-After": "60", **_penalty_headers()}
    h = Harness(store, clock, lambda r: httpx.Response(429, headers=headers))
    with pytest.raises(RateLimitedError):
        h.client.get(LADDER)
    assert store.hard_stop_state() is not None
    assert len(h.alerts) == 1 and "restart by hand" in h.alerts[0]
    assert h.breaker.retry_at() is not None  # the timed hold is stored as well


def test_header_hits_slow_the_client_down(store, clock) -> None:
    busy = {**LADDER_HEADERS, "X-Rate-Limit-Ip-State": "4:5:0,4:10:0"}
    h = Harness(store, clock, lambda r: httpx.Response(200, headers=busy))
    h.client.get(LADDER)
    start = clock.now
    h.client.get(LADDER)
    assert (clock.now - start).total_seconds() >= 5


def test_penalty_found_even_if_account_header_is_missing(store, clock) -> None:
    headers = {
        "X-Rate-Limit-Policy": "ladder-view",
        "X-Rate-Limit-Rules": "Ip,Account",
        "X-Rate-Limit-Ip": "5:5:10,10:10:60",
        "X-Rate-Limit-Ip-State": "1:5:0,1:10:0",
        "X-Rate-Limit-Account-State": "9:5:30,1:10:0",  # no X-Rate-Limit-Account header
    }
    h = Harness(store, clock, lambda r: httpx.Response(200, headers=headers))
    h.client.get(LADDER)
    assert store.hard_stop_state() is not None
    with pytest.raises(CircuitOpenError):
        h.client.get(LADDER)


def test_penalty_found_in_four_field_entry(store, clock) -> None:
    headers = {"X-Rate-Limit-Ip-State": "1:5:20:7,1:10:0:0"}
    h = Harness(store, clock, lambda r: httpx.Response(200, headers=headers))
    h.client.get(LADDER)
    assert store.hard_stop_state() is not None
    assert len([m for m in h.alerts if "restart by hand" in m]) == 1


def test_penalty_found_on_429_with_garbage_headers(store, clock) -> None:
    headers = {"X-Rate-Limit-Ip-State": "1:5:20", "Retry-After": "60"}
    h = Harness(store, clock, lambda r: httpx.Response(429, headers=headers))
    with pytest.raises(RateLimitedError):
        h.client.get(LADDER)
    assert store.hard_stop_state() is not None


def test_zero_limit_is_a_hard_stop(store, clock) -> None:
    headers = {**LADDER_HEADERS, "X-Rate-Limit-Ip": "0:5:10,10:10:60"}
    h = Harness(store, clock, lambda r: httpx.Response(200, headers=headers))
    h.client.get(LADDER)
    assert store.hard_stop_state() is not None
    assert len(h.alerts) == 1
    assert store.get_live_limits(POLICY_LADDER_VIEW) is None  # never stored
    with pytest.raises(CircuitOpenError):
        h.client.get(LADDER)


def test_malformed_headers_keep_limits_and_alert_once_per_policy_per_day(store, clock) -> None:
    bad = {"X-Rate-Limit-Policy": "ladder-view", "X-Rate-Limit-Rules": "Ip", "X-Rate-Limit-Ip": "x"}
    h = Harness(store, clock, lambda r: httpx.Response(200, headers=bad))
    h.client.get(LADDER)
    h.client.get(LADDER)
    assert h.alerts == ["rate-limit headers for ladder-view could not be parsed"]
    assert store.get_live_limits(POLICY_LADDER_VIEW) is None
    assert not h.breaker.is_open()
    clock.advance(24 * 3600)
    h.client.get(LADDER)
    assert len(h.alerts) == 2


def test_no_rate_limit_headers_means_no_malformed_alert(store, clock) -> None:
    h = Harness(store, clock)
    h.client.get(LADDER)
    assert h.alerts == []


class WriteFailingStore(InMemoryStateStore):
    def trip_breaker(self, open_until, reason):
        raise RuntimeError("db down")

    def set_hard_stop(self, reason, at):
        raise RuntimeError("db down")


def test_429_alerts_once_even_if_store_is_down(clock) -> None:
    h = Harness(WriteFailingStore(), clock, lambda r: httpx.Response(429))
    with pytest.raises(RateLimitedError):
        h.client.get(LADDER)
    assert len(h.alerts) == 1 and "could not persist" in h.alerts[0]
    with pytest.raises(CircuitOpenError):
        h.client.get(LADDER)  # local refusal
    assert len(h.alerts) == 1


def test_penalty_alerts_once_even_if_store_is_down(clock) -> None:
    headers = {"X-Rate-Limit-Ip-State": "1:5:20"}
    h = Harness(WriteFailingStore(), clock, lambda r: httpx.Response(200, headers=headers))
    h.client.get(LADDER)
    stops = [m for m in h.alerts if "restart by hand" in m]
    assert len(stops) == 1 and "could not persist" in stops[0]
    with pytest.raises(CircuitOpenError):
        h.client.get(LADDER)
    assert len([m for m in h.alerts if "restart by hand" in m]) == 1


def test_all_three_must_share_the_identical_store(store, clock) -> None:
    other = InMemoryStateStore()
    common = {"version": "1", "contact_email": "a@b.c", "project_url": "https://x.org"}
    limiter = SharedRateLimiter(store, clock=clock)
    breaker = CircuitBreaker(store, clock=clock)
    budget = DailyCharacterBudget(store, clock=clock)
    SafeHttpClient(limiter=limiter, breaker=breaker, budget=budget, **common)
    for bad in (
        dict(limiter=SharedRateLimiter(other, clock=clock), breaker=breaker, budget=budget),
        dict(limiter=limiter, breaker=CircuitBreaker(other, clock=clock), budget=budget),
        dict(limiter=limiter, breaker=breaker, budget=DailyCharacterBudget(other, clock=clock)),
    ):
        with pytest.raises(ValueError):
            SafeHttpClient(**bad, **common)


def test_create_builds_everything_from_one_store(store, clock) -> None:
    alerts: list[str] = []
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(429)

    client = SafeHttpClient.create(
        store,
        clock=clock,
        sleep=clock.sleep,
        version="9.9",
        contact_email="project@example.org",
        project_url="https://example.org/elo",
        transport=httpx.MockTransport(handler),
        alert=lambda msg, **kw: alerts.append(msg),
    )
    with pytest.raises(RateLimitedError):
        client.get(LADDER)
    assert seen[0].headers["user-agent"] == UA
    assert store.breaker_state() is not None
    assert len(store.request_times(POLICY_LADDER_VIEW, clock.now - timedelta(days=1))) == 1
    assert len(alerts) == 1


def test_zero_limit_found_without_strict_parse(store, clock) -> None:
    headers = {"X-Rate-Limit-Account": "0:5:10"}  # no policy/rules headers: strict parse fails
    h = Harness(store, clock, lambda r: httpx.Response(200, headers=headers))
    h.client.get(LADDER)
    assert store.hard_stop_state() is not None
    assert len([m for m in h.alerts if "restart by hand" in m]) == 1
    with pytest.raises(CircuitOpenError):
        h.client.get(LADDER)


def test_retention_exceeding_rule_is_refused_with_one_alert(store, clock) -> None:
    from backend.crawler.errors import HistoryRetentionError

    headers = {
        **LADDER_HEADERS,
        "X-Rate-Limit-Ip": "5:5:10,10:90000:60",
        "X-Rate-Limit-Ip-State": "1:5:0,1:90000:0",
    }
    h = Harness(store, clock, lambda r: httpx.Response(200, headers=headers))
    h.client.get(LADDER)  # the response itself is fine; the stored rule is the problem
    for _ in range(3):
        with pytest.raises(HistoryRetentionError):
            h.client.get(LADDER)
    assert len(h.requests) == 1
    assert len([m for m in h.alerts if "refuses to send" in m]) == 1


def test_negative_limit_is_a_hard_stop_via_lenient_scan(store, clock) -> None:
    headers = {**LADDER_HEADERS, "X-Rate-Limit-Ip": "-3:5:10,10:10:60"}
    h = Harness(store, clock, lambda r: httpx.Response(200, headers=headers))
    h.client.get(LADDER)
    assert store.hard_stop_state() is not None
    with pytest.raises(CircuitOpenError):
        h.client.get(LADDER)

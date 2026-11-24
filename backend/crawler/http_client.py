"""Safe HTTP client: the only way the crawler talks to GGG."""

import logging
from collections.abc import Callable, Mapping
from datetime import datetime, timedelta

import httpx

from backend.crawler.budget import DailyCharacterBudget, utc_day
from backend.crawler.circuit_breaker import CircuitBreaker
from backend.crawler.clock import Clock, SleepFn, system_clock, system_sleep
from backend.crawler.endpoints import resolve_endpoint
from backend.crawler.errors import (
    CircuitOpenError,
    DailyBudgetExceededError,
    HistoryRetentionError,
    RateLimitedError,
)
from backend.crawler.limiter import SharedRateLimiter
from backend.crawler.rate_limit_headers import (
    find_active_penalty,
    find_zero_limit,
    has_rate_limit_headers,
    has_zero_limit,
    hold_seconds,
    parse_rate_limit_headers,
    parse_retry_after,
    policy_header,
)
from backend.crawler.state import CrawlerStateStore
from backend.crawler.user_agent import build_user_agent

logger = logging.getLogger(__name__)


class SafeHttpClient:
    """Synchronous wrapper around `httpx.Client` (sync vs async is provisional).

    The rate-limit policy and the budget cost come from the hard-coded endpoint table
    (`backend.crawler.endpoints`), never from the caller; other URLs are refused.

    Order of checks for each request:
    0. endpoint table (refuse unknown host/path) and User-Agent (refuse if contact email or
       project URL is empty); nothing is touched on refusal
    1. process-local stop flags, then the circuit breaker / hard stop in the store
    2. daily budget pre-check (items endpoint only)
    3. rate limiter (waits without holding the lock; then, in one locked step, re-checks the
       breaker, charges the budget and records the request)
    4. the request
    5. on every response, before anything else: any `X-Rate-Limit-*-State` entry with an active
       penalty (found by a lenient scan that does not depend on the strict header parse) ->
       hard stop. Then: a limit of 0 hits -> hard stop; a different `X-Rate-Limit-Policy` than
       the table's -> hit recorded under it too, breaker tripped, alert; limiter updated from
       the headers
    6. on 429, the breaker is tripped first (alerts once) and RateLimitedError is raised

    Limiter, breaker and budget must share the identical store object (checked in `__init__`);
    `SafeHttpClient.create` builds all three from one store. Unparseable rate-limit headers
    keep the measured limits and raise one alert per policy per UTC day.

    After a 429, a policy mismatch or a hard stop the client also refuses locally (until the
    hold ends, or forever for a hard stop), even if the store write failed.

    Other status codes are returned unchanged; network errors propagate. Callers must not
    blindly retry items requests: every attempt charges one budget unit when it is sent.
    """

    def __init__(
        self,
        *,
        limiter: SharedRateLimiter,
        breaker: CircuitBreaker,
        budget: DailyCharacterBudget,
        version: str,
        contact_email: str | None,
        project_url: str | None,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 30.0,
        clock: Clock = system_clock,
    ) -> None:
        if not (limiter.store is breaker.store is budget.store):
            raise ValueError("limiter, breaker and budget must use the identical store object")
        self._limiter = limiter
        self._breaker = breaker
        self._budget = budget
        self._version = version
        self._contact_email = contact_email
        self._project_url = project_url
        self._clock = clock
        self._client = httpx.Client(transport=transport, timeout=timeout, follow_redirects=False)
        self._local_block_until: datetime | None = None
        self._local_hard_stop = False
        self._malformed_alerted: set[tuple[str, object]] = set()
        self._retention_alerted: set[str] = set()

    @classmethod
    def create(
        cls,
        store: CrawlerStateStore,
        *,
        clock: Clock = system_clock,
        sleep: SleepFn = system_sleep,
        version: str,
        contact_email: str | None,
        project_url: str | None,
        transport: httpx.BaseTransport | None = None,
        alert: Callable[..., None] | None = None,
        timeout: float = 30.0,
    ) -> "SafeHttpClient":
        """Build limiter, breaker, budget and client from one store."""
        return cls(
            limiter=SharedRateLimiter(store, clock=clock, sleep=sleep),
            breaker=CircuitBreaker(store, clock=clock, alert=alert),
            budget=DailyCharacterBudget(store, clock=clock),
            version=version,
            contact_email=contact_email,
            project_url=project_url,
            transport=transport,
            timeout=timeout,
            clock=clock,
        )

    def close(self) -> None:
        """Close the underlying httpx client."""
        self._client.close()

    def _block_locally(self, until: datetime) -> None:
        if self._local_block_until is None or until > self._local_block_until:
            self._local_block_until = until

    def _check_local(self) -> None:
        if self._local_hard_stop:
            raise CircuitOpenError(None, "Crawler is hard-stopped (reset by hand)")
        if self._local_block_until is not None and self._clock() < self._local_block_until:
            raise CircuitOpenError(self._local_block_until)

    @staticmethod
    def _guard(action: Callable[[], object], what: str) -> None:
        """Run a store/alert action; a failure must not hide the safety outcome."""
        try:
            action()
        except Exception:
            logger.exception("Crawler safety action failed: %s", what)

    def get(self, url: str, *, params: Mapping[str, str] | None = None) -> httpx.Response:
        """Send a GET request under the safety checks listed in the class docstring."""
        endpoint = resolve_endpoint(url)
        user_agent = build_user_agent(
            self._version, contact_email=self._contact_email, project_url=self._project_url
        )
        self._check_local()
        self._breaker.check()
        if endpoint.charges_budget and self._budget.remaining() < 1:
            raise DailyBudgetExceededError("Daily character budget exhausted")
        try:
            self._limiter.acquire(
                endpoint.policy, budget=self._budget if endpoint.charges_budget else None
            )
        except HistoryRetentionError as exc:
            if endpoint.policy not in self._retention_alerted:
                self._retention_alerted.add(endpoint.policy)
                message = f"crawler refuses to send: {exc}"
                self._guard(
                    lambda: self._breaker.send_notice(message),
                    "retention alert",
                )
            raise
        response = self._client.get(url, params=params, headers={"User-Agent": user_agent})
        at = self._clock()
        self._scan_penalty(response)  # before and independent of the strict header parse
        if response.status_code == 429:
            self._on_429(response, endpoint.policy, at)  # always raises
        self._after_response(response, endpoint.policy, at)
        return response

    def _scan_penalty(self, response: httpx.Response) -> None:
        found = find_active_penalty(response.headers)
        if found is not None:
            self._hard_stop_now(f"active penalty reported in {found}")
            return
        zero = find_zero_limit(response.headers)
        if zero is not None:
            self._hard_stop_now(f"GGG reports a limit of 0 hits in {zero}")

    def _hard_stop_now(self, reason: str) -> None:
        self._local_hard_stop = True
        self._guard(lambda: self._breaker.hard_stop(reason), "hard stop")

    def _notice_malformed(self, policy: str, at: datetime) -> None:
        key = (policy, utc_day(at))
        if key in self._malformed_alerted:
            return
        self._malformed_alerted.add(key)
        self._guard(
            lambda: self._breaker.send_notice(
                f"rate-limit headers for {policy} could not be parsed", level="warning"
            ),
            "malformed header alert",
        )

    def _on_429(self, response: httpx.Response, policy: str, at: datetime) -> None:
        try:
            retry_after = parse_retry_after(response.headers, now=at)
        except Exception:
            retry_after = None
        hold = hold_seconds(retry_after)
        self._block_locally(at + timedelta(seconds=hold))
        self._guard(lambda: self._breaker.trip(hold, f"HTTP 429 ({policy})"), "trip breaker")
        self._guard(lambda: self._limiter.on_rate_limited(hold), "limiter hold")
        self._after_response(response, policy, at)
        raise RateLimitedError(retry_after)

    def _after_response(self, response: httpx.Response, policy: str, at: datetime) -> None:
        snapshot = parse_rate_limit_headers(response.headers)
        if snapshot is None and has_rate_limit_headers(response.headers):
            self._notice_malformed(policy_header(response.headers) or policy, at)
        zero_limit = snapshot is not None and has_zero_limit(snapshot)
        header_policy = policy_header(response.headers)
        if header_policy is not None and header_policy != policy:
            self._block_locally(at + timedelta(seconds=hold_seconds(None)))
            self._guard(lambda: self._limiter.record_extra_hit(header_policy, at), "extra hit")
            self._guard(
                lambda: self._breaker.trip(
                    None, f"policy mismatch: expected {policy!r}, GGG says {header_policy!r}"
                ),
                "trip breaker (policy mismatch)",
            )
        if snapshot is not None and not zero_limit:
            self._guard(lambda: self._limiter.update_from_headers(snapshot, at=at), "update limits")

"""Circuit breaker: any 429 stops all jobs; an active GGG penalty stops them for good."""

from collections.abc import Callable
from datetime import datetime, timedelta

from backend.crawler.clock import Clock, system_clock
from backend.crawler.errors import CircuitOpenError
from backend.crawler.rate_limit_headers import hold_seconds
from backend.crawler.state import CrawlerStateStore

AlertFn = Callable[..., None]

HARD_STOP_MESSAGE = "crawler stopped: active penalty from GGG, restart by hand"
NOT_PERSISTED_NOTE = "could not persist the {what}; other jobs may still be running"


class CircuitBreaker:
    """Stops all crawler jobs after a 429 or a hard stop. State is kept in the store.

    Alerts never depend on the store: if a store write raises, the alert is still sent (with
    a note that the stop could not be persisted) and the exception is then re-raised.
    """

    def __init__(
        self,
        store: CrawlerStateStore,
        *,
        clock: Clock = system_clock,
        alert: AlertFn | None = None,
    ) -> None:
        self._store = store
        self._clock = clock
        self._alert = alert  # default: backend.common.alerts.send_alert, imported lazily

    @property
    def store(self) -> CrawlerStateStore:
        return self._store

    def send_notice(self, message: str, *, level: str = "error") -> None:
        """Send an admin alert through the configured alert function."""
        alert = self._alert
        if alert is None:
            from backend.common.alerts import send_alert

            alert = send_alert
        alert(message, level=level)

    def trip(self, retry_after_seconds: float | None, reason: str) -> None:
        """Open the breaker and stop all jobs for at least Retry-After (default 1 h).

        Calls `send_alert` once per trip, even if the store write raises (the exception is
        then re-raised). If the breaker is already open, the hold is only extended (never
        shortened) and no second alert is sent. A missing, non-finite or non-positive
        Retry-After means the default of 3,600 s; more than 30 days is clamped.
        """
        seconds = hold_seconds(retry_after_seconds)
        open_until = self._clock() + timedelta(seconds=seconds)
        was_open = False
        persisted = False
        try:
            with self._store.with_lock():
                was_open = self.is_open()
                self._store.trip_breaker(open_until, reason)
            persisted = True
        finally:
            if not was_open:
                note = "" if persisted else " " + NOT_PERSISTED_NOTE.format(what="hold") + "."
                self.send_notice(
                    f"Crawler circuit breaker tripped: {reason}. "
                    f"All GGG requests stopped until {open_until.isoformat()}.{note}"
                )

    def hard_stop(self, reason: str) -> None:
        """Set the persistent hard stop (never expires) and send one alert, once.

        The alert is sent even if the store write raises (then re-raised, with a note in the
        alert). Only `python -m backend.crawler.reset_stop` clears it. If the flag was already
        set, nothing changes and no second alert is sent.
        """
        newly_set = True  # assume so if the store cannot tell us
        persisted = False
        try:
            with self._store.with_lock():
                newly_set = self._store.set_hard_stop(reason, self._clock())
            persisted = True
        finally:
            if newly_set:
                note = "" if persisted else " " + NOT_PERSISTED_NOTE.format(what="stop") + "."
                self.send_notice(f"{HARD_STOP_MESSAGE} ({reason}).{note}")

    def is_hard_stopped(self) -> bool:
        """Return True while the hard-stop flag is set."""
        return self._store.hard_stop_state() is not None

    def is_open(self) -> bool:
        """Return True while the breaker is open or the crawler is hard-stopped."""
        return self.is_hard_stopped() or self.retry_at() is not None

    def retry_at(self) -> datetime | None:
        """Return when the timed breaker may close, or None if it is closed."""
        state = self._store.breaker_state()
        if state is not None and self._clock() < state.open_until:
            return state.open_until
        return None

    def check(self) -> None:
        """Raise CircuitOpenError if the breaker is open (retry_at None for a hard stop)."""
        if self.is_hard_stopped():
            raise CircuitOpenError(None, "Crawler is hard-stopped (reset by hand)")
        retry_at = self.retry_at()
        if retry_at is not None:
            raise CircuitOpenError(retry_at)

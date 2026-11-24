from datetime import timedelta

import pytest

from backend.crawler.circuit_breaker import CircuitBreaker
from backend.crawler.errors import CircuitOpenError
from backend.crawler.state import InMemoryStateStore


def make(store, clock, alerts: list[str] | None = None) -> CircuitBreaker:
    sink = alerts if alerts is not None else []
    return CircuitBreaker(store, clock=clock, alert=lambda msg, **kw: sink.append(msg))


def test_trip_opens_for_retry_after_and_alerts_once(store, clock) -> None:
    alerts: list[str] = []
    breaker = make(store, clock, alerts)
    assert not breaker.is_open()
    assert breaker.retry_at() is None
    breaker.check()
    breaker.trip(120, "429 test")
    assert breaker.is_open()
    assert breaker.retry_at() == clock.now + timedelta(seconds=120)
    with pytest.raises(CircuitOpenError) as exc:
        breaker.check()
    assert exc.value.retry_at == clock.now + timedelta(seconds=120)
    assert len(alerts) == 1 and "429 test" in alerts[0]
    breaker.trip(60, "again")
    assert len(alerts) == 1
    assert breaker.retry_at() == clock.now + timedelta(seconds=120)


def test_default_is_one_hour(store, clock) -> None:
    breaker = make(store, clock)
    breaker.trip(None, "no header")
    assert breaker.retry_at() == clock.now + timedelta(seconds=3600)
    breaker2 = make(type(store)(), clock)
    breaker2.trip(0, "zero")
    assert breaker2.retry_at() == clock.now + timedelta(seconds=3600)


@pytest.mark.parametrize("bad", [float("inf"), float("nan"), float("-inf"), -5.0])
def test_non_finite_or_negative_hold_uses_default(store, clock, bad) -> None:
    breaker = make(store, clock)
    breaker.trip(bad, "bad value")
    assert breaker.retry_at() == clock.now + timedelta(seconds=3600)


def test_huge_hold_is_clamped_to_30_days(store, clock) -> None:
    breaker = make(store, clock)
    breaker.trip(1e300, "huge")
    assert breaker.retry_at() == clock.now + timedelta(days=30)


def test_closes_after_retry_after(store, clock) -> None:
    breaker = make(store, clock)
    breaker.trip(30, "x")
    clock.advance(29)
    assert breaker.is_open()
    clock.advance(1)
    assert not breaker.is_open()
    breaker.check()


def test_stays_open_across_restart_and_new_trip_alerts_again(store, clock) -> None:
    alerts: list[str] = []
    make(store, clock, alerts).trip(100, "first")
    restarted = make(store, clock, alerts)
    assert restarted.is_open()
    clock.advance(100)
    restarted.trip(10, "second")
    assert len(alerts) == 2


def test_default_alert_is_send_alert(store, clock, monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr("backend.common.alerts.send_alert", lambda m, **k: calls.append(m))
    CircuitBreaker(store, clock=clock).trip(10, "default alert")
    assert len(calls) == 1


def test_hard_stop_never_expires_alerts_once_and_blocks_check(store, clock) -> None:
    alerts: list[str] = []
    breaker = make(store, clock, alerts)
    breaker.hard_stop("penalty on ladder-view")
    breaker.hard_stop("penalty again")
    assert len(alerts) == 1
    assert "restart by hand" in alerts[0]
    clock.advance(10 * 365 * 24 * 3600)
    assert breaker.is_hard_stopped() and breaker.is_open()
    assert breaker.retry_at() is None
    with pytest.raises(CircuitOpenError) as exc:
        breaker.check()
    assert exc.value.retry_at is None
    # persisted: a new breaker object on the same store sees it too
    assert make(store, clock).is_hard_stopped()


class FailingStore(InMemoryStateStore):
    def trip_breaker(self, open_until, reason):
        raise RuntimeError("db down")

    def set_hard_stop(self, reason, at):
        raise RuntimeError("db down")


def test_trip_alerts_even_if_store_write_fails(clock) -> None:
    alerts: list[str] = []
    breaker = make(FailingStore(), clock, alerts)
    with pytest.raises(RuntimeError):
        breaker.trip(60, "429")
    assert len(alerts) == 1
    assert "could not persist the hold; other jobs may still be running" in alerts[0]


def test_hard_stop_alerts_even_if_store_write_fails(clock) -> None:
    alerts: list[str] = []
    breaker = make(FailingStore(), clock, alerts)
    with pytest.raises(RuntimeError):
        breaker.hard_stop("penalty")
    assert len(alerts) == 1
    assert "could not persist the stop; other jobs may still be running" in alerts[0]

from datetime import UTC, datetime, timedelta, timezone

import pytest

from backend.crawler.budget import DailyCharacterBudget


def test_1701st_character_is_refused(store, clock) -> None:
    budget = DailyCharacterBudget(store, clock=clock)
    assert budget.remaining() == 1700
    for _ in range(1700):
        assert budget.try_consume()
    assert budget.remaining() == 0
    assert budget.try_consume() is False
    assert budget.remaining() == 0


def test_refused_consume_takes_nothing(store, clock) -> None:
    budget = DailyCharacterBudget(store, clock=clock, max_per_day=5)
    assert budget.try_consume(3)
    assert budget.try_consume(3) is False
    assert budget.remaining() == 2


def test_state_survives_a_new_budget_object(store, clock) -> None:
    DailyCharacterBudget(store, clock=clock).try_consume(1700)
    restarted = DailyCharacterBudget(store, clock=clock)
    assert restarted.remaining() == 0
    assert restarted.try_consume() is False


def test_resets_on_utc_midnight(store, clock) -> None:
    budget = DailyCharacterBudget(store, clock=clock)
    budget.try_consume(1700)
    clock.advance(24 * 3600)
    assert budget.remaining() == 1700
    assert budget.try_consume()


def test_day_boundary_is_utc(store, clock) -> None:
    clock.now = clock.now.replace(hour=23, minute=59, second=59)
    budget = DailyCharacterBudget(store, clock=clock)
    budget.try_consume(1700)
    clock.now += timedelta(seconds=1)
    assert budget.remaining() == 1700


def test_explicit_time_decides_the_day(store, clock) -> None:
    budget = DailyCharacterBudget(store, clock=clock)
    later = clock.now + timedelta(days=1)
    assert budget.try_consume(1, at=later)
    assert store.budget_used(later.date()) == 1
    assert store.budget_used(clock.now.date()) == 0


def test_non_utc_aware_time_is_converted(store, clock) -> None:
    budget = DailyCharacterBudget(store, clock=clock)
    # 01:00 on 25 Nov at UTC+2 is 23:00 on 24 Nov UTC.
    local = datetime(2026, 11, 25, 1, 0, tzinfo=timezone(timedelta(hours=2)))
    budget.try_consume(1, at=local)
    assert store.budget_used(datetime(2026, 11, 24, tzinfo=UTC).date()) == 1


def test_naive_datetime_is_rejected(store, clock) -> None:
    budget = DailyCharacterBudget(store, clock=clock)
    with pytest.raises(ValueError):
        budget.try_consume(1, at=datetime(2026, 11, 24, 12, 0))
    with pytest.raises(ValueError):
        budget.remaining(at=datetime(2026, 11, 24, 12, 0))
    naive = DailyCharacterBudget(store, clock=lambda: datetime(2026, 11, 24, 12, 0))
    with pytest.raises(ValueError):
        naive.remaining()

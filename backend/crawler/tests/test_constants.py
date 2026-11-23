import pytest

from backend.crawler import constants
from backend.crawler.budget import DailyCharacterBudget


def test_values() -> None:
    assert constants.RATE_LIMIT_CAP_FRACTION == 0.8
    assert constants.DAILY_CHARACTER_MAX == 1700
    assert constants.DEFAULT_RETRY_AFTER_SECONDS == 3600


def test_policy_names() -> None:
    assert constants.POLICY_LADDER_VIEW == "ladder-view"
    assert constants.POLICY_CHARACTER == "backend-character-request-limit"
    assert constants.POLICY_ITEMS == "backend-item-request-limit"


def test_measured_limits() -> None:
    assert dict(constants.MEASURED_LIMITS) == {
        "ladder-view": ((5, 5), (10, 10)),
        "backend-character-request-limit": ((15, 60), (90, 1800), (180, 7200)),
        "backend-item-request-limit": ((30, 60), (90, 1800), (180, 7200)),
    }


def test_measured_limits_read_only() -> None:
    with pytest.raises(TypeError):
        constants.MEASURED_LIMITS["x"] = ()  # type: ignore[index]


def test_budget_cap_guard() -> None:
    DailyCharacterBudget()
    DailyCharacterBudget(1700)
    DailyCharacterBudget(10)
    with pytest.raises(ValueError):
        DailyCharacterBudget(1701)


@pytest.mark.parametrize("bad", [0, -1, -1700])
def test_budget_rejects_non_positive(bad: int) -> None:
    with pytest.raises(ValueError):
        DailyCharacterBudget(bad)


@pytest.mark.parametrize("bad", [True, False, 1.5, "10", None])
def test_budget_rejects_non_int(bad: object) -> None:
    with pytest.raises(TypeError):
        DailyCharacterBudget(bad)  # type: ignore[arg-type]

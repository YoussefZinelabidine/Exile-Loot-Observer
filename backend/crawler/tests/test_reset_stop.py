import logging
from pathlib import Path

import pytest

from backend.crawler import reset_stop


def test_reset_clears_and_logs_who_and_when(store, clock, caplog) -> None:
    store.set_hard_stop("active penalty", clock.now)
    with caplog.at_level(logging.INFO, logger="backend.crawler.reset_stop"):
        assert reset_stop.reset_hard_stop(store, who="alice", clock=clock) is True
    assert store.hard_stop_state() is None
    text = caplog.text
    assert "restarted by hand" in text
    assert "alice" in text and clock.now.isoformat() in text and "active penalty" in text


def test_reset_with_nothing_set(store, clock) -> None:
    assert reset_stop.reset_hard_stop(store, who="alice", clock=clock) is False


def test_reset_requires_who(store, clock) -> None:
    store.set_hard_stop("x", clock.now)
    with pytest.raises(ValueError):
        reset_stop.reset_hard_stop(store, who="  ", clock=clock)
    assert store.hard_stop_state() is not None


def test_main_exits_2_when_the_store_cannot_be_opened(capsys) -> None:
    def broken():
        raise RuntimeError("no database")

    assert reset_stop.main(["--who", "alice"], store_factory=broken) == 2
    assert "Could not open" in capsys.readouterr().err


def test_main_with_store(store, clock) -> None:
    store.set_hard_stop("x", clock.now)
    assert reset_stop.main(["--who", "alice"], store_factory=lambda: store) == 0
    assert store.hard_stop_state() is None


def test_main_tells_the_operator_to_restart_crawlers(store, clock, capsys) -> None:
    store.set_hard_stop("x", clock.now)
    reset_stop.main(["--who", "alice"], store_factory=lambda: store)
    assert "restarted by hand" in capsys.readouterr().out


def test_no_code_path_uses_reset_stop() -> None:
    root = Path(reset_stop.__file__).parent
    offenders = []
    for path in root.rglob("*.py"):
        if path.name == "reset_stop.py" or "tests" in path.relative_to(root).parts:
            continue
        text = path.read_text(encoding="utf-8")
        for line in text.splitlines():
            if line.lstrip().startswith(("import ", "from ")) and "reset_stop" in line:
                offenders.append(path.name)
        if "clear_hard_stop(" in text and path.name not in ("state.py", "pg_store.py"):
            offenders.append(path.name)
    assert offenders == []


@pytest.mark.db
def test_reset_end_to_end_with_postgres(pg_store, clock, capsys) -> None:
    assert pg_store.set_hard_stop("active penalty", clock.now) is True
    assert reset_stop.main(["--who", "alice"], store_factory=lambda: _Keep(pg_store)) == 0
    assert "restarted by hand" in capsys.readouterr().out
    assert pg_store.hard_stop_state() is None


class _Keep:
    """Wrap a store so main()'s close() does not close the fixture's connection."""

    def __init__(self, inner) -> None:
        self._inner = inner

    def __getattr__(self, name):
        return getattr(self._inner, name)

    def close(self) -> None:
        pass

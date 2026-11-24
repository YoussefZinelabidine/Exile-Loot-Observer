"""Manual reset of the crawler hard stop: `python -m backend.crawler.reset_stop --who NAME`.

For humans only. No code path in the application may import or call this module (a test
checks that). It clears the persistent hard-stop flag and logs who did it and when.
"""

import argparse
import logging
import sys
from collections.abc import Callable, Sequence

from backend.crawler.clock import Clock, system_clock
from backend.crawler.state import CrawlerStateStore

logger = logging.getLogger(__name__)

RESTART_NOTE = (
    "Every running crawler process must be restarted by hand for the reset to take effect."
)


def reset_hard_stop(store: CrawlerStateStore, *, who: str, clock: Clock = system_clock) -> bool:
    """Clear the hard stop. Return True if it was set, False if there was nothing to clear."""
    if not who.strip():
        raise ValueError("who must name the person resetting the stop")
    with store.with_lock():
        state = store.hard_stop_state()
        if state is None:
            logger.info("Hard stop reset requested by %s, but none was set", who)
            return False
        store.clear_hard_stop()
    logger.warning(
        "Crawler hard stop cleared by %s at %s (was set %s: %s). %s",
        who,
        clock().isoformat(),
        state.since.isoformat(),
        state.reason,
        RESTART_NOTE,
    )
    return True


def _postgres_store_from_settings() -> CrawlerStateStore:
    from backend.crawler.pg_store import PostgresStateStore

    return PostgresStateStore.from_settings()


def main(
    argv: Sequence[str] | None = None,
    *,
    store_factory: Callable[[], CrawlerStateStore] | None = None,
) -> int:
    """Command-line entry point. Returns the exit code."""
    parser = argparse.ArgumentParser(description="Clear the crawler hard stop (manual only).")
    parser.add_argument("--who", required=True, help="who is resetting the stop (logged)")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO)
    if store_factory is None:
        store_factory = _postgres_store_from_settings
    try:
        store = store_factory()
    except Exception as exc:
        print(f"Could not open the crawler state store ({type(exc).__name__}).", file=sys.stderr)
        return 2
    try:
        cleared = reset_hard_stop(store, who=args.who)
    finally:
        close = getattr(store, "close", None)
        if callable(close):
            close()
    print(f"Hard stop cleared. {RESTART_NOTE}" if cleared else "No hard stop was set.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

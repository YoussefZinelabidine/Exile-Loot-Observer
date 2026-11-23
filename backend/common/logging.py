"""Logging setup with one consistent format. Callers must never log secrets."""

import logging

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def setup_logging(level: str | int = "INFO") -> None:
    if isinstance(level, str):
        level = level.upper()
    logging.basicConfig(level=level, format=LOG_FORMAT, force=True)
    # httpx logs full request URLs at INFO, which would leak webhook URLs.
    logging.getLogger("httpx").setLevel(logging.WARNING)

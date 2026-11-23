"""Admin alerts: Discord webhook when configured, otherwise log only."""

import logging

import httpx

from backend.common.config import get_settings

logger = logging.getLogger(__name__)

_LEVELS = {
    "debug": logging.DEBUG,
    "info": logging.INFO,
    "warning": logging.WARNING,
    "error": logging.ERROR,
    "critical": logging.CRITICAL,
}


def send_alert(message: str, *, level: str = "error") -> None:
    """Log the message and, if a webhook is set, post it. Never raises."""
    logger.log(_LEVELS.get(level.lower(), logging.ERROR), "ALERT: %s", message)
    try:
        webhook = get_settings().discord_webhook_url
        if webhook is None or not webhook.get_secret_value():
            return
        httpx.post(
            webhook.get_secret_value(),
            json={"content": f"[ELO {level.upper()}] {message}"[:2000]},
            timeout=5.0,
        ).raise_for_status()
    except Exception as exc:  # an alert must never crash a job
        # Log only the exception type: the message could contain the webhook URL.
        logger.warning("Alert delivery failed (%s)", type(exc).__name__)

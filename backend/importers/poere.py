"""poe.re importer: current.json -> patch -> SHA256SUMS + item file (checksum verified).

Layout (verified against the real host): ``https://data.poe.re/current.json`` is
``{"current": {"poe1": {"game", "patch", "commit", "time"}, ...}, "last_run": {...}}``; files
live at ``https://data.poe.re/generated/poe1/<patch>/<path>``, with ``SHA256SUMS`` (lines
``<hex64>  <path>``) in the same folder.
"""

import json
import logging
import re

import httpx

from backend.common import alerts
from backend.importers.checks import missing_scored_classes
from backend.importers.errors import ImporterError
from backend.importers.http import get_bytes
from backend.importers.result import ImportResult
from backend.importers.store import DataStore, sha256_hex

logger = logging.getLogger(__name__)

SOURCE = "poere"
BASE_URL = "https://data.poe.re"
FILES_PATH = "generated/poe1"
ITEM_FILE = "item/Generated.Item.ENGLISH.min.json"
STORED_ITEM_NAME = "Generated.Item.ENGLISH.min.json"

_SUM_LINE = re.compile(r"^([0-9a-fA-F]{64})\s+\*?(.+?)\s*$")


def parse_current(data: bytes) -> tuple[str, str | None]:
    """Return ``(patch, commit)`` of poe1 from current.json."""
    try:
        entry = json.loads(data)["current"]["poe1"]
        patch, commit = entry["patch"], entry.get("commit")
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        raise ImporterError("poe.re current.json has an unexpected shape") from exc
    if not isinstance(patch, str) or not re.fullmatch(r"[0-9]+(\.[0-9]+)+", patch):
        raise ImporterError("poe.re current.json has no valid poe1 patch")
    if commit is not None and not isinstance(commit, str):
        raise ImporterError("poe.re current.json has an invalid commit")
    return patch, commit


def parse_sha256sums(data: bytes) -> dict[str, str]:
    sums = {}
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ImporterError("poe.re SHA256SUMS is not valid text") from exc
    for line in text.splitlines():
        match = _SUM_LINE.match(line)
        if match:
            path = match.group(2).replace("\\", "/")
            sums[path.removeprefix("./")] = match.group(1).lower()
    return sums


def parse_items(data: bytes) -> list[dict]:
    try:
        parsed = json.loads(data)
    except ValueError as exc:
        raise ImporterError("poe.re item file is not valid JSON") from exc
    if not isinstance(parsed, list) or not parsed or not all("basetype" in x for x in parsed):
        raise ImporterError("poe.re item file has an unexpected shape")
    return parsed


def import_poere(
    client: httpx.Client, store: DataStore, *, base_url: str = BASE_URL
) -> ImportResult:
    patch = None
    commit = None
    try:
        patch, commit = parse_current(get_bytes(client, f"{base_url}/current.json"))
        if store.has_version(SOURCE, patch):
            return ImportResult(SOURCE, "unchanged", patch)
        sums = parse_sha256sums(get_bytes(client, f"{base_url}/{FILES_PATH}/{patch}/SHA256SUMS"))
        data = get_bytes(client, f"{base_url}/{FILES_PATH}/{patch}/{ITEM_FILE}")
        expected = sums.get(ITEM_FILE)
        if expected is None or sha256_hex(data) != expected:
            reason = "no checksum listed" if expected is None else "checksum mismatch"
            alerts.send_alert(f"poe.re {patch} rejected ({reason}), keeping last good copy")
            return ImportResult(SOURCE, "rejected", patch, message=reason, commit=commit)
        missing = missing_scored_classes(parse_items(data))
        if missing:
            reason = f"scored item classes missing from poe.re: {', '.join(missing)}"
            alerts.send_alert(f"poe.re {patch} rejected ({reason}), keeping last good copy")
            return ImportResult(SOURCE, "rejected", patch, message=reason, commit=commit)
        listing = store.commit(SOURCE, patch, {STORED_ITEM_NAME: data})
    except ImporterError as exc:
        alerts.send_alert(f"poe.re import failed, keeping last good copy: {exc}")
        return ImportResult(SOURCE, "failed", patch, message=str(exc))
    logger.info("poe.re %s staged", patch)
    return ImportResult(SOURCE, "staged", patch, listing, commit=commit)


def load_items(store: DataStore, version: str) -> list[dict]:
    return parse_items(store.read(SOURCE, version, STORED_ITEM_NAME))

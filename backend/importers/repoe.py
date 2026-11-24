"""RePoE importer: https://repoe-fork.github.io/<file> (site root, not /data/)."""

import json
import logging
from typing import Any

import httpx

from backend.common import alerts
from backend.importers.errors import ImporterError
from backend.importers.http import get_bytes
from backend.importers.result import ImportResult
from backend.importers.store import DataStore

logger = logging.getLogger(__name__)

SOURCE = "repoe"
BASE_URL = "https://repoe-fork.github.io"
VERSION_FILE = "version.txt"
# TODO (decision 35): the bench-craftable stat list (patch ``craftable_stat_ids``) is built from
# crafting_bench_options.json in the Phase 3 patch-builder job, not here; this module only
# downloads and checks the file.
JSON_FILES = (
    "mods.json",
    "stat_translations.json",
    "base_items.json",
    "mods_by_base.json",
    "gems.json",
    "crafting_bench_options.json",
)
# Expected top-level JSON type per file.
EXPECTED_TYPE: dict[str, type] = {
    "mods.json": dict,
    "stat_translations.json": list,
    "base_items.json": dict,
    "mods_by_base.json": dict,
    "gems.json": dict,
    "crafting_bench_options.json": list,
}


def parse_json_file(name: str, data: bytes) -> Any:
    try:
        parsed = json.loads(data)
    except ValueError as exc:
        raise ImporterError(f"{name} is not valid JSON") from exc
    expected = EXPECTED_TYPE[name]
    if not isinstance(parsed, expected) or not parsed:
        raise ImporterError(f"{name} is empty or not a JSON {expected.__name__}")
    return parsed


def parse_version(data: bytes) -> str:
    try:
        version = data.decode("utf-8").strip()
    except UnicodeDecodeError as exc:
        raise ImporterError("version.txt is not valid text") from exc
    if not version or "\n" in version:
        raise ImporterError("version.txt is empty or malformed")
    return version


def import_repoe(
    client: httpx.Client, store: DataStore, *, base_url: str = BASE_URL
) -> ImportResult:
    """Download one RePoE version into the store (not yet active).

    Any failure keeps the last good copy untouched, raises an alert, and returns ``failed``.
    """
    try:
        version = parse_version(get_bytes(client, f"{base_url}/{VERSION_FILE}"))
        if store.has_version(SOURCE, version):
            return ImportResult(SOURCE, "unchanged", version)
        files = {VERSION_FILE: f"{version}\n".encode()}
        for name in JSON_FILES:
            data = get_bytes(client, f"{base_url}/{name}")
            parse_json_file(name, data)
            files[name] = data
        if parse_version(get_bytes(client, f"{base_url}/{VERSION_FILE}")) != version:
            raise ImporterError("RePoE version changed during the download")
        listing = store.commit(SOURCE, version, files)
    except ImporterError as exc:
        alerts.send_alert(f"RePoE import failed, keeping last good copy: {exc}")
        return ImportResult(SOURCE, "failed", message=str(exc))
    logger.info("RePoE %s staged", version)
    return ImportResult(SOURCE, "staged", version, listing)


def load(store: DataStore, version: str, name: str) -> Any:
    return parse_json_file(name, store.read(SOURCE, version, name))

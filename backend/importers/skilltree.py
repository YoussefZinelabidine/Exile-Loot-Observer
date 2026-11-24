"""GGG skill tree export on GitHub (grindinggear/skilltree-export).

ASSUMPTIONS to confirm at the first real download: the default branch is ``master`` and the
export is ``data.json`` at its root. The commit SHA (first 12 characters) is recorded as the
version, and the file is fetched at that exact commit so version and content always match.
The spec also allows a release tag; this uses the commit.
"""

import json
import logging

import httpx

from backend.common import alerts
from backend.importers.errors import ImporterError
from backend.importers.http import get_bytes
from backend.importers.result import ImportResult
from backend.importers.store import DataStore

logger = logging.getLogger(__name__)

SOURCE = "skilltree"
REPO = "grindinggear/skilltree-export"
BRANCH = "master"
API_URL = "https://api.github.com"
RAW_URL = "https://raw.githubusercontent.com"
FILE = "data.json"


def parse_commit(data: bytes) -> str:
    try:
        sha = json.loads(data)["sha"]
    except (ValueError, KeyError, TypeError) as exc:
        raise ImporterError("GitHub commit response has an unexpected shape") from exc
    if not isinstance(sha, str) or len(sha) < 12 or any(c not in "0123456789abcdef" for c in sha):
        raise ImporterError("GitHub commit response has no valid sha")
    return sha


def parse_tree(data: bytes) -> dict:
    try:
        parsed = json.loads(data)
    except ValueError as exc:
        raise ImporterError("skill tree data.json is not valid JSON") from exc
    if not isinstance(parsed, dict) or not parsed:
        raise ImporterError("skill tree data.json is empty or not an object")
    return parsed


def import_skilltree(
    client: httpx.Client, store: DataStore, *, api_url: str = API_URL, raw_url: str = RAW_URL
) -> ImportResult:
    try:
        sha = parse_commit(get_bytes(client, f"{api_url}/repos/{REPO}/commits/{BRANCH}"))
        version = sha[:12]
        if store.has_version(SOURCE, version):
            return ImportResult(SOURCE, "unchanged", version)
        data = get_bytes(client, f"{raw_url}/{REPO}/{sha}/{FILE}")
        parse_tree(data)
        listing = store.commit(SOURCE, version, {FILE: data})
    except ImporterError as exc:
        alerts.send_alert(f"Skill tree import failed, keeping last good copy: {exc}")
        return ImportResult(SOURCE, "failed", message=str(exc))
    logger.info("skill tree %s staged", version)
    return ImportResult(SOURCE, "staged", version, listing)

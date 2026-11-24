"""Run all three importers once (``python -m backend.importers.run``).

Downloads into ``ELO_DATA_DIR`` and prints one line per source. It does not write to the
database and does not activate anything: activation (``store.set_active`` and
``registry.activate``) is a separate step after the cross-checks.
"""

import sys
from collections.abc import Callable

from backend.common import alerts
from backend.common.config import get_settings
from backend.common.logging import setup_logging
from backend.importers.checks import check_patch_versions
from backend.importers.errors import ImporterError
from backend.importers.http import build_data_user_agent, make_client
from backend.importers.poere import import_poere
from backend.importers.repoe import import_repoe
from backend.importers.result import ImportResult
from backend.importers.skilltree import import_skilltree
from backend.importers.store import DataStore


def _safe(source: str, run: Callable[[], ImportResult]) -> ImportResult:
    """Run one importer; any unexpected error becomes a ``failed`` result plus an alert."""
    try:
        return run()
    except Exception as exc:
        alerts.send_alert(f"{source} import crashed ({type(exc).__name__}), keeping last good copy")
        return ImportResult(source, "failed", message=type(exc).__name__)


def run_all(store: DataStore, client) -> list[ImportResult]:
    repoe = _safe("repoe", lambda: import_repoe(client, store))
    poere = _safe("poere", lambda: import_poere(client, store))
    skilltree = _safe("skilltree", lambda: import_skilltree(client, store))
    if repoe.version and poere.version:
        check_patch_versions(repoe.version, poere.version)
    return [repoe, poere, skilltree]


def main() -> int:
    settings = get_settings()
    setup_logging(settings.log_level)
    if settings.data_dir is None:
        print("ELO_DATA_DIR is not set", file=sys.stderr)
        return 2
    try:
        agent = build_data_user_agent(
            contact_email=settings.contact_email, project_url=settings.project_url
        )
    except ImporterError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    with make_client(agent) as client:
        results = run_all(DataStore(settings.data_dir), client)
    for result in results:
        print(f"{result.source}: {result.status} {result.version or ''} {result.message}".strip())
    return 0 if all(r.status != "failed" for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())

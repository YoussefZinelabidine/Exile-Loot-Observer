"""data_versions rows; run only on the throwaway elo_test database."""

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from backend.common.models import DataVersion
from backend.importers import registry
from backend.importers.result import ImportResult


@pytest.mark.db
def test_record_and_activate(test_engine: Engine):
    files = [{"path": "mods.json", "sha256": "ab" * 32}]
    with Session(test_engine) as s:
        try:
            assert registry.record_result(s, ImportResult("repoe", "unchanged", "1")) is None
            assert registry.record_result(s, ImportResult("repoe", "failed")) is None
            row = registry.record_result(s, ImportResult("repoe", "staged", "3.30", files))
            assert row is not None and row.status == "staged" and row.files == files
            assert registry.active_version(s, "repoe") is None
            registry.activate(s, "repoe", "3.30")
            assert registry.active_version(s, "repoe") == "3.30"
            # re-staging or rejecting an active version never demotes it
            registry.record_result(s, ImportResult("repoe", "staged", "3.30", files))
            registry.record_result(s, ImportResult("repoe", "rejected", "3.30"))
            assert registry.active_version(s, "repoe") == "3.30"
            # activating another version demotes the previous one (decision 36) ...
            registry.record_result(s, ImportResult("repoe", "staged", "3.31", files))
            registry.activate(s, "repoe", "3.31")
            assert registry.active_version(s, "repoe") == "3.31"
            assert s.get(DataVersion, ("repoe", "3.30")).status == "staged"
            # ... and rollback is activate on the old one
            registry.activate(s, "repoe", "3.30")
            assert registry.active_version(s, "repoe") == "3.30"
            assert s.get(DataVersion, ("repoe", "3.31")).status == "staged"
            rejected = registry.record_result(s, ImportResult("poere", "rejected", "3.30"))
            assert rejected is not None and rejected.status == "rejected"
            with pytest.raises(ValueError):
                registry.activate(s, "poere", "3.30")
        finally:
            s.rollback()

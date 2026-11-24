from datetime import UTC, date, datetime

import pytest
from alembic import command
from sqlalchemy import Engine, inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.common.config import Settings, get_settings, require_account_hash_salt
from backend.common.db import Base
from backend.common.models import (
    Character,
    CrawlerBreaker,
    CrawlerBudget,
    CrawlerHardStop,
    CrawlerLiveLimit,
    CrawlerOutsideHit,
    CrawlerRequest,
    DataVersion,
    League,
    RawGear,
    hash_account_name,
)
from backend.conftest import _alembic_config

TABLES = {
    "leagues",
    "characters",
    "raw_gear",
    "data_versions",
    "crawler_requests",
    "crawler_live_limits",
    "crawler_budget",
    "crawler_breaker",
    "crawler_outside_hits",
    "crawler_hard_stop",
}
SALT = "test-salt-not-a-secret"
NOW = datetime(2026, 11, 24, tzinfo=UTC)


# ---- no database needed ----


def test_metadata_has_expected_tables_and_no_plain_account_column():
    assert set(Base.metadata.tables) == TABLES
    for table in Base.metadata.tables.values():
        assert "account_name" not in table.columns
        assert "account" not in table.columns


def test_hash_account_name_is_hmac_sha256_hex():
    h = hash_account_name("SomeAccount#1234", salt=SALT)
    assert len(h) == 64 and int(h, 16) >= 0
    assert h == hash_account_name("SomeAccount#1234", salt=SALT)
    assert h != hash_account_name("SomeAccount#1234", salt="other")
    assert h != hash_account_name("OtherAccount#1234", salt=SALT)
    assert "SomeAccount" not in h


def test_require_salt_raises_when_missing():
    s = Settings(_env_file=None, db_host="h", db_name="n", db_user="u", db_pass="p")
    with pytest.raises(RuntimeError):
        require_account_hash_salt(s)


# ---- need PostgreSQL (elo_test) ----


@pytest.mark.db
def test_upgrade_downgrade_cycle(test_engine: Engine):
    assert TABLES <= set(inspect(test_engine).get_table_names())
    cfg = _alembic_config()
    assert get_settings().db_name == "elo_test"  # never downgrade any other database
    command.downgrade(cfg, "base")
    assert not (TABLES & set(inspect(test_engine).get_table_names()))
    command.upgrade(cfg, "head")
    assert TABLES <= set(inspect(test_engine).get_table_names())


@pytest.mark.db
def test_round_trip(test_engine: Engine):
    with Session(test_engine) as s:
        try:
            s.add(League(id="Standard", realm="pc", is_current=True))
            s.flush()
            account_hash = hash_account_name("PlainAccount#1", salt=SALT)
            s.add(
                Character(
                    id="c1",
                    league_id="Standard",
                    account_hash=account_hash,
                    character_name="Hero",
                    class_="Witch",
                    level=90,
                    experience=123456789012,
                    ladder_rank=5,
                )
            )
            s.flush()
            s.add(
                RawGear(
                    character_id="c1", kind="items", fetched_at=NOW, body=b"\x1f\x8b", sha256="ab"
                )
            )
            s.add(
                DataVersion(
                    source="repoe", version="3.30", status="staged", files=[{"sha256": "x"}]
                )
            )
            s.add(CrawlerRequest(policy="ladder", sent_at=NOW))
            s.add(
                CrawlerLiveLimit(
                    policy="ladder", rule="ip", max_hits=5, period_s=5, penalty_s=60, updated_at=NOW
                )
            )
            s.add(CrawlerBudget(day=date(2026, 11, 24)))
            s.add(CrawlerBreaker(id=1))
            s.add(CrawlerOutsideHit(policy="ladder", period_s=5, hits=2, at=NOW))
            s.add(CrawlerHardStop(id=1, reason="test", since=NOW))
            s.flush()

            c = s.scalars(select(Character)).one()
            assert c.status == "ok" and c.is_public is True
            assert c.account_hash == account_hash
            assert s.scalars(select(CrawlerBudget)).one().characters_used == 0
            assert s.scalars(select(CrawlerRequest)).one().id >= 1
            assert s.scalars(select(DataVersion)).one().files == [{"sha256": "x"}]
            # the plain account name appears nowhere in the stored row
            row = s.execute(text("SELECT c::text FROM characters c")).scalar_one()
            assert "PlainAccount" not in row
        finally:
            s.rollback()


@pytest.mark.db
@pytest.mark.parametrize(
    "make",
    [
        lambda: CrawlerBreaker(id=2),
        lambda: CrawlerHardStop(id=2, reason="x", since=NOW),
        lambda: CrawlerOutsideHit(policy="p", period_s=5, hits=0, at=NOW),
        lambda: CrawlerBudget(day=date(2026, 1, 1), characters_used=-1),
        lambda: DataVersion(source="bogus", version="1", status="staged", files=[]),
        lambda: DataVersion(source="repoe", version="1", status="bogus", files=[]),
    ],
)
def test_constraints_reject_bad_rows(test_engine: Engine, make):
    with Session(test_engine) as s:
        s.add(make())
        with pytest.raises(IntegrityError):
            s.flush()
        s.rollback()

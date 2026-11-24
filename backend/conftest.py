"""Fixtures shared by all backend tests.

Autouse: no test can send an alert or a webhook request. ``test_engine`` serves tests that
need PostgreSQL (marked ``db``).

Only the throwaway database ``elo_test`` is ever migrated or written to. The main database
named in the settings is never touched: the maintenance database ``postgres`` is used only to
CREATE / DROP ``elo_test``.
"""

import os
from collections.abc import Iterator
from pathlib import Path

import httpx
import psycopg
import pytest
from alembic import command
from alembic.config import Config
from psycopg import sql
from sqlalchemy import Engine, create_engine

from backend.common import alerts, db
from backend.common.config import REPO_ROOT, Settings, get_settings

TEST_DB = "elo_test"


def _alembic_config() -> Config:
    return Config(str(Path(REPO_ROOT) / "alembic.ini"))


@pytest.fixture(autouse=True)
def _no_alerts_no_webhooks(monkeypatch):
    """Alerts are recorded, never sent; any ``httpx.post`` (the webhook call) fails loudly."""
    sent: list[str] = []

    def fake_send_alert(message: str, *, level: str = "error") -> None:
        sent.append(message)

    def blocked_post(*args, **kwargs):
        raise RuntimeError("httpx.post is blocked in tests")

    monkeypatch.setattr(alerts, "send_alert", fake_send_alert)
    monkeypatch.setattr(httpx, "post", blocked_post)
    return sent


@pytest.fixture(scope="session")
def test_engine() -> Iterator[Engine]:
    try:
        settings = Settings()
    except Exception:
        pytest.skip("database settings are not available")
    if settings.db_name == TEST_DB:
        pytest.skip("the main database must not be named elo_test")

    conn_args = {
        "host": settings.db_host,
        "port": settings.db_port,
        "user": settings.db_user,
        "password": settings.db_pass.get_secret_value(),
        "connect_timeout": 5,
    }
    try:
        admin = psycopg.connect(dbname="postgres", autocommit=True, **conn_args)
    except psycopg.OperationalError:
        pytest.skip("PostgreSQL server is not reachable")

    old_name = os.environ.get("ELO_DB_NAME")
    old_testing = os.environ.get("ELO_TESTING")
    engine: Engine | None = None
    try:
        with admin.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (TEST_DB,))
            if cur.fetchone() is None:
                cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(TEST_DB)))

        # Environment variables override .env, so everything below targets elo_test only.
        os.environ["ELO_DB_NAME"] = TEST_DB
        os.environ["ELO_TESTING"] = "1"  # env.py refuses any other database in this mode
        get_settings.cache_clear()
        db.get_engine.cache_clear()
        db.get_sessionmaker.cache_clear()
        assert get_settings().db_name == TEST_DB  # safety guard before any migration

        command.upgrade(_alembic_config(), "head")
        engine = create_engine(get_settings().database_url)
        assert engine.url.database == TEST_DB
        yield engine
    finally:
        if engine is not None:
            engine.dispose()
        db.get_engine.cache_clear()
        db.get_sessionmaker.cache_clear()
        if old_name is None:
            os.environ.pop("ELO_DB_NAME", None)
        else:
            os.environ["ELO_DB_NAME"] = old_name
        if old_testing is None:
            os.environ.pop("ELO_TESTING", None)
        else:
            os.environ["ELO_TESTING"] = old_testing
        get_settings.cache_clear()
        with admin.cursor() as cur:
            cur.execute(
                sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(TEST_DB))
            )
        admin.close()

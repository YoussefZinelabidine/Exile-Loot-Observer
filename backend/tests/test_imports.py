import importlib
import pkgutil
import py_compile
from pathlib import Path

import backend
from backend.common.config import Settings


def test_all_modules_import():
    # backend.migrations.env runs Alembic at import time, so it is skipped.
    skip = ("backend.crawler", "backend.tests", "backend.migrations.env")
    names = [
        m.name
        for m in pkgutil.walk_packages(backend.__path__, "backend.")
        if not m.name.startswith(skip)
    ]
    assert "backend.common.config" in names
    for name in names:
        importlib.import_module(name)


def test_settings_explicit_values_hide_password():
    s = Settings(
        _env_file=None,
        db_host="h",
        db_port=5433,
        db_name="n",
        db_user="u",
        db_pass="supersecret",
    )
    url = s.database_url
    assert url.drivername == "postgresql+psycopg"
    assert url.port == 5433
    assert "supersecret" not in str(url)
    assert "supersecret" not in repr(s)


def test_migrations_env_compiles():
    env = Path(backend.__path__[0]) / "migrations" / "env.py"
    py_compile.compile(str(env), cfile=None, doraise=True)

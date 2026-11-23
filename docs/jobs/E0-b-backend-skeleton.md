# E0-b · Backend skeleton

- **Agent:** backend agent (Sonnet)
- **Approved by owner:** 2026-11-23 ("Yes, implement E0")
- **Design sections:** Implementation → Backend → Requirements, Build order 1 (skeleton only, no tables)

## Goal

A Python project that installs into the root `.venv` and gives every later backend and crawler job its shared foundations: config, logging, alert helper, database engine, Alembic wiring, and empty subpackages with clear docstrings. Surface code only.

## Files you may create or edit

- `pyproject.toml` (repo root)
- `alembic.ini` (repo root)
- `backend/__init__.py`
- `backend/common/**`
- `backend/migrations/**` (Alembic environment; **no revision files**)
- `backend/importers/`, `backend/normaliser/`, `backend/classifier/`, `backend/simulator/`, `backend/aggregation/`, `backend/snapshot/`, `backend/economy/` (each: `__init__.py` with a module docstring only)
- `backend/tests/**`

Do **not** touch `backend/crawler/` (another agent is writing it in parallel), `app/`, `shared/`, `docs/`, `specs/`, `.gitignore`, `.env`, `.env.example`.

## What to build

1. **`pyproject.toml`**: setuptools build, project name `elo-backend`, `requires-python = ">=3.12"`, packages found under `backend*`.
   - Dependencies: `httpx`, `psycopg[binary]` (v3), `SQLAlchemy>=2`, `alembic`, `pydantic>=2`, `pydantic-settings`, `numpy`.
   - Optional `dev` extra: `pytest`, `ruff`.
   - `[tool.ruff]` (line length 100, target py312, sensible rule set: E, F, I, B, UP) and `[tool.pytest.ini_options]` (`testpaths = ["backend"]`).
2. **`backend/common/config.py`**: `Settings` (pydantic-settings), `env_prefix="ELO_"`, `env_file` = the repo-root `.env` (resolved from the package location, not the CWD), extra keys ignored. Fields (names match `.env.example`):
   - `db_host: str`, `db_port: int = 5432`, `db_name: str`, `db_user: str`, `db_pass: SecretStr`
   - `account_hash_salt: SecretStr | None = None`
   - `discord_webhook_url: SecretStr | None = None`
   - `contact_email: str | None = None`, `project_url: str | None = None`
   - `log_level: str = "INFO"`
   - property `database_url` → SQLAlchemy URL object for `postgresql+psycopg` (use `sqlalchemy.URL.create`, so the password is never put in a plain string or logged).
   - `get_settings()` cached accessor.
   - `require_account_hash_salt()` helper that raises a clear error when the salt is missing (used later by anything that hashes account names).
3. **`backend/common/logging.py`**: `setup_logging(level)` with one consistent format (timestamp, level, logger name, message). Never logs secrets.
4. **`backend/common/alerts.py`**: `send_alert(message: str, *, level: str = "error") -> None`. If the webhook is set, POST to it with httpx (short timeout, swallow and log failures: an alert must never crash a job). If not set, only log the message. **This exact signature is used by the crawler agent.**
5. **`backend/common/db.py`**: `Base` (SQLAlchemy 2 `DeclarativeBase`), `get_engine()` (lazy, from settings), `session_scope()` context manager. No models yet. **Nothing connects at import time.**
6. **Alembic**: `alembic.ini` at the repo root with `script_location = backend/migrations`; `backend/migrations/env.py` takes the URL from `Settings.database_url` and `target_metadata = Base.metadata`; standard `script.py.mako`; empty `versions/` with `.gitkeep`.
7. **Empty subpackages** listed above, each with a docstring naming the build-order step it will hold (importers = 3, normaliser = 6, classifier = 7, simulator = 8, aggregation = 9, snapshot = 10, economy = 12).
8. **`backend/tests/test_imports.py`**: imports every module of the `backend` package except `backend.crawler`. One test that `Settings` can be built from explicit values (no `.env` read) and that `database_url` hides the password in its string form.

## Hard rules

- **Do not open or read `.env`.** Use `.env.example` for variable names. Never print settings values.
- **Do not connect to the database.** Do not run `alembic upgrade`, `alembic revision --autogenerate`, or anything that opens a DB connection.
- No git write commands. No Docker commands.
- No calls to GGG or any game website.
- If anything here is unclear or leaves more than one reasonable choice, stop and report back instead of choosing.

## Checks (definition of done)

From the repo root, in the root `.venv` (`.venv\Scripts\python.exe`):
1. `pip install -e ".[dev]"` succeeds.
2. `python -m pytest backend/tests -q` passes.
3. `python -m ruff check backend --exclude backend/crawler` reports nothing.

Report back: files created, the exact commands run and their results, and anything you were unsure about.

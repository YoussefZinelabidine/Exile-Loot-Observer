# backend/

Python jobs that run on the home server: static data importers, item normaliser, build classifier, natural roll simulator, aggregation, snapshot builder and publisher, poe.ninja importer, validation evaluation. No public API.

- **Owner:** backend agent (everything here except `crawler/`).
- **Package:** `backend` (installed from the root `pyproject.toml` into the root `.venv`).
- **Config:** read from the root `.env` through `backend.common.config`. Never hard-code credentials or secrets.
- **Database:** PostgreSQL through SQLAlchemy + psycopg 3; schema changes only through Alembic, and only run after the owner approves.
- **Never:** call GGG from here (all GGG traffic goes through `backend.crawler`), copy poe.re code, drop or reset the database.

# P1-B1 · Database tables (first migration)

- **Agent:** backend agent (Sonnet) · **Status:** approved by owner 2026-11-24 ("proceed with the next phase"); questions answered (see "Owner decisions")
- **Design sections:** Implementation → Backend 1; Crawler (invalid requests, league reset, snapshots); Decided → Privacy

## Goal

SQLAlchemy models and the first Alembic revision for: `leagues`, `characters`, `raw_gear`, `data_versions` (+ crawler state tables if P1-C1 question 1 = (a)).

## Files

`backend/common/models.py` (or `backend/common/models/`), `backend/migrations/versions/<first>.py`, `backend/tests/**`.

## Proposed tables

| Table | Columns (main) |
| --- | --- |
| `leagues` | id (GGG league id, PK), realm, is_current, first_seen, crawl_allowed_from (first seen + pause), ended_at |
| `characters` | id (GGG character id, PK), league_id FK, account_hash (HMAC-SHA256 with the salt), character_name, class, level, experience, ladder_rank, is_public, status (`ok` / `skip_private` / `skip_missing`), first_seen, last_seen_on_ladder, last_fetched |
| `raw_gear` | character_id FK, kind (`items` / `passives`), fetched_at, body (gzip JSON, `bytea`), sha256; keep latest per (character, kind) |
| `data_versions` | source (`repoe` / `poere` / `skilltree` / `poeninja`), version, fetched_at, status (`staged` / `active` / `rejected`), files (JSON list with sha256) |
| `crawler_rate_state`, `crawler_budget`, `crawler_breaker` | only if P1-C1 question 1 = (a); columns defined in that job |

## Acceptance tests

1. `alembic upgrade head` then `alembic downgrade base` on a **throwaway** database works (see question 3).
2. Model round-trip tests; account names are only ever stored hashed (`require_account_hash_salt()`), never plain.
3. No migration ever drops data outside `downgrade`.

## Open questions for the owner

1. **Character names:** store them plain (needed to fetch gear; they are public on the ladder) *(recommended)*, or hashed too (then the crawler can only work from the current ladder page).
2. **Raw gear history:** (a) keep only the latest per character and kind (design: raw data only for the current league) *(recommended)*; (b) keep every fetch.
3. **Where the migration is tested:** (a) the agent may create and drop a separate database `elo_test` in the existing container through SQL (not Docker commands), never touching the main database *(recommended)*; (b) only you run migrations; the agent only writes them.
4. **Running against the dev database:** after review, you run `alembic upgrade head` yourself, or you tell me to.

## Done when

Checks pass, the reviewer passes it, and the main dev database has **not** been touched by the agent.

## Owner decisions (2026-11-24)

Q1 character names plain, account names only as HMAC-SHA256 with the salt · Q2 latest raw gear per (character, kind) only · Q3 (a) the agent may create and drop a separate `elo_test` database through SQL (never Docker commands, never the main database) and run migrations there · Q4 the owner runs `alembic upgrade head` on the dev database after review.

## Crawler state tables (for P1-C1b; include them in this migration)

| Table | Columns |
| --- | --- |
| `crawler_requests` | id bigserial PK, policy text, sent_at timestamptz, status_code int null; index (policy, sent_at). Rows older than 3 h may be pruned. |
| `crawler_live_limits` | policy text, rule text, max_hits int, period_s int, penalty_s int, updated_at timestamptz; PK (policy, rule, period_s) |
| `crawler_budget` | day date PK (UTC), characters_used int not null default 0, check characters_used ≥ 0 |
| `crawler_breaker` | id smallint PK check id = 1, open_until timestamptz null, reason text null, tripped_at timestamptz null |

## Test database

Tests that need Postgres use a fixture that connects with the settings from `.env` (the agent never reads the file), creates `elo_test` if missing, runs migrations there, and drops it at the end. They are marked `@pytest.mark.db` and skipped when the server is unreachable.

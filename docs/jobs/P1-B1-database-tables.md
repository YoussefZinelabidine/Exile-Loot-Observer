# P1-B1 · Database tables (first migration)

- **Agent:** backend agent (Sonnet) · **Status:** draft, waiting for owner approval and answers below
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

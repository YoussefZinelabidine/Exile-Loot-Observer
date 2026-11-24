# Phase 1 status (2026-11-24)

All seven Phase 1 jobs are built and have passed the Opus review. Nothing in Phase 1 is committed yet.

| Job | Agent | Review |
| --- | --- | --- |
| P1-C1 Safe HTTP client, rate limiter, budget, breaker | Crawler | PASS (3 rounds; safety holes found and closed) |
| P1-C1b Postgres crawler state store | Crawler | PASS (2 rounds) — Postgres tests not yet run |
| P1-B1 Database tables (first migration) | Backend | PASS — Postgres tests not yet run |
| P1-B2 Static data importers + pydantic snapshot models | Backend | PASS (3 rounds) |
| P1-B3 Item normaliser | Backend | PASS (3 rounds) |
| P1-B4 Python scoring engine | Backend | PASS — 6,000 random verdicts identical to the app engine |
| P1-F1 Item parser + generated TS types | Frontend | PASS (3 rounds) |
| P1-F2 Scoring engine + market demand | Frontend | PASS (2 rounds) |

Checks on 2026-11-24: backend `pytest` 352 passed, 24 skipped (Postgres); `ruff` clean; `gen_models --check` OK. App `pnpm check` 0 errors, `pnpm test` 99 passed (2 todo), `pnpm build` OK.

## Still open

1. **Postgres tests (24) have never run.** `.env` line `ELO_DB_PORT` ends with a comma. Fix it, then run `.venv\Scripts\python.exe -m pytest -q -m db -rs`. They only touch a throwaway `elo_test` database.
2. **Dev database migration:** after the Postgres tests pass, the owner runs `alembic upgrade head` on the dev database (decision 12).
3. **First real data download** (P1-B2, owner-approved once): needs `ELO_DATA_DIR`, `ELO_PROJECT_URL` (and ideally `ELO_CONTACT_EMAIL`) in `.env`. Confirms the skill-tree branch/file and the RePoE shapes of `crafting_bench_options`, `gems`, `mods_by_base`.
4. **In-game check:** plain Ctrl+C in 3.30 gives the advanced format (parser assumes it).
5. **Phase 2 checks:** trade-API `extended.hashes` shape against a recorded response; real policy name for `/api/leagues`.
6. `cargo check` / first `pnpm tauri dev` (needs the Windows SDK) — Rust side and CSP still unverified.
7. Known deferred items (TODOs in code): stale-snapshot cap, item flags (influenced/synthesised/mirrored/double-corrupted), corruption implicits as extra mods, cluster jewels, merged identical-stat lines, bench-craftable list (Phase 3 patch builder).
8. Design doc corrections to apply (owner's local `specs/`): RePoE URL, trade IDs from RePoE, Royale exclusion.

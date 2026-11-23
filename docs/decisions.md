# Decisions log (implementation)

Decisions made by the owner during implementation. The design decisions from planning are in the v1 design doc (`specs/`, local only); if the two disagree, the design doc wins and the difference is flagged to the owner.

| Date | Decision | Notes |
| --- | --- | --- |
| 2026-11-23 | `specs/` stays git-ignored; tracked docs and job specs live in `docs/` (job specs in `docs/jobs/`) | |
| 2026-11-23 | Python: one root `.venv` (Python 3.12), `pyproject.toml` at the repo root, installed with `pip install -e ".[dev]"`; backend code is the `backend` package (`backend.crawler`, `backend.common`, ...) | Keeps the documented path `backend/crawler/` |
| 2026-11-23 | Frontend: Tauri v2 + Svelte 5 + TypeScript + Vite + Vitest, pnpm | |
| 2026-11-23 | Skeleton code is written by the Sonnet agents; the orchestrator writes specs, docs and `shared/` | Rule 2 |
| 2026-11-23 | Agents work directly in the owner's checkout on `develop`, each only in its own folder; the owner commits after review | |
| 2026-11-23 | Dev database: Docker container `exile_loot_observer`, image `postgres:18`, port 5432 | Credentials only in `.env` |

## Open questions (not decided yet)

1. Golden item sourcing (game texts, character-API JSON, trade-API JSON) and whether expected verdicts use a synthetic fixture snapshot.
2. `demand_low`: computed server-side and shipped, or computed in both engines; and its method.
3. Unvalidated thresholds stored as `null` (app caps verdicts at PRICE CHECK).
4. Plain Ctrl+C vs Ctrl+Alt+C for the advanced item format in 3.30 (needs an in-game check).
5. Ladder rate-limit rules: is `15:10` (HANDOFF) a typo? The design doc lists 5:5 and 10:10 only.
6. Snapshot compression: gzip only (recommended) vs gzip or zstd.
7. User-Agent contact email and project URL; whether the repo is public.
8. Crawler (Phase 1): how the one shared limiter is shared across processes; sync vs async HTTP client; constructor parameters for `SafeHttpClient`, limiter, breaker and budget; whether one character (items + tree) costs 1 budget unit.
9. App: add `tauri-plugin-opener` for opening links and trade searches in the system browser (needed by Frontend step 7), now or later.
10. App: installer type: NSIS only (recommended by review) vs `bundle.targets: "all"` (current).
11. App: identifier `com.exilelootobserver.elo` is provisional; changing it later moves the app's data folder.

## Pending checks

- `cargo check` / first `pnpm tauri dev` of `app/` once the Windows SDK is installed (Rust side and the CSP are unverified until then).

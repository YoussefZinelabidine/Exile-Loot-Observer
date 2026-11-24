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
| 2026-11-23 | Golden items: Phase 0 defines the format and a hand-written seed set (~8–10 items, all three forms); real game copies replace/extend it later; full 30–50 after the rate limiter exists (Phase 2) | |
| 2026-11-23 | Golden verdicts are scored against a synthetic fixture snapshot (made-up demand and thresholds); they test that Python and TypeScript scoring agree, not that verdicts are true | |
| 2026-11-23 | `demand_low` is computed on the server and shipped in the daily file; the app only reads it. Method chosen in the Phase 2 aggregation job | |
| 2026-11-23 | Unvalidated thresholds are `null` plus `validated: false`; the app never shows KEEP until they are set | |
| 2026-11-23 | Snapshot compression: gzip only | |
| 2026-11-23 | User-Agent format fixed in `shared/`; values from `ELO_CONTACT_EMAIL` / `ELO_PROJECT_URL`; the crawler refuses to call GGG while they are empty | |
| 2026-11-23 | Ladder rate-limit reference values: 5:5 and 10:10 (HANDOFF's 15:10 treated as a typo); re-check at the first smoke test | |
| 2026-11-23 | RePoE and poe.re data downloaded once (orchestrator, outside the repo) for real stat IDs in fixtures | RePoE 3.30.0.4.3; poe.re 3.30.0.4.3 (17bc109) |
| 2026-11-23 | Trade stat IDs for "Open trade search" come from RePoE `stat_translations.json` `trade_stats`, not poe.re's trade-ID map | poe.re's map covers only 127 stats. **Design doc to update.** |
| 2026-11-23 | A KEEP-level fit for a niche build (below `min_build_accounts`) gives PRICE CHECK and names that build | |
| 2026-11-23 | Snapshot readers (the app) ignore unknown fields; the publisher validates strictly. New optional fields need no schema version bump | |
| 2026-11-23 | Tier ladders exclude PoE Royale mods (`*Royale*` mod ids) | Found by the Phase 0 review |
| 2026-11-23 | RePoE files are served at `https://repoe-fork.github.io/<file>` (not `/data/<file>`) | **Design doc and HANDOFF to update.** |

## Open questions (not decided yet)

4. Plain Ctrl+C vs Ctrl+Alt+C for the advanced item format in 3.30 (needs an in-game check). Seed fixtures use the advanced format.
8. Crawler (Phase 1): how the one shared limiter is shared across processes; sync vs async HTTP client; constructor parameters for `SafeHttpClient`, limiter, breaker and budget; whether one character (items + tree) costs 1 budget unit.
9. App: add `tauri-plugin-opener` for opening links and trade searches in the system browser (needed by Frontend step 7), now or later.
10. App: installer type: NSIS only (recommended by review) vs `bundle.targets: "all"` (current).
11. App: identifier `com.exilelootobserver.elo` is provisional; changing it later moves the app's data folder.

## Pending checks

- `cargo check` / first `pnpm tauri dev` of `app/` once the Windows SDK is installed (Rust side and the CSP are unverified until then).

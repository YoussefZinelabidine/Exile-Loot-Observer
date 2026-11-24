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

### Phase 1 decisions (owner accepted all recommendations, 2026-11-24)

| # | Decision |
| --- | --- |
| 1 | Types are generated from the JSON Schemas (TypeScript: `json-schema-to-typescript`; Python: `datamodel-code-generator`), with a check that fails when they are out of date |
| 2 | New job P1-B4: Python scoring engine, so both engines are tested against the golden items from the start |
| 3 | Scoring rules R1–R9 as proposed in `shared/fixtures/README.md` |
| 4 | Fixture generator committed as `shared/tools/gen_fixtures.py` |
| 5 | Crawler limiter, budget and breaker state live in Postgres (advisory lock); in-memory store for tests |
| 6 | Sync `httpx` client |
| 7 | Rate cap = 80% of `min(live header limit, measured limit)` |
| 8 | Daily budget: 1 unit per character (items + tree), charged when its items request is sent; day = UTC calendar day |
| 9 | Breaker and budget state persisted |
| 10 | Character names stored plain; account names only as HMAC with the salt |
| 11 | Raw gear: latest per character and kind only |
| 12 | Agents may create and drop a separate `elo_test` database via SQL for tests; the main dev database is never touched by agents; the owner runs migrations on it |
| 13 | Downloaded static data lives in `ELO_DATA_DIR` (outside the repo), one folder per source and version |
| 14 | Skill tree from GGG's official export on GitHub |
| 15 | Ambiguous tier → best tier possible at the item level, row flagged `tier_ambiguous` |
| 16 | Hybrid mods → one row per stat, same family and tier |
| 17 | App parser reuses only Awakened PoE Trade's text-section helpers (MIT notice kept) |
| 18 | Market demand sums archetype nodes only |
| 19 | Craftable discount multiplies `demand_low` in the fit numerator only |
| 20 | Parser targets the advanced Ctrl+C format; in-game check still pending |
| 21 | Crawler derives the GGG policy (and whether a request costs budget) from the endpoint, via a hard-coded table; unknown endpoints are refused; a response whose policy header differs from the table trips the breaker and alerts |
| 22 | An active penalty in GGG's rate-limit headers is a **hard stop**: every crawler job stops, one Discord alert is sent, and nothing resumes automatically; the owner restarts it by hand (owner: "stop the server and notify me") |
| 24 | Unrecognised mod lines do not fail the item: it is scored on its known mods, the lines are listed in `unrecognised`, and the verdict carries reason `unrecognised_mods` (overlay flag). Same behaviour in the backend normaliser |
| 25 | Parsed mod values are in raw stat units (display conversions undone), matching RePoE tier ranges and the API data |
| 26 | Unidentified items: clear message ("identify this item first"), no verdict |
| 27 | Uniques skip the base lookup: identified by name, NOT SCORED + poe.ninja price whenever the name is in the price list |
| 28 | Nothing was copied from Awakened PoE Trade in P1-F1 (parser written from scratch), so no MIT notice is needed yet |
| 22a | (orchestrator, following 22) A live rate-limit rule of `0` allowed requests is treated like an active penalty: hard stop + alert. Penalty detection scans every `-State` header on its own, so a malformed header elsewhere cannot hide it. Alerts are sent even if the database write fails |
| 22b | Hard-stop flag lives in its own one-row table `crawler_hard_stop`, separate from the timed breaker; outside hits in `crawler_outside_hits` (both added to migration 0001, not yet applied anywhere) |
| 29 | KEEP's "≥ 2 core mods" counts distinct affixes (a hybrid affix = 1), not stats |
| 30 | Best buyer: among buyer-size builds meeting the KEEP condition, the highest fit; if none, the highest fit overall. Same for niche builds (any niche build meeting the KEEP condition) |
| 31 | Unvalidated / null thresholds: fit 0 with no boost stays NO BUYER; everything else is capped at PRICE CHECK |
| 32 | Item class or base not in the patch → NOT SCORED with reason `unsupported_item` |
| 33 | Cluster jewels: left as a TODO; detection and price key decided later after checking RePoE |
| 34 | What to farm: no filter or an archetype filter sums archetype nodes; a main-skill filter uses only that node |
| 35 | Bench-craftable stat list is built in the patch-builder job (Phase 3), not in P1-B2 |
| 36 | Activating a data version demotes the previous active row to `staged` (one active row; rollback through activate) |
| 37 | (orchestrator, from the P1-F2 review) Fit comparisons use an epsilon of 1e-9 (`fit ≥ threshold − 1e-9`); fit sums core stats in descending `demand_low` order, ties by stat id; duplicate core `stat_id`s in a node count once (highest `demand_low`) |
| 38 | Backend normaliser (no affix labels in character-API data): lines that could belong to a hybrid mod whose other half is not clearly present go to `unrecognised`; never a guessed tier. Strict reading (orchestrator): never store half a hybrid; a trade line the API marks as merged from several mods also goes to `unrecognised` |
| 39 | Backend normaliser: when any explicit or crafted line is unrecognised or has no known affix, `open_prefixes` / `open_suffixes` are recorded as unknown (null); the crafting-potential boost then never applies |
| 23 | Header hit counts are used conservatively: per window the limiter uses max(own recorded requests, header hits); they can only slow the crawler |

## Open questions (not decided yet)

4. Plain Ctrl+C vs Ctrl+Alt+C for the advanced item format in 3.30 (needs an in-game check). Seed fixtures use the advanced format.
8. Crawler (Phase 1): how the one shared limiter is shared across processes; sync vs async HTTP client; constructor parameters for `SafeHttpClient`, limiter, breaker and budget; whether one character (items + tree) costs 1 budget unit.
9. App: add `tauri-plugin-opener` for opening links and trade searches in the system browser (needed by Frontend step 7), now or later.
10. App: installer type: NSIS only (recommended by review) vs `bundle.targets: "all"` (current).
11. App: identifier `com.exilelootobserver.elo` is provisional; changing it later moves the app's data folder.

## Pending checks

- `cargo check` / first `pnpm tauri dev` of `app/` once the Windows SDK is installed (Rust side and the CSP are unverified until then).

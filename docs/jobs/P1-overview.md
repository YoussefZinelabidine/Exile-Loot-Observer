# Phase 1: overview

Phase 1 runs the three agents in parallel (design: "Order and parallel work"). Each job needs the owner's explicit approval ("implement P1-xx") before it starts, and the open questions it lists must be answered first.

| Job | Agent | Design step | Depends on |
| --- | --- | --- | --- |
| [P1-C1 HTTP client and rate limiter](P1-C1-http-client-rate-limiter.md) | Crawler | Backend 2 | E0-c; P1-B1 tables if limiter state lives in Postgres |
| [P1-B1 Database tables](P1-B1-database-tables.md) | Backend | Backend 1 (tables) | E0-b |
| [P1-B2 Static data importers](P1-B2-static-data-importers.md) | Backend | Backend 3 | E0-b, P1-B1 (`data_versions`) |
| [P1-B3 Item normaliser](P1-B3-item-normaliser.md) | Backend | Backend 6 | P1-B2 (parsed RePoE models), golden items |
| [P1-F1 Item parser](P1-F1-item-parser.md) | Frontend | Frontend 3 | E0-d, patch schema, golden items |
| [P1-F2 Scoring engine](P1-F2-scoring-engine.md) | Frontend | Frontend 4 | P1-F1, daily schema, golden items |

Frontend step 1 (skeleton) was done in E0-d.

## Questions that affect several jobs

1. **Types from the JSON Schemas.** (a) Generate them: TypeScript with `json-schema-to-typescript`, Python pydantic models with `datamodel-code-generator`, plus a check that fails when they are out of date (recommended: the schemas stay the single source of truth). (b) Write them by hand in each language.
2. **Python scoring engine.** The golden rule says both engines must reproduce every verdict, but no Phase 1 job builds the Python one. (a) Add a backend job "P1-B4 Python scoring engine" now, so parity is tested from the start (recommended). (b) Build it in Phase 5 with validation.
3. **Scoring rules.** Confirm or change the proposed rules in `shared/fixtures/README.md` ("Scoring rules the expected verdicts follow"). P1-F2 (and P1-B4) implement exactly what is confirmed.
4. **Fixture generator.** (Kept so far in the orchestrator's temporary folder, which can be cleared.) The golden items and fixture snapshot were built by an orchestrator script (kept outside the repo so far). (a) Commit it as `shared/tools/gen_fixtures.py` so fixtures can be regenerated when rules change (recommended). (b) Keep fixtures hand-maintained.

## Rules for every Phase 1 job

- Work only in the files the job lists. Changes to `shared/` go back to the orchestrator.
- No live calls to GGG. No calls to RePoE, poe.re or poe.ninja in tests (recorded files only).
- Never read `.env`. Never connect to the database unless the job says so and the owner approved it for that job.
- No git write commands. Stop and report anything the spec does not settle.
- Done = the job's checks pass and the Opus reviewer passes it.

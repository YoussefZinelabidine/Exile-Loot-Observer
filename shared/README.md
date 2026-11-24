# shared/

Contracts used by both the backend (Python) and the app (TypeScript). Owned by the orchestrator: agents never edit this folder; they report needed changes back.

| Folder | Contents | Status |
| --- | --- | --- |
| `schema/` | JSON Schemas (draft 2020-12): patch file, daily file, manifest, golden expected results. Format notes in `schema/README.md` | Schema version 1 (Phase 0) |
| `fixtures/snapshot/` | Synthetic fixture snapshot (valid example of all three files) | Phase 0 |
| `fixtures/golden/` | Golden test items in three forms with expected results; see `fixtures/README.md` | 9 hand-written seed items (Phase 0) |
| `user-agents.md` | User-Agent strings for every outside service | Phase 0 |
| `stat-handlers.json` | How to turn displayed stat numbers back into raw stat values (inverse of RePoE index handlers); shared by the app parser and the backend normaliser | Phase 1 |
| `tools/gen_fixtures.py` | Orchestrator tool that regenerates `fixtures/` | Phase 1 |

Rules:
- Every snapshot file carries a schema version; a breaking change bumps it.
- Python and TypeScript scoring must both reproduce every expected result in `fixtures/`.
- No real account names in fixtures.

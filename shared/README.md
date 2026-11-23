# shared/

Contracts used by both the backend (Python) and the app (TypeScript). Owned by the orchestrator: agents never edit this folder; they report needed changes back.

| Folder | Contents | Status |
| --- | --- | --- |
| `schema/` | JSON Schemas (draft 2020-12) for the snapshot files: patch file, daily file, manifest | To do (Phase 0, P0-2) |
| `fixtures/` | Golden test items (game text, character-API JSON, trade-API JSON, expected results) and fixture snapshots | To do (Phase 0, P0-3) |

Rules:
- Every snapshot file carries a schema version; a breaking change bumps it.
- Python and TypeScript scoring must both reproduce every expected result in `fixtures/`.
- No real account names in fixtures.

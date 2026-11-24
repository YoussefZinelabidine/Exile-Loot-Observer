# P1-B2 · Static data importers

- **Agent:** backend agent (Sonnet) · **Status:** draft, waiting for owner approval and answers below
- **Design sections:** Data sources; Stash search builder → Data flow; Implementation → Backend 3; To do priority 2

## Goal

Download, pin, verify and parse the static game data the backend and the patch file need: RePoE (`mods.json`, `stat_translations.json`, `base_items.json`, `mods_by_base.json`, `gems.json`, `crafting_bench_options.json` (bench-craftable stats; RePoE's crafted mods have no spawn weights), `version.txt`), poe.re (`current.json`, `SHA256SUMS`, `item/Generated.Item.ENGLISH.min.json`), and GGG's skill tree export. Record versions in `data_versions`. Keep the last good copy when a download fails.

## Corrections found in Phase 0 (design doc to be updated)

- RePoE files are served at `https://repoe-fork.github.io/<file>` (site root), **not** `/data/<file>` (404). Version 3.30.0.4.3 on 23 Nov 2026.
- poe.re's trade-ID map has only 127 entries. Official trade stat IDs come from RePoE `stat_translations.json` → `trade_stats` instead. The poe.re map is not imported.
- poe.re's item file is grouped by poe.re "basetype" (plural class names such as `Abyss Jewels`); fragments are matched to RePoE by stat ID.

## Files

`backend/importers/**`, `backend/tests/**`, small recorded excerpts under `backend/tests/fixtures/importers/`.

## Acceptance tests (offline)

1. Parsers for each file work on small recorded excerpts (RePoE and poe.re are not GGG, but tests still never download).
2. poe.re file checked against `SHA256SUMS`; mismatch → keep last good copy, alert.
3. A poe.re patch that differs from the RePoE version is reported (To do, priority 2), and every scored item class must be present in poe.re's file.
4. Tier ladders built from RePoE match `shared/fixtures/snapshot/patch.json` for the fixture bases (same rule: domain = base domain, prefix/suffix, not essence-only, not PoE Royale (`*Royale*`), first matching spawn tag > 0, best tier first by required level).
5. Stat text has RePoE `[Id|Text]` markup reduced to `Text`.
6. User-Agent from `shared/user-agents.md`.

## Open questions for the owner

1. **Where downloaded files live:** (a) a data folder outside the repo, path from `ELO_DATA_DIR` in `.env`, with one sub-folder per source and version *(recommended)*; (b) in the database as blobs.
2. **Skill tree export source:** GGG's official export on GitHub (`grindinggear/skilltree-export`) as the design says, or RePoE's passive data. *(recommended: GGG export; it is a GitHub download, not a GGG website request)*
3. **First real download:** after review, may the orchestrator run the importer once (a few MB, these hosts only)?

## Done when

Checks pass, the reviewer passes it; no network access in tests.

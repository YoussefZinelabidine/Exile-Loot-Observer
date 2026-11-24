# Snapshot format (schema version 1)

ELO's server publishes three files to GitHub Releases. The app reads only these; it never calls GGG, RePoE, poe.re or poe.ninja.

| File | Schema | When rebuilt | Compression |
| --- | --- | --- | --- |
| `manifest.json` | `manifest.schema.json` | every publish | none (small) |
| `patch-<game_patch>.json.gz` | `patch.schema.json` | only when RePoE / poe.re data changes | gzip |
| `daily-<crawl_date>.json.gz` | `daily.schema.json` | after each crawl | gzip |

Budgets: daily file < 500 KB compressed; everything on disk < 10 MB. The app keeps only the latest of each.

`golden-expected.schema.json` describes test fixtures (`shared/fixtures/golden/*/expected.json`), not a published file.

## Rules

- **Versioning** (owner decision 2026-11-23). Every file has `schema` (a constant name) and `schema_version`. The schemas here are strict (`additionalProperties: false`) and are used by the **publisher**, which validates every file before publishing. **Readers (the app) ignore fields they do not know.** So adding an optional field is not a version bump; removing, renaming or changing the meaning of a field is. The app refuses a file whose `schema_version` it does not know and keeps its cached snapshot.
- **Reproducible checksums.** Published files are compact JSON (UTF-8, no ASCII escaping) compressed with gzip level 9 and `mtime = 0`.
- **Pairing.** `daily.patch_ref` must equal `patch.game_patch`. The app never mixes a daily file with a different patch file.
- **Integrity.** The app verifies each download's SHA-256 against the manifest before replacing its cached copy.
- **Keys.** Item classes use RePoE `item_class` names (`Ring`, `Jewel`, `AbyssJewel`, `Body Armour`, …). Stats use RePoE stat IDs (`base_maximum_life`). Mod families use `<affix>:<RePoE mod type>` (`prefix:IncreasedLife`). Build nodes use `all`, `arch:<defence>-<damage>`, `skill:<gem-slug>`.
- **No personal data.** No account or character names, no hashes of them, ever.

## Patch file in short

- `item_classes`: affix limits, whether the bench can craft on it, which stats are bench-craftable (from RePoE `crafting_bench_options.json`; the only place "craftable" is recorded), which poe.re group the fragments came from, the trade-site category.
- `bases` → `tier_set`: bases with the same spawn tags share one set of tier ladders.
- `tier_sets[set][family].tiers`: best tier first (`tiers[0]` is T1). Only tiers that can spawn on those bases in leagues: same domain as the base, prefix or suffix, not essence-only, not PoE Royale (`*Royale*` mod ids), first matching spawn tag with weight > 0. `required_level` is the minimum item level.
- `translations`: RePoE English stat text, used by the parser, with `[Id|Text]` markup reduced to `Text`.
- `trade_ids`: official trade-site stat IDs per RePoE stat. **Source: RePoE `stat_translations.json` `trade_stats`** (owner decision 2026-11-23; poe.re's trade-ID map covers only 127 stats).
- `search_fragments`: poe.re regex fragments per item class, matched to RePoE by stat ID.

## Daily file in short

- `validated`: false until thresholds come from validation. While false, no KEEP is ever shown.
- `params.thresholds`: `null` = not validated → any decision needing it is capped at PRICE CHECK.
- `params.tier_gate`: a roll qualifies if its tier ≤ `max(always_top_tiers, ceil(top_fraction × ladder length))`, ladder length taken from the patch file for the item's base.
- `params.stale_after_days`: a snapshot older than this caps verdicts at PRICE CHECK with the "low data" marker.
- `build_nodes`: `all` → archetypes → main skills. `shown_on_own = false` means the node is not named or filterable (its archetype stands in). `low_data = true` caps verdicts naming it at PRICE CHECK.
- `demand[item_class][node].mods`: every mod with demand, sorted by demand, core mods flagged. `demand_low` (cautious lower bound) is computed on the server; the app only reads it.
- Market demand for What to farm is **not** in the file: the app computes `Σ_b demand × accounts_b`. Which nodes are summed (so players are not counted twice through nested nodes) is decided in job P1-F2.
- Python: a pydantic model needs an alias for the field `schema` (it shadows a `BaseModel` attribute).

## Fixtures

`shared/fixtures/snapshot/` holds a valid example of all three files. It is a **synthetic** snapshot (made-up demand, thresholds and build sizes on top of a subset of real RePoE 3.30.0.4.3 tier data) and is the snapshot the golden items are scored against. See `shared/fixtures/README.md`.

# Test fixtures

## `snapshot/`: synthetic fixture snapshot

| File | What |
| --- | --- |
| `patch.json` | Real RePoE 3.30.0.4.3 tier ladders, stat text and trade IDs, plus real poe.re 3.30.0.4.3 fragments, **cut down** to the 8 fixture bases and to the mod families the fixtures and the synthetic demand use. |
| `daily.json` | **Made-up** build nodes, demand, thresholds (`keep_fit` 0.5, `price_check_fit` 0.25, `min_build_accounts` 100, `craftable_discount` 0), `validated: true`. |
| `manifest.json` | Example manifest; checksums are of the gzip of the compact JSON. |

These numbers test that the Python and TypeScript engines agree. They say nothing about real demand.

## `golden/`: golden items

One folder per item: `NNN-slug/`.

| File | What | Read by |
| --- | --- | --- |
| `game.txt` | Item text as copied in game (advanced format, Ctrl+C since 3.29) | App parser (Vitest) |
| `character.json` | `{ "item": … }` shaped like one entry of the character API's `items` | Backend normaliser (pytest) |
| `trade.json` | `{ "result": … }` shaped like one result of `/api/trade/fetch` (with `extended` tiers and stat hashes) | Backend normaliser / validation (pytest) |
| `expected.json` | Expected `item`, `mods` and `verdict` (schema: `shared/schema/golden-expected.schema.json`) | Both |

**Acceptance rule:** for every golden item, the app parser (from `game.txt`) and the backend normaliser (from `character.json` and `trade.json`) produce the same `item` and `mods`; both scoring engines, given the snapshot in `expected.snapshot`, produce exactly `verdict` (`fit` within 1e-4).

**How to compare:**
- `mods`: as a multiset, order ignored. Each entry is matched on all its fields. (Files list implicits, then prefixes, then suffixes, as the game does.)
- `reasons` and `counted_stat_ids`: as sets, order ignored.
- Every other field: exact equality.
- Line endings: fixture files are LF; parsers must accept both LF and CRLF (the Windows clipboard gives CRLF).

### Seed set (Phase 0)

All **hand-written** from documented formats and real RePoE data (`source: "hand-written"`). Replace or extend them with real game copies and recorded API responses as they become available (Phase 2 for API responses).

| Item | Class | Expected | Exercises |
| --- | --- | --- | --- |
| 001-ring-keep-life-attack | Ring | KEEP, Life · Attack, fit 0.6087 | KEEP path; tier gate rejects a T5 resistance on an 8-tier ladder |
| 002-abyss-keep-life-minion | Abyss jewel | KEEP, Life · Minion, fit 0.8507 | k = 4; Raise Spectre would fit better (0.875) but is not shown on its own, so it is skipped |
| 003-jewel-partial-life-attack | Jewel | PRICE CHECK, fit 0.5 | fit reaches `keep_fit` with only 1 core mod → partial fit (≥ 2 mods needed for KEEP) |
| 004-boots-no-buyer | Boots | NO BUYER | no core mods; base below boost item level |
| 005-body-corrupted-partial | Body armour | PRICE CHECK, fit 0.3297 | corrupted with open slots; flat ES T8 of 11 fails the gate |
| 006-gloves-fractured-core | Gloves | PRICE CHECK (boost), fit 0.16 | fractured core mod lifts NO BUYER; no buyer named |
| 007-unique-ring-not-scored | Ring (unique) | NOT SCORED, 3 chaos | unique → price lookup; unique mods not normalised in v1 |
| 008-french-client-unsupported | – | UNSUPPORTED LANGUAGE | non-English text (game form only) |
| 009-amulet-low-data-cap | Amulet | PRICE CHECK, low data, fit 0.75 | would be KEEP; best buyer is low data |

Not covered yet (to add): base-value boost, crafting-potential boost, niche-build fit, `validated: false` cap, mirrored, influenced, synthesised, hybrid mods, cluster jewels, craftable discount > 0, magic items, items with enchants or corruption implicits.

### Scoring rules the expected verdicts follow (proposed)

The design leaves some details open. The seed verdicts follow these rules; the Phase 1 scoring job spec will ask the owner to confirm or change them, and any change regenerates `expected.json`.

1. **Tier gate:** a mod qualifies if `tier ≤ max(always_top_tiers, ceil(top_fraction × ladder_length))`. Implicits and crafted mods never qualify.
2. **Candidate builds:** every node except `all` with `shown_on_own = true` and demand for the item class.
3. **Fit:** `Σ demand_low of the node's core mods whose stat is on a qualifying mod ÷ Σ of the node's top-k core demand_low`, k = max prefixes + max suffixes of the class. Each core stat counts once.
4. **Best buyer** (decision 30): among candidates with `accounts ≥ min_build_accounts` that meet the KEEP condition (rule 5), the highest fit; if none meets it, the highest fit among those candidates. Ties: higher fit, then more accounts, then node id.
5. **KEEP:** best buyer fit ≥ `keep_fit` with ≥ 2 counted core mods, counted as **distinct affixes** (a hybrid affix counts once; decision 29) → reason `keep_fit`; then capped to PRICE CHECK if the buyer is `low_data` (adds `cap_low_data`) or the file is not validated (adds `cap_not_validated`). A capped KEEP lists both reasons.
6. **PRICE CHECK (partial):** otherwise, best buyer fit ≥ `price_check_fit`. **Niche** (owner decision 2026-11-23): otherwise, a candidate below `min_build_accounts` meets the KEEP condition → PRICE CHECK naming that build.
7. **Boosts** apply only when the result would be NO BUYER, and their reasons are listed only then. Fractured core mod (a qualifying fractured mod whose stat is core for a buyer-size build), base value (base price ≥ `base_value_min_chaos` at ilvl ≥ `base_value_min_ilvl`), crafting potential (≥ 2 counted core mods for a buyer-size build, an open prefix or suffix, not corrupted or mirrored). A boost names no buyer.
8. **Corrupted** items with open slots get `corrupted_open_slots_ignored` and never the crafting boost.
11. **Numbers** (decision 37): comparisons use `fit ≥ threshold − 1e-9`; fit sums core stats in descending `demand_low` order (ties by stat id); duplicate core `stat_id`s in a node count once (highest `demand_low`).
12. **Unvalidated / null thresholds** (decision 31): a null threshold needed for a decision caps the result at PRICE CHECK (`cap_not_validated`), except that fit 0 with no boost stays NO BUYER.
13. **Unsupported items** (decision 32): item class or base not in the patch → NOT SCORED with reason `unsupported_item`. Uniques are handled by name first (decision 27). Cluster jewels: TODO (decision 33).
10. **Unrecognised mods** (owner decision 2026-11-24): lines that map to no known stat are listed in `unrecognised`, ignored by scoring, and add reason `unrecognised_mods` to whatever verdict the known mods give.
9. `fit` in `expected.json` is the best buyer's fit (0 when no candidate has any fit); `counted_stat_ids` are the counted core stats of the named buyer.

Not yet covered by any rule: stale-snapshot cap (`stale_after_days`), flags for influenced / synthesised / mirrored / double-corrupted items, corruption implicits as extra mods, the "small" crafting boost for abyss jewels. The full list of interpretations for the owner to confirm is in `docs/jobs/P1-F2-scoring-engine.md`.

### Known unknowns in the seed texts

- Advanced-format tier numbers are taken from RePoE ladders on that base (PoE Royale mods excluded); confirm against real copies.
- The mod tag labels after "—" (e.g. `— Defences, Energy Shield`) are approximated from RePoE `implicit_tags`. Parsers must not depend on them.
- Property blocks (`Energy Shield: N (augmented)`), `Requirements` values and socket colours are approximate; armour movement-speed penalty lines and quality lines are not included. Parsers must skip blocks they do not use.
- Character API forms: the game merges identical stats on one line (e.g. two rarity mods); no seed item has that case yet.
- Plain Ctrl+C giving the advanced format in 3.30 is still to be confirmed in game.

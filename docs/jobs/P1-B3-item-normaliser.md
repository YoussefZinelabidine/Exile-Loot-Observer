# P1-B3 · Item normaliser

- **Agent:** backend agent (Sonnet) · **Status:** draft, waiting for owner approval and answers below
- **Design sections:** Relevance formula → What is counted; Implementation → Backend 6

## Goal

Turn an item from the character API (and the trade API) into normalised rows: item class, base, item level, rarity flags, and one row per mod (source, affix, stat IDs, values, tier, family). Uses the parsed RePoE data from P1-B2. Must reproduce `item` and `mods` of every golden item's `expected.json` from both `character.json` and `trade.json`.

## Files

`backend/normaliser/**`, `backend/tests/**`.

## Approach

- Mod text → stat IDs and values through the RePoE English translations (template matching, including `format` and `index_handlers`).
- Character API has no tiers or prefix/suffix: find the family whose ladder on that base contains the value, with `required_level ≤ ilvl`.
- Trade API has `extended.mods` with tier labels (`P1`, `S2`) and stat hashes: use them, and cross-check with the ladder.
- Sources: explicit, fractured, crafted (bench), implicit, enchant, corruption implicits. Uniques: `item` only, `mods` empty (v1).
- Tree-socketed jewels from the passive-skills response go through the same path (no fixture yet).

## Acceptance tests

1. All golden items with `character` / `trade` forms: `item` and `mods` equal `expected.json`.
2. Unknown mod text is reported (logged with the base and line), never guessed.

## Open questions for the owner

1. **Ambiguous tiers:** when a value fits two tiers' ranges (overlapping or shared values, e.g. hybrid families), (a) pick the best tier possible at that item level and mark the row `tier_ambiguous` *(recommended)*; (b) store no tier.
2. **Hybrid mods** (e.g. ES + life on one line pair): (a) one row per stat, each linked to the same family and tier *(recommended; design: hybrid mods add to the pure stat)*; (b) one row with several stat IDs.

## Done when

Checks pass and the reviewer passes it.

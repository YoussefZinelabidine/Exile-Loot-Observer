# P1-F1 · Item parser (app)

- **Agent:** frontend and overlay agent (Sonnet) · **Status:** draft, waiting for owner approval and answers below
- **Design sections:** Item scoring → step 1; What the user sees → Reading items; Implementation → Frontend 3; Data sources (Awakened PoE Trade)

## Goal

`parseItem(text, patch)` in `app/src/lib/parser/`: clipboard text in; the same `item` and `mods` shape as golden `expected.json` out, or a typed error (`unsupported_language`, `not_an_item`, `unknown_mod`). Starts from Awakened PoE Trade's MIT parser with its licence notice kept next to the copied code.

## Files

`app/src/lib/parser/**`, `app/src/lib/snapshot/types.ts` (types for the patch file), Vitest tests.

## Approach

- Read the advanced format (`{ Prefix Modifier "Name" (Tier: N) — Tags }`), plus `(implicit)`, `(fractured)`, `(crafted)`, `Corrupted`, `Mirrored`, `Fractured Item`, influence and synthesised lines.
- Mod lines → stat IDs and values through `patch.translations`; tier from the header, cross-checked with `patch.tier_sets`.
- Non-English detection from the first lines (`Item Class:` / `Rarity:` missing) → `unsupported_language`.
- Golden fixtures are read from `shared/fixtures/` at test time (read-only).

## Acceptance tests

1. Every golden `game.txt` gives exactly `expected.item` and `expected.mods` (fixture 008 gives `unsupported_language`).
2. A licence notice file for any code taken from Awakened PoE Trade.

## Open questions for the owner

1. **Plain Ctrl+C format:** please confirm in game (3.30) that plain Ctrl+C gives the advanced format. If not, the parser also needs the simple format.
2. **How much of Awakened PoE Trade to copy:** (a) only its text-section parsing helpers, adapted to our patch data *(recommended: its stat data format differs from ours)*; (b) its whole parser with its own stat database.

## Done when

`pnpm check`, `pnpm test` pass with the golden items, and the reviewer passes it.

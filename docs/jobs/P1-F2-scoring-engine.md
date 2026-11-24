# P1-F2 · Scoring engine (app)

- **Agent:** frontend and overlay agent (Sonnet) · **Status:** draft, waiting for owner approval and answers below
- **Design sections:** Relevance formula (tier gate); Item scoring and verdict; Where calculations run

## Goal

`scoreItem(parsed, patch, daily)` in `app/src/lib/scoring/`: tier gate, fit per build, best buyer, verdict with caps and boosts, reasons, counted stats; special items (unique / cluster jewel price lookup). Also `marketDemand(daily, itemClass, filter)` for What to farm (Σ demand × accounts). Pure functions, no I/O.

## Files

`app/src/lib/scoring/**`, `app/src/lib/snapshot/types.ts` (daily-file types), Vitest tests.

## Approach

Implements exactly the rules the owner confirms from `shared/fixtures/README.md` ("Scoring rules the expected verdicts follow"). Thresholds and gate parameters come only from the daily file; nothing is hard-coded. `validated: false` or a `null` threshold caps at PRICE CHECK.

## Acceptance tests

1. Every golden item (parsed by P1-F1, or from `expected.item`/`expected.mods` directly) scored against `shared/fixtures/snapshot/` gives exactly `expected.verdict` (`fit` within 1e-4).
2. Unit tests for each rule, including the not-yet-covered cases listed in the fixtures README (base value, crafting potential, niche build, not validated).

## Open questions for the owner

1. **Confirm the proposed scoring rules** (`shared/fixtures/README.md`). These points are interpretations, not stated in the design:
   - R1a: the tier gate uses the full ladder length on that base, ignoring item level (alternative: only tiers possible at the item's level).
   - R1b: implicits and crafted mods never qualify (but the design scores corruption implicits as extra mods: they need their own rule).
   - R2: the `all` node is never a buyer; archetypes and shown main-skill nodes compete together.
   - R3: k = max prefixes + max suffixes; each core stat counts once; fit is not capped at 1.
   - R4: "meaningful number of players" uses raw `accounts`, not `effective_accounts`.
   - R6: the niche check runs only after the partial-fit check fails.
   - R7a: boosts apply, and are shown as reasons, only when the result would otherwise be NO BUYER (the design says the reason is shown "when it applies").
   - R7b: the fractured boost needs the fractured mod to pass the tier gate and be core for a buyer-size build.
   - R7c: base value = price ≥ X at item level ≥ Y; how widely the base is worn is not used yet.
   - R7d: the crafting boost treats abyss jewels like other items (the design says it is "small" for them).
   - R8: the corrupted reason appears only when the item has open slots.
   - R9: no buyer is named for a boost or NO BUYER; `fit` still reports the top candidate's fit.
   - Missing: stale-snapshot cap, flags for influenced / synthesised / mirrored / double-corrupted items.
2. **Market demand nodes:** which nodes are summed for What to farm. (a) Archetypes only, so each player counts once *(recommended)*; (b) archetypes and main skills (counts players twice).
3. **Craftable discount:** the design says naturally rolled craftable stats are "discounted in item scoring". (a) Multiply that mod's `demand_low` by `(1 − craftable_discount)` in the numerator only *(recommended: an ideal item's demand stays the same)*; (b) in both numerator and denominator.

## Done when

`pnpm check`, `pnpm test` pass with the golden items, and the reviewer passes it.

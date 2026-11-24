# P1-B4 · Python scoring engine

- **Agent:** backend agent (Sonnet) · **Status:** approved by owner 2026-11-24 (overview question 2: add it now)
- **Design sections:** Relevance formula (tier gate); Item scoring and verdict; Validation (scoring exists twice)

## Goal

`backend/scoring/`: the Python twin of the app's scoring engine (P1-F2), used later by validation. `score_item(item, mods, patch, daily) -> Verdict` and `market_demand(daily, item_class, node_filter)`. Pure functions on the pydantic snapshot models from P1-B2.

## Files

`backend/scoring/**`, `backend/tests/**`.

## Rules

Exactly the confirmed rules in `shared/fixtures/README.md` ("Scoring rules the expected verdicts follow", R1–R9) and the owner decisions in `docs/decisions.md` (market demand: archetype nodes only; craftable discount: numerator only; niche build named; `validated: false` / `null` threshold → cap at PRICE CHECK). Nothing hard-coded: thresholds and gate parameters come from the daily file. Not covered yet (leave named TODOs, do not implement): stale-snapshot cap, influenced / synthesised / mirrored / double-corrupted flags, corruption implicits as extra mods.

Also decisions 29–37 (distinct affixes for "≥ 2 mods", KEEP-first best buyer, null thresholds keep fit-0 NO BUYER, `unsupported_item`, cluster-jewel TODO, market-demand main-skill filter, epsilon 1e-9 and summation order, duplicate core stats once). Mirror the app engine's function names, inputs and outputs (`app/src/lib/scoring/`) so a parity test can run both.

## Acceptance tests

1. Every golden item: scoring `expected.item` + `expected.mods` against `shared/fixtures/snapshot/` gives exactly `expected.verdict` (`fit` within 1e-4; `reasons` and `counted_stat_ids` compared as sets).
2. Unit tests for each rule, including cases not in the golden set (base value, crafting potential, niche build, `validated: false`, `null` thresholds).
3. Same function names and outputs as the TypeScript engine (P1-F2), so a parity test can later run both on the same inputs.

## Done when

`pytest`, `ruff` pass and the reviewer passes it.

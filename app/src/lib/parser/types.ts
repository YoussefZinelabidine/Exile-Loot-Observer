export type Rarity = "Normal" | "Magic" | "Rare" | "Unique";
export type Influence = "shaper" | "elder" | "crusader" | "redeemer" | "hunter" | "warlord";
export type ModSource =
  | "implicit"
  | "explicit"
  | "fractured"
  | "crafted"
  | "enchant"
  | "corruption_implicit";

// Same shape as `item` in the golden expected.json files (shared/fixtures/golden).
export interface ParsedItem {
  rarity: Rarity;
  item_class: string;
  base: string;
  name: string | null;
  ilvl: number;
  corrupted: boolean;
  mirrored: boolean;
  fractured: boolean;
  synthesised: boolean;
  influences: Influence[];
  /** Rare and magic items only. */
  open_prefixes?: number;
  open_suffixes?: number;
}

/**
 * Same shape as an entry of `mods` in expected.json, without `qualifies`
 * (that is the scoring engine's tier-gate result, not parser output).
 */
export interface ParsedMod {
  source: ModSource;
  affix: "prefix" | "suffix" | null;
  stat_ids: string[];
  values: number[];
  tier: number | null;
  family: string | null;
  /** Internal: the header tier was missing or unknown, so the tier was found by the mod name. Not part of the golden shape. */
  tier_mismatch?: boolean;
}

export interface ParseResult {
  item: ParsedItem;
  mods: ParsedMod[];
  /** Mod lines that could not be mapped to a known stat (or were ambiguous). The item is still usable. */
  unrecognised: string[];
}

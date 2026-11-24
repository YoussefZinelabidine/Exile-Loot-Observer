export type VerdictResult = "KEEP" | "PRICE_CHECK" | "NO_BUYER" | "NOT_SCORED";

export type VerdictReason =
  | "keep_fit"
  | "partial_fit"
  | "niche_build_fit"
  | "no_fit"
  | "boost_base_value"
  | "boost_crafting_potential"
  | "boost_fractured_core_mod"
  | "cap_low_data"
  | "cap_not_validated"
  | "corrupted_open_slots_ignored"
  | "unique_price_lookup"
  | "unsupported_item"
  | "cluster_jewel_price_lookup"
  | "unrecognised_mods";

/** Same shape as `verdict` in golden expected.json (UNSUPPORTED_LANGUAGE is a parser error, not a verdict). */
export interface Verdict {
  result: VerdictResult;
  best_buyer: string | null;
  /** Best buyer's fit rounded to 4 decimals; null when not scored. */
  fit: number | null;
  low_data: boolean;
  reasons: VerdictReason[];
  counted_stat_ids: string[];
  /** Price lookup only (uniques, cluster jewels). null = not in the price list. */
  special_price_chaos?: number | null;
}

/**
 * What to farm filter (decision 34). No filter, or defence / damage, sums the matching ARCHETYPE nodes.
 * `node_id` naming a main-skill node uses only that node; naming an archetype uses only that archetype.
 */
export interface MarketDemandFilter {
  defence?: "life" | "es" | "hybrid";
  damage?: "attack" | "spell" | "minion" | "dot";
  node_id?: string;
}

export interface MarketDemandRow {
  stat_id: string;
  /** Σ over archetype nodes b of demand(stat, b) × accounts_b. */
  demand: number;
  /** Archetype nodes that contribute. */
  nodes: string[];
}

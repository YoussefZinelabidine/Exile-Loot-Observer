import type { DailyBuildNode, DailyFile, DailyModDemand, DailyThresholds, PatchFile } from "../snapshot/types";
import type { ParsedItem, ParsedMod } from "../parser/types";
import type { Verdict, VerdictReason } from "./types";
import { compareIds } from "./compare";

// TODO(stale-snapshot-cap): cap at PRICE CHECK with a low-data marker when crawl_date is older than
//   params.stale_after_days. No rule yet (owner: do not implement).
// TODO(item-flags): influenced / synthesised / mirrored / double-corrupted items have no scoring rule yet.
//   (Mirrored only blocks the crafting boost, as R7 says; influences only keep the base-value lookup to
//   un-influenced base prices.)
// TODO(cluster-jewels): cluster jewel detection and price key are decided later (decision 33); for now a
//   class marked scored:false is NOT_SCORED / unsupported_item.
// TODO(corruption-implicits): corruption implicits as extra mods have no rule yet; they are ignored here.

export interface ScoreInput {
  item: Omit<ParsedItem, "open_prefixes" | "open_suffixes"> & {
    /** null or absent = unknown (no crafting-potential boost). */
    open_prefixes?: number | null;
    open_suffixes?: number | null;
  };
  /** `qualifies` and `tier_mismatch` on mods are ignored: the tier gate is computed here. */
  mods: ParsedMod[];
  unrecognised?: string[];
}

interface Candidate {
  node: DailyBuildNode;
  fit: number;
  counted: string[];
  /** Distinct affixes (a hybrid affix counts once) holding a counted core stat; "≥ 2 core mods" means this (decision 29). */
  affixes: number;
  coreStats: Set<string>;
}

const round4 = (x: number) => Math.round(x * 1e4) / 1e4;
/** Comparisons use `value >= threshold - EPS` (decision 37). */
const EPS = 1e-9;

function thresholdsFor(daily: DailyFile, itemClass: string): DailyThresholds {
  const base = daily.params.thresholds.default;
  const over = daily.params.thresholds.by_item_class?.[itemClass] ?? {};
  return { ...base, ...over };
}

/** R1: tier gate. Explicit and fractured mods only; implicits and crafts never qualify. */
function qualifyingStats(
  mods: ParsedMod[],
  patch: PatchFile,
  daily: DailyFile,
  tierSetKey: string,
): { qualifying: Map<ParsedMod, boolean> } {
  const set = patch.tier_sets[tierSetKey] ?? {};
  const { top_fraction, always_top_tiers } = daily.params.tier_gate;
  const qualifying = new Map<ParsedMod, boolean>();
  for (const m of mods) {
    let ok = false;
    if ((m.source === "explicit" || m.source === "fractured") && m.tier !== null && m.family) {
      const ladder = set[m.family]?.tiers.length;
      if (ladder) {
        const limit = Math.max(always_top_tiers, Math.ceil(top_fraction * ladder - 1e-9));
        ok = m.tier <= limit;
      }
    }
    qualifying.set(m, ok);
  }
  return { qualifying };
}

function uniquePrice(daily: DailyFile, name: string | null): number | null {
  const entries = (daily.special_prices ?? []).filter((e) => e.kind === "unique" && e.name === name);
  // Several variants of one name: prefer the plain one (no variant, no links), else the first listed.
  const plain = entries.find((e) => !e.variant && !e.links);
  return (plain ?? entries[0])?.chaos ?? null;
}

export function scoreItem(parsed: ScoreInput, patch: PatchFile, daily: DailyFile): Verdict {
  const { item, mods } = parsed;
  const unrecognised = parsed.unrecognised ?? [];

  // Special items: price lookup, not scored.
  if (item.rarity === "Unique") {
    return {
      result: "NOT_SCORED",
      best_buyer: null,
      fit: null,
      low_data: false,
      reasons: withUnrecognised(["unique_price_lookup"], unrecognised),
      counted_stat_ids: [],
      special_price_chaos: uniquePrice(daily, item.name),
    };
  }
  // Item class or base not in the patch (or a class that is recognised but not scored): decision 32 / 33.
  const classInfo = patch.item_classes[item.item_class];
  const baseInfo = patch.bases[item.base];
  if (!classInfo || !baseInfo || classInfo.scored === false) {
    return {
      result: "NOT_SCORED",
      best_buyer: null,
      fit: null,
      low_data: false,
      reasons: withUnrecognised(["unsupported_item"], unrecognised),
      counted_stat_ids: [],
    };
  }

  const t = thresholdsFor(daily, item.item_class);
  let nullThreshold = false; // a threshold needed for a decision was null
  const need = <T>(v: T | null | undefined): T | null => {
    if (v === null || v === undefined) {
      nullThreshold = true;
      return null;
    }
    return v;
  };

  const { qualifying } = qualifyingStats(mods, patch, daily, baseInfo.tier_set);
  const qualStats = new Set<string>();
  for (const m of mods) if (qualifying.get(m)) for (const id of m.stat_ids) qualStats.add(id);

  const k = classInfo.max_prefixes + classInfo.max_suffixes;
  const craftable = new Set(classInfo.craftable_stat_ids ?? []);

  // R2: candidate builds.
  const candidates: Candidate[] = [];
  for (const node of daily.build_nodes) {
    if (node.id === "all" || !node.shown_on_own) continue;
    const nd = daily.demand[item.item_class]?.[node.id];
    if (!nd) continue;
    const core = coreMods(nd.mods);
    const denom = core.slice(0, k).reduce((s, m) => s + m.demand_low, 0);
    let numer = 0;
    const counted: string[] = [];
    for (const m of core) {
      if (!qualStats.has(m.stat_id)) continue;
      counted.push(m.stat_id);
      // Craftable discount: numerator only (owner decision 2026-11-24).
      const discount = craftable.has(m.stat_id) ? (need(t.craftable_discount) ?? 0) : 0;
      numer += m.demand_low * (1 - discount);
    }
    const coreIds = new Set(core.map((m) => m.stat_id));
    const affixes = new Set<string>();
    for (const m of mods) {
      if (qualifying.get(m) && m.stat_ids.some((id) => coreIds.has(id))) affixes.add(m.family ?? m.stat_ids.join("|"));
    }
    candidates.push({
      node,
      fit: denom > 0 ? numer / denom : 0,
      counted,
      affixes: affixes.size,
      coreStats: new Set(core.map((m) => m.stat_id)),
    });
  }

  // R4: buyers have enough accounts; the rest are niche.
  const minAccounts = need(t.min_build_accounts) ?? 0;
  // Fits equal within EPS tie: then more accounts, then node id.
  const byFit = (a: Candidate, b: Candidate) =>
    (Math.abs(b.fit - a.fit) > EPS ? b.fit - a.fit : 0) ||
    b.node.accounts - a.node.accounts ||
    compareIds(a.node.id, b.node.id);
  const buyers = candidates.filter((c) => c.node.accounts >= minAccounts).sort(byFit);
  const niche = candidates.filter((c) => c.node.accounts < minAccounts).sort(byFit);

  const topFit = Math.max(0, ...candidates.map((c) => c.fit)); // R9: best candidate's fit even when no buyer is named

  const reasons: VerdictReason[] = [];
  let result: Verdict["result"];
  let buyer: Candidate | null = null;
  let fit = topFit;
  let counted: string[] = [];

  const keepFitOk = (c: Candidate) => {
    const kf = need(t.keep_fit);
    return c.affixes >= 2 && (kf === null ? c.fit > 0 : c.fit >= kf - EPS);
  };

  // Decision 30: among buyer-size builds that meet the KEEP condition the highest fit, else the highest fit.
  const best = buyers.find(keepFitOk) ?? buyers[0];

  if (best && keepFitOk(best)) {
    // R5
    buyer = best;
    result = "KEEP";
    reasons.push("keep_fit");
    if (best.node.low_data) {
      result = "PRICE_CHECK";
      reasons.push("cap_low_data");
    }
    if (!daily.validated || nullThreshold) {
      result = "PRICE_CHECK";
      reasons.push("cap_not_validated");
    }
  } else if (best && best.fit > 0 && (() => { const p = need(t.price_check_fit); return p === null || best.fit >= p - EPS; })()) {
    // R6 partial fit
    buyer = best;
    result = "PRICE_CHECK";
    reasons.push("partial_fit");
  } else if (niche.some(keepFitOk)) {
    // R6 niche build (owner decision 2026-11-23): the highest-fit niche build that meets the KEEP condition
    buyer = niche.find(keepFitOk)!;
    result = "PRICE_CHECK";
    reasons.push("niche_build_fit");
  } else {
    // R7: boosts, only when the result would be NO BUYER.
    const boosts: VerdictReason[] = [];
    if (fracturedCoreBoost(mods, qualifying, buyers)) boosts.push("boost_fractured_core_mod");
    if (baseValueBoost(item, daily, t, need)) boosts.push("boost_base_value");
    if (craftingBoost(item, buyers)) boosts.push("boost_crafting_potential");
    if (boosts.length > 0) {
      result = "PRICE_CHECK";
      reasons.push(...boosts);
    } else {
      result = "NO_BUYER";
      reasons.push("no_fit");
    }
  }

  if (buyer) {
    fit = buyer.fit;
    counted = buyer.counted;
  }
  if (result === "NO_BUYER" && nullThreshold && topFit > 0) {
    // A needed threshold is missing and some build fits a little: the engine cannot rule a buyer out.
    // (Fit 0 with no boost stays NO BUYER, decision 31.)
    result = "PRICE_CHECK";
    reasons.length = 0;
    reasons.push("cap_not_validated");
  } else if (nullThreshold && result !== "NO_BUYER" && !reasons.includes("cap_not_validated")) {
    reasons.push("cap_not_validated");
  }

  // R8
  const openSlots = (item.open_prefixes ?? 0) + (item.open_suffixes ?? 0);
  if (item.corrupted && openSlots > 0) reasons.push("corrupted_open_slots_ignored");

  return {
    result,
    best_buyer: buyer ? buyer.node.id : null,
    fit: round4(fit),
    low_data: buyer ? buyer.node.low_data : false,
    reasons: withUnrecognised(reasons, unrecognised),
    counted_stat_ids: counted,
  };
}

/** Core mods of a node, highest demand_low first (ties by stat id); a duplicated stat id counts once, with its highest demand_low (decision 37). */
function coreMods(mods: DailyModDemand[]): DailyModDemand[] {
  const best = new Map<string, DailyModDemand>();
  for (const m of mods) {
    if (!m.core) continue;
    const prev = best.get(m.stat_id);
    if (!prev || m.demand_low > prev.demand_low) best.set(m.stat_id, m);
  }
  return [...best.values()].sort((a, b) => b.demand_low - a.demand_low || compareIds(a.stat_id, b.stat_id));
}

function withUnrecognised(reasons: VerdictReason[], unrecognised: string[]): VerdictReason[] {
  // R10
  return unrecognised.length > 0 ? [...reasons, "unrecognised_mods"] : reasons;
}

/** R7: a qualifying fractured mod whose stat is core for a buyer-size build. */
function fracturedCoreBoost(mods: ParsedMod[], qualifying: Map<ParsedMod, boolean>, buyers: Candidate[]): boolean {
  return mods.some(
    (m) => m.source === "fractured" && qualifying.get(m) && buyers.some((b) => m.stat_ids.some((id) => b.coreStats.has(id))),
  );
}

/** R7: base price >= base_value_min_chaos at item level >= base_value_min_ilvl. */
function baseValueBoost(
  item: ScoreInput["item"],
  daily: DailyFile,
  t: DailyThresholds,
  need: <T>(v: T | null | undefined) => T | null,
): boolean {
  const minChaos = need(t.base_value_min_chaos);
  const minIlvl = need(t.base_value_min_ilvl);
  if (minChaos === null || minIlvl === null) return false;
  if (item.ilvl < minIlvl) return false;
  // Plain (un-influenced) prices only until influenced items have a rule (see TODO(item-flags)).
  if (item.influences.length > 0) return false;
  const entries = (daily.base_values ?? [])
    .filter((e) => e.base === item.base && e.influence === null && e.min_ilvl <= item.ilvl)
    .sort((a, b) => b.min_ilvl - a.min_ilvl);
  return entries.length > 0 && entries[0].chaos >= minChaos;
}

/** R7: >= 2 counted core mods for a buyer-size build, an open affix, not corrupted or mirrored. */
function craftingBoost(item: ScoreInput["item"], buyers: Candidate[]): boolean {
  if (item.corrupted || item.mirrored) return false;
  // Unknown open slots (null or absent, e.g. from the character API) never give the boost.
  if (typeof item.open_prefixes !== "number" || typeof item.open_suffixes !== "number") return false;
  if (item.open_prefixes + item.open_suffixes === 0) return false;
  return buyers.some((b) => b.affixes >= 2);
}

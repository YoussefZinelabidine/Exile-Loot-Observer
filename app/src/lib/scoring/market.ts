import type { DailyFile } from "../snapshot/types";
import { compareIds } from "./compare";
import type { MarketDemandFilter, MarketDemandRow } from "./types";

/**
 * Market demand for "What to farm" (owner decision 2026-11-24): Σ_b demand × accounts_b over ARCHETYPE nodes
 * only, so no player is counted twice. A main-skill filter (node_id) uses only that node (decision 34). Sorted by demand, highest first.
 */
export function marketDemand(daily: DailyFile, itemClass: string, filter: MarketDemandFilter = {}): MarketDemandRow[] {
  const byNode = daily.demand[itemClass] ?? {};
  const rows = new Map<string, MarketDemandRow>();
  const picked = filter.node_id ? daily.build_nodes.find((n) => n.id === filter.node_id) : undefined;
  if (filter.node_id && (!picked || picked.level === "all")) return [];
  for (const node of daily.build_nodes) {
    if (picked) {
      // A main-skill (or single archetype) filter uses only that node.
      if (node.id !== picked.id) continue;
    } else if (node.level !== "archetype") continue;
    if (filter.defence && node.defence !== filter.defence) continue;
    if (filter.damage && node.damage !== filter.damage) continue;
    const d = byNode[node.id];
    if (!d) continue;
    for (const mod of d.mods) {
      if (mod.demand <= 0) continue;
      const row = rows.get(mod.stat_id) ?? { stat_id: mod.stat_id, demand: 0, nodes: [] };
      row.demand += mod.demand * node.accounts;
      row.nodes.push(node.id);
      rows.set(mod.stat_id, row);
    }
  }
  return [...rows.values()].sort((a, b) => b.demand - a.demand || compareIds(a.stat_id, b.stat_id));
}

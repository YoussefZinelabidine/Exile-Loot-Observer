import { readdirSync, readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { parseItem } from "../parser";
import type { DailyFile, GoldenExpectedFile, PatchFile } from "../snapshot/types";
import { compareIds } from "./compare";
import { marketDemand, scoreItem } from "./index";
import type { ScoreInput } from "./score";

const fixtures = fileURLToPath(new URL("../../../../shared/fixtures/", import.meta.url));
const read = (p: string) => readFileSync(fixtures + p, "utf8");
const patch: PatchFile = JSON.parse(read("snapshot/patch.json"));
const daily: DailyFile = JSON.parse(read("snapshot/daily.json"));

const goldenDirs = readdirSync(fixtures + "golden", { withFileTypes: true })
  .filter((d) => d.isDirectory())
  .map((d) => d.name)
  .sort();

const goldenExpected = (dir: string): GoldenExpectedFile => JSON.parse(read(`golden/${dir}/expected.json`));

function expectVerdict(got: ReturnType<typeof scoreItem>, want: GoldenExpectedFile["verdict"]) {
  expect(got.result).toBe(want.result);
  expect(got.best_buyer).toBe(want.best_buyer);
  if (want.fit === null) expect(got.fit).toBeNull();
  else expect(Math.abs((got.fit ?? NaN) - want.fit)).toBeLessThanOrEqual(1e-4);
  expect(got.low_data).toBe(want.low_data);
  expect(new Set(got.reasons)).toEqual(new Set(want.reasons));
  expect(got.reasons.length).toBe(new Set(got.reasons).size);
  expect(new Set(got.counted_stat_ids)).toEqual(new Set(want.counted_stat_ids));
  if (want.special_price_chaos !== undefined) expect(got.special_price_chaos).toBe(want.special_price_chaos);
}

describe("golden verdicts", () => {
  for (const dir of goldenDirs) {
    const expected = goldenExpected(dir);
    if (expected.item === null) continue; // unsupported language: the parser refuses it, nothing to score

    it(`${dir} (from expected item and mods)`, () => {
      const input: ScoreInput = { item: expected.item as ScoreInput["item"], mods: expected.mods as ScoreInput["mods"] };
      expectVerdict(scoreItem(input, patch, daily), expected.verdict);
    });

    if (expected.forms.includes("game")) {
      it(`${dir} (from parseItem(game.txt))`, () => {
        const parsed = parseItem(read(`golden/${dir}/game.txt`), patch);
        expectVerdict(scoreItem(parsed, patch, daily), expected.verdict);
      });
    }
  }
});

// ---- cases outside the golden set ------------------------------------------------------------

const clone = <T>(x: T): T => JSON.parse(JSON.stringify(x));
const golden = (dir: string): ScoreInput => {
  const e = goldenExpected(dir);
  return { item: e.item as ScoreInput["item"], mods: e.mods as ScoreInput["mods"] };
};
const withThresholds = (over: Record<string, number | null>): DailyFile => {
  const d = clone(daily);
  Object.assign(d.params.thresholds.default, over);
  return d;
};

describe("rules outside the golden set", () => {
  it("base value boost lifts NO BUYER to PRICE CHECK", () => {
    const boots = golden("004-boots-no-buyer");
    boots.item.ilvl = 84;
    const d = clone(daily);
    d.base_values = [{ base: "Sorcerer Boots", min_ilvl: 84, influence: null, chaos: 25 }];
    const v = scoreItem(boots, patch, d);
    expect(v.result).toBe("PRICE_CHECK");
    expect(v.reasons).toEqual(["boost_base_value"]);
    expect(v.best_buyer).toBeNull();
  });

  it("no base value boost below the item level or the price", () => {
    const boots = golden("004-boots-no-buyer");
    expect(scoreItem(boots, patch, daily).result).toBe("NO_BUYER");
    boots.item.ilvl = 84;
    expect(scoreItem(boots, patch, daily).result).toBe("NO_BUYER"); // 6 chaos < 20
  });

  it("crafting potential boost", () => {
    const d = withThresholds({ keep_fit: 0.99, price_check_fit: 0.99 });
    const v = scoreItem(golden("001-ring-keep-life-attack"), patch, d);
    expect(v.result).toBe("PRICE_CHECK");
    expect(v.reasons).toEqual(["boost_crafting_potential"]);
    expect(v.best_buyer).toBeNull();
    expect(v.fit).toBeCloseTo(0.6087, 4); // top candidate's fit is still reported
  });

  it("no crafting boost when the open slots are null or absent", () => {
    const d = withThresholds({ keep_fit: 0.99, price_check_fit: 0.99 });
    const nulls = golden("001-ring-keep-life-attack");
    nulls.item.open_prefixes = null;
    nulls.item.open_suffixes = null;
    expect(scoreItem(nulls, patch, d).result).toBe("NO_BUYER");
    const absent = golden("001-ring-keep-life-attack");
    delete absent.item.open_prefixes;
    delete absent.item.open_suffixes;
    expect(scoreItem(absent, patch, d).result).toBe("NO_BUYER");
    const half = golden("001-ring-keep-life-attack");
    half.item.open_suffixes = null;
    expect(scoreItem(half, patch, d).result).toBe("NO_BUYER");
  });

  it("buyers whose fits are equal within 1e-9 tie on accounts, then node id", () => {
    const d = clone(daily);
    const a = d.demand.Ring["arch:life-attack"];
    d.build_nodes.push({
      id: "arch:twin",
      level: "archetype",
      parent: "all",
      label: "twin",
      accounts: 5000,
      effective_accounts: 5000,
      shown_on_own: true,
      low_data: false,
    });
    d.demand.Ring["arch:twin"] = clone(a);
    // A fit differing by less than 1e-9 must not decide: the build with more accounts wins.
    d.demand.Ring["arch:twin"].mods.forEach((m) => (m.demand_low *= 1 - 1e-12));
    expect(scoreItem(golden("001-ring-keep-life-attack"), patch, d).best_buyer).toBe("arch:twin");
  });

  it("no crafting boost for corrupted or mirrored items, or without an open affix", () => {
    const d = withThresholds({ keep_fit: 0.99, price_check_fit: 0.99 });
    const corrupted = golden("001-ring-keep-life-attack");
    corrupted.item.corrupted = true;
    expect(scoreItem(corrupted, patch, d).result).toBe("NO_BUYER");
    const mirrored = golden("001-ring-keep-life-attack");
    mirrored.item.mirrored = true;
    expect(scoreItem(mirrored, patch, d).result).toBe("NO_BUYER");
    const full = golden("001-ring-keep-life-attack");
    full.item.open_prefixes = 0;
    full.item.open_suffixes = 0;
    expect(scoreItem(full, patch, d).result).toBe("NO_BUYER");
  });

  it("niche build: KEEP-level fit below min_build_accounts gives PRICE CHECK naming it", () => {
    const d = withThresholds({ min_build_accounts: 2000 });
    const v = scoreItem(golden("001-ring-keep-life-attack"), patch, d);
    expect(v.result).toBe("PRICE_CHECK");
    expect(v.best_buyer).toBe("arch:life-attack");
    expect(v.reasons).toEqual(["niche_build_fit"]);
    expect(v.fit).toBeCloseTo(0.6087, 4);
  });

  it("validated:false caps KEEP at PRICE CHECK", () => {
    const d = clone(daily);
    d.validated = false;
    const v = scoreItem(golden("001-ring-keep-life-attack"), patch, d);
    expect(v.result).toBe("PRICE_CHECK");
    expect(new Set(v.reasons)).toEqual(new Set(["keep_fit", "cap_not_validated"]));
    expect(v.best_buyer).toBe("arch:life-attack");
  });

  it("a null keep_fit caps KEEP at PRICE CHECK", () => {
    const v = scoreItem(golden("001-ring-keep-life-attack"), patch, withThresholds({ keep_fit: null }));
    expect(v.result).toBe("PRICE_CHECK");
    expect(v.reasons).toContain("cap_not_validated");
  });

  it("null thresholds: fit 0 with no boost stays NO BUYER (decision 31)", () => {
    const d = withThresholds({ price_check_fit: null, keep_fit: null });
    const v = scoreItem(golden("004-boots-no-buyer"), patch, d);
    expect(v.result).toBe("NO_BUYER");
    expect(v.reasons).toEqual(["no_fit"]);
  });

  it("null thresholds: a non-zero fit that would be NO BUYER is capped at PRICE CHECK", () => {
    const d = withThresholds({ keep_fit: 0.99, price_check_fit: 0.99, base_value_min_chaos: null });
    const ring = golden("001-ring-keep-life-attack");
    ring.item.corrupted = true; // no crafting boost
    const v = scoreItem(ring, patch, d);
    expect(v.result).toBe("PRICE_CHECK");
    expect(v.reasons).toEqual(["cap_not_validated", "corrupted_open_slots_ignored"]);
  });

  it("unrecognised mod lines add a reason and leave the known mods scored", () => {
    const input = { ...golden("001-ring-keep-life-attack"), unrecognised: ["+7 to Frobnication"] };
    const v = scoreItem(input, patch, daily);
    expect(v.result).toBe("KEEP");
    expect(new Set(v.reasons)).toEqual(new Set(["keep_fit", "unrecognised_mods"]));
  });

  it("craftable discount lowers the numerator only", () => {
    const p = clone(patch);
    p.item_classes.Ring.craftable_stat_ids = ["base_maximum_life"];
    const d = withThresholds({ craftable_discount: 0.5 });
    const plain = scoreItem(golden("001-ring-keep-life-attack"), patch, daily).fit as number;
    const v = scoreItem(golden("001-ring-keep-life-attack"), p, d);
    // life demand_low 0.3 of a numerator of 0.7: 0.15 less on an unchanged denominator.
    const denominator = 0.7 / plain;
    expect(v.fit).toBeCloseTo(0.55 / denominator, 4);
    expect(v.counted_stat_ids).toContain("base_maximum_life");
  });

  it("uniques: price by name, null when the name is not listed", () => {
    const u = golden("007-unique-ring-not-scored");
    expect(scoreItem(u, patch, daily).special_price_chaos).toBe(3);
    u.item.name = "Nobody's Ring";
    const v = scoreItem(u, patch, daily);
    expect(v.result).toBe("NOT_SCORED");
    expect(v.special_price_chaos).toBeNull();
  });

  it("tier gate comes from the daily file", () => {
    // T5 of 8 resistance fails at 0.4 but passes when the gate is wide open.
    const d = clone(daily);
    d.params.tier_gate = { top_fraction: 1, always_top_tiers: 1 };
    const v = scoreItem(golden("001-ring-keep-life-attack"), patch, d);
    expect(v.counted_stat_ids).toContain("base_lightning_damage_resistance_%");
  });
});

describe("decisions 29-37", () => {
  const mod = (stat_id: string, family: string, tier = 1): ScoreInput["mods"][number] => ({
    source: "explicit",
    affix: "prefix",
    stat_ids: [stat_id],
    values: [1],
    tier,
    family,
  });

  /** Adds an archetype node with the given core mods (stat id, demand_low) for the Ring class. */
  const withNode = (id: string, accounts: number, mods: [string, number][]) => {
    const d = clone(daily);
    d.build_nodes.push({
      id,
      level: "archetype",
      parent: "all",
      label: id,
      accounts,
      effective_accounts: accounts,
      shown_on_own: true,
      low_data: false,
    });
    d.demand.Ring[id] = {
      effective_items: 100,
      mods: mods.map(([stat_id, demand_low]) => ({
        stat_id,
        core: true,
        demand: demand_low,
        demand_low,
        share: 0.5,
        effective_obs: 50,
        demand_tier: "A" as const,
      })),
    };
    return d;
  };

  it("niche: the first niche build that meets KEEP is named, not just the top-fit one (decision 30)", () => {
    // es-spell (900 accounts) keeps only life as core: fit 1.0 but one affix, so it cannot meet KEEP.
    const d = withThresholds({ min_build_accounts: 5000 });
    const es = d.demand.Ring["arch:es-spell"];
    es.mods = es.mods.filter((m) => m.stat_id === "base_maximum_life");
    const v = scoreItem(golden("001-ring-keep-life-attack"), patch, d);
    expect(v.result).toBe("PRICE_CHECK");
    expect(v.best_buyer).toBe("arch:life-attack");
    expect(v.reasons).toEqual(["niche_build_fit"]);
    expect(v.fit).toBeCloseTo(0.6087, 4);
  });

  it("best buyer prefers a buyer-size build that meets KEEP over a higher-fit one that does not (decision 30)", () => {
    const d = withNode("arch:one-mod", 5000, [["base_maximum_life", 0.5]]); // fit 1.0, one affix
    const v = scoreItem(golden("001-ring-keep-life-attack"), patch, d);
    expect(v.result).toBe("KEEP");
    expect(v.best_buyer).toBe("arch:life-attack");
  });

  it("without any KEEP-level buyer the highest-fit buyer is named", () => {
    const d = withNode("arch:one-mod", 5000, [["base_maximum_life", 0.5]]);
    const only = golden("001-ring-keep-life-attack");
    only.mods = only.mods.filter((m) => m.stat_ids[0] === "base_maximum_life"); // one affix: nobody meets KEEP
    const v = scoreItem(only, patch, d);
    expect(v.best_buyer).toBe("arch:one-mod");
    expect(v.result).toBe("PRICE_CHECK");
  });

  it("KEEP counts distinct affixes, not stats (decision 29)", () => {
    // Two core stats from ONE affix (same family): two counted stats, one affix.
    const hybrid = golden("001-ring-keep-life-attack");
    hybrid.mods = [
      mod("base_maximum_life", "prefix:IncreasedLife"),
      mod("base_fire_damage_resistance_%", "prefix:IncreasedLife"),
    ];
    const v = scoreItem(hybrid, patch, daily);
    expect(v.counted_stat_ids).toHaveLength(2);
    expect(v.result).toBe("PRICE_CHECK");
    expect(v.reasons).toEqual(["partial_fit"]);
  });

  it("the crafting boost needs two distinct affixes too", () => {
    const d = withThresholds({ keep_fit: 0.99, price_check_fit: 0.99 });
    const hybrid = golden("001-ring-keep-life-attack");
    hybrid.mods = [
      mod("base_maximum_life", "prefix:IncreasedLife"),
      mod("base_fire_damage_resistance_%", "prefix:IncreasedLife"),
    ];
    expect(scoreItem(hybrid, patch, d).result).toBe("NO_BUYER");
    expect(scoreItem(golden("001-ring-keep-life-attack"), patch, d).reasons).toEqual(["boost_crafting_potential"]);
  });

  it("unsupported items: base or class not in the patch, or a scored:false class (decisions 32, 33)", () => {
    const unknownBase = golden("001-ring-keep-life-attack");
    unknownBase.item.base = "Nonexistent Ring";
    expect(scoreItem(unknownBase, patch, daily)).toMatchObject({
      result: "NOT_SCORED",
      reasons: ["unsupported_item"],
      fit: null,
      best_buyer: null,
    });

    const unknownClass = golden("001-ring-keep-life-attack");
    unknownClass.item.item_class = "Belt";
    expect(scoreItem(unknownClass, patch, daily).reasons).toEqual(["unsupported_item"]);

    const p = clone(patch);
    p.item_classes.Ring.scored = false;
    expect(scoreItem(golden("001-ring-keep-life-attack"), p, daily).reasons).toEqual(["unsupported_item"]);
  });

  it("a unique is looked up by name before the base is checked (decision 27)", () => {
    const u = golden("007-unique-ring-not-scored");
    u.item.base = "Nonexistent Ring";
    const v = scoreItem(u, patch, daily);
    expect(v.reasons).toEqual(["unique_price_lookup"]);
    expect(v.special_price_chaos).toBe(3);
  });

  it("fit comparisons allow an epsilon (decision 37)", () => {
    const exact = scoreItem(golden("001-ring-keep-life-attack"), patch, daily).fit as number;
    // keep_fit a hair above the true fit still passes (true fit is 0.60869...; 0.6086957 > it by < 1e-9 is not
    // representable here, so check the boundary from the other side): a threshold of the exact ratio passes.
    const trueFit = 0.7 / 1.15;
    const d = withThresholds({ keep_fit: trueFit + 5e-10 });
    expect(scoreItem(golden("001-ring-keep-life-attack"), patch, d).result).toBe("KEEP");
    expect(exact).toBeCloseTo(trueFit, 4);
  });

  it("a duplicated core stat id in a node counts once, with its highest demand_low (decision 37)", () => {
    const d = clone(daily);
    const mods = d.demand.Ring["arch:life-attack"].mods;
    const life = mods.find((m) => m.stat_id === "base_maximum_life")!;
    const before = scoreItem(golden("001-ring-keep-life-attack"), patch, d);
    mods.push({ ...life, demand_low: life.demand_low / 3 });
    expect(scoreItem(golden("001-ring-keep-life-attack"), patch, d).fit).toBe(before.fit);
  });
});

describe("id tie-breaks use code-point order", () => {
  it("compareIds orders by code point (\"-\" 45 before \"_\" 95, digits before letters)", () => {
    expect(compareIds("arch:x-y", "arch:x_y")).toBe(-1);
    expect(compareIds("arch:x_y", "arch:x-y")).toBe(1);
    expect(compareIds("a1", "a1")).toBe(0);
    expect(compareIds("arch:9", "arch:a")).toBe(-1);
    expect(compareIds("B", "a")).toBe(-1); // uppercase before lowercase, unlike most locales
  });

  it("equal-fit equal-account buyers: the smaller code-point id wins", () => {
    const d = JSON.parse(JSON.stringify(daily)) as DailyFile;
    for (const id of ["arch:tie_a", "arch:tie-a"]) {
      d.build_nodes.push({
        id,
        level: "archetype",
        parent: "all",
        label: id,
        accounts: 9000,
        effective_accounts: 9000,
        shown_on_own: true,
        low_data: false,
      });
      d.demand.Ring[id] = JSON.parse(JSON.stringify(d.demand.Ring["arch:life-attack"]));
    }
    const input = golden("001-ring-keep-life-attack");
    expect(scoreItem(input, patch, d).best_buyer).toBe("arch:tie-a");
  });
});

describe("marketDemand filters", () => {
  it("a main-skill filter uses only that node (decision 34)", () => {
    const rows = marketDemand(daily, "Ring", { node_id: "skill:lightning-strike" });
    expect(rows.length).toBeGreaterThan(0);
    expect(rows.every((r) => r.nodes.length === 1 && r.nodes[0] === "skill:lightning-strike")).toBe(true);
    const node = daily.build_nodes.find((n) => n.id === "skill:lightning-strike")!;
    const top = daily.demand.Ring["skill:lightning-strike"].mods[0];
    expect(rows.find((r) => r.stat_id === top.stat_id)!.demand).toBeCloseTo(top.demand * node.accounts, 6);
    expect(marketDemand(daily, "Ring", { node_id: "skill:missing" })).toEqual([]);
  });
});

describe("marketDemand", () => {
  it("sums archetype nodes only, demand x accounts", () => {
    const rows = marketDemand(daily, "Ring");
    const life = rows.find((r) => r.stat_id === "base_maximum_life")!;
    expect(life.nodes.every((n) => n.startsWith("arch:"))).toBe(true);
    expect(life.nodes).not.toContain("skill:lightning-strike");
    expect(life.nodes).not.toContain("all");
    const expected = daily.build_nodes
      .filter((n) => n.level === "archetype")
      .reduce((s, n) => {
        const m = daily.demand.Ring[n.id]?.mods.find((x) => x.stat_id === "base_maximum_life");
        return s + (m ? m.demand * n.accounts : 0);
      }, 0);
    expect(life.demand).toBeCloseTo(expected, 6);
    for (let i = 1; i < rows.length; i++) expect(rows[i - 1].demand).toBeGreaterThanOrEqual(rows[i].demand);
  });

  it("filters by node attributes and returns [] for an unknown class", () => {
    const es = marketDemand(daily, "Ring", { defence: "es" });
    expect(es.every((r) => r.nodes.every((n) => n === "arch:es-spell"))).toBe(true);
    expect(marketDemand(daily, "Nothing")).toEqual([]);
  });
});

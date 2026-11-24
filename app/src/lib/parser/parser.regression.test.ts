import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import type { PatchFile } from "../snapshot/types";
import { parseItem, ParseError } from "./index";

const fixtures = fileURLToPath(new URL("../../../../shared/fixtures/", import.meta.url));
const patch: PatchFile = JSON.parse(readFileSync(fixtures + "snapshot/patch.json", "utf8"));

/** Joins sections with the separator line. */
const doc = (...sections: string[]) => sections.join("\n--------\n");

const ring = (...extra: string[]) =>
  doc(
    "Item Class: Rings\nRarity: Rare\nGale Coil\nDiamond Ring",
    "Requirements:\nLevel: 67",
    "Item Level: 84",
    ...extra,
  );

const regalia = (...extra: string[]) =>
  doc("Item Class: Body Armours\nRarity: Rare\nGhoul Shroud\nVaal Regalia", "Item Level: 86", ...extra);

function codeOf(fn: () => unknown): string | null {
  try {
    fn();
    return null;
  } catch (e) {
    return e instanceof ParseError ? e.code : `other: ${String(e)}`;
  }
}

describe("open affixes", () => {
  it("counts a hybrid mod as one slot", () => {
    const r = parseItem(
      regalia(
        [
          `{ Prefix Modifier "Seraphim's" (Tier: 1) — Defences }`,
          "40(39-42)% increased Energy Shield",
          "16(16-17)% increased Stun and Block Recovery",
          `{ Prefix Modifier "Unfaltering" (Tier: 1) — Defences }`,
          "105(101-110)% increased Energy Shield",
        ].join("\n"),
      ),
      patch,
    );
    expect(r.mods).toHaveLength(3);
    expect(r.mods[0]).toMatchObject({
      stat_ids: ["local_energy_shield_+%"],
      values: [40],
      tier: 1,
      family: "prefix:LocalEnergyShieldAndStunRecoveryPercent",
    });
    expect(r.mods[1].family).toBe("prefix:LocalEnergyShieldAndStunRecoveryPercent");
    expect(r.item.open_prefixes).toBe(1);
    expect(r.item.open_suffixes).toBe(3);
  });

  it("counts a multi-line craft as one slot", () => {
    const r = parseItem(
      ring(
        [
          `{ Master Crafted Suffix Modifier "of Craft" (Rank: 3) — Resistance }`,
          "+12% to Cold Resistance (crafted)",
          "+12% to Fire Resistance (crafted)",
        ].join("\n"),
      ),
      patch,
    );
    expect(r.mods.map((m) => m.source)).toEqual(["crafted", "crafted"]);
    expect(r.mods[0]).toMatchObject({ affix: "suffix", tier: null, family: null });
    expect(r.item.open_suffixes).toBe(2);
    expect(r.item.open_prefixes).toBe(3);
  });
});

describe("base line prefixes", () => {
  it("strips Superior on a normal item", () => {
    const r = parseItem(
      doc("Item Class: Body Armours\nRarity: Normal\nSuperior Vaal Regalia", "Quality: +12%", "Item Level: 80"),
      patch,
    );
    expect(r.item).toMatchObject({ base: "Vaal Regalia", name: null, rarity: "Normal" });
    expect(r.item.open_prefixes).toBeUndefined();
  });

  it("strips Synthesised and sets the flag", () => {
    const r = parseItem(
      doc("Item Class: Amulets\nRarity: Rare\nDoom Beads\nSynthesised Onyx Amulet", "Item Level: 84"),
      patch,
    );
    expect(r.item).toMatchObject({ base: "Onyx Amulet", synthesised: true });
  });
});

describe("mod section details", () => {
  it("skips reminder text in parentheses", () => {
    const r = parseItem(
      ring(
        [
          `{ Prefix Modifier "Virile" (Tier: 1) — Life }`,
          "+108(100-114) to maximum Life",
          "(Some reminder text about life.)",
        ].join("\n"),
      ),
      patch,
    );
    expect(r.mods).toHaveLength(1);
    expect(r.unrecognised).toEqual([]);
  });

  it("reads enchants from header-less lines", () => {
    const r = parseItem(ring("10% increased Cast Speed (enchant)"), patch);
    expect(r.mods).toEqual([
      { source: "enchant", affix: null, stat_ids: ["base_cast_speed_+%"], values: [10], tier: null, family: null },
    ]);
  });

  it("reads reduced values as negative raw values", () => {
    const r = parseItem(
      ring(`{ Implicit Modifier — Speed }\n12% reduced Attack Speed (implicit)`),
      patch,
    );
    expect(r.mods[0]).toMatchObject({ stat_ids: ["attack_speed_+%"], values: [-12] });
  });

  it("returns unrecognised lines and keeps the known mods", () => {
    const r = parseItem(
      ring(
        [
          `{ Prefix Modifier "Virile" (Tier: 1) — Life }`,
          "+108(100-114) to maximum Life",
          `{ Suffix Modifier "of Nothing" (Tier: 1) }`,
          "+7(5-9) to Frobnication",
        ].join("\n"),
      ),
      patch,
    );
    expect(r.mods).toHaveLength(1);
    expect(r.unrecognised).toEqual(["+7(5-9) to Frobnication"]);
    expect(r.item.open_suffixes).toBe(2); // the unknown header still uses a slot
  });

  it("uses the mod name when the header tier is wrong, and flags the row", () => {
    const r = parseItem(
      ring([`{ Prefix Modifier "Virile" (Tier: 3) — Life }`, "+108(100-114) to maximum Life"].join("\n")),
      patch,
    );
    expect(r.mods[0]).toMatchObject({ tier: 1, family: "prefix:IncreasedLife", tier_mismatch: true });
  });

  it("puts a mod whose tier and name are both unknown into unrecognised", () => {
    const r = parseItem(
      ring([`{ Prefix Modifier "Nobody" (Tier: 99) — Life }`, "+108(100-114) to maximum Life"].join("\n")),
      patch,
    );
    expect(r.mods).toEqual([]);
    expect(r.unrecognised).toHaveLength(1);
  });
});

describe("items", () => {
  it("parses a magic item", () => {
    const r = parseItem(
      doc(
        "Item Class: Rings\nRarity: Magic\nVirile Diamond Ring of Haast",
        "Item Level: 84",
        `{ Prefix Modifier "Virile" (Tier: 1) — Life }\n+108(100-114) to maximum Life`,
      ),
      patch,
    );
    expect(r.item).toMatchObject({ rarity: "Magic", base: "Diamond Ring", name: null, open_prefixes: 0, open_suffixes: 1 });
  });

  it("reads influence lines", () => {
    const r = parseItem(ring("Hunter Item\nShaper Item"), patch);
    expect(r.item.influences).toEqual(["shaper", "hunter"]);
  });

  it("reads Mirrored", () => {
    expect(parseItem(ring("Mirrored"), patch).item.mirrored).toBe(true);
  });

  it("keeps a unique whose base is not in the patch", () => {
    const r = parseItem(
      doc(
        "Item Class: Belts\nRarity: Unique\nHeadhunter\nLeather Belt",
        "Item Level: 80",
        `{ Unique Modifier — Life }\n+60(40-60) to maximum Life`,
      ),
      patch,
    );
    expect(r).toEqual({
      item: {
        rarity: "Unique",
        item_class: "Belts",
        base: "Leather Belt",
        name: "Headhunter",
        ilvl: 80,
        corrupted: false,
        mirrored: false,
        fractured: false,
        synthesised: false,
        influences: [],
      },
      mods: [],
      unrecognised: [],
    });
  });

  it("maps the Item Class text of a unique to a known class", () => {
    const r = parseItem(
      doc("Item Class: Rings\nRarity: Unique\nSome Ring\nTopaz Ring", "Item Level: 80"),
      patch,
    );
    expect(r.item.item_class).toBe("Ring");
  });
});

describe("errors", () => {
  it.each([
    ["currency", "Item Class: Stackable Currency\nRarity: Currency\nDivine Orb\n--------\nStack Size: 1/10"],
    ["gem", "Item Class: Skill Gems\nRarity: Gem\nFireball\n--------\nLevel: 20"],
    ["flask", "Item Class: Utility Flasks\nRarity: Magic\nQuicksilver Flask of Heat\n--------\nItem Level: 80"],
    ["plain text", "buy milk"],
    ["colon text without a level", "Note: buy milk\n--------\nthen eggs\n--------\nthat is all"],
  ])("not_an_item for %s", (_label, text) => {
    expect(codeOf(() => parseItem(text, patch))).toBe("not_an_item");
  });

  it("unidentified", () => {
    expect(codeOf(() => parseItem(ring("Unidentified"), patch))).toBe("unidentified");
  });

  it("unsupported_language for a foreign copy with a level line", () => {
    const text = "Classe d'objet: Anneaux\nRareté: Rare\nA\nB\n--------\nNiveau de l'objet: 84\n--------\nx";
    expect(codeOf(() => parseItem(text, patch))).toBe("unsupported_language");
  });
});

describe("translations with display conversions", () => {
  const custom: PatchFile = {
    ...patch,
    translations: [
      ...patch.translations,
      {
        ids: ["base_life_regeneration_rate_per_minute"],
        english: [
          {
            string: "Regenerate {0} Life per second",
            format: ["#"],
            condition: [{ min: null, max: null, negated: null }],
            index_handlers: [["per_minute_to_per_second"]],
          },
        ],
      },
      {
        ids: ["fixture_extra_arrow"],
        english: [
          {
            string: "Bow Attacks fire an additional Arrow",
            format: [],
            condition: [{ min: 1, max: null, negated: null }],
            index_handlers: [],
          },
        ],
      },
      {
        ids: ["fixture_weird"],
        english: [
          {
            string: "Weird {0} thing",
            format: ["#"],
            condition: [{ min: null, max: null, negated: null }],
            index_handlers: [["canonical_line"]],
          },
        ],
      },
    ],
  };

  it("converts per-minute display values back to raw stat units", () => {
    const r = parseItem(ring(`{ Implicit Modifier — Life }\nRegenerate 1.5(1-2) Life per second (implicit)`), custom);
    expect(r.mods[0]).toMatchObject({ stat_ids: ["base_life_regeneration_rate_per_minute"], values: [90] });
  });

  it("matches text without a number literally, with min as the value (a lower bound)", () => {
    const r = parseItem(ring(`{ Implicit Modifier }\nBow Attacks fire an additional Arrow (implicit)`), custom);
    expect(r.mods[0]).toMatchObject({ stat_ids: ["fixture_extra_arrow"], values: [1] });
  });

  // Groups with hidden stats. The physical-damage group is RePoE 3.30 stat_translations.json's entry for
  // local_physical_damage_+% (English part only; local_weapon_no_physical_damage is never shown with a number).
  const hidden: PatchFile = {
    ...patch,
    translations: [
      ...patch.translations,
      {
        ids: ["local_physical_damage_+%", "local_weapon_no_physical_damage"],
        english: [
          {
            string: "No Physical Damage",
            format: ["ignore", "ignore"],
            condition: [{ min: null, max: null, negated: null }, { min: 1, max: null, negated: null }],
            index_handlers: [[], []],
          },
          {
            string: "No Physical Damage",
            format: ["ignore", "ignore"],
            condition: [{ min: null, max: null, negated: null }, { min: null, max: -1, negated: null }],
            index_handlers: [[], []],
          },
          {
            string: "No Physical Damage",
            format: ["ignore", "ignore"],
            condition: [{ min: null, max: -100, negated: null }, { min: null, max: null, negated: null }],
            index_handlers: [[], []],
          },
          {
            string: "{0}% increased Physical Damage",
            format: ["#", "ignore"],
            condition: [{ min: 1, max: null, negated: null }, { min: 0, max: 0, negated: null }],
            index_handlers: [[], []],
          },
          {
            string: "{0}% reduced Physical Damage",
            format: ["#", "ignore"],
            condition: [{ min: -99, max: -1, negated: null }, { min: 0, max: 0, negated: null }],
            index_handlers: [["negate"], []],
          },
        ],
      },
      {
        ids: ["fixture_on_kill_effect", "fixture_on_kill_hidden_zero"],
        english: [
          {
            string: "Grants a bonus on Kill",
            format: ["ignore", "ignore"],
            condition: [
              { min: 1, max: 1 },
              { min: 0, max: 0 },
            ],
            index_handlers: [[], []],
          },
        ],
      },
    ],
  };

  it("keeps only the visible stat of a group with a hidden stat", () => {
    const r = parseItem(ring(`{ Implicit Modifier }\n20(15-25)% increased Physical Damage (implicit)`), hidden);
    expect(r.mods).toHaveLength(1);
    expect(r.mods[0]).toMatchObject({ stat_ids: ["local_physical_damage_+%"], values: [20] });
    const rr = parseItem(ring(`{ Implicit Modifier }\n20% reduced Physical Damage (implicit)`), hidden);
    expect(rr.mods[0]).toMatchObject({ stat_ids: ["local_physical_damage_+%"], values: [-20] });
  });

  it("is ambiguous when same-text variants of a group name different stats (implicit)", () => {
    const r = parseItem(ring(`{ Implicit Modifier }
No Physical Damage (implicit)`), hidden);
    expect(r.mods).toEqual([]);
    expect(r.unrecognised).toEqual(["No Physical Damage (implicit)"]);
  });

  it("resolves same-text variants through the tier set", () => {
    // A decoy group with the same text as "maximum Life" comes first in RePoE order.
    const decoy: PatchFile = {
      ...patch,
      translations: [
        {
          ids: ["fixture_decoy_stat"],
          english: [
            {
              string: "{0} to maximum Life",
              format: ["+#"],
              condition: [{ min: null, max: null, negated: null }],
              index_handlers: [[]],
            },
          ],
        },
        ...patch.translations,
      ],
    };
    const r = parseItem(ring([`{ Prefix Modifier "Virile" (Tier: 1) — Life }`, "+108(100-114) to maximum Life"].join("\n")), decoy);
    expect(r.unrecognised).toEqual([]);
    expect(r.mods[0]).toMatchObject({ stat_ids: ["base_maximum_life"], family: "prefix:IncreasedLife" });
  });

  it("honours a negated condition: the value must lie outside the range", () => {
    const neg: PatchFile = {
      ...patch,
      translations: [
        ...patch.translations,
        {
          ids: ["fixture_neg"],
          english: [
            {
              string: "{0} to Negated",
              format: ["+#"],
              condition: [{ min: 5, max: 10, negated: true }],
              index_handlers: [[]],
            },
          ],
        },
      ],
    };
    expect(parseItem(ring("{ Implicit Modifier }\n+7 to Negated (implicit)"), neg).unrecognised).toHaveLength(1);
    expect(parseItem(ring("{ Implicit Modifier }\n+11 to Negated (implicit)"), neg).mods).toHaveLength(1);
    expect(parseItem(ring("{ Implicit Modifier }\n+4 to Negated (implicit)"), neg).mods).toHaveLength(1);
  });

  it("rejects a variant whose condition the value violates", () => {
    const cond: PatchFile = {
      ...patch,
      translations: [
        ...patch.translations,
        {
          ids: ["fixture_cond"],
          english: [
            {
              string: "{0} to Condition",
              format: ["+#"],
              condition: [{ min: 5, max: null, negated: null }],
              index_handlers: [[]],
            },
          ],
        },
      ],
    };
    expect(parseItem(ring("{ Implicit Modifier }\n+9 to Condition (implicit)"), cond).mods).toHaveLength(1);
    expect(parseItem(ring("{ Implicit Modifier }\n+3 to Condition (implicit)"), cond).unrecognised).toHaveLength(1);
  });

  it("drops a stat whose condition allows 0 from text without a number", () => {
    const r = parseItem(ring(`{ Implicit Modifier }\nGrants a bonus on Kill (implicit)`), hidden);
    expect(r.mods[0]).toMatchObject({ stat_ids: ["fixture_on_kill_effect"], values: [1] });
    for (const m of r.mods) expect(m.values).toHaveLength(m.stat_ids.length);
  });

  it("sends lines with an unsupported index handler to unrecognised", () => {
    const r = parseItem(ring(`{ Implicit Modifier }\nWeird 5 thing (implicit)`), custom);
    expect(r.mods).toEqual([]);
    expect(r.unrecognised).toEqual(["Weird 5 thing (implicit)"]);
  });
});

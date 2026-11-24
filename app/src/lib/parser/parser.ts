import type { PatchFamily, PatchFile, PatchTier } from "../snapshot/types";
import { ParseError } from "./errors";
import { matchStatLine, type StatMatch } from "./translations";
import { normalizeText, splitSections } from "./text";
import type { Influence, ModSource, ParsedItem, ParsedMod, ParseResult, Rarity } from "./types";

const RARITIES: readonly string[] = ["Normal", "Magic", "Rare", "Unique"];
const INFLUENCES: readonly Influence[] = ["shaper", "elder", "crusader", "redeemer", "hunter", "warlord"];

type TierSet = Record<string, PatchFamily>;

interface ModHeader {
  kind: "implicit" | "prefix" | "suffix" | "unique";
  crafted: boolean;
  name: string | null;
  tier: number | null;
}

type LineResult = { mod: ParsedMod } | { unrecognised: string };

function parseHeader(line: string): ModHeader | null {
  if (!line.startsWith("{") || !line.endsWith("}")) return null;
  const inner = line.slice(1, -1).trim();
  const kind = /Implicit Modifier/i.test(inner)
    ? "implicit"
    : /Prefix Modifier/i.test(inner)
      ? "prefix"
      : /Suffix Modifier/i.test(inner)
        ? "suffix"
        : /Unique Modifier/i.test(inner)
          ? "unique"
          : null;
  if (!kind) return null;
  const name = /"([^"]+)"/.exec(inner)?.[1] ?? null;
  const tier = /\(Tier:\s*(\d+)\)/i.exec(inner);
  return {
    kind,
    crafted: /Master Crafted/i.test(inner),
    name,
    tier: tier ? Number(tier[1]) : null,
  };
}

/** A non-English copy: no "Item Class:" / "Rarity:" line, but separators, a "Key: value" first line and a level-like line. */
function looksLikeForeignItem(text: string, sections: string[][]): boolean {
  if (sections.length < 3) return false;
  if (/^(Item Class|Rarity):/m.test(text)) return false;
  if (!/^[^:{}\d]{2,40}:\s*\S/.test(sections[0][0] ?? "")) return false;
  return /^[^:{}\d]{2,40}:\s*\d+\s*$/m.test(text);
}

function checkFirstLines(text: string, sections: string[][]): { rarity: Rarity; names: string[]; itemClassText: string } {
  const head = sections[0] ?? [];
  const first = head[0] ?? "";
  if (!/^Item Class: /.test(first) || !/^Rarity: /.test(head[1] ?? "")) {
    if (looksLikeForeignItem(text, sections)) throw new ParseError("unsupported_language", `first line "${first}"`);
    throw new ParseError("not_an_item", "no Item Class / Rarity header");
  }
  const rarity = head[1].slice("Rarity: ".length).trim();
  if (!RARITIES.includes(rarity)) throw new ParseError("not_an_item", `rarity "${rarity}"`);
  return { rarity: rarity as Rarity, names: head.slice(2), itemClassText: first.slice("Item Class: ".length).trim() };
}

/** "Superior Vaal Regalia" (quality) and "Synthesised Onyx Amulet" carry a prefix the base lookup must not see. */
function stripBasePrefix(line: string): { base: string; synthesised: boolean } {
  let base = line.trim();
  let synthesised = false;
  for (;;) {
    if (base.startsWith("Superior ")) base = base.slice("Superior ".length);
    else if (base.startsWith("Synthesised ")) {
      base = base.slice("Synthesised ".length);
      synthesised = true;
    } else break;
  }
  return { base, synthesised };
}

function findBase(
  patch: PatchFile,
  rarity: Rarity,
  names: string[],
): { base: string; name: string | null; synthesised: boolean } {
  if (rarity === "Rare" || rarity === "Unique") {
    if (names.length < 2) throw new ParseError("not_an_item", "name and base lines missing");
    return { name: names[0], ...stripBasePrefix(names[1]) };
  }
  if (rarity === "Normal") {
    if (names.length < 1) throw new ParseError("not_an_item", "base line missing");
    return { name: null, ...stripBasePrefix(names[0]) };
  }
  // Magic: "<prefix> <base> <of suffix>": longest known base contained in the name line.
  const line = names[0] ?? "";
  let best = "";
  for (const b of Object.keys(patch.bases)) if (b.length > best.length && line.includes(b)) best = b;
  if (!best) throw new ParseError("not_an_item", `unknown base in "${line}"`);
  return { name: null, base: best, synthesised: /^Synthesised /.test(line) };
}

/** Item class key for an item whose base is not in the patch (uniques): from the "Item Class:" text if known, else the raw text. */
function itemClassFromText(patch: PatchFile, base: string, text: string): string {
  const known = patch.bases[base]?.item_class;
  if (known) return known;
  for (const [key, c] of Object.entries(patch.item_classes)) {
    if (text === key || text === c.label || text === c.poere_basetype || text === `${c.label}s`) return key;
  }
  return text;
}

interface Hit {
  key: string;
  match: StatMatch;
  tier: PatchTier;
  mismatch: boolean;
}

/** Families of the tier set that can roll a matched stat, found by (affix, tier, name), then by name alone. */
function resolveFamily(
  tierSet: TierSet,
  matches: StatMatch[],
  affix: "prefix" | "suffix",
  header: ModHeader,
): Hit[] {
  const strict: Hit[] = [];
  const byName: Hit[] = [];
  for (const [key, fam] of Object.entries(tierSet)) {
    if (fam.affix !== affix) continue;
    for (const m of matches) {
      if (!m.stat_ids.every((id) => fam.stat_ids.includes(id))) continue;
      if (header.tier !== null) {
        const t = fam.tiers.find((x) => x.tier === header.tier);
        if (t && (!t.name || !header.name || t.name === header.name)) strict.push({ key, match: m, tier: t, mismatch: false });
      }
      if (header.name) {
        const t = fam.tiers.find((x) => x.name === header.name);
        if (t) byName.push({ key, match: m, tier: t, mismatch: true });
      }
    }
  }
  return strict.length ? strict : byName;
}

/** Tie-break between several possible families: the header's roll range, in raw units, must equal the tier's range. */
function filterByRange(hits: Hit[]): Hit[] {
  return hits.filter((h) =>
    h.match.stat_ids.every((id, i) => {
      const range = h.match.ranges[i];
      const stat = h.tier.stats.find((s) => s.id === id);
      if (!range || !stat) return false;
      // Shown numbers are rounded for display: allow one display step, in raw units.
      const tol = h.match.range_tolerance[i] + 1e-9;
      return Math.abs(range[0] - stat.min) <= tol && Math.abs(range[1] - stat.max) <= tol;
    }),
  );
}

export function parseItem(rawText: string, patch: PatchFile): ParseResult {
  const text = normalizeText(rawText);
  if (!text) throw new ParseError("not_an_item", "empty text");
  const sections = splitSections(text);
  const { rarity, names, itemClassText } = checkFirstLines(text, sections);

  if (sections.some((s) => s.includes("Unidentified"))) throw new ParseError("unidentified");

  const found = findBaseOrUnique(patch, rarity, names);
  const { base, name } = found;

  let itemClass: string;
  let tierSet: TierSet = {};
  let classInfo: PatchFile["item_classes"][string] | undefined;
  const baseInfo = patch.bases[base];
  if (rarity === "Unique") {
    itemClass = itemClassFromText(patch, base, itemClassText);
  } else {
    if (!baseInfo) throw new ParseError("not_an_item", `unknown base "${base}"`);
    itemClass = baseInfo.item_class;
    classInfo = patch.item_classes[itemClass];
    if (!classInfo) throw new ParseError("not_an_item", `unknown item class "${itemClass}"`);
    tierSet = patch.tier_sets[baseInfo.tier_set] ?? {};
  }

  let ilvl: number | null = null;
  let corrupted = false;
  let mirrored = false;
  let fracturedFlag = false;
  let synthesised = found.synthesised;
  const influences = new Set<Influence>();
  const mods: ParsedMod[] = [];
  const unrecognised: string[] = [];
  const slots = { prefix: 0, suffix: 0 };

  const take = (r: LineResult) => ("mod" in r ? mods.push(r.mod) : unrecognised.push(r.unrecognised));

  for (const section of sections.slice(1)) {
    if (!parseHeader(section[0])) {
      // Properties, requirements, sockets, placement text, flavour: only flags, item level and enchants are used.
      for (const line of section) {
        const lvl = /^Item Level: (\d+)$/.exec(line);
        if (lvl) ilvl = Number(lvl[1]);
        else if (line === "Corrupted") corrupted = true;
        else if (line === "Mirrored") mirrored = true;
        else if (line === "Fractured Item") fracturedFlag = true;
        else if (line === "Synthesised Item") synthesised = true;
        else if (/\s\(enchant\)$/.test(line)) {
          if (rarity !== "Unique") {
            take(parseModLine(line, { kind: "implicit", crafted: false, name: null, tier: null }, patch, base, tierSet));
          }
        } else {
          const inf = /^(\w+) Item$/.exec(line)?.[1]?.toLowerCase() as Influence | undefined;
          if (inf && INFLUENCES.includes(inf)) influences.add(inf);
        }
      }
      continue;
    }
    if (rarity === "Unique") continue; // uniques: item only, mods []

    let header: ModHeader | null = null;
    for (const line of section) {
      const h = parseHeader(line);
      if (h) {
        header = h;
        // One affix slot per header, however many lines (hybrids, multi-line crafts) follow it.
        if (h.kind === "prefix" || h.kind === "suffix") slots[h.kind]++;
        continue;
      }
      if (!header) continue;
      if (/^\(.*\)$/.test(line)) continue; // reminder text
      take(parseModLine(line, header, patch, base, tierSet));
    }
  }

  if (ilvl === null) throw new ParseError("not_an_item", "no Item Level line");

  // Corrupted items: implicits the base does not have are corruption implicits.
  const baseImplicits = baseInfo?.implicit_stat_ids ?? [];
  for (const m of mods) {
    if (m.source === "implicit" && corrupted && !m.stat_ids.every((id) => baseImplicits.includes(id))) {
      m.source = "corruption_implicit";
    }
  }

  const item: ParsedItem = {
    rarity,
    item_class: itemClass,
    base,
    name,
    ilvl,
    corrupted,
    mirrored,
    fractured: fracturedFlag || mods.some((m) => m.source === "fractured"),
    synthesised,
    influences: INFLUENCES.filter((i) => influences.has(i)),
  };

  if (classInfo && (rarity === "Rare" || rarity === "Magic")) {
    const maxP = rarity === "Magic" ? Math.min(1, classInfo.max_prefixes) : classInfo.max_prefixes;
    const maxS = rarity === "Magic" ? Math.min(1, classInfo.max_suffixes) : classInfo.max_suffixes;
    item.open_prefixes = Math.max(0, maxP - slots.prefix);
    item.open_suffixes = Math.max(0, maxS - slots.suffix);
  }

  return { item, mods, unrecognised };
}

function findBaseOrUnique(patch: PatchFile, rarity: Rarity, names: string[]) {
  if (rarity === "Unique") {
    // Uniques skip the patch lookup: the base is taken as written.
    if (names.length < 1) throw new ParseError("not_an_item", "name line missing");
    if (names.length < 2) return { name: null, ...stripBasePrefix(names[0]) };
    return { name: names[0], ...stripBasePrefix(names[1]) };
  }
  return findBase(patch, rarity, names);
}

function parseModLine(rawLine: string, header: ModHeader, patch: PatchFile, base: string, tierSet: TierSet): LineResult {
  let line = rawLine;
  let suffix: string | null = null;
  const sfx = /\s+\((implicit|fractured|crafted|enchant)\)$/.exec(line);
  if (sfx) {
    suffix = sfx[1];
    line = line.slice(0, sfx.index);
  }
  const bad: LineResult = { unrecognised: rawLine };

  const matches = matchStatLine(patch, line);
  if (matches.length === 0) return bad;

  let source: ModSource;
  if (suffix === "implicit" || (header.kind === "implicit" && !suffix)) source = "implicit";
  else if (suffix === "fractured") source = "fractured";
  else if (suffix === "crafted" || header.crafted) source = "crafted";
  else if (suffix === "enchant") source = "enchant";
  else source = "explicit";

  const affix: "prefix" | "suffix" | null =
    header.kind === "prefix" || header.kind === "suffix" ? header.kind : null;

  if (source === "implicit" || source === "enchant" || affix === null) {
    // No tier ladder for these. Prefer the stat the base is known to roll as its implicit.
    const implicitIds = patch.bases[base]?.implicit_stat_ids ?? [];
    let pool = matches.filter((m) => m.stat_ids.every((id) => implicitIds.includes(id)));
    if (pool.length === 0) pool = matches;
    if (pool.length > 1) return bad;
    return { mod: { source, affix: null, stat_ids: pool[0].stat_ids, values: pool[0].values, tier: null, family: null } };
  }

  if (source === "crafted") {
    const inSet = matches.filter((m) =>
      Object.values(tierSet).some((f) => f.affix === affix && m.stat_ids.every((id) => f.stat_ids.includes(id))),
    );
    const pool = inSet.length ? inSet : matches;
    if (pool.length > 1) return bad;
    return { mod: { source, affix, stat_ids: pool[0].stat_ids, values: pool[0].values, tier: null, family: null } };
  }

  // explicit / fractured: tier from the header, cross-checked against the base's tier set (by name, in raw units).
  let hits = resolveFamily(tierSet, matches, affix, header);
  if (hits.length > 1) hits = filterByRange(hits);
  if (hits.length !== 1) return bad;
  const hit = hits[0];
  const mod: ParsedMod = {
    source,
    affix,
    stat_ids: hit.match.stat_ids,
    values: hit.match.values,
    tier: hit.tier.tier,
    family: hit.key,
  };
  if (hit.mismatch) mod.tier_mismatch = true;
  return { mod };
}

import handlerTable from "../../../../shared/stat-handlers.json";
import type { PatchFile } from "../snapshot/types";
import { escapeRegExp } from "./text";

// One placeholder: the value, then an optional roll range "(min-max)" (advanced format).
const PLACEHOLDER = String.raw`([+-]?\d+(?:\.\d+)?)(?:\((-?\d+(?:\.\d+)?)-(-?\d+(?:\.\d+)?)\))?`;
const PLACEHOLDER_GROUPS = 3;

/**
 * RePoE index handlers turn a raw stat value into the number shown in the text. The shared table
 * shared/stat-handlers.json (also used by the backend) says how to undo each one; every inverse is a
 * multiplication, so the inverses of an entry's handlers collapse into one factor. A handler that is
 * not in the table makes the whole translation entry unusable: its lines end up in `unrecognised`.
 */
interface HandlerEntry {
  op: string;
  by?: number;
}
const INVERSE = handlerTable.inverse as Record<string, HandlerEntry>;

function factorOf(handlers: string[]): number | null {
  let f = 1;
  for (const h of handlers) {
    const e = INVERSE[h];
    if (!e) return null;
    if (e.op === "multiply" && typeof e.by === "number") f *= e.by;
    else if (e.op !== "identity") return null;
  }
  return f;
}

/** Raw stat values are integers: round the converted display value. */
const toRaw = (v: number, factor: number) => {
  const r = Math.round(v * factor);
  return r === 0 ? 0 : r; // no -0
};

const decimalsOf = (shown: string) => shown.split(".")[1]?.length ?? 0;

/** RePoE condition on a raw value; `negated` flips it (the value must then lie OUTSIDE [min, max]). */
function conditionHolds(c: { min?: number | null; max?: number | null; negated?: boolean | null }, v: number): boolean {
  const inside = (c.min == null || v >= c.min) && (c.max == null || v <= c.max);
  return c.negated ? !inside : inside;
}

interface Matcher {
  /** Index of the translation group (RePoE order); variants of one group share it. */
  group: number;
  regex: RegExp;
  /** Stat IDs of the mod: only those the text shows (see buildMatchers). */
  ids: string[];
  /** For each kept stat: index of its capture slot, or -1 for a fixed value. */
  slot: number[];
  /** Per capture slot: factor from displayed number to raw stat value. */
  factor: number[];
  /** Fixed values for text without a number (condition.min), per kept stat. */
  fixed?: number[];
  /** RePoE condition per kept stat: the raw value must lie within it for this text variant to apply. */
  cond: { min?: number | null; max?: number | null; negated?: boolean | null }[];
}

export interface StatMatch {
  /** Translation group (RePoE order). Variants of one group with the same text can name different stats. */
  group: number;
  /** Only the stats the text shows; same length as values. */
  stat_ids: string[];
  /** Raw stat units (integers), same order as stat_ids. */
  values: number[];
  /** Roll range per value in raw units, null where the text has no range. */
  ranges: ([number, number] | null)[];
  /** Tolerance per range: one display step in raw units. */
  range_tolerance: number[];
}

const cache = new WeakMap<PatchFile, Matcher[]>();

function buildMatchers(patch: PatchFile): Matcher[] {
  const out: Matcher[] = [];
  patch.translations.forEach((t, group) => {
    for (const e of t.english) {
      const handlers = e.index_handlers ?? [];
      const factors: number[] = [];
      let usable = true;
      t.ids.forEach((_, i) => {
        const f = factorOf(handlers[i] ?? []);
        if (f === null) usable = false;
        factors[i] = f ?? 1;
      });
      if (!usable) continue;

      const parts = e.string.split(/\{(\d+)\}/);
      let src = "^";
      const slotOfId = new Map<number, number>(); // stat index -> capture slot
      const slotFactor: number[] = [];
      for (let i = 0; i < parts.length; i++) {
        if (i % 2 === 0) {
          src += escapeRegExp(parts[i]);
          continue;
        }
        const idx = Number(parts[i]);
        if (e.format[idx] === "ignore") continue; // not shown in the text
        slotOfId.set(idx, slotFactor.length);
        slotFactor.push(factors[idx] ?? 1);
        src += PLACEHOLDER;
      }
      src += "$";

      // Hidden stats: a translation group can hold stats the text does not show.
      // With visible numbers, only stats with a visible {n} (format not "ignore") belong to the mod.
      // Without any number, a stat belongs to the mod only if its condition excludes 0 (min > 0 or
      // max < 0); its value is min when min > 0 (a lower bound if max differs or is null), else max.
      // Stats whose condition allows 0 are hidden. (shared/stat-handlers.json, rules)
      const keep: number[] = [];
      const fixed: number[] = [];
      if (slotFactor.length > 0) {
        t.ids.forEach((_, i) => {
          if (slotOfId.has(i)) keep.push(i);
        });
      } else {
        t.ids.forEach((_, i) => {
          const c = e.condition[i];
          if (!c) return;
          if (typeof c.min === "number" && c.min > 0) {
            keep.push(i);
            fixed.push(c.min);
          } else if (typeof c.max === "number" && c.max < 0) {
            keep.push(i);
            fixed.push(c.max);
          }
        });
      }
      if (keep.length === 0) continue;

      out.push({
        group,
        regex: new RegExp(src),
        ids: keep.map((i) => t.ids[i]),
        slot: keep.map((i) => slotOfId.get(i) ?? -1),
        factor: slotFactor,
        fixed: slotFactor.length === 0 ? fixed : undefined,
        cond: keep.map((i) => e.condition[i] ?? {}),
      });
    }
  });
  return out;
}

/**
 * Every distinct stat-ID set whose English text matches `line` (a mod line without its
 * "(implicit)" / "(fractured)" / ... suffix; roll ranges allowed).
 *
 * Text with no number (e.g. "Bow Attacks fire an additional Arrow") gets its value from the translation's
 * condition: min when min > 0 (a lower bound if max differs), else max. Fine for on/off stats.
 */
export function matchStatLine(patch: PatchFile, line: string): StatMatch[] {
  let matchers = cache.get(patch);
  if (!matchers) {
    matchers = buildMatchers(patch);
    cache.set(patch, matchers);
  }
  const found = new Map<string, StatMatch>();
  for (const m of matchers) {
    const r = m.regex.exec(line);
    if (!r) continue;
    const values: number[] = [];
    const ranges: ([number, number] | null)[] = [];
    const range_tolerance: number[] = [];
    m.ids.forEach((_, k) => {
      const slot = m.slot[k];
      if (m.fixed) {
        values.push(m.fixed[k]);
        ranges.push(null);
        range_tolerance.push(0);
        return;
      }
      const g = 1 + slot * PLACEHOLDER_GROUPS;
      const factor = m.factor[slot];
      values.push(toRaw(parseFloat(r[g]), factor));
      const lo = r[g + 1];
      const hi = r[g + 2];
      if (lo !== undefined && hi !== undefined) {
        const a = toRaw(parseFloat(lo), factor);
        const b = toRaw(parseFloat(hi), factor);
        ranges.push([Math.min(a, b), Math.max(a, b)]);
      } else ranges.push(null);
      range_tolerance.push(Math.abs(factor) * 10 ** -Math.max(decimalsOf(r[g]), decimalsOf(lo ?? ""), decimalsOf(hi ?? "")));
    });
    // A variant whose condition the value violates is not the text the game shows for it.
    if (values.some((v, k) => !conditionHolds(m.cond[k], v))) continue;
    // Same stat set from several variants: the first in RePoE order wins. Different stat sets stay separate
    // candidates for the caller (tier-set family, base implicits) to narrow down.
    const key = m.ids.join("|");
    if (!found.has(key)) found.set(key, { group: m.group, stat_ids: [...m.ids], values, ranges, range_tolerance });
  }
  return [...found.values()];
}

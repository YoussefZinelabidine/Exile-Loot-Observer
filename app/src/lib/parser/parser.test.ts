import { readdirSync, readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import type { GoldenExpectedFile, PatchFile } from "../snapshot/types";
import { parseItem, ParseError } from "./index";

const fixtures = fileURLToPath(new URL("../../../../shared/fixtures/", import.meta.url));
const patch: PatchFile = JSON.parse(readFileSync(fixtures + "snapshot/patch.json", "utf8"));

const goldenDirs = readdirSync(fixtures + "golden", { withFileTypes: true })
  .filter((d) => d.isDirectory())
  .map((d) => d.name)
  .sort();

function load(dir: string) {
  const game = readFileSync(`${fixtures}golden/${dir}/game.txt`, "utf8");
  const expected: GoldenExpectedFile = JSON.parse(readFileSync(`${fixtures}golden/${dir}/expected.json`, "utf8"));
  return { game, expected };
}

function codeOf(fn: () => unknown): string | null {
  try {
    fn();
    return null;
  } catch (e) {
    return e instanceof ParseError ? e.code : `other: ${String(e)}`;
  }
}

describe("golden items", () => {
  it("finds the seed items", () => {
    expect(goldenDirs.length).toBeGreaterThanOrEqual(9);
  });

  for (const dir of goldenDirs) {
    const { game, expected } = load(dir);
    if (!expected.forms.includes("game")) continue;
    const lf = game.replace(/\r\n/g, "\n");

    for (const [label, text] of [
      ["LF", lf],
      ["CRLF", lf.replace(/\n/g, "\r\n")],
    ] as const) {
      it(`${dir} (${label})`, () => {
        if (expected.item === null) {
          expect(codeOf(() => parseItem(text, patch))).toBe(
            expected.verdict.result === "UNSUPPORTED_LANGUAGE" ? "unsupported_language" : "not_an_item",
          );
          return;
        }
        const got = parseItem(text, patch);
        expect(got.item).toEqual(expected.item);
        // `qualifies` is the scoring engine's tier-gate result, not parser output.
        const want = expected.mods.map((m) => {
          const rest: Record<string, unknown> = { ...m };
          delete rest.qualifies;
          return rest;
        });
        // Mods are compared as a multiset (order ignored).
        const key = (m: object) => JSON.stringify(m);
        const gotMods = got.mods.map((m) => {
          const rest: Record<string, unknown> = { ...m };
          delete rest.tier_mismatch; // internal flag, not part of the golden shape
          return rest;
        });
        expect(gotMods.map(key).sort()).toEqual(want.map(key).sort());
        expect(got.unrecognised).toEqual(expected.unrecognised ?? []);
      });
    }
  }
});

describe("errors", () => {
  it("not_an_item for plain text", () => {
    expect(codeOf(() => parseItem("hello world", patch))).toBe("not_an_item");
  });

  it("not_an_item for empty text", () => {
    expect(codeOf(() => parseItem("  \r\n", patch))).toBe("not_an_item");
  });

  it("an unknown stat text is unrecognised, not an error", () => {
    const { game } = load("001-ring-keep-life-attack");
    const r = parseItem(game.replace("to Fire Resistance", "to Frobnication"), patch);
    expect(r.unrecognised).toEqual(["+47(46-48)% to Frobnication"]);
    expect(r.mods).toHaveLength(4);
  });
});

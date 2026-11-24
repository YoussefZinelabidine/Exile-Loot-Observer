import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { generate, outputPath } from "../../../scripts/gen-types.mjs";

describe("generated snapshot types", () => {
  it("types.generated.ts is up to date with shared/schema (run `pnpm gen:types`)", async () => {
    const committed = readFileSync(outputPath, "utf8").replace(/\r\n/g, "\n");
    expect(committed).toBe(await generate());
  });
});

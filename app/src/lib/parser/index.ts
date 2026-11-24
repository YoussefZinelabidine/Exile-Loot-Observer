// Item text parser: clipboard text (advanced format) in, the `item` and `mods` shape of the golden
// expected.json out, or a typed ParseError. Types for the patch file come from ../snapshot/types.
export { parseItem } from "./parser";
export { ParseError, type ParseErrorCode } from "./errors";
export type { ParsedItem, ParsedMod, ParseResult, Rarity, Influence, ModSource } from "./types";

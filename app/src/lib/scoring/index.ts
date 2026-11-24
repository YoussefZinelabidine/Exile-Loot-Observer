// Item scoring (rules R1-R10 in shared/fixtures/README.md) and market demand. Pure functions, no I/O.
export { scoreItem } from "./score";
export { marketDemand } from "./market";
export type { Verdict, VerdictResult, VerdictReason, MarketDemandFilter, MarketDemandRow } from "./types";

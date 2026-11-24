// Friendly names for the generated snapshot types (types.generated.ts, from shared/schema).
// Readers ignore unknown fields (schema README), so these types describe only what the schemas declare.
import type { Daily, GoldenExpected, Manifest, Patch } from "./types.generated";

export type { Daily, GoldenExpected, Manifest, Patch };

export type PatchFile = Patch.ELOPatchFile;
export type DailyFile = Daily.ELODailyFile;
export type ManifestFile = Manifest.ELOSnapshotManifest;
export type GoldenExpectedFile = GoldenExpected.ELOGoldenItemExpectedResults;

export type PatchBase = Patch.Base;
export type PatchItemClass = Patch.ItemClass;
export type PatchTierSet = Patch.TierSet;
export type PatchFamily = Patch.Family;
export type PatchTier = Patch.Tier;
export type PatchTranslation = Patch.Translation;

export type DailyBuildNode = Daily.BuildNode;
export type DailyNodeDemand = Daily.NodeDemand;
export type DailyModDemand = Daily.ModDemand;
export type DailyThresholds = Daily.Thresholds;
export type DailyBaseValue = Daily.BaseValue;
export type DailySpecialPrice = Daily.SpecialPrice;

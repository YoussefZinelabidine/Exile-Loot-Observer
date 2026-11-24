"""Scoring types: same shapes as ``app/src/lib/scoring/types.ts``."""

from typing import Any, Literal, NotRequired, TypedDict

VerdictResult = Literal["KEEP", "PRICE_CHECK", "NO_BUYER", "NOT_SCORED"]

VerdictReason = Literal[
    "keep_fit",
    "partial_fit",
    "niche_build_fit",
    "no_fit",
    "boost_base_value",
    "boost_crafting_potential",
    "boost_fractured_core_mod",
    "cap_low_data",
    "cap_not_validated",
    "corrupted_open_slots_ignored",
    "unique_price_lookup",
    "unsupported_item",
    "cluster_jewel_price_lookup",
    "unrecognised_mods",
]


class Verdict(TypedDict):
    """Same shape as ``verdict`` in a golden ``expected.json``."""

    result: VerdictResult
    best_buyer: str | None
    fit: float | None  # best buyer's fit rounded to 4 decimals; None when not scored
    low_data: bool
    reasons: list[str]
    counted_stat_ids: list[str]
    special_price_chaos: NotRequired[float | None]  # price lookup only (uniques)


class MarketDemandFilter(TypedDict, total=False):
    """What to farm filter (decision 34): ``defence`` / ``damage`` / ``node_id``."""

    defence: Literal["life", "es", "hybrid"]
    damage: Literal["attack", "spell", "minion", "dot"]
    node_id: str


class MarketDemandRow(TypedDict):
    stat_id: str
    demand: float  # sum over archetype nodes b of demand(stat, b) x accounts_b
    nodes: list[str]


# Inputs are plain JSON-shaped dicts (or the pydantic Patch / Daily models, converted on entry).
PlainDict = dict[str, Any]

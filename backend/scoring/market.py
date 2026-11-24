"""Market demand for "What to farm" (mirror of ``app/src/lib/scoring/market.ts``).

Sum over ARCHETYPE nodes b of demand x accounts_b, so no player is counted twice. A main-skill
filter (``node_id``) uses only that node (decision 34). Sorted by demand, highest first.
"""

from functools import cmp_to_key
from typing import Any

from backend.scoring.plain import to_plain
from backend.scoring.score import str_cmp
from backend.scoring.types import MarketDemandFilter, MarketDemandRow


def market_demand(
    daily: Any, item_class: str, node_filter: MarketDemandFilter | None = None
) -> list[MarketDemandRow]:
    daily = to_plain(daily)
    flt = node_filter or {}
    by_node = daily["demand"].get(item_class) or {}
    rows: dict[str, MarketDemandRow] = {}
    nodes = daily["build_nodes"]
    picked = None
    if flt.get("node_id"):
        picked = next((n for n in nodes if n["id"] == flt["node_id"]), None)
        if picked is None or picked["level"] == "all":
            return []
    for node in nodes:
        if picked is not None:
            # A main-skill (or single archetype) filter uses only that node.
            if node["id"] != picked["id"]:
                continue
        elif node["level"] != "archetype":
            continue
        if flt.get("defence") and node.get("defence") != flt["defence"]:
            continue
        if flt.get("damage") and node.get("damage") != flt["damage"]:
            continue
        node_demand = by_node.get(node["id"])
        if not node_demand:
            continue
        for mod in node_demand["mods"]:
            if mod["demand"] <= 0:
                continue
            row = rows.setdefault(
                mod["stat_id"], {"stat_id": mod["stat_id"], "demand": 0, "nodes": []}
            )
            row["demand"] += mod["demand"] * node["accounts"]
            row["nodes"].append(node["id"])

    def by_demand(a: MarketDemandRow, b: MarketDemandRow) -> float:
        return (b["demand"] - a["demand"]) or str_cmp(a["stat_id"], b["stat_id"])

    return sorted(rows.values(), key=cmp_to_key(by_demand))

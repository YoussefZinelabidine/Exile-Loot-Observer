"""Item scoring (rules R1-R10 in shared/fixtures/README.md, decisions 18-37).

Python twin of ``app/src/lib/scoring/score.ts``: same steps, same tie-breaks, same sub-rules, so
a parity test can run both on the same inputs. Pure functions, no I/O.
"""

import math
from functools import cmp_to_key
from typing import Any

from backend.scoring.plain import to_plain
from backend.scoring.types import Verdict

# TODO(stale-snapshot-cap): cap at PRICE CHECK with a low-data marker when crawl_date is older than
#   params.stale_after_days. No rule yet (owner: do not implement).
# TODO(item-flags): influenced / synthesised / mirrored / double-corrupted items have no rule
#   yet. (Mirrored only blocks the crafting boost, as R7 says; influences only keep the base-value
#   lookup to un-influenced base prices.)
# TODO(cluster-jewels): cluster jewel detection and price key are decided later (decision 33); for
#   now a class marked scored:false is NOT_SCORED / unsupported_item.
# TODO(corruption-implicits): corruption implicits as extra mods have no rule yet; they are
#   ignored here.


def str_cmp(a: str, b: str) -> int:
    """Plain code-point order for id tie-breaks (the app uses the same, no locale collation)."""
    return (a > b) - (a < b)


# Comparisons use ``value >= threshold - EPS`` (decision 37).
EPS = 1e-9


def round4(x: float) -> float:
    """JavaScript ``Math.round(x * 1e4) / 1e4`` (halves go up)."""
    return math.floor(x * 1e4 + 0.5) / 1e4


class _Candidate:
    def __init__(
        self,
        node: dict[str, Any],
        fit: float,
        counted: list[str],
        affixes: int,
        core_stats: set[str],
    ):
        self.node = node
        self.fit = fit
        self.counted = counted
        # Distinct affixes (a hybrid affix counts once) holding a counted core stat: "at least two
        # core mods" means this (decision 29).
        self.affixes = affixes
        self.core_stats = core_stats


class _Need:
    """``need(v)``: reads a threshold and remembers that a needed one was null."""

    def __init__(self) -> None:
        self.null_threshold = False

    def __call__(self, value: Any) -> Any:
        if value is None:
            self.null_threshold = True
            return None
        return value


def _parsed(parsed: Any) -> tuple[dict[str, Any], list[dict[str, Any]], list[str]]:
    """Accepts ``{"item", "mods", "unrecognised"?}`` or an object with ``to_expected()``."""
    if hasattr(parsed, "to_expected"):
        parsed = parsed.to_expected()
    return parsed["item"], list(parsed["mods"]), list(parsed.get("unrecognised") or [])


def _thresholds_for(daily: dict[str, Any], item_class: str) -> dict[str, Any]:
    thresholds = daily["params"]["thresholds"]
    merged = dict(thresholds["default"])
    over = (thresholds.get("by_item_class") or {}).get(item_class) or {}
    merged.update(over)
    return merged


def _qualifying(
    mods: list[dict[str, Any]], patch: dict[str, Any], daily: dict[str, Any], tier_set_key: str
) -> list[bool]:
    """R1: tier gate. Explicit and fractured mods only; implicits and crafts never qualify."""
    tier_set = patch["tier_sets"].get(tier_set_key) or {}
    gate = daily["params"]["tier_gate"]
    out = []
    for mod in mods:
        ok = False
        if (
            mod["source"] in ("explicit", "fractured")
            and mod.get("tier") is not None
            and mod.get("family")
        ):
            family = tier_set.get(mod["family"])
            ladder = len(family["tiers"]) if family else 0
            if ladder:
                limit = max(
                    gate["always_top_tiers"], math.ceil(gate["top_fraction"] * ladder - 1e-9)
                )
                ok = mod["tier"] <= limit
        out.append(ok)
    return out


def _unique_price(daily: dict[str, Any], name: str | None) -> float | None:
    entries = [
        e
        for e in (daily.get("special_prices") or [])
        if e.get("kind") == "unique" and e.get("name") == name
    ]
    # Several variants of one name: prefer the plain one (no variant, no links), else the first.
    plain = next((e for e in entries if not e.get("variant") and not e.get("links")), None)
    chosen = plain if plain is not None else (entries[0] if entries else None)
    return None if chosen is None else chosen.get("chaos")


def _core_mods(mods: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Core mods of a node, highest demand_low first (ties by stat id).

    A duplicated stat id counts once, with its highest demand_low (decision 37).
    """
    best: dict[str, dict[str, Any]] = {}
    for mod in mods:
        if not mod.get("core"):
            continue
        prev = best.get(mod["stat_id"])
        if prev is None or mod["demand_low"] > prev["demand_low"]:
            best[mod["stat_id"]] = mod

    def order(a: dict[str, Any], b: dict[str, Any]) -> float:
        return (b["demand_low"] - a["demand_low"]) or str_cmp(a["stat_id"], b["stat_id"])

    return sorted(best.values(), key=cmp_to_key(order))


def _with_unrecognised(reasons: list[str], unrecognised: list[str]) -> list[str]:
    # R10
    return [*reasons, "unrecognised_mods"] if unrecognised else reasons


def _not_scored(reason: str, unrecognised: list[str]) -> Verdict:
    return {
        "result": "NOT_SCORED",
        "best_buyer": None,
        "fit": None,
        "low_data": False,
        "reasons": _with_unrecognised([reason], unrecognised),
        "counted_stat_ids": [],
    }


def score_item(parsed: Any, patch: Any, daily: Any) -> Verdict:
    """Verdict for one item. ``parsed`` is ``{"item", "mods", "unrecognised"?}``.

    ``qualifies`` and ``tier_mismatch`` on mods are ignored: the tier gate is computed here.
    """
    patch, daily = to_plain(patch), to_plain(daily)
    item, mods, unrecognised = _parsed(parsed)

    # Special items: price lookup, not scored.
    if item["rarity"] == "Unique":
        verdict = _not_scored("unique_price_lookup", unrecognised)
        verdict["special_price_chaos"] = _unique_price(daily, item.get("name"))
        return verdict
    # Item class or base not in the patch (or a class that is recognised but not scored).
    class_info = patch["item_classes"].get(item["item_class"])
    base_info = patch["bases"].get(item["base"])
    if not class_info or not base_info or class_info.get("scored") is False:
        return _not_scored("unsupported_item", unrecognised)

    t = _thresholds_for(daily, item["item_class"])
    need = _Need()

    qualifying = _qualifying(mods, patch, daily, base_info["tier_set"])
    qual_stats: set[str] = set()
    for mod, ok in zip(mods, qualifying, strict=True):
        if ok:
            qual_stats.update(mod["stat_ids"])

    k = class_info["max_prefixes"] + class_info["max_suffixes"]
    craftable = set(class_info.get("craftable_stat_ids") or [])

    # R2: candidate builds.
    candidates: list[_Candidate] = []
    for node in daily["build_nodes"]:
        if node["id"] == "all" or not node["shown_on_own"]:
            continue
        node_demand = (daily["demand"].get(item["item_class"]) or {}).get(node["id"])
        if not node_demand:
            continue
        core = _core_mods(node_demand["mods"])
        denom = 0.0
        for m in core[:k]:
            denom += m["demand_low"]
        numer = 0.0
        counted: list[str] = []
        for m in core:
            if m["stat_id"] not in qual_stats:
                continue
            counted.append(m["stat_id"])
            # Craftable discount: numerator only (decision 19).
            discount = 0
            if m["stat_id"] in craftable:
                found = need(t.get("craftable_discount"))
                discount = found if found is not None else 0
            numer += m["demand_low"] * (1 - discount)
        core_ids = {m["stat_id"] for m in core}
        affixes: set[str] = set()
        for mod, ok in zip(mods, qualifying, strict=True):
            if ok and any(sid in core_ids for sid in mod["stat_ids"]):
                affixes.add(mod.get("family") or "|".join(mod["stat_ids"]))
        candidates.append(
            _Candidate(node, numer / denom if denom > 0 else 0, counted, len(affixes), core_ids)
        )

    # R4: buyers have enough accounts; the rest are niche.
    found_min = need(t.get("min_build_accounts"))
    min_accounts = found_min if found_min is not None else 0

    def by_fit(a: _Candidate, b: _Candidate) -> float:
        # Fits equal within EPS tie: then more accounts, then node id.
        return (
            (b.fit - a.fit if abs(b.fit - a.fit) > EPS else 0)
            or (b.node["accounts"] - a.node["accounts"])
            or str_cmp(a.node["id"], b.node["id"])
        )

    buyers = sorted(
        (c for c in candidates if c.node["accounts"] >= min_accounts), key=cmp_to_key(by_fit)
    )
    niche = sorted(
        (c for c in candidates if c.node["accounts"] < min_accounts), key=cmp_to_key(by_fit)
    )

    # R9: best candidate's fit even when no buyer is named.
    top_fit = max([0, *[c.fit for c in candidates]])

    reasons: list[str] = []
    buyer: _Candidate | None = None
    fit = top_fit
    counted_ids: list[str] = []

    def keep_fit_ok(c: _Candidate) -> bool:
        keep_fit = need(t.get("keep_fit"))
        return c.affixes >= 2 and (c.fit > 0 if keep_fit is None else c.fit >= keep_fit - EPS)

    # Decision 30: among buyer-size builds that meet the KEEP condition the highest fit, else the
    # highest fit.
    best = next((c for c in buyers if keep_fit_ok(c)), buyers[0] if buyers else None)

    def partial_fit_ok(c: _Candidate) -> bool:
        threshold = need(t.get("price_check_fit"))
        return threshold is None or c.fit >= threshold - EPS

    if best is not None and keep_fit_ok(best):
        # R5
        buyer = best
        result = "KEEP"
        reasons.append("keep_fit")
        if best.node["low_data"]:
            result = "PRICE_CHECK"
            reasons.append("cap_low_data")
        if not daily["validated"] or need.null_threshold:
            result = "PRICE_CHECK"
            reasons.append("cap_not_validated")
    elif best is not None and best.fit > 0 and partial_fit_ok(best):
        # R6 partial fit
        buyer = best
        result = "PRICE_CHECK"
        reasons.append("partial_fit")
    elif any(keep_fit_ok(c) for c in niche):
        # R6 niche build (owner decision 2026-11-23): the highest-fit niche build that meets KEEP.
        buyer = next(c for c in niche if keep_fit_ok(c))
        result = "PRICE_CHECK"
        reasons.append("niche_build_fit")
    else:
        # R7: boosts, only when the result would be NO BUYER.
        boosts: list[str] = []
        if _fractured_core_boost(mods, qualifying, buyers):
            boosts.append("boost_fractured_core_mod")
        if _base_value_boost(item, daily, t, need):
            boosts.append("boost_base_value")
        if _crafting_boost(item, buyers):
            boosts.append("boost_crafting_potential")
        if boosts:
            result = "PRICE_CHECK"
            reasons.extend(boosts)
        else:
            result = "NO_BUYER"
            reasons.append("no_fit")

    if buyer is not None:
        fit = buyer.fit
        counted_ids = buyer.counted
    if result == "NO_BUYER" and need.null_threshold and top_fit > 0:
        # A needed threshold is missing and some build fits a little: the engine cannot rule a
        # buyer out. (Fit 0 with no boost stays NO BUYER, decision 31.)
        result = "PRICE_CHECK"
        reasons = ["cap_not_validated"]
    elif need.null_threshold and result != "NO_BUYER" and "cap_not_validated" not in reasons:
        reasons.append("cap_not_validated")

    # R8
    open_slots = (item.get("open_prefixes") or 0) + (item.get("open_suffixes") or 0)
    if item.get("corrupted") and open_slots > 0:
        reasons.append("corrupted_open_slots_ignored")

    return {
        "result": result,  # type: ignore[typeddict-item]
        "best_buyer": buyer.node["id"] if buyer else None,
        "fit": round4(fit),
        "low_data": buyer.node["low_data"] if buyer else False,
        "reasons": _with_unrecognised(reasons, unrecognised),
        "counted_stat_ids": counted_ids,
    }


def _fractured_core_boost(
    mods: list[dict[str, Any]], qualifying: list[bool], buyers: list[_Candidate]
) -> bool:
    """R7: a qualifying fractured mod whose stat is core for a buyer-size build."""
    return any(
        mod["source"] == "fractured"
        and ok
        and any(any(sid in b.core_stats for sid in mod["stat_ids"]) for b in buyers)
        for mod, ok in zip(mods, qualifying, strict=True)
    )


def _base_value_boost(
    item: dict[str, Any], daily: dict[str, Any], t: dict[str, Any], need: _Need
) -> bool:
    """R7: base price >= base_value_min_chaos at item level >= base_value_min_ilvl."""
    min_chaos = need(t.get("base_value_min_chaos"))
    min_ilvl = need(t.get("base_value_min_ilvl"))
    if min_chaos is None or min_ilvl is None:
        return False
    if item["ilvl"] < min_ilvl:
        return False
    # Plain (un-influenced) prices only until influenced items have a rule (TODO(item-flags)).
    if item.get("influences"):
        return False
    entries = sorted(
        (
            e
            for e in (daily.get("base_values") or [])
            if e["base"] == item["base"]
            and "influence" in e
            and e["influence"] is None
            and e["min_ilvl"] <= item["ilvl"]
        ),
        key=lambda e: -e["min_ilvl"],
    )
    return bool(entries) and entries[0]["chaos"] >= min_chaos


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _crafting_boost(item: dict[str, Any], buyers: list[_Candidate]) -> bool:
    """R7: at least 2 counted core affixes for a buyer-size build, an open affix, not corrupted
    or mirrored."""
    if item.get("corrupted") or item.get("mirrored"):
        return False
    # Unknown open slots (null or absent, e.g. from the character API) never give the boost.
    open_prefixes, open_suffixes = item.get("open_prefixes"), item.get("open_suffixes")
    if not _is_number(open_prefixes) or not _is_number(open_suffixes):
        return False
    if open_prefixes + open_suffixes == 0:
        return False
    return any(b.affixes >= 2 for b in buyers)

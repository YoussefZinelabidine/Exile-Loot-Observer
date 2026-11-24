"""Scoring engine tests: golden verdicts plus a one-for-one port of ``scoring.test.ts``."""

import copy
import json
from pathlib import Path

import pytest

from backend.common.snapshot_models import Daily, Patch
from backend.normaliser import Normaliser, PatchIndex
from backend.scoring import market_demand, score_item
from backend.scoring.score import str_cmp

FIXTURES = Path(__file__).resolve().parents[2] / "shared" / "fixtures"


def read(path: str) -> dict:
    return json.loads((FIXTURES / path).read_text(encoding="utf-8"))


PATCH = read("snapshot/patch.json")
DAILY = read("snapshot/daily.json")
GOLDEN_DIRS = sorted(d.name for d in (FIXTURES / "golden").iterdir() if d.is_dir())


def clone(x):
    return copy.deepcopy(x)


def golden_expected(name: str) -> dict:
    return read(f"golden/{name}/expected.json")


def golden(name: str) -> dict:
    e = golden_expected(name)
    return {"item": clone(e["item"]), "mods": clone(e["mods"])}


def with_thresholds(**over) -> dict:
    d = clone(DAILY)
    d["params"]["thresholds"]["default"].update(over)
    return d


def assert_verdict(got: dict, want: dict) -> None:
    assert got["result"] == want["result"]
    assert got["best_buyer"] == want["best_buyer"]
    if want["fit"] is None:
        assert got["fit"] is None
    else:
        assert abs(got["fit"] - want["fit"]) <= 1e-4
    assert got["low_data"] == want["low_data"]
    assert set(got["reasons"]) == set(want["reasons"])
    assert len(got["reasons"]) == len(set(got["reasons"]))
    assert set(got["counted_stat_ids"]) == set(want["counted_stat_ids"])
    if "special_price_chaos" in want:
        assert got["special_price_chaos"] == want["special_price_chaos"]


# ---------------------------------------------------------------- golden verdicts


def scorable(name: str) -> bool:
    return golden_expected(name)["item"] is not None


@pytest.mark.parametrize("name", [n for n in GOLDEN_DIRS if scorable(n)])
def test_golden_from_expected_item_and_mods(name):
    expected = golden_expected(name)
    parsed = {"item": expected["item"], "mods": expected["mods"]}
    assert_verdict(score_item(parsed, PATCH, DAILY), expected["verdict"])


@pytest.mark.parametrize("name", [n for n in GOLDEN_DIRS if scorable(n)])
def test_golden_from_pydantic_models_equals_dict_input(name):
    expected = golden_expected(name)
    parsed = {"item": expected["item"], "mods": expected["mods"]}
    from_models = score_item(parsed, Patch.model_validate(PATCH), Daily.model_validate(DAILY))
    assert from_models == score_item(parsed, PATCH, DAILY)


NORMALISER = Normaliser(PatchIndex.from_patch(PATCH))


@pytest.mark.parametrize("form", ["character", "trade"])
@pytest.mark.parametrize("name", [n for n in GOLDEN_DIRS if scorable(n)])
def test_golden_from_normaliser_output(name, form):
    path = FIXTURES / "golden" / name / f"{form}.json"
    if not path.exists():
        pytest.skip(f"no {form} form")
    data = json.loads(path.read_text(encoding="utf-8"))
    if form == "character":
        normalised = NORMALISER.character_item(data["item"])
    else:
        normalised = NORMALISER.trade_result(data["result"])
    assert_verdict(score_item(normalised, PATCH, DAILY), golden_expected(name)["verdict"])


# ---------------------------------------------------------------- rules outside the golden set


def test_base_value_boost_lifts_no_buyer_to_price_check():
    boots = golden("004-boots-no-buyer")
    boots["item"]["ilvl"] = 84
    d = clone(DAILY)
    d["base_values"] = [{"base": "Sorcerer Boots", "min_ilvl": 84, "influence": None, "chaos": 25}]
    v = score_item(boots, PATCH, d)
    assert v["result"] == "PRICE_CHECK"
    assert v["reasons"] == ["boost_base_value"]
    assert v["best_buyer"] is None


def test_no_base_value_boost_below_the_item_level_or_the_price():
    boots = golden("004-boots-no-buyer")
    assert score_item(boots, PATCH, DAILY)["result"] == "NO_BUYER"
    boots["item"]["ilvl"] = 84
    assert score_item(boots, PATCH, DAILY)["result"] == "NO_BUYER"  # 6 chaos < 20


def test_crafting_potential_boost():
    d = with_thresholds(keep_fit=0.99, price_check_fit=0.99)
    v = score_item(golden("001-ring-keep-life-attack"), PATCH, d)
    assert v["result"] == "PRICE_CHECK"
    assert v["reasons"] == ["boost_crafting_potential"]
    assert v["best_buyer"] is None
    assert v["fit"] == pytest.approx(0.6087, abs=1e-4)  # top candidate fit is still reported


def test_no_crafting_boost_when_open_slots_are_null_or_absent():
    d = with_thresholds(keep_fit=0.99, price_check_fit=0.99)
    nulls = golden("001-ring-keep-life-attack")
    nulls["item"]["open_prefixes"] = None
    nulls["item"]["open_suffixes"] = None
    assert score_item(nulls, PATCH, d)["result"] == "NO_BUYER"
    absent = golden("001-ring-keep-life-attack")
    del absent["item"]["open_prefixes"]
    del absent["item"]["open_suffixes"]
    assert score_item(absent, PATCH, d)["result"] == "NO_BUYER"
    half = golden("001-ring-keep-life-attack")
    half["item"]["open_suffixes"] = None
    assert score_item(half, PATCH, d)["result"] == "NO_BUYER"


def test_buyers_with_fits_equal_within_1e9_tie_on_accounts_then_node_id():
    d = clone(DAILY)
    a = d["demand"]["Ring"]["arch:life-attack"]
    d["build_nodes"].append(
        {
            "id": "arch:twin",
            "level": "archetype",
            "parent": "all",
            "label": "twin",
            "accounts": 5000,
            "effective_accounts": 5000,
            "shown_on_own": True,
            "low_data": False,
        }
    )
    d["demand"]["Ring"]["arch:twin"] = clone(a)
    # A fit differing by less than 1e-9 must not decide: the build with more accounts wins.
    for m in d["demand"]["Ring"]["arch:twin"]["mods"]:
        m["demand_low"] *= 1 - 1e-12
    assert score_item(golden("001-ring-keep-life-attack"), PATCH, d)["best_buyer"] == "arch:twin"


def test_no_crafting_boost_for_corrupted_or_mirrored_items_or_without_an_open_affix():
    d = with_thresholds(keep_fit=0.99, price_check_fit=0.99)
    corrupted = golden("001-ring-keep-life-attack")
    corrupted["item"]["corrupted"] = True
    assert score_item(corrupted, PATCH, d)["result"] == "NO_BUYER"
    mirrored = golden("001-ring-keep-life-attack")
    mirrored["item"]["mirrored"] = True
    assert score_item(mirrored, PATCH, d)["result"] == "NO_BUYER"
    full = golden("001-ring-keep-life-attack")
    full["item"]["open_prefixes"] = 0
    full["item"]["open_suffixes"] = 0
    assert score_item(full, PATCH, d)["result"] == "NO_BUYER"


def test_niche_build_keep_level_fit_below_min_build_accounts_gives_price_check():
    d = with_thresholds(min_build_accounts=2000)
    v = score_item(golden("001-ring-keep-life-attack"), PATCH, d)
    assert v["result"] == "PRICE_CHECK"
    assert v["best_buyer"] == "arch:life-attack"
    assert v["reasons"] == ["niche_build_fit"]
    assert v["fit"] == pytest.approx(0.6087, abs=1e-4)


def test_validated_false_caps_keep_at_price_check():
    d = clone(DAILY)
    d["validated"] = False
    v = score_item(golden("001-ring-keep-life-attack"), PATCH, d)
    assert v["result"] == "PRICE_CHECK"
    assert set(v["reasons"]) == {"keep_fit", "cap_not_validated"}
    assert v["best_buyer"] == "arch:life-attack"


def test_a_null_keep_fit_caps_keep_at_price_check():
    v = score_item(golden("001-ring-keep-life-attack"), PATCH, with_thresholds(keep_fit=None))
    assert v["result"] == "PRICE_CHECK"
    assert "cap_not_validated" in v["reasons"]


def test_null_thresholds_fit_zero_with_no_boost_stays_no_buyer():  # decision 31
    d = with_thresholds(price_check_fit=None, keep_fit=None)
    v = score_item(golden("004-boots-no-buyer"), PATCH, d)
    assert v["result"] == "NO_BUYER"
    assert v["reasons"] == ["no_fit"]


def test_null_thresholds_a_non_zero_fit_that_would_be_no_buyer_is_capped():
    d = with_thresholds(keep_fit=0.99, price_check_fit=0.99, base_value_min_chaos=None)
    ring = golden("001-ring-keep-life-attack")
    ring["item"]["corrupted"] = True  # no crafting boost
    v = score_item(ring, PATCH, d)
    assert v["result"] == "PRICE_CHECK"
    assert v["reasons"] == ["cap_not_validated", "corrupted_open_slots_ignored"]


def test_unrecognised_mod_lines_add_a_reason_and_leave_the_known_mods_scored():
    parsed = {**golden("001-ring-keep-life-attack"), "unrecognised": ["+7 to Frobnication"]}
    v = score_item(parsed, PATCH, DAILY)
    assert v["result"] == "KEEP"
    assert set(v["reasons"]) == {"keep_fit", "unrecognised_mods"}


def test_craftable_discount_lowers_the_numerator_only():
    p = clone(PATCH)
    p["item_classes"]["Ring"]["craftable_stat_ids"] = ["base_maximum_life"]
    d = with_thresholds(craftable_discount=0.5)
    plain = score_item(golden("001-ring-keep-life-attack"), PATCH, DAILY)["fit"]
    v = score_item(golden("001-ring-keep-life-attack"), p, d)
    # life demand_low 0.3 of a numerator of 0.7: 0.15 less on an unchanged denominator.
    denominator = 0.7 / plain
    assert v["fit"] == pytest.approx(0.55 / denominator, abs=1e-4)
    assert "base_maximum_life" in v["counted_stat_ids"]


def test_uniques_price_by_name_null_when_not_listed():
    u = golden("007-unique-ring-not-scored")
    assert score_item(u, PATCH, DAILY)["special_price_chaos"] == 3
    u["item"]["name"] = "Nobody's Ring"
    v = score_item(u, PATCH, DAILY)
    assert v["result"] == "NOT_SCORED"
    assert v["special_price_chaos"] is None


def test_unique_prefers_the_plain_variant():
    u = golden("007-unique-ring-not-scored")
    d = clone(DAILY)
    d["special_prices"] = [
        {"kind": "unique", "name": "Ventor's Gamble", "variant": "x", "links": None, "chaos": 9},
        {"kind": "unique", "name": "Ventor's Gamble", "variant": None, "links": None, "chaos": 4},
    ]
    assert score_item(u, PATCH, d)["special_price_chaos"] == 4


def test_tier_gate_comes_from_the_daily_file():
    # T5 of 8 resistance fails at 0.4 but passes when the gate is wide open.
    d = clone(DAILY)
    d["params"]["tier_gate"] = {"top_fraction": 1, "always_top_tiers": 1}
    v = score_item(golden("001-ring-keep-life-attack"), PATCH, d)
    assert "base_lightning_damage_resistance_%" in v["counted_stat_ids"]


# ---------------------------------------------------------------- decisions 29-37


def mod(stat_id: str, family: str, tier: int = 1) -> dict:
    return {
        "source": "explicit",
        "affix": "prefix",
        "stat_ids": [stat_id],
        "values": [1],
        "tier": tier,
        "family": family,
    }


def with_node(node_id: str, accounts: int, mods: list[tuple[str, float]]) -> dict:
    """Adds an archetype node with the given core mods (stat id, demand_low) for the Ring class."""
    d = clone(DAILY)
    d["build_nodes"].append(
        {
            "id": node_id,
            "level": "archetype",
            "parent": "all",
            "label": node_id,
            "accounts": accounts,
            "effective_accounts": accounts,
            "shown_on_own": True,
            "low_data": False,
        }
    )
    d["demand"]["Ring"][node_id] = {
        "effective_items": 100,
        "mods": [
            {
                "stat_id": stat_id,
                "core": True,
                "demand": demand_low,
                "demand_low": demand_low,
                "share": 0.5,
                "effective_obs": 50,
                "demand_tier": "A",
            }
            for stat_id, demand_low in mods
        ],
    }
    return d


def test_niche_first_niche_build_that_meets_keep_is_named():  # decision 30
    # es-spell (900 accounts) keeps only life as core: fit 1.0 but one affix, so no KEEP.
    d = with_thresholds(min_build_accounts=5000)
    es = d["demand"]["Ring"]["arch:es-spell"]
    es["mods"] = [m for m in es["mods"] if m["stat_id"] == "base_maximum_life"]
    v = score_item(golden("001-ring-keep-life-attack"), PATCH, d)
    assert v["result"] == "PRICE_CHECK"
    assert v["best_buyer"] == "arch:life-attack"
    assert v["reasons"] == ["niche_build_fit"]
    assert v["fit"] == pytest.approx(0.6087, abs=1e-4)


def test_best_buyer_prefers_a_keep_buyer_over_a_higher_fit_one():  # decision 30
    d = with_node("arch:one-mod", 5000, [("base_maximum_life", 0.5)])  # fit 1.0, one affix
    v = score_item(golden("001-ring-keep-life-attack"), PATCH, d)
    assert v["result"] == "KEEP"
    assert v["best_buyer"] == "arch:life-attack"


def test_without_any_keep_level_buyer_the_highest_fit_buyer_is_named():
    d = with_node("arch:one-mod", 5000, [("base_maximum_life", 0.5)])
    only = golden("001-ring-keep-life-attack")
    only["mods"] = [m for m in only["mods"] if m["stat_ids"][0] == "base_maximum_life"]
    v = score_item(only, PATCH, d)
    assert v["best_buyer"] == "arch:one-mod"
    assert v["result"] == "PRICE_CHECK"


def hybrid_mods() -> dict:
    parsed = golden("001-ring-keep-life-attack")
    parsed["mods"] = [
        mod("base_maximum_life", "prefix:IncreasedLife"),
        mod("base_fire_damage_resistance_%", "prefix:IncreasedLife"),
    ]
    return parsed


def test_keep_counts_distinct_affixes_not_stats():  # decision 29
    v = score_item(hybrid_mods(), PATCH, DAILY)
    assert len(v["counted_stat_ids"]) == 2
    assert v["result"] == "PRICE_CHECK"
    assert v["reasons"] == ["partial_fit"]


def test_the_crafting_boost_needs_two_distinct_affixes_too():
    d = with_thresholds(keep_fit=0.99, price_check_fit=0.99)
    assert score_item(hybrid_mods(), PATCH, d)["result"] == "NO_BUYER"
    assert score_item(golden("001-ring-keep-life-attack"), PATCH, d)["reasons"] == [
        "boost_crafting_potential"
    ]


def test_unsupported_items():  # decisions 32, 33
    unknown_base = golden("001-ring-keep-life-attack")
    unknown_base["item"]["base"] = "Nonexistent Ring"
    v = score_item(unknown_base, PATCH, DAILY)
    assert (v["result"], v["reasons"], v["fit"], v["best_buyer"]) == (
        "NOT_SCORED",
        ["unsupported_item"],
        None,
        None,
    )
    unknown_class = golden("001-ring-keep-life-attack")
    unknown_class["item"]["item_class"] = "Belt"
    assert score_item(unknown_class, PATCH, DAILY)["reasons"] == ["unsupported_item"]
    p = clone(PATCH)
    p["item_classes"]["Ring"]["scored"] = False
    assert score_item(golden("001-ring-keep-life-attack"), p, DAILY)["reasons"] == [
        "unsupported_item"
    ]


def test_a_unique_is_looked_up_by_name_before_the_base_is_checked():  # decision 27
    u = golden("007-unique-ring-not-scored")
    u["item"]["base"] = "Nonexistent Ring"
    v = score_item(u, PATCH, DAILY)
    assert v["reasons"] == ["unique_price_lookup"]
    assert v["special_price_chaos"] == 3


def test_fit_comparisons_allow_an_epsilon():  # decision 37
    exact = score_item(golden("001-ring-keep-life-attack"), PATCH, DAILY)["fit"]
    true_fit = 0.7 / 1.15
    d = with_thresholds(keep_fit=true_fit + 5e-10)
    assert score_item(golden("001-ring-keep-life-attack"), PATCH, d)["result"] == "KEEP"
    assert exact == pytest.approx(true_fit, abs=1e-4)


def test_a_duplicated_core_stat_id_counts_once_with_its_highest_demand_low():  # decision 37
    d = clone(DAILY)
    mods = d["demand"]["Ring"]["arch:life-attack"]["mods"]
    life = next(m for m in mods if m["stat_id"] == "base_maximum_life")
    before = score_item(golden("001-ring-keep-life-attack"), PATCH, d)
    mods.append({**life, "demand_low": life["demand_low"] / 3})
    assert score_item(golden("001-ring-keep-life-attack"), PATCH, d)["fit"] == before["fit"]


def test_open_slots_missing_means_no_corrupted_reason_and_no_boost():
    parsed = golden("001-ring-keep-life-attack")
    parsed["item"]["corrupted"] = True
    parsed["item"]["open_prefixes"] = None
    parsed["item"]["open_suffixes"] = None
    assert "corrupted_open_slots_ignored" not in score_item(parsed, PATCH, DAILY)["reasons"]


def test_fractured_core_mod_boost():
    parsed = golden("006-gloves-fractured-core")
    v = score_item(parsed, PATCH, DAILY)
    assert "boost_fractured_core_mod" in v["reasons"] and v["result"] == "PRICE_CHECK"


# ---------------------------------------------------------------- market demand


def test_market_demand_main_skill_filter_uses_only_that_node():  # decision 34
    rows = market_demand(DAILY, "Ring", {"node_id": "skill:lightning-strike"})
    assert rows
    assert all(r["nodes"] == ["skill:lightning-strike"] for r in rows)
    node = next(n for n in DAILY["build_nodes"] if n["id"] == "skill:lightning-strike")
    top = DAILY["demand"]["Ring"]["skill:lightning-strike"]["mods"][0]
    row = next(r for r in rows if r["stat_id"] == top["stat_id"])
    assert row["demand"] == pytest.approx(top["demand"] * node["accounts"], abs=1e-6)
    assert market_demand(DAILY, "Ring", {"node_id": "skill:missing"}) == []
    assert market_demand(DAILY, "Ring", {"node_id": "all"}) == []


def test_market_demand_sums_archetype_nodes_only():
    rows = market_demand(DAILY, "Ring")
    life = next(r for r in rows if r["stat_id"] == "base_maximum_life")
    assert all(n.startswith("arch:") for n in life["nodes"])
    expected = 0.0
    for n in DAILY["build_nodes"]:
        if n["level"] != "archetype":
            continue
        m = next(
            (x for x in DAILY["demand"]["Ring"].get(n["id"], {}).get("mods", [])
             if x["stat_id"] == "base_maximum_life"),
            None,
        )  # fmt: skip
        expected += m["demand"] * n["accounts"] if m else 0
    assert life["demand"] == pytest.approx(expected, abs=1e-6)
    for earlier, later in zip(rows, rows[1:], strict=False):
        assert earlier["demand"] >= later["demand"]


def test_market_demand_filters_and_unknown_class():
    es = market_demand(DAILY, "Ring", {"defence": "es"})
    assert all(all(n == "arch:es-spell" for n in r["nodes"]) for r in es)
    assert market_demand(DAILY, "Nothing") == []
    assert market_demand(Daily.model_validate(DAILY), "Ring") == market_demand(DAILY, "Ring")


# ---------------------------------------------------------------- tie-break order


def test_ties_use_code_point_order_not_locale_order():
    # "-" (45) sorts before "_" (95) by code point; ICU locale order puts "_" first.
    assert str_cmp("arch:life-attack", "arch:life_attack") < 0
    assert str_cmp("b", "a") > 0 and str_cmp("a", "a") == 0 and str_cmp("B", "a") < 0
    d = clone(DAILY)
    twin = clone(next(n for n in d["build_nodes"] if n["id"] == "arch:life-attack"))
    twin["id"] = "arch:life_attack"
    d["build_nodes"].append(twin)
    d["demand"]["Ring"]["arch:life_attack"] = clone(d["demand"]["Ring"]["arch:life-attack"])
    # identical fit and accounts: the code-point order of the ids decides
    assert score_item(golden("001-ring-keep-life-attack"), PATCH, d)["best_buyer"] == (
        "arch:life-attack"
    )

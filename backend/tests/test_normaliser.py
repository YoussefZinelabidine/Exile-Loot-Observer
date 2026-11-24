import copy
import json
import logging
from collections import Counter
from pathlib import Path

import pytest

from backend.common.snapshot_models import Patch
from backend.normaliser import Normaliser, NormaliserError, PatchIndex, db_rows
from backend.normaliser.patch_index import js_round

REPO = Path(__file__).resolve().parents[2]
GOLDEN = REPO / "shared" / "fixtures" / "golden"
PATCH_DATA = json.loads(
    (REPO / "shared" / "fixtures" / "snapshot" / "patch.json").read_text(encoding="utf-8")
)


@pytest.fixture(scope="module")
def normaliser() -> Normaliser:
    return Normaliser(PatchIndex.from_patch(Patch.model_validate(PATCH_DATA)))


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def key(mod: dict) -> str:
    return json.dumps(mod, sort_keys=True)


def expected_of(folder: Path) -> dict:
    expected = load(folder / "expected.json")
    expected["mods"] = [{k: v for k, v in m.items() if k != "qualifies"} for m in expected["mods"]]
    return expected


def assert_matches_golden(result: dict, expected: dict) -> None:
    assert result["item"] == expected["item"]
    assert Counter(map(key, result["mods"])) == Counter(map(key, expected["mods"]))
    assert result["unrecognised"] == expected.get("unrecognised", [])


def golden_cases(form: str) -> list[Path]:
    return [d for d in sorted(GOLDEN.iterdir()) if (d / f"{form}.json").exists()]


@pytest.mark.parametrize("folder", golden_cases("character"), ids=lambda p: p.name)
def test_golden_character(normaliser, folder):
    result = normaliser.character_item(load(folder / "character.json")["item"])
    assert_matches_golden(result.to_expected(), expected_of(folder))


@pytest.mark.parametrize("folder", golden_cases("trade"), ids=lambda p: p.name)
def test_golden_trade(normaliser, folder):
    result = normaliser.trade_result(load(folder / "trade.json")["result"])
    assert_matches_golden(result.to_expected(), expected_of(folder))
    assert not any(m.tier_mismatch for m in result.mods)


def test_golden_sets_are_not_empty():
    assert len(golden_cases("character")) >= 7 and len(golden_cases("trade")) >= 7


# ---------------------------------------------------------------- unit cases


def test_js_round_halves_go_up():
    assert js_round(2.5) == 3 and js_round(-2.5) == -2 and js_round(99.9) == 100


def ring(**extra) -> dict:
    item = {
        "name": "Test",
        "baseType": "Diamond Ring",
        "typeLine": "Diamond Ring",
        "rarity": "Rare",
        "ilvl": 84,
        "implicitMods": [],
        "explicitMods": [],
    }
    item.update(extra)
    return item


def test_unknown_line_is_reported_and_logged_not_guessed(normaliser, caplog):
    item = ring(explicitMods=["+108 to maximum Life", "Totally Unknown Line 5"])
    with caplog.at_level(logging.WARNING, logger="backend.normaliser.normalise"):
        result = normaliser.character_item(item)
    assert result.unrecognised == ["Totally Unknown Line 5"]
    assert [m.stat_ids for m in result.mods] == [["base_maximum_life"]]
    assert "Diamond Ring" in caplog.text and "Totally Unknown Line 5" in caplog.text


def test_value_outside_every_ladder_is_unrecognised(normaliser):
    result = normaliser.character_item(ring(explicitMods=["+9999 to maximum Life"]))
    assert result.mods == [] and result.unrecognised == ["+9999 to maximum Life"]


def test_ilvl_limits_the_tiers(normaliser):
    # 108 life is T1 (needs item level 44+... check both sides of the requirement)
    high = normaliser.character_item(ring(explicitMods=["+108 to maximum Life"], ilvl=84))
    assert high.mods[0].tier == 1
    low = normaliser.character_item(ring(explicitMods=["+108 to maximum Life"], ilvl=10))
    assert low.mods == [] and low.unrecognised


def test_unique_has_item_only(normaliser):
    result = normaliser.character_item(
        load(GOLDEN / "007-unique-ring-not-scored" / "character.json")["item"]
    )
    assert result.mods == [] and result.unrecognised == []
    assert result.item["rarity"] == "Unique"


def test_veiled_lines_are_reported_not_mapped(normaliser):
    result = normaliser.character_item(ring(veiledMods=["Unrevealed Veiled Prefix"]))
    assert result.unrecognised == ["Unrevealed Veiled Prefix"]


def test_unknown_base_raises_for_non_unique(normaliser):
    with pytest.raises(NormaliserError) as info:
        normaliser.character_item(ring(baseType="Nonexistent Ring"))
    assert info.value.code == "unsupported_item"


def test_unique_with_unknown_base_has_empty_item_class(normaliser):
    result = normaliser.character_item(ring(rarity="Unique", baseType="Mystery Ring"))
    assert result.item["item_class"] == "" and result.mods == []


def test_corruption_implicit_and_enchant_sources(normaliser):
    item = ring(
        corrupted=True,
        implicitMods=["25% increased Global Critical Strike Chance", "+30 to maximum Life"],
        enchantMods=["+20% to Fire Resistance"],
    )
    result = normaliser.character_item(item)
    sources = {tuple(m.stat_ids): m.source for m in result.mods}
    assert sources[("critical_strike_chance_+%",)] == "implicit"
    assert sources[("base_maximum_life",)] == "corruption_implicit"
    assert sources[("base_fire_damage_resistance_%",)] == "enchant"
    assert all(m.tier is None and m.family is None and m.affix is None for m in result.mods)


def test_item_flags_from_the_api(normaliser):
    item = ring(corrupted=True, duplicated=True, influences={"shaper": True, "hunter": True})
    out = normaliser.character_item(item).item
    assert out["corrupted"] and out["mirrored"] and out["influences"] == ["shaper", "hunter"]


# ---------------------------------------------------------------- synthetic patches


def synthetic_patch(families: dict, translations: list, bases=None) -> PatchIndex:
    data = copy.deepcopy(PATCH_DATA)
    data["tier_sets"] = {"Ring|default+ring": families}
    data["translations"] = translations
    data["trade_ids"] = {}
    if bases is not None:
        data["bases"] = bases
    return PatchIndex.from_patch(data)


def tier(n, level, lo, hi, stat, name=None):
    return {
        "tier": n,
        "mod_id": f"M{n}",
        "name": name,
        "required_level": level,
        "stats": [{"id": stat, "min": lo, "max": hi}],
    }


def entry(ids, string, fmt, handlers=None, cond=None):
    return {
        "ids": ids,
        "english": [
            {
                "string": string,
                "format": fmt,
                "condition": cond or [{"min": None, "max": None, "negated": None}] * len(ids),
                "index_handlers": handlers or [[] for _ in ids],
            }
        ],
    }


def test_overlapping_tiers_take_the_best_and_flag_ambiguity():
    families = {
        "prefix:A": {
            "affix": "prefix",
            "stat_ids": ["stat_a"],
            "tiers": [tier(1, 50, 20, 30, "stat_a"), tier(2, 1, 10, 25, "stat_a")],
        }
    }
    norm = Normaliser(synthetic_patch(families, [entry(["stat_a"], "{0} to A", ["+#"])]))
    result = norm.character_item(ring(explicitMods=["+22 to A"]))
    assert (result.mods[0].tier, result.mods[0].tier_ambiguous) == (1, True)
    # at an item level below T1's requirement only T2 is possible: not ambiguous
    low = norm.character_item(ring(explicitMods=["+22 to A"], ilvl=20))
    assert (low.mods[0].tier, low.mods[0].tier_ambiguous) == (2, False)
    sure = norm.character_item(ring(explicitMods=["+12 to A"]))
    assert (sure.mods[0].tier, sure.mods[0].tier_ambiguous) == (2, False)


def test_hybrid_lines_share_family_and_tier_one_row_per_stat():
    families = {
        "prefix:Hybrid": {
            "affix": "prefix",
            "stat_ids": ["stat_a", "stat_b"],
            "tiers": [
                {
                    "tier": 1,
                    "mod_id": "H1",
                    "required_level": 60,
                    "stats": [
                        {"id": "stat_a", "min": 10, "max": 20},
                        {"id": "stat_b", "min": 5, "max": 9},
                    ],
                },
                {
                    "tier": 2,
                    "mod_id": "H2",
                    "required_level": 1,
                    "stats": [
                        {"id": "stat_a", "min": 1, "max": 15},
                        {"id": "stat_b", "min": 1, "max": 4},
                    ],
                },
            ],
        }
    }
    translations = [
        entry(["stat_a"], "{0} to A", ["+#"]),
        entry(["stat_b"], "{0}% increased B", ["#"]),
    ]
    norm = Normaliser(synthetic_patch(families, translations))
    # A=12 fits both tiers, B=7 only T1: the shared tier is T1 for both lines, not ambiguous
    result = norm.character_item(ring(explicitMods=["+12 to A", "7% increased B"]))
    assert [(m.family, m.tier, m.tier_ambiguous) for m in result.mods] == [
        ("prefix:Hybrid", 1, False)
    ] * 2
    rows = db_rows(result)
    assert [(r.stat_id, r.value, r.tier, r.source) for r in rows] == [
        ("stat_a", 12, 1, "explicit"),
        ("stat_b", 7, 1, "explicit"),
    ]
    assert rows[0].item_class == "Ring" and rows[0].base == "Diamond Ring" and rows[0].ilvl == 84
    # a hybrid family needs all of its stats on the item
    alone = norm.character_item(ring(explicitMods=["+12 to A"]))
    assert alone.mods == [] and alone.unrecognised == ["+12 to A"]


def test_merged_identical_stat_lines_are_unrecognised_not_guessed():
    families = {
        "prefix:A": {
            "affix": "prefix",
            "stat_ids": ["stat_a"],
            "tiers": [tier(1, 1, 5, 10, "stat_a")],
        },
        "suffix:A": {
            "affix": "suffix",
            "stat_ids": ["stat_a"],
            "tiers": [tier(1, 1, 5, 10, "stat_a")],
        },
    }
    norm = Normaliser(synthetic_patch(families, [entry(["stat_a"], "{0} to A", ["+#"])]))
    merged = norm.character_item(ring(explicitMods=["+16 to A"]))  # 7 + 9, shown as one line
    assert merged.mods == [] and merged.unrecognised == ["+16 to A"]
    # one family or the other fits on its own -> two families fit -> also not guessed
    both = norm.character_item(ring(explicitMods=["+7 to A"]))
    assert both.mods == [] and both.unrecognised == ["+7 to A"]


def test_handlers_and_rounding_follow_the_shared_table():
    families = {
        "suffix:Speed": {
            "affix": "suffix",
            "stat_ids": ["speed_raw"],
            "tiers": [tier(1, 1, 150, 180, "speed_raw")],
        },
        "suffix:Neg": {
            "affix": "suffix",
            "stat_ids": ["reduced_raw"],
            "tiers": [tier(1, 1, -30, -10, "reduced_raw")],
        },
    }
    translations = [
        entry(["speed_raw"], "{0}% speed", ["#"], [["divide_by_one_hundred"]]),
        entry(["reduced_raw"], "{0}% reduced thing", ["#"], [["negate"]]),
    ]
    norm = Normaliser(synthetic_patch(families, translations))
    result = norm.character_item(ring(explicitMods=["1.65% speed", "20% reduced thing"]))
    by_stat = {m.stat_ids[0]: m.values[0] for m in result.mods}
    assert by_stat == {"speed_raw": 165, "reduced_raw": -20}


def test_unsupported_handler_makes_the_line_unrecognised():
    families = {
        "suffix:X": {"affix": "suffix", "stat_ids": ["x"], "tiers": [tier(1, 1, 1, 9, "x")]}
    }
    translations = [entry(["x"], "{0} weird", ["#"], [["times_one_point_five"]])]
    norm = Normaliser(synthetic_patch(families, translations))
    assert norm.character_item(ring(explicitMods=["5 weird"])).unrecognised == ["5 weird"]


def test_hidden_stats_are_never_added():
    translations = [
        entry(
            ["shown", "hidden"],
            "{0} things",
            ["#", "ignore"],
            cond=[{"min": None, "max": None, "negated": None}] * 2,
        ),
        entry(
            ["flag_on", "flag_zero"],
            "Does a thing",
            ["ignore", "ignore"],
            cond=[
                {"min": 1, "max": None, "negated": None},
                {"min": None, "max": None, "negated": None},
            ],
        ),
    ]
    index = synthetic_patch({}, translations)
    shown = index.match_line("5 things")
    assert [(m.stat_ids, m.values) for m in shown] == [(["shown"], [5])]
    flag = index.match_line("Does a thing")
    assert [(m.stat_ids, m.values) for m in flag] == [(["flag_on"], [1])]


# ---------------------------------------------------------------- trade specifics


def trade_ring(normaliser_data: dict) -> dict:
    return copy.deepcopy(load(GOLDEN / "001-ring-keep-life-attack" / "trade.json")["result"])


def test_trade_label_disagreeing_with_ladder_falls_back_and_flags(normaliser):
    result = trade_ring({})
    # claim the life mod is T3: the ladder says T1 for 108, so the ladder wins
    result["item"]["extended"]["mods"]["explicit"][0]["tier"] = "P3"
    out = normaliser.trade_result(result)
    life = next(m for m in out.mods if m.family == "prefix:IncreasedLife")
    assert life.tier == 1 and life.tier_mismatch


def test_trade_label_with_wrong_name_is_flagged(normaliser):
    result = trade_ring({})
    result["item"]["extended"]["mods"]["explicit"][0]["name"] = "Not Virile"
    out = normaliser.trade_result(result)
    life = next(m for m in out.mods if m.family == "prefix:IncreasedLife")
    assert life.tier == 1 and life.tier_mismatch


def test_trade_without_extended_behaves_like_character(normaliser):
    result = trade_ring({})
    del result["item"]["extended"]
    out = normaliser.trade_result(result)
    expected = normaliser.character_item(result["item"])
    assert out.to_expected() == expected.to_expected()


# ---------------------------------------------------------------- review fixes (P1-B3)


def boots(mods, **extra):
    item = ring(baseType="Sorcerer Boots", typeLine="Sorcerer Boots", explicitMods=mods)
    item.update(extra)
    return item


def test_variants_follow_the_app_parser():
    n = {"min": None, "max": None, "negated": None}
    translations = [
        {  # same text twice: the raw value picks the variant the game shows
            "ids": ["s"],
            "english": [
                {
                    "string": "{0}% more X",
                    "format": ["#"],
                    "condition": [{"min": 1, "max": 9, "negated": None}],
                    "index_handlers": [["divide_by_ten_1dp"]],
                },
                {
                    "string": "{0}% more X",
                    "format": ["#"],
                    "condition": [{"min": 10, "max": None, "negated": None}],
                    "index_handlers": [[]],
                },
            ],
        },
        {  # one group, two variants with different visible stat sets
            "ids": ["a", "b"],
            "english": [
                {
                    "string": "{0} to Y",
                    "format": ["#", "ignore"],
                    "condition": [n, n],
                    "index_handlers": [[], []],
                },
                {
                    "string": "{1} to Y",
                    "format": ["ignore", "#"],
                    "condition": [n, n],
                    "index_handlers": [[], []],
                },
            ],
        },
        {  # negated condition: valid for any value outside 1..5
            "ids": ["z"],
            "english": [
                {
                    "string": "{0} to Z",
                    "format": ["#"],
                    "condition": [{"min": 1, "max": 5, "negated": True}],
                    "index_handlers": [[]],
                }
            ],
        },
    ]
    index = synthetic_patch({}, translations)
    assert [(m.stat_ids, m.values) for m in index.match_line("50% more X")] == [(["s"], [50])]
    # 0.5 shown -> raw 5, inside the first variant range 1..9
    assert [(m.stat_ids, m.values) for m in index.match_line("0.5% more X")] == [(["s"], [5])]
    both = index.match_line("5 to Y")
    assert [(m.stat_ids, m.values, m.group) for m in both] == [(["a"], [5], 1), (["b"], [5], 1)]
    assert index.match_line("3 to Z") == []
    assert [m.values for m in index.match_line("9 to Z")] == [[9]]


def test_one_sided_hybrid_lines_are_unrecognised(normaliser):
    # P4: 8% ES only fits the ES+stun hybrid, 25% stun only the pure stun family
    both = normaliser.character_item(
        boots(["8% increased Energy Shield", "25% increased Stun and Block Recovery"])
    )
    assert both.mods == [] and len(both.unrecognised) == 2
    alone = normaliser.character_item(boots(["8% increased Energy Shield"]))
    assert alone.mods == [] and alone.unrecognised == ["8% increased Energy Shield"]
    # P14: ES 13 also fits pure T5, but the life half 120 does not fit the hybrid
    mixed = normaliser.character_item(
        boots(["+13 to maximum Energy Shield", "+120 to maximum Life"])
    )
    assert mixed.mods == [] and len(mixed.unrecognised) == 2


def test_hybrid_versus_two_pure_mods_is_not_guessed(normaliser):
    result = normaliser.character_item(
        boots(["+12 to maximum Energy Shield", "+26 to maximum Life"])
    )
    assert result.mods == [] and len(result.unrecognised) == 2


def test_merged_line_from_pure_and_hybrid_es_is_unrecognised(normaliser):
    # pure ES 20 + hybrid ES 10 are shown as one "+30" line; the hybrid life half (20) is a
    # separate line. Neither line may be given a tier.
    result = normaliser.character_item(
        boots(["+30 to maximum Energy Shield", "+20 to maximum Life"])
    )
    assert result.mods == [] and len(result.unrecognised) == 2


def test_open_slots_are_unknown_when_an_affix_line_is_unrecognised(normaliser):
    item = ring(explicitMods=["+108 to maximum Life", "Some unknown prefix 5"])
    result = normaliser.character_item(item)
    assert result.item["open_prefixes"] is None and result.item["open_suffixes"] is None
    out = result.to_expected()["item"]
    assert "open_prefixes" not in out and "open_suffixes" not in out
    known = normaliser.character_item(ring(explicitMods=["+108 to maximum Life"]))
    assert "open_prefixes" in known.to_expected()["item"]


def test_open_slots_unknown_for_crafted_without_affix_and_for_veiled(normaliser):
    # a crafted mod whose stat fits no family of the tier set: affix unknown
    crafted = ring(explicitMods=["+108 to maximum Life"], craftedMods=["+10 to all Attributes"])
    result = normaliser.character_item(crafted)
    assert result.item["open_prefixes"] is None
    veiled = normaliser.character_item(
        ring(explicitMods=["+108 to maximum Life"], veiledMods=["Unrevealed Veiled Prefix"])
    )
    assert veiled.item["open_suffixes"] is None


def test_crafted_affix_from_the_tier_set_keeps_slots_known(normaliser):
    result = normaliser.character_item(
        ring(explicitMods=["+108 to maximum Life"], craftedMods=["+30% to Fire Resistance"])
    )
    crafted = next(m for m in result.mods if m.source == "crafted")
    assert crafted.affix == "suffix" and crafted.family is None
    assert (result.item["open_prefixes"], result.item["open_suffixes"]) == (2, 2)


def test_item_validity_errors(normaliser):
    with pytest.raises(NormaliserError) as unidentified:
        normaliser.character_item(ring(identified=False))
    assert unidentified.value.code == "unidentified"
    with pytest.raises(NormaliserError) as no_ilvl:
        normaliser.character_item({k: v for k, v in ring().items() if k != "ilvl"})
    assert no_ilvl.value.code == "invalid_item"


def test_frame_types_gems_and_flasks(normaliser):
    relic = {"name": "Foo", "baseType": "Gold Ring", "frameType": 9, "ilvl": 80}
    assert normaliser.character_item(relic).item["rarity"] == "Unique"
    for item in (
        {"baseType": "Lightning Strike", "typeLine": "Lightning Strike", "frameType": 4},  # gem
        {"baseType": "Currency", "frameType": 5, "ilvl": 1},
        {"baseType": "Quicksilver Flask", "rarity": "Magic", "frameType": 1, "ilvl": 80},  # flask
        {"baseType": "Diamond Ring", "frameType": 99, "ilvl": 80},
    ):
        with pytest.raises(NormaliserError) as info:
            normaliser.character_item(item)
        assert info.value.code == "unsupported_item", item


def test_db_rows_carry_family_affix_and_flags(normaliser):
    rows = db_rows(normaliser.character_item(ring(explicitMods=["+108 to maximum Life"])))
    row = rows[0]
    assert (row.family, row.affix, row.tier_ambiguous, row.tier_mismatch) == (
        "prefix:IncreasedLife",
        "prefix",
        False,
        False,
    )


def golden_trade_result(name: str) -> dict:
    return copy.deepcopy(load(GOLDEN / name / "trade.json")["result"])


def reordered_trade() -> dict:
    """Golden 001 with ``extended.mods.explicit`` in reverse order: hashes stay aligned with the
    lines, and their inner lists point at the reversed positions.

    The real-API shape of ``extended.hashes`` must be confirmed against a recorded response in
    Phase 2; this is the shape the normaliser assumes.
    """
    result = golden_trade_result("001-ring-keep-life-attack")
    ext = result["item"]["extended"]
    count = len(ext["mods"]["explicit"])
    ext["mods"]["explicit"] = list(reversed(ext["mods"]["explicit"]))
    ext["hashes"]["explicit"] = [
        [h, [count - 1 - i for i in idxs]] for h, idxs in ext["hashes"]["explicit"]
    ]
    return result


def test_trade_hashes_are_aligned_with_lines_not_mods(normaliser):
    out = normaliser.trade_result(reordered_trade())
    expected = expected_of(GOLDEN / "001-ring-keep-life-attack")
    assert_matches_golden(out.to_expected(), expected)
    assert not any(m.tier_mismatch for m in out.mods)


def test_null_inner_mod_index_list_behaves_like_empty(normaliser):
    result = reordered_trade()
    result["item"]["extended"]["hashes"]["explicit"][1][1] = None
    out = normaliser.trade_result(result)
    # no hint for that line: the ladder still resolves it, nothing is lost or mismatched
    assert len(out.mods) == 5 and out.unrecognised == []
    assert not any(m.tier_mismatch for m in out.mods)


def test_trade_unique_skips_hints(normaliser):
    result = golden_trade_result("007-unique-ring-not-scored")
    result["item"]["extended"] = {"mods": None, "hashes": {"explicit": [["h", None]]}}
    out = normaliser.trade_result(result)
    assert out.mods == [] and out.item["rarity"] == "Unique"


def test_trade_crafted_hint_filters_the_affix(normaliser):
    result = golden_trade_result("001-ring-keep-life-attack")
    item = result["item"]
    item["craftedMods"] = ["+30% to Fire Resistance"]
    ext = item["extended"]
    magnitude = {"hash": "crafted.stat_3372524247", "min": "30", "max": "30"}
    ext["mods"]["crafted"] = [{"name": "", "tier": "S1", "level": 1, "magnitudes": [magnitude]}]
    ext["hashes"]["crafted"] = [["crafted.stat_3372524247", [0]]]
    out = normaliser.trade_result(result)
    crafted = next(m for m in out.mods if m.source == "crafted")
    assert crafted.affix == "suffix"


# ---------------------------------------------------------------- re-review fixes


def test_trade_line_with_two_contributing_mods_is_unrecognised(normaliser):
    result = golden_trade_result("001-ring-keep-life-attack")
    result["item"]["extended"]["hashes"]["explicit"][0][1] = [0, 1]  # the life line is merged
    out = normaliser.trade_result(result)
    assert out.unrecognised == ["+108 to maximum Life"]
    assert "base_maximum_life" not in {s for m in out.mods for s in m.stat_ids}
    assert len(out.mods) == 4  # the implicit and three resolved resistances
    assert out.item["open_prefixes"] is None and out.item["open_suffixes"] is None
    assert "open_prefixes" not in out.to_expected()["item"]


def test_merged_crafted_trade_line_is_unrecognised(normaliser):
    result = golden_trade_result("001-ring-keep-life-attack")
    item = result["item"]
    item["craftedMods"] = ["+30% to Fire Resistance"]
    item["extended"]["mods"]["crafted"] = []
    item["extended"]["hashes"]["crafted"] = [["crafted.stat_3372524247", [0, 1]]]
    out = normaliser.trade_result(result)
    assert "+30% to Fire Resistance" in out.unrecognised
    assert not any(m.source == "crafted" for m in out.mods)


def test_a_hybrid_half_is_never_stored_even_when_the_other_half_is_ambiguous(normaliser):
    # H1: 8% ES only the hybrid gives, 17% stun fits hybrid T1 or pure T4: both lines are dropped
    result = normaliser.character_item(
        boots(["8% increased Energy Shield", "17% increased Stun and Block Recovery"])
    )
    assert result.mods == []
    assert set(result.unrecognised) == {
        "8% increased Energy Shield",
        "17% increased Stun and Block Recovery",
    }


def test_a_complete_hybrid_is_still_stored(normaliser):
    # Both halves only the hybrid gives (ES 8%, stun 7% = hybrid T6): resolved as one mod
    result = normaliser.character_item(
        boots(["8% increased Energy Shield", "7% increased Stun and Block Recovery"])
    )
    assert [(m.family, m.tier) for m in result.mods] == [
        ("prefix:LocalEnergyShieldAndStunRecoveryPercent", 6)
    ] * 2
    assert result.unrecognised == []

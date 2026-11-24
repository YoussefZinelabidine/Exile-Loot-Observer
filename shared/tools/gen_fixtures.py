"""Orchestrator tool: builds shared/fixtures (fixture snapshot + golden seed items) from downloaded RePoE + poe.re data.

Inputs: <dir>/data/repoe/{mods,stat_translations,base_items}.json, <dir>/data/repoe/version.txt and
<dir>/data/poere/Generated.Item.ENGLISH.min.json (poe.re 3.30.0.4.3). Data is downloaded separately, never by this script.

Usage: python -I shared/tools/gen_fixtures.py <dir_with_data_subfolder> <repo_root>
Re-run after changing the scoring rules or ITEMS; it rewrites shared/fixtures/snapshot and shared/fixtures/golden.
"""
import gzip
import hashlib
import json
import math
import sys
from pathlib import Path

SCRATCH = Path(sys.argv[1])
REPO = Path(sys.argv[2])
DATA = SCRATCH / "data"
OUT = REPO / "shared" / "fixtures"

mods = json.loads((DATA / "repoe/mods.json").read_text(encoding="utf-8"))
bases_all = json.loads((DATA / "repoe/base_items.json").read_text(encoding="utf-8"))
st_all = json.loads((DATA / "repoe/stat_translations.json").read_text(encoding="utf-8"))
poere_items = json.loads((DATA / "poere/Generated.Item.ENGLISH.min.json").read_text(encoding="utf-8"))
REPOE_VERSION = (DATA / "repoe/version.txt").read_text().strip()
POERE_PATCH = "3.30.0.4.3"
POERE_COMMIT = "17bc109"
GAME_PATCH = REPOE_VERSION

CLASS_INFO = {
    # item_class: (label, game "Item Class:" text, poe.re basetype, max_prefix, max_suffix, bench_craftable)
    "Ring": ("Ring", "Rings", "Rings", 3, 3, True),
    "Amulet": ("Amulet", "Amulets", "Amulets", 3, 3, True),
    "Boots": ("Boots", "Boots", "Boots", 3, 3, True),
    "Gloves": ("Gloves", "Gloves", "Gloves", 3, 3, True),
    "Body Armour": ("Body Armour", "Body Armours", "Body Armours", 3, 3, True),
    "Jewel": ("Jewel", "Jewels", "Jewels", 2, 2, False),
    "AbyssJewel": ("Abyss Jewel", "Abyss Jewels", "Abyss Jewels", 2, 2, False),
}
TRADE_CAT = {"Ring": "accessory.ring", "Amulet": "accessory.amulet", "Boots": "armour.boots",
             "Gloves": "armour.gloves", "Body Armour": "armour.chest", "Jewel": "jewel.base",
             "AbyssJewel": "jewel.abyss"}
FIXTURE_BASES = ["Diamond Ring", "Gold Ring", "Onyx Amulet", "Sorcerer Boots", "Sorcerer Gloves",
                 "Vaal Regalia", "Cobalt Jewel", "Ghastly Eye Jewel"]


def base(name):
    return next(v for v in bases_all.values() if v["name"] == name and v.get("release_state") == "released")


def spawn_weight(m, tags):
    for sw in m["spawn_weights"]:
        if sw["tag"] in tags:
            return sw["weight"]
    return 0


def families_for(bname):
    b = base(bname)
    tags = set(b["tags"])
    fam = {}
    for mid, m in mods.items():
        if m["domain"] != b["domain"] or m["generation_type"] not in ("prefix", "suffix"):
            continue
        if m.get("is_essence_only") or "Royale" in mid:
            continue
        w = spawn_weight(m, tags)
        if w > 0:
            fam.setdefault(f"{m['generation_type']}:{m['type']}", []).append((mid, m, w))
    for k in fam:
        fam[k].sort(key=lambda t: (-t[1]["required_level"], t[0]))
    return b, fam


def tier_set_id(b):
    return f"{b['item_class']}|{'+'.join(sorted(b['tags']))}"


# ---------------------------------------------------------------- daily (synthetic demand)
# core lists: (stat_id, demand_low). demand = 1.25 * demand_low. Order = rank.
DEMAND = {
    "Ring": {
        "arch:life-attack": [("base_maximum_life", .30), ("base_fire_damage_resistance_%", .20),
                             ("base_cold_damage_resistance_%", .20), ("base_lightning_damage_resistance_%", .20),
                             ("base_chaos_damage_resistance_%", .15), ("accuracy_rating", .10),
                             ("elemental_damage_with_attack_skills_+%", .08)],
        "skill:lightning-strike": [("elemental_damage_with_attack_skills_+%", .35), ("accuracy_rating", .25),
                                   ("base_maximum_life", .20), ("base_lightning_damage_resistance_%", .15),
                                   ("base_chaos_damage_resistance_%", .12), ("additional_dexterity", .10)],
        "arch:es-spell": [("base_maximum_energy_shield", .30), ("base_cast_speed_+%", .20),
                          ("base_chaos_damage_resistance_%", .15), ("additional_intelligence", .12),
                          ("base_maximum_mana", .10), ("base_cold_damage_resistance_%", .08)],
    },
    "Amulet": {
        "arch:life-spell": [("spell_damage_+%", .30), ("base_cast_speed_+%", .25), ("base_maximum_life", .20),
                            ("critical_strike_chance_+%", .10), ("base_critical_strike_multiplier_+", .10),
                            ("base_resist_all_elements_%", .05)],
        "arch:life-attack": [("base_maximum_life", .30), ("base_critical_strike_multiplier_+", .20),
                             ("accuracy_rating", .15), ("base_fire_damage_resistance_%", .10),
                             ("base_cold_damage_resistance_%", .10), ("base_lightning_damage_resistance_%", .10)],
    },
    "Boots": {
        "arch:life-attack": [("base_maximum_life", .30), ("base_movement_velocity_+%", .30),
                             ("base_fire_damage_resistance_%", .15), ("base_cold_damage_resistance_%", .15),
                             ("base_lightning_damage_resistance_%", .15), ("base_chaos_damage_resistance_%", .10)],
        "arch:es-spell": [("base_movement_velocity_+%", .30), ("local_energy_shield", .25),
                          ("local_energy_shield_+%", .20), ("base_chaos_damage_resistance_%", .10),
                          ("base_cold_damage_resistance_%", .08), ("base_fire_damage_resistance_%", .08)],
    },
    "Gloves": {
        "arch:life-attack": [("attack_speed_+%", .30), ("base_maximum_life", .20),
                             ("base_fire_damage_resistance_%", .20), ("base_cold_damage_resistance_%", .20),
                             ("base_lightning_damage_resistance_%", .20), ("base_chaos_damage_resistance_%", .15),
                             ("accuracy_rating", .10)],
    },
    "Body Armour": {
        "arch:es-spell": [("local_energy_shield_+%", .30), ("local_energy_shield", .25),
                          ("base_maximum_mana", .10), ("energy_shield_recharge_rate_+%", .10),
                          ("additional_intelligence", .08), ("base_chaos_damage_resistance_%", .08),
                          ("base_cold_damage_resistance_%", .06)],
    },
    "Jewel": {
        "arch:life-attack": [("maximum_life_+%", .35), ("attack_speed_+%", .15), ("base_resist_all_elements_%", .10),
                             ("attack_and_cast_speed_+%", .10), ("base_chaos_damage_resistance_%", .08)],
        "arch:es-spell": [("maximum_energy_shield_+%", .30), ("base_cast_speed_+%", .20), ("spell_damage_+%", .15),
                          ("base_resist_all_elements_%", .10), ("energy_shield_recharge_rate_+%", .10),
                          ("base_chaos_damage_resistance_%", .08)],
    },
    "AbyssJewel": {
        "arch:life-minion": [("minion_maximum_life_+%", .25), ("base_maximum_life", .20),
                             ("minion_elemental_resistance_%", .12),
                             ("minion_damage_+%_if_have_used_a_minion_skill_recently", .10),
                             ("minion_movement_speed_+%", .08), ("minion_life_regeneration_rate_per_second", .06),
                             ("base_resist_all_elements_%", .05)],
        "skill:raise-spectre": [("minion_maximum_life_+%", .30), ("base_maximum_life", .20),
                                ("minion_elemental_resistance_%", .20), ("minion_movement_speed_+%", .10)],
    },
}

NODES = [
    dict(id="all", level="all", parent=None, label="All builds", accounts=4000, effective_accounts=3720.0,
         shown_on_own=True, low_data=False),
    dict(id="arch:life-attack", level="archetype", parent="all", label="Life · Attack", defence="life",
         damage="attack", flags=[], accounts=1800, effective_accounts=1690.5, shown_on_own=True, low_data=False),
    dict(id="skill:lightning-strike", level="main_skill", parent="arch:life-attack", label="Lightning Strike",
         defence="life", damage="attack", flags=[], main_skill="Lightning Strike", accounts=400,
         effective_accounts=371.2, shown_on_own=True, low_data=False),
    dict(id="arch:es-spell", level="archetype", parent="all", label="Energy Shield · Spell", defence="es",
         damage="spell", flags=[], accounts=900, effective_accounts=842.0, shown_on_own=True, low_data=False),
    dict(id="arch:life-minion", level="archetype", parent="all", label="Life · Minion", defence="life",
         damage="minion", flags=[], accounts=600, effective_accounts=556.3, shown_on_own=True, low_data=False),
    dict(id="skill:raise-spectre", level="main_skill", parent="arch:life-minion", label="Raise Spectre",
         defence="life", damage="minion", flags=[], main_skill="Raise Spectre", accounts=160,
         effective_accounts=141.5, shown_on_own=False, low_data=True),
    dict(id="arch:life-spell", level="archetype", parent="all", label="Life · Spell", defence="life",
         damage="spell", flags=[], accounts=150, effective_accounts=61.0, shown_on_own=True, low_data=True),
]
THRESHOLDS = dict(keep_fit=0.5, price_check_fit=0.25, min_build_accounts=100, craftable_discount=0.0,
                  base_value_min_chaos=20, base_value_min_ilvl=84)
TIER_GATE = dict(top_fraction=0.4, always_top_tiers=2)
BASE_VALUES = [
    dict(base="Vaal Regalia", min_ilvl=86, influence=None, chaos=12, worn_share=0.21),
    dict(base="Sorcerer Gloves", min_ilvl=84, influence=None, chaos=5, worn_share=0.18),
    dict(base="Sorcerer Boots", min_ilvl=84, influence=None, chaos=6, worn_share=0.15),
]
SPECIAL = [dict(kind="unique", name="Ventor's Gamble", base="Gold Ring", variant=None, links=None, chaos=3)]


def tier_letter(rank):
    return "S" if rank < 2 else ("A" if rank < 4 else "B")


def build_daily():
    demand = {}
    for cls, nodes in DEMAND.items():
        demand[cls] = {}
        all_stats = {}
        for nid, core in nodes.items():
            mlist = []
            for rank, (sid, dl) in enumerate(core):
                mlist.append(dict(stat_id=sid, core=True, demand=round(dl * 1.25, 4), demand_low=dl,
                                  share=round(min(0.95, 0.2 + dl), 4), effective_obs=round(60 - rank * 5.0, 1),
                                  demand_tier=tier_letter(rank)))
                all_stats[sid] = max(all_stats.get(sid, 0), dl)
            eff = {"arch": 0.42, "skil": 0.09}.get(nid[:4], 0.1) * 3600
            demand[cls][nid] = dict(effective_items=round(eff + 7 * len(core), 1), mods=mlist)
        allm = sorted(all_stats.items(), key=lambda t: -t[1])
        demand[cls]["all"] = dict(effective_items=float(round(3400 + 25 * len(allm))), mods=[
            dict(stat_id=s, core=i < 8, demand=round(d * 1.1, 4), demand_low=round(d * 0.9, 4),
                 share=round(min(0.95, 0.15 + d), 4), effective_obs=80.0, demand_tier=tier_letter(i))
            for i, (s, d) in enumerate(allm)])
    return dict(
        schema="elo.daily", schema_version=1, league="Covens", patch_ref=GAME_PATCH, crawl_date="2026-11-23",
        built_at="2026-11-23T05:00:00Z", validated=True,
        freshness=dict(characters_used=8400, accounts_used=4000, oldest_gear_days=6.5, ladder_coverage=0.71),
        params=dict(thresholds=dict(default=THRESHOLDS, by_item_class={}), tier_gate=TIER_GATE,
                    min_effective_accounts_own_node=150, core_min_effective_obs=10, stale_after_days=3),
        build_nodes=NODES, demand=demand, base_values=BASE_VALUES, special_prices=SPECIAL,
        currency=dict(divine_chaos=180))


# ---------------------------------------------------------------- items
# (family key, tier, value-or-None(=mid), source)
ITEMS = [
    dict(id="001-ring-keep-life-attack", desc="Rare ring with life and two qualifying resistances: KEEP for Life · Attack.",
         base="Diamond Ring", name="Gale Coil", ilvl=84,
         mods=[("prefix:IncreasedLife", 1, 108, "explicit"), ("suffix:FireResistance", 1, 47, "explicit"),
               ("suffix:ColdResistance", 2, 44, "explicit"), ("suffix:LightningResistance", 5, None, "explicit")]),
    dict(id="002-abyss-keep-life-minion", desc="Abyss jewel with life, minion life and minion resistances: KEEP for Life · Minion.",
         base="Ghastly Eye Jewel", name="Grim Eye", ilvl=84,
         mods=[("prefix:AbyssJewelLife", 1, 38, "explicit"), ("suffix:MinionLifeForJewel", 1, 11, "explicit"),
               ("suffix:MinionElementalResistancesForJewel", 1, 9, "explicit")]),
    dict(id="003-jewel-partial-life-attack", desc="Cobalt jewel with one strong core mod: PRICE CHECK (partial fit).",
         base="Cobalt Jewel", name="Storm Spark", ilvl=80,
         mods=[("prefix:PercentIncreasedLifeForJewel", 1, 6, "explicit"),
               ("suffix:StunRecoveryForJewel", 1, 30, "explicit")]),
    dict(id="004-boots-no-buyer", desc="Boots with no core mods for any build: NO BUYER.",
         base="Sorcerer Boots", name="Dusk Stride", ilvl=75,
         mods=[("prefix:IncreasedMana", 6, None, "explicit"), ("suffix:Intelligence", 5, None, "explicit"),
               ("suffix:StunRecovery", 3, None, "explicit")]),
    dict(id="005-body-corrupted-partial", desc="Corrupted body armour with one qualifying ES mod and open slots: PRICE CHECK, open slots ignored.",
         base="Vaal Regalia", name="Ghoul Shroud", ilvl=86, corrupted=True,
         mods=[("prefix:LocalEnergyShieldPercent", 1, None, "explicit"), ("prefix:LocalEnergyShield", 8, None, "explicit"),
               ("suffix:Intelligence", 7, None, "explicit")]),
    dict(id="006-gloves-fractured-core", desc="Gloves whose only core mod is fractured life: NO BUYER lifted to PRICE CHECK by the fractured boost.",
         base="Sorcerer Gloves", name="Rapture Grasp", ilvl=84,
         mods=[("prefix:IncreasedLife", 2, None, "fractured"), ("prefix:IncreasedMana", 4, None, "explicit"),
               ("suffix:LifeGainedFromEnemyDeath", 2, None, "explicit")]),
    dict(id="007-unique-ring-not-scored", desc="Unique ring: not scored, poe.ninja price instead.", unique=True,
         base="Gold Ring", name="Ventor's Gamble", ilvl=83, mods=[]),
    dict(id="008-french-client-unsupported", desc="Item copied from the French client: unsupported language.", french=True,
         base="Diamond Ring", name=None, ilvl=84, mods=[]),
    dict(id="009-amulet-low-data-cap", desc="Amulet that fits Life · Spell well enough for KEEP, but that build is low data: capped at PRICE CHECK.",
         base="Onyx Amulet", name="Doom Beads", ilvl=84,
         mods=[("prefix:SpellDamage", 1, None, "explicit"), ("suffix:IncreasedCastSpeed", 1, None, "explicit"),
               ("prefix:IncreasedLife", 3, None, "explicit")]),
]

used_families = {}  # tier_set_id -> set(family keys)
base_cache = {}


def fam_of(bname):
    if bname not in base_cache:
        base_cache[bname] = families_for(bname)
    return base_cache[bname]


def resolve_mod(bname, fkey, tier, value):
    b, fam = fam_of(bname)
    ladder = fam[fkey]
    mid, m, w = ladder[tier - 1]
    stats = m["stats"]
    if value is None:
        value = (stats[0]["min"] + stats[0]["max"]) / 2
        value = math.floor(value) if isinstance(stats[0]["min"], int) else round(value, 1)
    assert stats[0]["min"] <= value <= stats[0]["max"], (fkey, tier, value)
    return dict(mod_id=mid, mod=m, tier=tier, ladder=len(ladder), values=[value] + [s["min"] for s in stats[1:]],
                family=fkey)


def n_qualifying(ladder_len):
    return max(TIER_GATE["always_top_tiers"], math.ceil(TIER_GATE["top_fraction"] * ladder_len))


# ---------------------------------------------------------------- patch
import re as _re


def clean_markup(t):
    return _re.sub(r"\[(?:[^\]|]*\|)?([^\]]*)\]", r"\1", t)

def translation_for(sid):
    for e in st_all:
        if sid in e.get("ids", []):
            return e
    return None


def build_patch(core_stats_by_class, item_families):
    item_classes, bases_out, tier_sets, trans, trade, frags = {}, {}, {}, [], {}, {}
    seen_trans = set()
    stat_ids = set()
    for bname in FIXTURE_BASES:
        b, fam = fam_of(bname)
        cls = b["item_class"]
        label, _, poere_bt, mp, ms, bench = CLASS_INFO[cls]
        tsid = tier_set_id(b)
        wanted = {k for k, L in fam.items() if any(s["id"] in core_stats_by_class.get(cls, set()) for s in L[0][1]["stats"])}
        wanted |= item_families.get(bname, set())
        ts = tier_sets.setdefault(tsid, {})
        for k in sorted(wanted):
            L = fam[k]
            ts[k] = dict(affix=k.split(":")[0], stat_ids=[s["id"] for s in L[0][1]["stats"]], tiers=[
                dict(tier=i + 1, mod_id=mid, name=m["name"], required_level=m["required_level"], spawn_weight=w,
                     stats=[dict(id=s["id"], min=s["min"], max=s["max"]) for s in m["stats"]])
                for i, (mid, m, w) in enumerate(L)])
            stat_ids.update(ts[k]["stat_ids"])
        impl_ids = [s["id"] for i in b["implicits"] for s in mods[i]["stats"]]
        stat_ids.update(impl_ids)
        bases_out[bname] = dict(item_class=cls, tier_set=tsid, drop_level=b["drop_level"], implicit_stat_ids=impl_ids)
        tags = set(b["tags"])
        craftable = sorted({s["id"] for m in mods.values() if m["domain"] == "crafted" and spawn_weight(m, tags) > 0
                            for s in m["stats"]})
        item_classes[cls] = dict(scored=True, label=label, max_prefixes=mp, max_suffixes=ms, bench_craftable=bench,
                                 craftable_stat_ids=[], poere_basetype=poere_bt,
                                 trade_category=TRADE_CAT[cls])
    for sid in sorted(stat_ids):
        e = translation_for(sid)
        if e is None:
            continue
        key = tuple(e["ids"])
        if key not in seen_trans:
            seen_trans.add(key)
            trans.append(dict(ids=e["ids"], english=[dict(string=clean_markup(x["string"]), format=x["format"],
                                                          condition=[{k: c.get(k) for k in ("min", "max", "negated")} for c in x["condition"]],
                                                          index_handlers=x.get("index_handlers") or [])
                                                     for x in e["English"]]))
        if len(e["ids"]) == 1:
            t = {ts["type"]: ts["id"] for ts in (e.get("trade_stats") or [])
                 if ts["type"] in ("explicit", "implicit", "fractured", "crafted")}
            if t:
                trade[sid] = t
    for cls, info in CLASS_INFO.items():
        poere = next(x for x in poere_items if x["basetype"] == info[2])
        cls_stats = {s for ts_id, ts in tier_sets.items() if ts_id.startswith(cls + "|") for f in ts.values() for s in f["stat_ids"]}
        out = []
        for cat in poere["categoryRegex"]:
            if cat["category"] not in ("prefix", "suffix"):
                continue
            for mdf in cat["modifiers"]:
                ids = [s["id"] for s in mdf["stats"]]
                if ids and set(ids) <= cls_stats:
                    out.append(dict(stat_ids=ids, affix=mdf["affixtype"].lower(), category=cat["category"],
                                    text=mdf["desc"], regex=mdf["regex"],
                                    number=dict(before=mdf["before"], on=mdf["on"], after=mdf["after"])))
        frags[cls] = out
    return dict(schema="elo.patch", schema_version=1, game_patch=GAME_PATCH,
                sources=dict(repoe_version=REPOE_VERSION, poere_patch=POERE_PATCH, poere_commit=POERE_COMMIT),
                built_at="2026-11-23T04:00:00Z", item_classes=item_classes, bases=bases_out, tier_sets=tier_sets,
                translations=trans, trade_ids=trade, search_fragments=frags)


# ---------------------------------------------------------------- rendering
def fmt_num(v):
    return str(int(v)) if float(v).is_integer() else str(v)


def mod_line_values(m, values):
    """Render RePoE mod text with rolled values, e.g. '+(100-114) to maximum Life' -> '+108 to maximum Life'."""
    text = m["text"]
    out, vi = "", 0
    i = 0
    while i < len(text):
        if text[i] == "(" and "-" in text[i:text.index(")", i)] and vi < len(values):
            j = text.index(")", i)
            out += fmt_num(values[vi])
            vi += 1
            i = j + 1
        else:
            out += text[i]
            i += 1
    return out.replace("[PlayerItemRarity|", "").replace("]", "")


def adv_line(m, values):
    text = m["text"].replace("[PlayerItemRarity|", "").replace("]", "")
    out, vi, i = "", 0, 0
    while i < len(text):
        if text[i] == "(" and ")" in text[i:] and "-" in text[i:text.index(")", i)] and vi < len(values):
            j = text.index(")", i)
            out += fmt_num(values[vi]) + text[i:j + 1]
            vi += 1
            i = j + 1
        else:
            out += text[i]
            i += 1
    return out


def tags_label(m):
    tags = [t for t in m.get("implicit_tags", []) if t not in ("resource",)]
    return ", ".join(t.replace("_", " ").title() for t in tags)


def fake_id(seed):
    return hashlib.sha256(seed.encode()).hexdigest()


def game_text(item, b, resolved):
    cls_text = CLASS_INFO[b["item_class"]][1]
    rarity = "Unique" if item.get("unique") else "Rare"
    lines = [f"Item Class: {cls_text}", f"Rarity: {rarity}", item["name"], item["base"], "--------"]
    props = b.get("properties") or {}
    es = props.get("energy_shield")
    if es:
        flat = sum(r["values"][0] for r in resolved if r["mod"]["stats"][0]["id"] == "local_energy_shield")
        pct = sum(r["values"][0] for r in resolved if r["mod"]["stats"][0]["id"] == "local_energy_shield_+%")
        total = math.floor(((es["min"] + es["max"]) // 2 + flat) * (1 + pct / 100))
        aug = " (augmented)" if (flat or pct) else ""
        lines += [f"Energy Shield: {total}{aug}", "--------"]
    breq = b.get("requirements") or {}
    if b["item_class"] != "Jewel":
        req = max([0] + [r["mod"]["required_level"] for r in resolved]) * 4 // 5
        req = max(req, breq.get("level") or 0, b["drop_level"] if b["item_class"] != "AbyssJewel" else 0)
        lines += ["Requirements:", f"Level: {req}"]
        for key, lab in (("strength", "Str"), ("dexterity", "Dex"), ("intelligence", "Int")):
            if breq.get(key):
                lines.append(f"{lab}: {breq[key]}")
        lines.append("--------")
    if b["item_class"] in ("Body Armour",):
        lines += ["Sockets: B-B-B B ", "--------"]
    elif b["item_class"] in ("Boots", "Gloves"):
        lines += ["Sockets: B-B B ", "--------"]
    lines += [f"Item Level: {item['ilvl']}", "--------"]
    for imp in b["implicits"]:
        m = mods[imp]
        lab = tags_label(m)
        lines.append("{ Implicit Modifier" + (f" — {lab}" if lab else "") + " }")
        vals = [math.floor((s["min"] + s["max"]) / 2) for s in m["stats"]]
        lines.append(adv_line(m, vals) + " (implicit)")
        lines.append("--------")
    for r in sorted(resolved, key=lambda r: (r["family"].split(":")[0] != "prefix",)):
        m = r["mod"]
        kind = "Prefix" if m["generation_type"] == "prefix" else "Suffix"
        lab = tags_label(m)
        lines.append(f'{{ {kind} Modifier "{m["name"]}" (Tier: {r["tier"]})' + (f" — {lab}" if lab else "") + " }")
        line = adv_line(m, r["values"])
        if r["source"] == "fractured":
            line += " (fractured)"
        lines.append(line)
    tail = []
    if b["item_class"] == "Jewel":
        tail.append("Place into an allocated Jewel Socket on the Passive Skill Tree. Right click to remove from the Socket.")
    elif b["item_class"] == "AbyssJewel":
        tail.append("Place into an Abyssal Socket on an Item or into an allocated Jewel Socket on the Passive Skill Tree. Right click to remove from the Socket.")
    if item.get("corrupted"):
        tail.append("Corrupted")
    if any(r["source"] == "fractured" for r in resolved):
        tail.append("Fractured Item")
    for t in tail:
        lines += ["--------", t]
    return "\n".join(lines) + "\n"


UNIQUE_TEXT = """Item Class: Rings
Rarity: Unique
Ventor's Gamble
Gold Ring
--------
Requirements:
Level: 65
--------
Item Level: 83
--------
{ Implicit Modifier — Drop }
+12(6-15)% to Item Rarity (implicit)
--------
{ Unique Modifier — Life }
+45(0-60) to maximum Life
{ Unique Modifier — Drop }
4(-10-10)% increased Quantity of Items found
{ Unique Modifier — Drop }
+22(0-40)% to Item Rarity
{ Unique Modifier — Elemental, Fire, Resistance }
+31(-25-50)% to Fire Resistance
{ Unique Modifier — Elemental, Cold, Resistance }
-8(-25-50)% to Cold Resistance
{ Unique Modifier — Elemental, Lightning, Resistance }
+40(-25-50)% to Lightning Resistance
"""

FRENCH_TEXT = """Classe d'objet: Anneaux
Rareté: Rare
Boucle de la Tempête
Anneau de diamant
--------
Prérequis:
Niveau: 35
--------
Niveau de l'objet: 84
--------
25% d'augmentation des chances globales de coup critique (implicite)
--------
+108 à la Vie maximale
+47% à la Résistance au feu
+44% à la Résistance au froid
"""

INVENTORY = {"Ring": "Ring", "Amulet": "Amulet", "Boots": "Boots", "Gloves": "Gloves", "Body Armour": "BodyArmour",
             "Jewel": "PassiveJewels", "AbyssJewel": "Belt"}


def api_item(item, b, resolved, with_extended, trade_ids):
    frame = 3 if item.get("unique") else 2
    d = dict(verified=False, w=1, h=1, icon="", league="Covens", id=fake_id(item["id"]), name=item["name"],
             typeLine=item["base"], baseType=item["base"], rarity="Unique" if item.get("unique") else "Rare",
             identified=True, ilvl=item["ilvl"], frameType=frame)
    impl = []
    for imp in b["implicits"]:
        m = mods[imp]
        impl.append(mod_line_values(m, [math.floor((s["min"] + s["max"]) / 2) for s in m["stats"]]))
    if impl:
        d["implicitMods"] = impl
    if item.get("unique"):
        d["implicitMods"] = ["+12% to Item Rarity"]
        d["explicitMods"] = ["+45 to maximum Life", "4% increased Quantity of Items found",
                             "+22% to Item Rarity", "+31% to Fire Resistance",
                             "-8% to Cold Resistance", "+40% to Lightning Resistance"]
    else:
        ex = [mod_line_values(r["mod"], r["values"]) for r in resolved if r["source"] == "explicit"]
        fr = [mod_line_values(r["mod"], r["values"]) for r in resolved if r["source"] == "fractured"]
        if ex:
            d["explicitMods"] = ex
        if fr:
            d["fracturedMods"] = fr
            d["fractured"] = True
    if item.get("corrupted"):
        d["corrupted"] = True
    if with_extended and not item.get("unique"):
        ext_mods, hashes = {}, {}
        for src in ("explicit", "fractured"):
            rs = [r for r in resolved if r["source"] == src]
            if not rs:
                continue
            ext_mods[src] = []
            hashes[src] = []
            for idx, r in enumerate(rs):
                m = r["mod"]
                tid = trade_ids.get(m["stats"][0]["id"], {}).get(src)
                ext_mods[src].append(dict(name=m["name"], tier=("P" if m["generation_type"] == "prefix" else "S") + str(r["tier"]),
                                          level=m["required_level"],
                                          magnitudes=[dict(hash=tid, min=fmt_num(s["min"]), max=fmt_num(s["max"])) for s in m["stats"]]))
                hashes[src].append([tid, [idx]])
        d["extended"] = dict(mods=ext_mods, hashes=hashes)
    return d


def character_json(item, b, resolved, trade_ids):
    it = api_item(item, b, resolved, False, trade_ids)
    if b["item_class"] == "AbyssJewel":
        it.update(socket=0)
        return dict(_fixture_note="Abyss jewel in the shape of one entry of a belt's 'socketedItems' in get-items. Hand-written; replace with a recorded response.",
                    item=it)
    it.update(inventoryId=INVENTORY[b["item_class"]], x=0, y=0)
    return dict(_fixture_note="Single item in the shape of one entry of get-items 'items'. Hand-written; replace with a recorded response.",
                item=it)


def trade_json(item, b, resolved, trade_ids):
    it = api_item(item, b, resolved, True, trade_ids)
    return dict(_fixture_note="One result of /api/trade/fetch. Hand-written; replace with a recorded response.",
                result=dict(id=fake_id("trade" + item["id"]),
                            listing=dict(method="psapi", indexed="2026-11-22T18:00:00Z",
                                         stash=dict(name="Fixture", x=0, y=0),
                                         account=dict(name="FixtureAccount#0000", lastCharacterName="FixtureChar",
                                                      language="en_US", realm="pc"),
                                         price=dict(type="~price", amount=5, currency="chaos")),
                            item=it))


# ---------------------------------------------------------------- reference scoring (fixture rules, see README)
def score(item, b, resolved, daily, patch):
    cls = b["item_class"]
    ci = patch["item_classes"][cls]
    k = ci["max_prefixes"] + ci["max_suffixes"]
    th = daily["params"]["thresholds"]["default"]
    nodes = {n["id"]: n for n in daily["build_nodes"]}
    qual = []
    for r in resolved:
        r["qualifies"] = r["tier"] <= n_qualifying(r["ladder"])
        if r["qualifies"]:
            qual.append(r)
    qual_stats = {s["id"] for r in qual for s in r["mod"]["stats"]}
    fits = {}
    for nid, nd in daily["demand"].get(cls, {}).items():
        n = nodes[nid]
        if nid == "all" or not n["shown_on_own"]:
            continue
        core = [m for m in nd["mods"] if m["core"]]
        den = sum(sorted((m["demand_low"] for m in core), reverse=True)[:k])
        matched = [m for m in core if m["stat_id"] in qual_stats]
        num = sum(m["demand_low"] for m in matched)
        fits[nid] = (num / den if den else 0.0, [m["stat_id"] for m in matched], n)
    meaningful = {nid: v for nid, v in fits.items() if v[2]["accounts"] >= th["min_build_accounts"]}
    best = max(meaningful.items(), key=lambda t: t[1][0]) if meaningful else None
    reasons, low_data = [], False
    open_p = ci["max_prefixes"] - sum(1 for r in resolved if r["mod"]["generation_type"] == "prefix")
    open_s = ci["max_suffixes"] - sum(1 for r in resolved if r["mod"]["generation_type"] == "suffix")
    result, buyer, fit, counted = "NO_BUYER", None, (best[1][0] if best else 0.0), []
    if best and best[1][0] >= th["keep_fit"] and len(best[1][1]) >= 2:
        buyer, counted = best[0], best[1][1]
        reasons.append("keep_fit")
        if best[1][2]["low_data"]:
            result, low_data = "PRICE_CHECK", True
            reasons.append("cap_low_data")
        elif not daily["validated"]:
            result = "PRICE_CHECK"
            reasons.append("cap_not_validated")
        else:
            result = "KEEP"
    elif best and best[1][0] >= th["price_check_fit"]:
        result, buyer, counted = "PRICE_CHECK", best[0], best[1][1]
        reasons.append("partial_fit")
        if best[1][2]["low_data"]:
            low_data = True
            reasons.append("cap_low_data")
    else:
        niche = [(nid, v) for nid, v in fits.items() if nid not in meaningful and v[0] >= th["keep_fit"] and len(v[1]) >= 2]
        if niche:
            nid, v = max(niche, key=lambda t: t[1][0])
            result, buyer, fit, counted = "PRICE_CHECK", nid, v[0], v[1]
            reasons.append("niche_build_fit")
    if item.get("corrupted") and (open_p or open_s):
        reasons.append("corrupted_open_slots_ignored")
    if result == "NO_BUYER":
        fr_core = [r for r in resolved if r["source"] == "fractured" and r["qualifies"]
                   and any(s["id"] in fits[nid][1] or any(m["stat_id"] == s["id"] and m["core"] for m in daily["demand"][cls][nid]["mods"])
                           for nid in meaningful for s in r["mod"]["stats"])]
        if fr_core:
            result = "PRICE_CHECK"
            reasons.append("boost_fractured_core_mod")
        bv = [x for x in daily.get("base_values", []) if x["base"] == item["base"] and item["ilvl"] >= x["min_ilvl"]
              and item["ilvl"] >= th["base_value_min_ilvl"] and x["chaos"] >= th["base_value_min_chaos"]]
        if bv:
            result = "PRICE_CHECK"
            reasons.append("boost_base_value")
        if not item.get("corrupted") and (open_p or open_s) and any(len(v[1]) >= 2 for v in meaningful.values()):
            result = "PRICE_CHECK"
            reasons.append("boost_crafting_potential")
        if result == "NO_BUYER":
            reasons.append("no_fit")
    return dict(result=result, best_buyer=buyer, fit=round(fit, 4), low_data=low_data, reasons=reasons,
                counted_stat_ids=counted), open_p, open_s, fits


def main():
    daily = build_daily()
    core_stats = {cls: {m["stat_id"] for nd in nodes.values() for m in nd["mods"]} for cls, nodes in daily["demand"].items()}
    item_fams = {}
    for it in ITEMS:
        for f, *_ in it["mods"]:
            item_fams.setdefault(it["base"], set()).add(f)
    patch = build_patch(core_stats, item_fams)

    snap = OUT / "snapshot"
    snap.mkdir(parents=True, exist_ok=True)
    files = []
    for kind, obj in (("patch", patch), ("daily", daily)):
        raw = (json.dumps(obj, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
        (snap / f"{kind}.json").write_bytes(raw)
        gz = gzip.compress(json.dumps(obj, separators=(",", ":"), ensure_ascii=False).encode("utf-8"), mtime=0)
        ent = dict(kind=kind, name=f"{kind}-{GAME_PATCH if kind == 'patch' else '2026-11-23'}.json.gz", schema_version=1,
                   sha256=hashlib.sha256(gz).hexdigest(), bytes=len(gz),
                   uncompressed_bytes=len(json.dumps(obj, separators=(",", ":"), ensure_ascii=False).encode("utf-8")))
        if kind == "patch":
            ent["game_patch"] = GAME_PATCH
        else:
            ent["crawl_date"] = "2026-11-23"
        files.append(ent)
    manifest = dict(schema="elo.manifest", schema_version=1, published_at="2026-11-23T05:10:00Z", league="Covens",
                    min_app_version="0.0.1", files=files)
    (snap / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n")

    golden = OUT / "golden"
    for it in ITEMS:
        d = golden / it["id"]
        d.mkdir(parents=True, exist_ok=True)
        b = base(it["base"])
        resolved = []
        for f, tier, val, src in it["mods"]:
            r = resolve_mod(it["base"], f, tier, val)
            r["source"] = src
            assert r["mod"]["required_level"] <= it["ilvl"], (it["id"], f)
            resolved.append(r)
        resolved.sort(key=lambda r: r["mod"]["generation_type"] != "prefix")  # game order: prefixes first
        snapref = dict(patch="snapshot/patch.json", daily="snapshot/daily.json")
        if it.get("french"):
            (d / "game.txt").write_text(FRENCH_TEXT, encoding="utf-8", newline="\n")
            exp = dict(id=it["id"], description=it["desc"], source="hand-written", forms=["game"], snapshot=snapref,
                       item=None, mods=[], verdict=dict(result="UNSUPPORTED_LANGUAGE", best_buyer=None, fit=None,
                                                        low_data=False, reasons=["unsupported_language"], counted_stat_ids=[]))
        elif it.get("unique"):
            (d / "game.txt").write_text(UNIQUE_TEXT, encoding="utf-8", newline="\n")
            (d / "character.json").write_text(json.dumps(character_json(it, b, [], patch["trade_ids"]), indent=2) + "\n", encoding="utf-8", newline="\n")
            (d / "trade.json").write_text(json.dumps(trade_json(it, b, [], patch["trade_ids"]), indent=2) + "\n", encoding="utf-8", newline="\n")
            exp = dict(id=it["id"], description=it["desc"] + " Unique mods are not normalised in v1, so `mods` is empty.",
                       source="hand-written", forms=["game", "character", "trade"], snapshot=snapref,
                       item=dict(rarity="Unique", item_class="Ring", base="Gold Ring", name="Ventor's Gamble", ilvl=83,
                                 corrupted=False, mirrored=False, fractured=False, synthesised=False, influences=[]),
                       mods=[], verdict=dict(result="NOT_SCORED", best_buyer=None, fit=None, low_data=False,
                                             reasons=["unique_price_lookup"], counted_stat_ids=[], special_price_chaos=3))
        else:
            (d / "game.txt").write_text(game_text(it, b, resolved), encoding="utf-8", newline="\n")
            (d / "character.json").write_text(json.dumps(character_json(it, b, resolved, patch["trade_ids"]), indent=2) + "\n", encoding="utf-8", newline="\n")
            (d / "trade.json").write_text(json.dumps(trade_json(it, b, resolved, patch["trade_ids"]), indent=2) + "\n", encoding="utf-8", newline="\n")
            verdict, op, osf, fits = score(it, b, resolved, daily, patch)
            mods_out = []
            for imp in b["implicits"]:
                m = mods[imp]
                mods_out.append(dict(source="implicit", affix=None, stat_ids=[s["id"] for s in m["stats"]],
                                     values=[math.floor((s["min"] + s["max"]) / 2) for s in m["stats"]], tier=None, family=None))
            for r in resolved:
                mods_out.append(dict(source=r["source"], affix=r["mod"]["generation_type"],
                                     stat_ids=[s["id"] for s in r["mod"]["stats"]], values=r["values"], tier=r["tier"],
                                     family=r["family"], qualifies=r["qualifies"]))
            exp = dict(id=it["id"], description=it["desc"], source="hand-written", forms=["game", "character", "trade"],
                       snapshot=snapref,
                       item=dict(rarity="Rare", item_class=b["item_class"], base=it["base"], name=it["name"], ilvl=it["ilvl"],
                                 corrupted=bool(it.get("corrupted")), mirrored=False,
                                 fractured=any(r["source"] == "fractured" for r in resolved), synthesised=False,
                                 influences=[], open_prefixes=op, open_suffixes=osf),
                       mods=mods_out, verdict=verdict)
            print(it["id"], verdict["result"], verdict["best_buyer"], verdict["fit"], verdict["reasons"],
                  {k: round(v[0], 4) for k, v in fits.items()}, [(r["family"], r["tier"], r["ladder"], r["qualifies"]) for r in resolved])
        (d / "expected.json").write_text(json.dumps(exp, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    print("patch bytes", (snap / "patch.json").stat().st_size, "daily bytes", (snap / "daily.json").stat().st_size)
    print("gz", [(f["kind"], f["bytes"]) for f in files])


main()

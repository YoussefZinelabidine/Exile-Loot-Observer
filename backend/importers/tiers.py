"""Tier ladders from RePoE ``mods.json`` + ``base_items.json``.

Rule (same as the fixture snapshot): a mod belongs to a base's ladders when

- its domain equals the base's domain,
- it is a prefix or a suffix,
- it is not essence-only and its id does not contain ``Royale`` (PoE Royale mods),
- the **first** of its spawn tags that the base has gives a weight greater than 0.

Mods are grouped into families ``<affix>:<RePoE mod type>``; each family is ordered best
tier first (highest required level first, mod id as tie-break).
"""

from typing import Any


def spawn_weight(mod: dict[str, Any], base_tags: set[str]) -> int:
    for entry in mod["spawn_weights"]:
        if entry["tag"] in base_tags:
            return entry["weight"]
    return 0


def tier_set_id(base: dict[str, Any]) -> str:
    """Bases with the same item class and spawn tags share one tier set."""
    return f"{base['item_class']}|{'+'.join(sorted(base['tags']))}"


def find_base(base_items: dict[str, Any], name: str) -> dict[str, Any]:
    for base in base_items.values():
        if base["name"] == name and base.get("release_state") == "released":
            return base
    raise KeyError(f"no released base named {name!r}")


def families_for_base(
    mods: dict[str, Any], base: dict[str, Any]
) -> dict[str, list[tuple[str, dict[str, Any], int]]]:
    """Family key -> ladder of ``(mod_id, mod, spawn_weight)``, best tier first."""
    tags = set(base["tags"])
    families: dict[str, list[tuple[str, dict[str, Any], int]]] = {}
    for mod_id, mod in mods.items():
        if mod["domain"] != base["domain"] or mod["generation_type"] not in ("prefix", "suffix"):
            continue
        if mod.get("is_essence_only") or "Royale" in mod_id:
            continue
        weight = spawn_weight(mod, tags)
        if weight > 0:
            families.setdefault(f"{mod['generation_type']}:{mod['type']}", []).append(
                (mod_id, mod, weight)
            )
    for ladder in families.values():
        ladder.sort(key=lambda entry: (-entry[1]["required_level"], entry[0]))
    return families


def build_family(ladder: list[tuple[str, dict[str, Any], int]], key: str) -> dict[str, Any]:
    """Patch-file shape of one family (``shared/schema/patch.schema.json`` -> family)."""
    return {
        "affix": key.split(":")[0],
        "stat_ids": [stat["id"] for stat in ladder[0][1]["stats"]],
        "tiers": [
            {
                "tier": index + 1,
                "mod_id": mod_id,
                "name": mod["name"],
                "required_level": mod["required_level"],
                "spawn_weight": weight,
                "stats": [
                    {"id": stat["id"], "min": stat["min"], "max": stat["max"]}
                    for stat in mod["stats"]
                ],
            }
            for index, (mod_id, mod, weight) in enumerate(ladder)
        ],
    }


def build_tier_set(
    mods: dict[str, Any], base: dict[str, Any], only_families: set[str] | None = None
) -> dict[str, Any]:
    """All (or the listed) families of one base, in patch-file shape."""
    families = families_for_base(mods, base)
    keys = sorted(families if only_families is None else only_families & set(families))
    return {key: build_family(families[key], key) for key in keys}

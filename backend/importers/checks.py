"""Cross-source checks run before staged data is activated."""

from typing import Any

from backend.common import alerts

# Scored item classes -> poe.re "basetype" group (as in the fixture snapshot).
SCORED_CLASSES: dict[str, str] = {
    "Ring": "Rings",
    "Amulet": "Amulets",
    "Boots": "Boots",
    "Gloves": "Gloves",
    "Body Armour": "Body Armours",
    "Jewel": "Jewels",
    "AbyssJewel": "Abyss Jewels",
}


def check_patch_versions(repoe_version: str, poere_patch: str) -> bool:
    """True when RePoE and poe.re are on the same game patch; otherwise alert and return False."""
    if repoe_version == poere_patch:
        return True
    alerts.send_alert(
        f"Data patch mismatch: RePoE {repoe_version} vs poe.re {poere_patch}",
        level="warning",
    )
    return False


def missing_scored_classes(
    poere_items: list[dict[str, Any]], scored: dict[str, str] | None = None
) -> list[str]:
    """Scored item classes whose poe.re group is absent from poe.re's item file."""
    present = {group["basetype"] for group in poere_items}
    wanted = SCORED_CLASSES if scored is None else scored
    return sorted(cls for cls, basetype in wanted.items() if basetype not in present)

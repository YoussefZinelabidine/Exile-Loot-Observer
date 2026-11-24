"""Output types of the normaliser."""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class NormalisedMod:
    """One mod line, in the shape of an entry of ``mods`` in a golden ``expected.json``.

    ``tier_ambiguous`` and ``tier_mismatch`` are internal flags and never part of that shape.
    """

    source: str  # implicit / explicit / fractured / crafted / enchant / corruption_implicit
    affix: str | None
    stat_ids: list[str]
    values: list[int]
    tier: int | None = None
    family: str | None = None
    tier_ambiguous: bool = False  # the value fits several tiers; the best one was taken
    tier_mismatch: bool = False  # trade tier label and ladder disagreed; ladder was used

    def as_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "affix": self.affix,
            "stat_ids": list(self.stat_ids),
            "values": list(self.values),
            "tier": self.tier,
            "family": self.family,
        }


@dataclass
class NormalisedItem:
    item: dict[str, Any]
    mods: list[NormalisedMod] = field(default_factory=list)
    unrecognised: list[str] = field(default_factory=list)

    def to_expected(self) -> dict[str, Any]:
        """``item``, ``mods`` and ``unrecognised`` as in a golden ``expected.json``."""
        item = {
            k: v for k, v in self.item.items() if not (k.startswith("open_") and v is None)
        }  # unknown open slots (decision 39) are omitted
        return {
            "item": item,
            "mods": [m.as_dict() for m in self.mods],
            "unrecognised": list(self.unrecognised),
        }


@dataclass(frozen=True)
class ModRow:
    """One database row for later aggregation: one row per stat (decision 16)."""

    item_class: str
    base: str
    ilvl: int
    stat_id: str
    value: int
    tier: int | None
    source: str
    family: str | None = None
    affix: str | None = None
    tier_ambiguous: bool = False
    tier_mismatch: bool = False


def db_rows(normalised: NormalisedItem) -> list[ModRow]:
    item = normalised.item
    return [
        ModRow(
            item_class=item["item_class"],
            base=item["base"],
            ilvl=item["ilvl"],
            stat_id=stat_id,
            value=value,
            tier=mod.tier,
            source=mod.source,
            family=mod.family,
            affix=mod.affix,
            tier_ambiguous=mod.tier_ambiguous,
            tier_mismatch=mod.tier_mismatch,
        )
        for mod in normalised.mods
        for stat_id, value in zip(mod.stat_ids, mod.values, strict=True)
    ]

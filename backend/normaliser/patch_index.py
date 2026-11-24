"""Patch data prepared for normalising: tier sets, bases and compiled stat-text matchers.

The matcher logic mirrors the app parser (``app/src/lib/parser/translations.ts``) and uses the
same ``shared/stat-handlers.json`` (inverse handlers, integer rounding, hidden-stat rules), so
both sides agree on every line.
"""

import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from backend.common.config import REPO_ROOT
from backend.common.snapshot_models import Patch

HANDLERS_PATH = REPO_ROOT / "shared" / "stat-handlers.json"

# One placeholder: the value, then an optional roll range "(min-max)" (advanced format).
_PLACEHOLDER = r"([+-]?\d+(?:\.\d+)?)(?:\((-?\d+(?:\.\d+)?)-(-?\d+(?:\.\d+)?)\))?"
_GROUPS = 3


def js_round(value: float) -> int:
    """JavaScript ``Math.round`` (halves go up), without a negative zero."""
    return int(math.floor(value + 0.5))


def _decimals(shown: str | None) -> int:
    if not shown or "." not in shown:
        return 0
    return len(shown.split(".")[1])


def load_inverse_handlers(path: Path = HANDLERS_PATH) -> dict[str, dict[str, Any]]:
    return json.loads(path.read_text(encoding="utf-8"))["inverse"]


def _condition_ok(value: int, cond: dict[str, Any]) -> bool:
    """RePoE condition on the raw value; ``negated`` inverts it."""
    low, high = cond.get("min"), cond.get("max")
    inside = (low is None or value >= low) and (high is None or value <= high)
    return (not inside) if cond.get("negated") else inside


def _factor_of(handlers: list[str], inverse: dict[str, dict[str, Any]]) -> float | None:
    factor = 1.0
    for name in handlers:
        entry = inverse.get(name)
        if entry is None:
            return None
        if entry["op"] == "multiply":
            factor *= entry["by"]
        elif entry["op"] != "identity":
            return None
    return factor


@dataclass
class StatMatch:
    """One way a mod line can be read: stat ids (only those the text shows) and raw values."""

    group: int  # index of the translation group (RePoE order)
    stat_ids: list[str]
    values: list[int]
    ranges: list[tuple[int, int] | None]
    range_tolerance: list[float]


@dataclass
class _Matcher:
    group: int
    regex: re.Pattern[str]
    ids: list[str]
    slot: list[int]
    factor: list[float]
    cond: list[dict[str, Any]]
    fixed: list[float] | None = None


@dataclass
class PatchIndex:
    bases: dict[str, dict[str, Any]]
    item_classes: dict[str, dict[str, Any]]
    tier_sets: dict[str, dict[str, dict[str, Any]]]
    trade_stat_by_hash: dict[str, str]
    matchers: list[_Matcher] = field(default_factory=list)

    @classmethod
    def from_patch(
        cls, patch: Patch | dict[str, Any], inverse: dict[str, dict[str, Any]] | None = None
    ) -> "PatchIndex":
        data = patch.model_dump(mode="json", by_alias=True) if isinstance(patch, Patch) else patch
        inverse = inverse if inverse is not None else load_inverse_handlers()
        trade_stat_by_hash = {
            hash_id: stat_id
            for stat_id, by_type in data["trade_ids"].items()
            for hash_id in by_type.values()
        }
        index = cls(
            bases=data["bases"],
            item_classes=data["item_classes"],
            tier_sets=data["tier_sets"],
            trade_stat_by_hash=trade_stat_by_hash,
        )
        index.matchers = _build_matchers(data["translations"], inverse)
        return index

    def match_line(self, line: str) -> list[StatMatch]:
        """Every distinct stat-id set whose English text matches ``line`` (a plain mod line)."""
        found: dict[str, StatMatch] = {}
        for matcher in self.matchers:
            result = matcher.regex.search(line)
            if result is None:
                continue
            values: list[int] = []
            ranges: list[tuple[int, int] | None] = []
            tolerance: list[float] = []
            for k in range(len(matcher.ids)):
                if matcher.fixed is not None:
                    values.append(int(matcher.fixed[k]))
                    ranges.append(None)
                    tolerance.append(0.0)
                    continue
                slot = matcher.slot[k]
                first = 1 + slot * _GROUPS
                factor = matcher.factor[slot]
                shown, low, high = (
                    result.group(first),
                    result.group(first + 1),
                    result.group(first + 2),
                )
                values.append(js_round(float(shown) * factor))
                if low is not None and high is not None:
                    a, b = js_round(float(low) * factor), js_round(float(high) * factor)
                    ranges.append((min(a, b), max(a, b)))
                else:
                    ranges.append(None)
                places = max(_decimals(shown), _decimals(low), _decimals(high))
                tolerance.append(abs(factor) * 10**-places)
            # A variant whose condition the value violates is not the text the game shows.
            if any(not _condition_ok(v, matcher.cond[k]) for k, v in enumerate(values)):
                continue
            # Same stat set from several variants: the first in RePoE order wins. Different stat
            # sets stay separate candidates for the caller (family, base implicits).
            key = "|".join(matcher.ids)
            found.setdefault(
                key, StatMatch(matcher.group, list(matcher.ids), values, ranges, tolerance)
            )
        return list(found.values())


def _build_matchers(translations: list[dict[str, Any]], inverse: dict[str, Any]) -> list[_Matcher]:
    out: list[_Matcher] = []
    for group, translation in enumerate(translations):
        ids = translation["ids"]
        for variant in translation["english"]:
            handlers = variant.get("index_handlers") or []
            factors: list[float] = []
            usable = True
            for i in range(len(ids)):
                factor = _factor_of(handlers[i] if i < len(handlers) else [], inverse)
                if factor is None:
                    usable = False
                    factor = 1.0
                factors.append(factor)
            if not usable:
                continue  # an unsupported handler makes the whole variant unusable

            parts = re.split(r"\{(\d+)\}", variant["string"])
            source = "^"
            slot_of_id: dict[int, int] = {}
            slot_factor: list[float] = []
            for i, part in enumerate(parts):
                if i % 2 == 0:
                    source += re.escape(part)
                    continue
                idx = int(part)
                if idx < len(variant["format"]) and variant["format"][idx] == "ignore":
                    continue  # not shown in the text
                slot_of_id[idx] = len(slot_factor)
                slot_factor.append(factors[idx] if idx < len(factors) else 1.0)
                source += _PLACEHOLDER
            source += "$"

            keep: list[int] = []
            fixed: list[float] = []
            if slot_factor:
                keep = [i for i in range(len(ids)) if i in slot_of_id]
            else:
                conditions = variant["condition"]
                for i in range(len(ids)):
                    if i >= len(conditions):
                        continue
                    low, high = conditions[i].get("min"), conditions[i].get("max")
                    if isinstance(low, (int, float)) and low > 0:
                        keep.append(i)
                        fixed.append(low)
                    elif isinstance(high, (int, float)) and high < 0:
                        keep.append(i)
                        fixed.append(high)
            if not keep:
                continue
            out.append(
                _Matcher(
                    group=group,
                    regex=re.compile(source),
                    ids=[ids[i] for i in keep],
                    slot=[slot_of_id.get(i, -1) for i in keep],
                    factor=slot_factor,
                    cond=[
                        variant["condition"][i] if i < len(variant["condition"]) else {}
                        for i in keep
                    ],
                    fixed=fixed if not slot_factor else None,
                )
            )
    return out

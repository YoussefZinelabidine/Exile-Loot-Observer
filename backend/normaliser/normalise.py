"""Turn a character-API or trade-API item into normalised mods.

Rules (job P1-B3, decisions 15, 16, 24 to 27):

- Mod text -> stat ids and raw values through the RePoE English translations
  (``PatchIndex.match_line``, same rules as the app parser).
- Character API has no tiers or affixes: the family is the one on the base's tier set whose
  ladder holds the value with ``required_level <= ilvl``. A value that fits several tiers of the
  family gets the best tier and ``tier_ambiguous``. A line that fits several families, or none,
  is never guessed: it goes to ``unrecognised`` (and is logged with base and line).
- Trade API: ``extended.mods`` tier labels (``P1`` / ``S2``), names and stat hashes pick the tier;
  they are cross-checked against the ladder. If they disagree the ladder wins and the mod is
  flagged ``tier_mismatch``.
- One entry per matched line; a line is split into rows per stat only for the database
  (``db_rows``). Hybrids are separate lines sharing family and tier.
- Uniques: item only, no mods. Values are raw stat units.
"""

import logging
import re
from dataclasses import dataclass
from typing import Any

from backend.normaliser.errors import NormaliserError
from backend.normaliser.models import NormalisedItem, NormalisedMod
from backend.normaliser.patch_index import PatchIndex, StatMatch

logger = logging.getLogger(__name__)

INFLUENCES = ("shaper", "elder", "crusader", "redeemer", "hunter", "warlord")
# frameType 9 (relic) counts as a unique. Other frame types (gems, currency, ...) are rejected.
FRAME_RARITY = {0: "Normal", 1: "Magic", 2: "Rare", 3: "Unique", 9: "Unique"}
RARITIES = ("Normal", "Magic", "Rare", "Unique")
# (API key, mod source). Ladder-based sources are resolved against the tier set.
SOURCE_KEYS = (
    ("implicitMods", "implicit"),
    ("enchantMods", "enchant"),
    ("craftedMods", "crafted"),
    ("fracturedMods", "fractured"),
    ("explicitMods", "explicit"),
)
# Lines that are never mapped (veiled, eldritch): reported, not guessed.
UNMAPPED_KEYS = ("veiledMods", "searingExarchImplicitMods", "eaterOfWorldsImplicitMods")
_TIER_LABEL = re.compile(r"^([PS])(\d+)$")
_EPS = 1e-9


@dataclass
class _Line:
    text: str
    index: int  # index of the API entry the line came from (for trade hashes)
    source: str


@dataclass
class _Hint:
    affix: str
    tier: int
    name: str | None
    stat_id: str | None
    magnitudes: list[tuple[str, float, float]]


class _Merged:
    """Marker for a trade line that several mods contributed to (identical stats merged)."""


MERGED = _Merged()


@dataclass
class _Option:
    family: str
    affix: str
    match: StatMatch
    tiers: list[int]
    hinted: bool = False
    mismatch: bool = False


def _lines(item: dict[str, Any], key: str, source: str) -> list[_Line]:
    out = []
    for index, raw in enumerate(item.get(key) or []):
        for part in str(raw).split("\n"):
            text = part.strip()
            if text and not re.fullmatch(r"\(.*\)", text):  # skip reminder text
                out.append(_Line(text, index, source))
    return out


def _strip_base_prefix(name: str) -> str:
    base = name.strip()
    while True:
        for prefix in ("Superior ", "Synthesised "):
            if base.startswith(prefix):
                base = base[len(prefix) :]
                break
        else:
            return base


def _item_fields(item: dict[str, Any]) -> dict[str, Any]:
    rarity = item.get("rarity")
    if not rarity:
        rarity = FRAME_RARITY.get(item.get("frameType"))
    if rarity not in RARITIES:
        raise NormaliserError("unsupported_item", f"unsupported item type {rarity!r}")
    base = _strip_base_prefix(item.get("baseType") or item.get("typeLine") or "")
    influences = item.get("influences")
    found: set[str] = set()
    if isinstance(influences, dict):
        found = {k for k, v in influences.items() if v}
    elif isinstance(influences, list):
        found = {str(k) for k in influences}
    found |= {k for k in INFLUENCES if item.get(k)}
    synthesised = bool(item.get("synthesised")) or str(item.get("baseType", "")).startswith(
        "Synthesised "
    )
    return {
        "rarity": rarity,
        "base": base,
        "name": item.get("name") or None,
        "ilvl": item.get("ilvl"),
        "corrupted": bool(item.get("corrupted")),
        "mirrored": bool(item.get("duplicated") or item.get("mirrored")),
        "fractured": bool(item.get("fractured") or item.get("fracturedMods")),
        "synthesised": synthesised,
        "influences": [i for i in INFLUENCES if i in found],
    }


def _in_range(stat_ids: list[str], values: list[int], tier: dict[str, Any]) -> bool:
    by_id = {s["id"]: s for s in tier["stats"]}
    return all(
        sid in by_id and by_id[sid]["min"] - _EPS <= v <= by_id[sid]["max"] + _EPS
        for sid, v in zip(stat_ids, values, strict=True)
    )


def _ladder_options(
    tier_set: dict[str, dict[str, Any]], matches: list[StatMatch], ilvl: int
) -> list[_Option]:
    options = []
    for key in sorted(tier_set):
        family = tier_set[key]
        for match in matches:
            if not all(sid in family["stat_ids"] for sid in match.stat_ids):
                continue
            tiers = [
                t["tier"]
                for t in family["tiers"]
                if t["required_level"] <= ilvl and _in_range(match.stat_ids, match.values, t)
            ]
            if tiers:
                options.append(_Option(key, family["affix"], match, tiers))
    return options


def _apply_hint(
    options: list[_Option], tier_set: dict[str, dict[str, Any]], hint: _Hint
) -> list[_Option]:
    """Use the trade tier label when the ladder agrees; otherwise keep the ladder and flag it."""
    good = []
    for opt in options:
        if opt.affix != hint.affix or hint.tier not in opt.tiers:
            continue
        tier = next(t for t in tier_set[opt.family]["tiers"] if t["tier"] == hint.tier)
        if hint.name and tier.get("name") and tier["name"] != hint.name:
            continue
        good.append(_Option(opt.family, opt.affix, opt.match, [hint.tier], hinted=True))
    if good:
        return good
    for opt in options:
        opt.mismatch = True
    return options


class Normaliser:
    """Normalises items against one patch file (as a ``PatchIndex``)."""

    def __init__(self, patch: PatchIndex):
        self.patch = patch

    # ------------------------------------------------------------ public

    def character_item(self, item: dict[str, Any]) -> NormalisedItem:
        """``item`` of get-items (or one ``socketedItems`` entry, e.g. an abyss jewel)."""
        return self._normalise(item, hints={})

    def trade_result(self, result: dict[str, Any]) -> NormalisedItem:
        """One result of ``/api/trade/fetch`` (``{"item": ..., "listing": ...}``)."""
        item = result["item"]
        unique = (
            item.get("rarity") == "Unique" or FRAME_RARITY.get(item.get("frameType")) == "Unique"
        )
        return self._normalise(item, hints={} if unique else self._trade_hints(item))

    # ------------------------------------------------------------ internals

    def _trade_hints(self, item: dict[str, Any]) -> dict[tuple[str, int], _Hint | _Merged]:
        """Hints per ``(source, line index)`` from ``extended``.

        ASSUMED SHAPE, to be confirmed against a recorded response in Phase 2:
        ``extended.hashes[source][i] = [hash, mod_idxs]`` is aligned with the i-th entry of
        ``<source>Mods``, and ``mod_idxs`` index into ``extended.mods[source]``. A line with
        exactly one contributing mod gets that mod's tier label as a hint; a line with several
        (identical stats merged into one line) or none gets no hint.
        """
        extended = item.get("extended") or {}
        ext_mods = extended.get("mods") or {}
        ext_hashes = extended.get("hashes") or {}
        hints: dict[tuple[str, int], _Hint | _Merged] = {}
        for source in ("explicit", "fractured", "crafted"):
            entries = ext_mods.get(source) or []
            for line_index, pair in enumerate(ext_hashes.get(source) or []):
                if not isinstance(pair, (list, tuple)) or len(pair) < 2:
                    continue
                line_hash, mod_idxs = pair[0], pair[1] or []
                if len(mod_idxs) >= 2:
                    hints[(source, line_index)] = MERGED  # a known merged line: never guessed
                    continue
                if len(mod_idxs) != 1 or not 0 <= mod_idxs[0] < len(entries):
                    continue
                entry = entries[mod_idxs[0]]
                label = _TIER_LABEL.match(str(entry.get("tier", "")))
                if not label:
                    continue
                magnitudes = [
                    (m["hash"], float(m["min"]), float(m["max"]))
                    for m in entry.get("magnitudes") or []
                ]
                hints[(source, line_index)] = _Hint(
                    "prefix" if label.group(1) == "P" else "suffix",
                    int(label.group(2)),
                    entry.get("name") or None,
                    self.patch.trade_stat_by_hash.get(line_hash),
                    magnitudes,
                )
        return hints

    def _normalise(
        self, item: dict[str, Any], hints: dict[tuple[str, int], _Hint | _Merged]
    ) -> NormalisedItem:
        if item.get("identified") is False:
            raise NormaliserError("unidentified", "the item is not identified")
        fields = _item_fields(item)
        base = fields["base"]
        base_info = self.patch.bases.get(base)
        rarity = fields["rarity"]
        if base_info is None and rarity != "Unique":
            raise NormaliserError("unsupported_item", f"base {base!r} is not in the patch")
        if base_info is None:
            # The API gives no item class for a unique whose base the patch lacks; the schema
            # needs a string, so it stays empty.
            logger.warning(
                "unique with a base not in the patch: base=%r, item_class left empty", base
            )
        if not isinstance(fields["ilvl"], int) or isinstance(fields["ilvl"], bool):
            raise NormaliserError("invalid_item", "the item has no item level")
        item_class = base_info["item_class"] if base_info else ""
        tier_set = self.patch.tier_sets.get(base_info["tier_set"], {}) if base_info else {}
        implicit_ids = list(base_info.get("implicit_stat_ids") or []) if base_info else []

        mods: list[NormalisedMod] = []
        unrecognised: list[str] = []
        affix_unknown = False  # an affix-bearing line could not be placed (decision 39)
        if rarity != "Unique":
            for key, source in SOURCE_KEYS:
                lines = _lines(item, key, source)
                if source in ("implicit", "enchant"):
                    self._implicit_lines(
                        lines, source, fields["corrupted"], implicit_ids, base, mods, unrecognised
                    )
                    continue
                before = len(unrecognised)
                if source == "crafted":
                    self._crafted_lines(lines, tier_set, hints, base, mods, unrecognised)
                else:
                    self._ladder_lines(
                        lines, source, tier_set, fields["ilvl"], hints, base, mods, unrecognised
                    )
                affix_unknown = affix_unknown or len(unrecognised) > before
            for key in UNMAPPED_KEYS:
                for line in _lines(item, key, "unmapped"):
                    self._report(base, line.text, "not mapped", unrecognised)
                    affix_unknown = affix_unknown or key == "veiledMods"  # a veiled mod is an affix
            affix_unknown = affix_unknown or any(
                m.source == "crafted" and m.affix is None for m in mods
            )

        item_out: dict[str, Any] = {
            "rarity": rarity,
            "item_class": item_class,
            "base": base,
            "name": fields["name"],
            "ilvl": fields["ilvl"],
            "corrupted": fields["corrupted"],
            "mirrored": fields["mirrored"],
            "fractured": fields["fractured"] or any(m.source == "fractured" for m in mods),
            "synthesised": fields["synthesised"],
            "influences": fields["influences"],
        }
        class_info = self.patch.item_classes.get(item_class or "")
        if class_info and rarity in ("Rare", "Magic"):
            slots = self._slots(mods)
            max_p, max_s = class_info["max_prefixes"], class_info["max_suffixes"]
            if rarity == "Magic":
                max_p, max_s = min(1, max_p), min(1, max_s)
            if affix_unknown:  # decision 39: unknown, never a guess
                item_out["open_prefixes"] = None
                item_out["open_suffixes"] = None
            else:
                item_out["open_prefixes"] = max(0, max_p - slots["prefix"])
                item_out["open_suffixes"] = max(0, max_s - slots["suffix"])
        return NormalisedItem(item_out, mods, unrecognised)

    @staticmethod
    def _report(base: str, line: str, why: str, unrecognised: list[str]) -> None:
        logger.warning("unrecognised mod line (%s) base=%r line=%r", why, base, line)
        unrecognised.append(line)

    @staticmethod
    def _slots(mods: list[NormalisedMod]) -> dict[str, int]:
        """Affix slots in use: one per distinct family, one per crafted mod with a known affix."""
        slots = {"prefix": 0, "suffix": 0}
        for affix, _ in {(m.affix, m.family) for m in mods if m.family and m.affix}:
            slots[affix] += 1
        for m in mods:
            if m.source == "crafted" and m.affix:
                slots[m.affix] += 1
        return slots

    def _implicit_lines(
        self,
        lines: list[_Line],
        source: str,
        corrupted: bool,
        implicit_ids: list[str],
        base: str,
        mods: list[NormalisedMod],
        unrecognised: list[str],
    ) -> None:
        for line in lines:
            matches = self.patch.match_line(line.text)
            if not matches:
                self._report(base, line.text, "no stat text matches", unrecognised)
                continue
            # Prefer the stat the base is known to roll as its implicit.
            pool = [m for m in matches if all(s in implicit_ids for s in m.stat_ids)] or matches
            if len(pool) > 1:
                self._report(base, line.text, "ambiguous stat text", unrecognised)
                continue
            match = pool[0]
            kind = source
            if (
                source == "implicit"
                and corrupted
                and not all(s in implicit_ids for s in match.stat_ids)
            ):
                kind = "corruption_implicit"
            mods.append(NormalisedMod(kind, None, match.stat_ids, match.values))

    def _crafted_lines(
        self,
        lines: list[_Line],
        tier_set: dict[str, dict[str, Any]],
        hints: dict[tuple[str, int], _Hint | _Merged],
        base: str,
        mods: list[NormalisedMod],
        unrecognised: list[str],
    ) -> None:
        for line in lines:
            if hints.get((line.source, line.index)) is MERGED:
                self._report(base, line.text, "merged line (several mods)", unrecognised)
                continue
            matches = self.patch.match_line(line.text)
            if not matches:
                self._report(base, line.text, "no stat text matches", unrecognised)
                continue
            in_set = [
                m
                for m in matches
                if any(all(s in f["stat_ids"] for s in m.stat_ids) for f in tier_set.values())
            ]
            hint = hints.get((line.source, line.index))
            if hint is not None:
                in_set = [
                    m
                    for m in in_set
                    if any(
                        f["affix"] == hint.affix and all(s in f["stat_ids"] for s in m.stat_ids)
                        for f in tier_set.values()
                    )
                ]
            pool = in_set or matches
            if len(pool) > 1:
                self._report(base, line.text, "ambiguous stat text", unrecognised)
                continue
            match = pool[0]
            if hint is not None:
                affix: str | None = hint.affix
            else:
                affixes = {
                    f["affix"]
                    for f in tier_set.values()
                    if all(s in f["stat_ids"] for s in match.stat_ids)
                }
                affix = affixes.pop() if len(affixes) == 1 else None
            mods.append(NormalisedMod("crafted", affix, match.stat_ids, match.values))

    # TODO: merged identical-stat lines (the game shows two mods of one stat as a single summed
    # line) are reported as unrecognised for now; decomposing them needs a recorded example.
    def _ladder_lines(
        self,
        lines: list[_Line],
        source: str,
        tier_set: dict[str, dict[str, Any]],
        ilvl: int,
        hints: dict[tuple[str, int], _Hint | _Merged],
        base: str,
        mods: list[NormalisedMod],
        unrecognised: list[str],
    ) -> None:
        matched: list[tuple[_Line, list[StatMatch]]] = []
        for line in lines:
            if hints.get((line.source, line.index)) is MERGED:
                self._report(base, line.text, "merged line (several mods)", unrecognised)
                continue
            matches = self.patch.match_line(line.text)
            if not matches:
                self._report(base, line.text, "no stat text matches", unrecognised)
            else:
                matched.append((line, matches))
        present = {sid for _, ms in matched for m in ms for sid in m.stat_ids}

        # Phase 1: ladder options per line. A hybrid family is only a candidate when every one of
        # its stats is on the item.
        prepared: list[tuple[_Line, list[StatMatch], list[_Option], _Hint | None]] = []
        for line, matches in matched:
            hint = hints.get((line.source, line.index))
            if hint is not None and hint.stat_id:
                narrowed = [m for m in matches if hint.stat_id in m.stat_ids]
                matches = narrowed or matches
            options = [
                o
                for o in _ladder_options(tier_set, matches, ilvl)
                if all(s in present for s in tier_set[o.family]["stat_ids"])
            ]
            prepared.append((line, matches, options, hint))

        # Phase 2 (decision 38): without affix labels a hybrid is only trusted when every one of
        # its stats is resolved to it. Otherwise every line holding one of its stats may be a
        # half (or a merged line) and goes to unrecognised; never a guessed tier.
        cover: dict[str, set[str]] = {}
        for _, _, options, hint in prepared:
            if hint is not None:
                continue
            for o in options:
                if len(tier_set[o.family]["stat_ids"]) > 1:
                    cover.setdefault(o.family, set()).update(o.match.stat_ids)
        incomplete = {
            fam: set(tier_set[fam]["stat_ids"])
            for fam, covered in cover.items()
            if not set(tier_set[fam]["stat_ids"]) <= covered
        }
        incomplete_stats = set().union(*incomplete.values()) if incomplete else set()

        resolved: list[tuple[_Line, _Option]] = []
        for line, matches, options, hint in prepared:
            if hint is None and incomplete_stats:
                if any(s in incomplete_stats for m in matches for s in m.stat_ids):
                    self._report(base, line.text, "possible hybrid half", unrecognised)
                    continue
            if hint is not None:
                options = _apply_hint(options, tier_set, hint)
            if not options:
                self._report(base, line.text, "no tier ladder fits", unrecognised)
                continue
            if any(o.hinted for o in options):
                options = [o for o in options if o.hinted]
            families = {o.family for o in options}
            pairs = {(o.family, tuple(o.match.stat_ids)) for o in options}
            if len(families) > 1 or len(pairs) > 1:
                self._report(base, line.text, "ambiguous family", unrecognised)
                continue
            merged = _Option(
                options[0].family,
                options[0].affix,
                options[0].match,
                sorted({t for o in options for t in o.tiers}),
                hinted=options[0].hinted,
                mismatch=any(o.mismatch for o in options),
            )
            resolved.append((line, merged))

        # Decision 38 (strict): never store half a hybrid. Every stat of a hybrid family must have
        # a line resolved to that family, otherwise all of its lines go to unrecognised.
        resolved_stats: dict[str, set[str]] = {}
        for _, opt in resolved:
            resolved_stats.setdefault(opt.family, set()).update(opt.match.stat_ids)
        half = {
            fam
            for fam, stats in resolved_stats.items()
            if len(tier_set[fam]["stat_ids"]) > 1 and not set(tier_set[fam]["stat_ids"]) <= stats
        }
        if half:
            kept = []
            for line, opt in resolved:
                if opt.family in half:
                    self._report(base, line.text, "half of a hybrid mod", unrecognised)
                else:
                    kept.append((line, opt))
            resolved = kept

        # Lines of one family (hybrid halves) share one tier: intersect their candidate tiers.
        by_family: dict[str, list[_Option]] = {}
        for _, opt in resolved:
            by_family.setdefault(opt.family, []).append(opt)
        chosen: dict[str, tuple[int, bool]] = {}
        for family, opts in by_family.items():
            common = set(opts[0].tiers)
            for opt in opts[1:]:
                common &= set(opt.tiers)
            if common:
                ambiguous = len(common) > 1
                chosen[family] = (min(common), ambiguous)
            else:  # the halves disagree: keep the best tier any of them allows, flagged
                chosen[family] = (min(t for o in opts for t in o.tiers), True)

        for _, opt in resolved:
            tier, ambiguous = chosen[opt.family]
            mods.append(
                NormalisedMod(
                    source,
                    opt.affix,
                    opt.match.stat_ids,
                    opt.match.values,
                    tier,
                    opt.family,
                    tier_ambiguous=ambiguous,
                    tier_mismatch=opt.mismatch,
                )
            )

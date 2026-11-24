"""English stat text and trade-site stat IDs from RePoE ``stat_translations.json``."""

import re
from typing import Any

_MARKUP = re.compile(r"\[(?:[^\]|]*\|)?([^\]]*)\]")
TRADE_TYPES = ("explicit", "implicit", "fractured", "crafted")


def clean_markup(text: str) -> str:
    """RePoE ``[Id|Text]`` -> ``Text`` and ``[Text]`` -> ``Text``."""
    return _MARKUP.sub(r"\1", text)


def translation_entry(entry: dict[str, Any]) -> dict[str, Any]:
    """Patch-file shape of one translation entry."""
    return {
        "ids": entry["ids"],
        "english": [
            {
                "string": clean_markup(variant["string"]),
                "format": variant["format"],
                "condition": [
                    {key: cond.get(key) for key in ("min", "max", "negated")}
                    for cond in variant["condition"]
                ],
                "index_handlers": variant.get("index_handlers") or [],
            }
            for variant in entry["English"]
        ],
    }


def build_translations(
    stat_translations: list[dict[str, Any]], stat_ids: set[str]
) -> list[dict[str, Any]]:
    """Entries that cover at least one of ``stat_ids``, each entry once, in file order."""
    return [
        translation_entry(entry)
        for entry in stat_translations
        if "English" in entry and stat_ids & set(entry["ids"])
    ]


def build_trade_ids(
    stat_translations: list[dict[str, Any]], stat_ids: set[str]
) -> dict[str, dict[str, str]]:
    """Trade-site stat IDs per RePoE stat (single-stat entries only)."""
    trade: dict[str, dict[str, str]] = {}
    for entry in stat_translations:
        ids = entry["ids"]
        if len(ids) != 1 or ids[0] not in stat_ids:
            continue
        found = {
            t["type"]: t["id"]
            for t in (entry.get("trade_stats") or [])
            if t.get("type") in TRADE_TYPES
        }
        if found:
            trade.setdefault(ids[0], found)
    return trade

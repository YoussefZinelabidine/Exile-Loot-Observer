"""Snapshot inputs as plain JSON-shaped dicts.

The engine mirrors the TypeScript one, which works on parsed JSON: a key that is absent and a key
that is ``null`` both read as "no value". The pydantic models are dumped with ``exclude_unset``
so a partial override (``by_item_class``) only carries the keys the file actually has.
"""

from typing import Any

from pydantic import BaseModel


def to_plain(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json", by_alias=True, exclude_unset=True)
    return value

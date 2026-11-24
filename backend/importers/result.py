"""Outcome of one importer run."""

from dataclasses import dataclass, field
from typing import Literal

Status = Literal["unchanged", "staged", "rejected", "failed"]


@dataclass
class ImportResult:
    source: str  # repoe / poere / skilltree
    status: Status
    version: str | None = None
    files: list[dict[str, str]] = field(default_factory=list)  # [{path, sha256}]
    message: str = ""
    commit: str | None = None  # upstream commit, when the source reports one (poe.re)

"""Python scoring engine (job P1-B4): twin of the app engine in ``app/src/lib/scoring/``.

``score_item`` and ``market_demand`` take the snapshot as plain dicts (or the pydantic ``Patch`` /
``Daily`` models) and use the same function semantics as the TypeScript ``scoreItem`` and
``marketDemand``, so validation and the app agree on every verdict.
"""

from backend.scoring.market import market_demand
from backend.scoring.score import score_item
from backend.scoring.types import MarketDemandFilter, MarketDemandRow, Verdict

__all__ = [
    "MarketDemandFilter",
    "MarketDemandRow",
    "Verdict",
    "market_demand",
    "score_item",
]

"""ORM models for the first migration (P1-B1).

Account names are never stored: only ``hash_account_name`` output (HMAC-SHA256 with the salt).
"""

import hashlib
import hmac
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    SmallInteger,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from backend.common.config import require_account_hash_salt
from backend.common.db import Base


def hash_account_name(account_name: str, salt: str | None = None) -> str:
    """HMAC-SHA256 (hex) of an account name. Pass ``salt`` explicitly in tests."""
    key = (salt if salt is not None else require_account_hash_salt()).encode("utf-8")
    return hmac.new(key, account_name.encode("utf-8"), hashlib.sha256).hexdigest()


class League(Base):
    __tablename__ = "leagues"

    id: Mapped[str] = mapped_column(Text, primary_key=True)  # GGG league id
    realm: Mapped[str] = mapped_column(Text)
    is_current: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    crawl_allowed_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Character(Base):
    __tablename__ = "characters"
    __table_args__ = (
        CheckConstraint(
            "status IN ('ok', 'skip_private', 'skip_missing')", name="ck_characters_status"
        ),
        Index("ix_characters_league_id", "league_id"),
        Index("ix_characters_account_hash", "account_hash"),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)  # GGG character id
    league_id: Mapped[str] = mapped_column(ForeignKey("leagues.id"))
    account_hash: Mapped[str] = mapped_column(Text)
    character_name: Mapped[str] = mapped_column(Text)
    class_: Mapped[str] = mapped_column("class", Text)
    level: Mapped[int] = mapped_column(Integer)
    experience: Mapped[int | None] = mapped_column(BigInteger)
    ladder_rank: Mapped[int | None] = mapped_column(Integer)
    is_public: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    status: Mapped[str] = mapped_column(Text, default="ok", server_default="ok")
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen_on_ladder: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_fetched: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RawGear(Base):
    """Latest fetch per (character, kind) only."""

    __tablename__ = "raw_gear"
    __table_args__ = (CheckConstraint("kind IN ('items', 'passives')", name="ck_raw_gear_kind"),)

    character_id: Mapped[str] = mapped_column(ForeignKey("characters.id"), primary_key=True)
    kind: Mapped[str] = mapped_column(Text, primary_key=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    body: Mapped[bytes] = mapped_column(LargeBinary)  # gzip JSON
    sha256: Mapped[str] = mapped_column(Text)


class DataVersion(Base):
    __tablename__ = "data_versions"
    __table_args__ = (
        CheckConstraint(
            "source IN ('repoe', 'poere', 'skilltree', 'poeninja')", name="ck_data_versions_source"
        ),
        CheckConstraint(
            "status IN ('staged', 'active', 'rejected')", name="ck_data_versions_status"
        ),
    )

    source: Mapped[str] = mapped_column(Text, primary_key=True)
    version: Mapped[str] = mapped_column(Text, primary_key=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    status: Mapped[str] = mapped_column(Text)
    files: Mapped[Any] = mapped_column(JSONB)  # list of {path, sha256}


class CrawlerRequest(Base):
    """Sent requests per policy; rows older than 3 h may be pruned."""

    __tablename__ = "crawler_requests"
    __table_args__ = (Index("ix_crawler_requests_policy_sent_at", "policy", "sent_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    policy: Mapped[str] = mapped_column(Text)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status_code: Mapped[int | None] = mapped_column(Integer)


class CrawlerLiveLimit(Base):
    __tablename__ = "crawler_live_limits"

    policy: Mapped[str] = mapped_column(Text, primary_key=True)
    rule: Mapped[str] = mapped_column(Text, primary_key=True)
    max_hits: Mapped[int] = mapped_column(Integer)
    period_s: Mapped[int] = mapped_column(Integer, primary_key=True)
    penalty_s: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class CrawlerBudget(Base):
    __tablename__ = "crawler_budget"
    __table_args__ = (CheckConstraint("characters_used >= 0", name="ck_crawler_budget_used"),)

    day: Mapped[date] = mapped_column(Date, primary_key=True)  # UTC calendar day
    characters_used: Mapped[int] = mapped_column(Integer, default=0, server_default="0")


class CrawlerBreaker(Base):
    __tablename__ = "crawler_breaker"
    __table_args__ = (CheckConstraint("id = 1", name="ck_crawler_breaker_single_row"),)

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, autoincrement=False)
    open_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reason: Mapped[str | None] = mapped_column(Text)
    tripped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CrawlerOutsideHit(Base):
    """Hits on a rate-limit rule that did not come from this crawler."""

    __tablename__ = "crawler_outside_hits"
    __table_args__ = (
        CheckConstraint("hits > 0", name="ck_crawler_outside_hits_hits"),
        Index("ix_crawler_outside_hits_policy_period_at", "policy", "period_s", "at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    policy: Mapped[str] = mapped_column(Text)
    period_s: Mapped[int] = mapped_column(Integer)
    hits: Mapped[int] = mapped_column(Integer)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class CrawlerHardStop(Base):
    """Single-row hard stop, separate from crawler_breaker so they never overwrite each other."""

    __tablename__ = "crawler_hard_stop"
    __table_args__ = (CheckConstraint("id = 1", name="ck_crawler_hard_stop_single_row"),)

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, autoincrement=False)
    reason: Mapped[str] = mapped_column(Text)
    since: Mapped[datetime] = mapped_column(DateTime(timezone=True))

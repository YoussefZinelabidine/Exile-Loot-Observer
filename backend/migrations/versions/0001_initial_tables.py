"""initial tables

Revision ID: 0001
Revises:
Create Date: 2026-11-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "leagues",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("realm", sa.Text(), nullable=False),
        sa.Column("is_current", sa.Boolean(), server_default="false", nullable=False),
        sa.Column(
            "first_seen", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("crawl_allowed_from", sa.DateTime(timezone=True)),
        sa.Column("ended_at", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "characters",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("league_id", sa.Text(), sa.ForeignKey("leagues.id"), nullable=False),
        sa.Column("account_hash", sa.Text(), nullable=False),
        sa.Column("character_name", sa.Text(), nullable=False),
        sa.Column("class", sa.Text(), nullable=False),
        sa.Column("level", sa.Integer(), nullable=False),
        sa.Column("experience", sa.BigInteger()),
        sa.Column("ladder_rank", sa.Integer()),
        sa.Column("is_public", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("status", sa.Text(), server_default="ok", nullable=False),
        sa.Column(
            "first_seen", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("last_seen_on_ladder", sa.DateTime(timezone=True)),
        sa.Column("last_fetched", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "status IN ('ok', 'skip_private', 'skip_missing')", name="ck_characters_status"
        ),
    )
    op.create_index("ix_characters_league_id", "characters", ["league_id"])
    op.create_index("ix_characters_account_hash", "characters", ["account_hash"])
    op.create_table(
        "raw_gear",
        sa.Column("character_id", sa.Text(), sa.ForeignKey("characters.id"), primary_key=True),
        sa.Column("kind", sa.Text(), primary_key=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("body", sa.LargeBinary(), nullable=False),
        sa.Column("sha256", sa.Text(), nullable=False),
        sa.CheckConstraint("kind IN ('items', 'passives')", name="ck_raw_gear_kind"),
    )
    op.create_table(
        "data_versions",
        sa.Column("source", sa.Text(), primary_key=True),
        sa.Column("version", sa.Text(), primary_key=True),
        sa.Column(
            "fetched_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("files", postgresql.JSONB(), nullable=False),
        sa.CheckConstraint(
            "source IN ('repoe', 'poere', 'skilltree', 'poeninja')", name="ck_data_versions_source"
        ),
        sa.CheckConstraint(
            "status IN ('staged', 'active', 'rejected')", name="ck_data_versions_status"
        ),
    )
    op.create_table(
        "crawler_requests",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("policy", sa.Text(), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status_code", sa.Integer()),
    )
    op.create_index("ix_crawler_requests_policy_sent_at", "crawler_requests", ["policy", "sent_at"])
    op.create_table(
        "crawler_live_limits",
        sa.Column("policy", sa.Text(), primary_key=True),
        sa.Column("rule", sa.Text(), primary_key=True),
        sa.Column("max_hits", sa.Integer(), nullable=False),
        sa.Column("period_s", sa.Integer(), primary_key=True),
        sa.Column("penalty_s", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "crawler_budget",
        sa.Column("day", sa.Date(), primary_key=True),
        sa.Column("characters_used", sa.Integer(), server_default="0", nullable=False),
        sa.CheckConstraint("characters_used >= 0", name="ck_crawler_budget_used"),
    )
    op.create_table(
        "crawler_breaker",
        sa.Column("id", sa.SmallInteger(), primary_key=True, autoincrement=False),
        sa.Column("open_until", sa.DateTime(timezone=True)),
        sa.Column("reason", sa.Text()),
        sa.Column("tripped_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("id = 1", name="ck_crawler_breaker_single_row"),
    )
    op.create_table(
        "crawler_outside_hits",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("policy", sa.Text(), nullable=False),
        sa.Column("period_s", sa.Integer(), nullable=False),
        sa.Column("hits", sa.Integer(), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("hits > 0", name="ck_crawler_outside_hits_hits"),
    )
    op.create_index(
        "ix_crawler_outside_hits_policy_period_at",
        "crawler_outside_hits",
        ["policy", "period_s", "at"],
    )
    op.create_table(
        "crawler_hard_stop",
        sa.Column("id", sa.SmallInteger(), primary_key=True, autoincrement=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("since", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("id = 1", name="ck_crawler_hard_stop_single_row"),
    )


def downgrade() -> None:
    op.drop_table("crawler_hard_stop")
    op.drop_index("ix_crawler_outside_hits_policy_period_at", table_name="crawler_outside_hits")
    op.drop_table("crawler_outside_hits")
    op.drop_table("crawler_breaker")
    op.drop_table("crawler_budget")
    op.drop_table("crawler_live_limits")
    op.drop_index("ix_crawler_requests_policy_sent_at", table_name="crawler_requests")
    op.drop_table("crawler_requests")
    op.drop_table("data_versions")
    op.drop_table("raw_gear")
    op.drop_index("ix_characters_account_hash", table_name="characters")
    op.drop_index("ix_characters_league_id", table_name="characters")
    op.drop_table("characters")
    op.drop_table("leagues")

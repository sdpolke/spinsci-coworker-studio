"""add LangGraph rollout controls and immutable operator alerts

Revision ID: f4a7c9e2d1b6
Revises: e0f6a8b2c4d6
Create Date: 2026-08-14 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f4a7c9e2d1b6"
down_revision: str | None = "e0f6a8b2c4d6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "langgraph_rollout_states",
        sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "langgraph_rollout_states",
        sa.Column("internal_tenant_ids", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
    )
    op.add_column(
        "langgraph_rollout_states",
        sa.Column("allowlisted_tenant_ids", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
    )
    op.add_column(
        "langgraph_rollout_states",
        sa.Column("percentage_cohort", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "langgraph_rollout_states",
        sa.Column(
            "cohort_salt",
            sa.String(128),
            nullable=False,
            server_default="langgraph-rollout-v1",
        ),
    )
    op.add_column(
        "langgraph_rollout_states",
        sa.Column("expansion_halted", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "langgraph_rollout_states",
        sa.Column("expansion_halted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "langgraph_rollout_states",
        sa.Column("last_evaluated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_check_constraint(
        "ck_langgraph_rollout_percentage",
        "langgraph_rollout_states",
        "percentage_cohort >= 0 AND percentage_cohort <= 100",
    )

    op.create_table(
        "langgraph_rollout_alerts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Integer(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("rollout_stage", sa.String(64), nullable=False),
        sa.Column("evaluation_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("evaluation_ended_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reason", sa.String(255), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint(
            "organization_id",
            "rollout_stage",
            "evaluation_ended_at",
            "reason",
            name="uq_langgraph_rollout_alert_window",
        ),
    )
    op.create_index(
        "ix_langgraph_rollout_alert_org_end",
        "langgraph_rollout_alerts",
        ["organization_id", "evaluation_ended_at"],
    )


def downgrade() -> None:
    op.drop_table("langgraph_rollout_alerts")
    op.drop_constraint(
        "ck_langgraph_rollout_percentage",
        "langgraph_rollout_states",
        type_="check",
    )
    for column in (
        "last_evaluated_at",
        "expansion_halted_at",
        "expansion_halted",
        "cohort_salt",
        "percentage_cohort",
        "allowlisted_tenant_ids",
        "internal_tenant_ids",
        "disabled_at",
    ):
        op.drop_column("langgraph_rollout_states", column)

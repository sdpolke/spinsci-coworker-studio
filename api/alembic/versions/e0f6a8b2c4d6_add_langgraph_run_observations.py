"""add tenant-scoped LangGraph causal run observations

Revision ID: e0f6a8b2c4d6
Revises: d9e5f7a1b3c4
Create Date: 2026-08-13 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e0f6a8b2c4d6"
down_revision: str | None = "d9e5f7a1b3c4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "langgraph_run_observations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("workflow_run_id", sa.Integer(), sa.ForeignKey("workflow_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("invocation_id", sa.Integer(), sa.ForeignKey("langgraph_invocations.id", ondelete="CASCADE"), nullable=True),
        sa.Column("observation_type", sa.String(length=64), nullable=False),
        sa.Column("monotonic_order", sa.Integer(), nullable=False),
        sa.Column("observed_at_ms", sa.BigInteger(), nullable=False),
        sa.Column("runtime_sequence", sa.Integer(), nullable=True),
        sa.Column("attributes", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("workflow_run_id", "monotonic_order", name="uq_langgraph_run_observation_order"),
    )
    op.create_index(
        "ix_langgraph_run_observation_org_run",
        "langgraph_run_observations",
        ["organization_id", "workflow_run_id"],
    )
    op.create_table(
        "langgraph_external_identifiers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("run_binding_id", sa.Integer(), sa.ForeignKey("langgraph_voice_run_bindings.id", ondelete="CASCADE"), nullable=False),
        sa.Column("identifier_type", sa.String(length=32), nullable=False),
        sa.Column("opaque_value", sa.String(length=512), nullable=False),
        sa.Column("trace_id", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("run_binding_id", "identifier_type", "opaque_value", name="uq_langgraph_external_identifier_value"),
    )
    op.create_index(
        "ix_langgraph_external_identifier_org_binding",
        "langgraph_external_identifiers",
        ["organization_id", "run_binding_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_langgraph_external_identifier_org_binding", table_name="langgraph_external_identifiers")
    op.drop_table("langgraph_external_identifiers")
    op.drop_index("ix_langgraph_run_observation_org_run", table_name="langgraph_run_observations")
    op.drop_table("langgraph_run_observations")

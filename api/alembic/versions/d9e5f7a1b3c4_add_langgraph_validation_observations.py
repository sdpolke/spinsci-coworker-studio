"""add LangGraph validation observations

Revision ID: d9e5f7a1b3c4
Revises: c8d4e6f8a0b2
Create Date: 2026-08-12 00:00:00.000000

This additive migration stores immutable, tenant-scoped scheduled-validation
and endpoint-health observations without changing existing workflow data.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d9e5f7a1b3c4"
down_revision: Union[str, None] = "c8d4e6f8a0b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLE_NAME = "langgraph_validation_observations"
IMMUTABLE_TRIGGER = "trg_langgraph_validation_observations_immutable"


def upgrade() -> None:
    op.create_table(
        TABLE_NAME,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Integer(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "registration_id",
            sa.Integer(),
            sa.ForeignKey(
                "langgraph_endpoint_registrations.id", ondelete="CASCADE"
            ),
            nullable=False,
        ),
        sa.Column("event_key", sa.String(255), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("successful", sa.Boolean(), nullable=False),
        sa.Column(
            "observed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("window_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.UniqueConstraint(
            "registration_id",
            "event_key",
            name="uq_langgraph_observation_registration_key",
        ),
    )
    op.create_index(
        "ix_langgraph_observation_org_registration_time",
        TABLE_NAME,
        ["organization_id", "registration_id", "observed_at"],
    )
    op.execute(
        f"CREATE TRIGGER {IMMUTABLE_TRIGGER} BEFORE UPDATE ON {TABLE_NAME} "
        "FOR EACH ROW EXECUTE FUNCTION reject_langgraph_immutable_mutation()"
    )


def downgrade() -> None:
    op.execute(f"DROP TRIGGER IF EXISTS {IMMUTABLE_TRIGGER} ON {TABLE_NAME}")
    op.drop_index(
        "ix_langgraph_observation_org_registration_time",
        table_name=TABLE_NAME,
    )
    op.drop_table(TABLE_NAME)

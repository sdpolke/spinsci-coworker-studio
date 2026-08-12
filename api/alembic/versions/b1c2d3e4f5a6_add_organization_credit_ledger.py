"""add organization credit ledger

Revision ID: b1c2d3e4f5a6
Revises: c7a1e4f93b26
Create Date: 2026-08-10 15:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b1c2d3e4f5a6"
down_revision: Union[str, None] = "c7a1e4f93b26"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "organization_credit_accounts",
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column(
            "balance_credits",
            sa.Float(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "currency",
            sa.String(),
            nullable=False,
            server_default=sa.text("'USD'"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("organization_id"),
    )
    op.create_table(
        "organization_credit_ledger",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("entry_type", sa.String(), nullable=False),
        sa.Column("origin", sa.String(), nullable=True),
        sa.Column("credits_delta", sa.Float(), nullable=False),
        sa.Column("balance_after", sa.Float(), nullable=False),
        sa.Column("metric_code", sa.String(), nullable=True),
        sa.Column("billable_quantity", sa.Float(), nullable=True),
        sa.Column("quantity_unit", sa.String(), nullable=True),
        sa.Column("workflow_run_id", sa.Integer(), nullable=True),
        sa.Column("workflow_id", sa.Integer(), nullable=True),
        sa.Column("idempotency_key", sa.String(), nullable=True),
        sa.Column(
            "metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column("created_by", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organization_credit_accounts.organization_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workflow_run_id"],
            ["workflow_runs.id"],
        ),
        sa.ForeignKeyConstraint(
            ["workflow_id"],
            ["workflows.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key"),
    )
    op.create_index(
        "idx_org_credit_ledger_org_created",
        "organization_credit_ledger",
        ["organization_id", "created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_organization_credit_ledger_id"),
        "organization_credit_ledger",
        ["id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_organization_credit_ledger_idempotency_key"),
        "organization_credit_ledger",
        ["idempotency_key"],
        unique=False,
    )
    op.create_index(
        op.f("ix_organization_credit_ledger_organization_id"),
        "organization_credit_ledger",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_organization_credit_ledger_created_at"),
        "organization_credit_ledger",
        ["created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_organization_credit_ledger_created_at"),
        table_name="organization_credit_ledger",
    )
    op.drop_index(
        op.f("ix_organization_credit_ledger_organization_id"),
        table_name="organization_credit_ledger",
    )
    op.drop_index(
        op.f("ix_organization_credit_ledger_idempotency_key"),
        table_name="organization_credit_ledger",
    )
    op.drop_index(
        op.f("ix_organization_credit_ledger_id"),
        table_name="organization_credit_ledger",
    )
    op.drop_index(
        "idx_org_credit_ledger_org_created",
        table_name="organization_credit_ledger",
    )
    op.drop_table("organization_credit_ledger")
    op.drop_table("organization_credit_accounts")

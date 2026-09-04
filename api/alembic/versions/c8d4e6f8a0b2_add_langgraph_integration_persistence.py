"""add LangGraph integration persistence

Revision ID: c8d4e6f8a0b2
Revises: b1c2d3e4f5a6
Create Date: 2026-08-11 00:00:00.000000

This frozen migration is strictly additive. Existing workflows and workflow
runs receive no columns or backfill; absence of a run binding means the
historical/non-endpoint behavior remains authoritative.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c8d4e6f8a0b2"
down_revision: Union[str, None] = "b1c2d3e4f5a6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


LIFECYCLE = "'pending_validation','validation_only','active','degraded','disabled','incompatible','retired'"
ROLLOUT = "'internal_test_tenant','selected_tenant_allowlist','percentage_cohort','general_experimental_availability'"
IMMUTABLE_TABLES = (
    "langgraph_compatibility_matrices",
    "langgraph_capability_snapshots",
    "langgraph_validation_reports",
    "langgraph_validation_results",
)
TABLES = (
    "langgraph_security_events",
    "langgraph_tool_effects",
    "langgraph_accepted_events",
    "langgraph_invocation_attempts",
    "langgraph_invocations",
    "langgraph_voice_run_bindings",
    "langgraph_validation_results",
    "langgraph_validation_reports",
    "langgraph_capability_snapshots",
    "langgraph_endpoint_registrations",
    "langgraph_compatibility_matrices",
    "langgraph_retention_policies",
    "langgraph_rollout_states",
)


def _id():
    return sa.Column("id", sa.Integer(), primary_key=True)


def _org(ondelete: str = "CASCADE"):
    return sa.Column(
        "organization_id",
        sa.Integer(),
        sa.ForeignKey("organizations.id", ondelete=ondelete),
        nullable=False,
    )


def _timestamps(*, updated: bool = False):
    columns = [
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        )
    ]
    if updated:
        columns.append(
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            )
        )
    return columns


def upgrade() -> None:
    op.create_table(
        "langgraph_compatibility_matrices",
        _id(),
        sa.Column("matrix_uuid", sa.String(36), nullable=False, unique=True),
        sa.Column("matrix_version", sa.String(32), nullable=False, unique=True),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("mural_release_version", sa.String(64), nullable=False),
        sa.Column("matrix", sa.JSON(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "langgraph_endpoint_registrations",
        _id(),
        sa.Column("endpoint_uuid", sa.String(36), nullable=False, unique=True),
        _org(),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("endpoint_url", sa.String(2048), nullable=False),
        sa.Column("credential_id", sa.Integer(), sa.ForeignKey("external_credentials.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("selected_profile", sa.String(64), nullable=False),
        sa.Column("selected_capabilities", sa.JSON(), nullable=False),
        sa.Column("lifecycle_status", sa.String(32), nullable=False, server_default="pending_validation"),
        sa.Column("current_validation_report_id", sa.Integer(), nullable=True),
        sa.Column("current_capability_snapshot_id", sa.Integer(), nullable=True),
        sa.Column("private_network_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        *_timestamps(updated=True),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(f"lifecycle_status IN ({LIFECYCLE})", name="ck_langgraph_endpoint_lifecycle"),
        sa.CheckConstraint("char_length(endpoint_url) <= 2048", name="ck_langgraph_endpoint_url_length"),
        sa.UniqueConstraint("organization_id", "name", name="uq_langgraph_endpoint_org_name"),
    )
    op.create_index("ix_langgraph_endpoint_org_status", "langgraph_endpoint_registrations", ["organization_id", "lifecycle_status"])

    op.create_table(
        "langgraph_capability_snapshots",
        _id(),
        sa.Column("snapshot_uuid", sa.String(36), nullable=False, unique=True),
        _org(),
        sa.Column("registration_id", sa.Integer(), sa.ForeignKey("langgraph_endpoint_registrations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("manifest", sa.JSON(), nullable=False),
        sa.Column("manifest_digest", sa.String(64), nullable=False),
        sa.Column("schema_version", sa.String(16), nullable=False),
        sa.Column("discovered_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("registration_id", "manifest_digest", name="uq_langgraph_snapshot_registration_digest"),
    )
    op.create_index("ix_langgraph_snapshot_org_registration", "langgraph_capability_snapshots", ["organization_id", "registration_id"])

    op.create_table(
        "langgraph_validation_reports",
        _id(),
        sa.Column("report_uuid", sa.String(36), nullable=False, unique=True),
        _org(),
        sa.Column("registration_id", sa.Integer(), sa.ForeignKey("langgraph_endpoint_registrations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("capability_snapshot_id", sa.Integer(), sa.ForeignKey("langgraph_capability_snapshots.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("compatibility_matrix_id", sa.Integer(), sa.ForeignKey("langgraph_compatibility_matrices.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("suite_version", sa.String(32), nullable=False),
        sa.Column("contract_version", sa.String(16), nullable=False),
        sa.Column("selected_profile", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("report_digest", sa.String(64), nullable=False),
        *_timestamps(),
        sa.UniqueConstraint("registration_id", "report_digest", name="uq_langgraph_report_registration_digest"),
    )
    op.create_index("ix_langgraph_report_org_registration", "langgraph_validation_reports", ["organization_id", "registration_id"])
    op.create_foreign_key("fk_langgraph_endpoint_current_report", "langgraph_endpoint_registrations", "langgraph_validation_reports", ["current_validation_report_id"], ["id"], ondelete="SET NULL")
    op.create_foreign_key("fk_langgraph_endpoint_current_snapshot", "langgraph_endpoint_registrations", "langgraph_capability_snapshots", ["current_capability_snapshot_id"], ["id"], ondelete="SET NULL")

    op.create_table(
        "langgraph_validation_results",
        _id(),
        _org(),
        sa.Column("report_id", sa.Integer(), sa.ForeignKey("langgraph_validation_reports.id", ondelete="CASCADE"), nullable=False),
        sa.Column("test_identifier", sa.String(128), nullable=False),
        sa.Column("test_version", sa.String(32), nullable=False),
        sa.Column("required", sa.Boolean(), nullable=False),
        sa.Column("outcome", sa.String(32), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("measurements", sa.JSON(), nullable=False),
        sa.Column("redacted_error", sa.JSON(), nullable=True),
        *_timestamps(),
        sa.UniqueConstraint("report_id", "test_identifier", "test_version", name="uq_langgraph_validation_result_test"),
    )
    op.create_index("ix_langgraph_result_org_report", "langgraph_validation_results", ["organization_id", "report_id"])

    op.create_table(
        "langgraph_voice_run_bindings",
        _id(),
        _org(),
        sa.Column("workflow_run_id", sa.Integer(), sa.ForeignKey("workflow_runs.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("workflow_definition_id", sa.Integer(), sa.ForeignKey("workflow_definitions.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("registration_id", sa.Integer(), sa.ForeignKey("langgraph_endpoint_registrations.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("pinned_snapshot", sa.JSON(), nullable=False),
        sa.Column("contract_version", sa.String(16), nullable=False),
        sa.Column("compatibility_profile", sa.String(64), nullable=False),
        sa.Column("state_mode", sa.String(32), nullable=False),
        sa.Column("invocation_modes", sa.JSON(), nullable=False),
        sa.Column("feature_enabled_at_creation", sa.Boolean(), nullable=False),
        sa.Column("external_identifiers", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        *_timestamps(),
    )
    op.create_index("ix_langgraph_binding_org_run", "langgraph_voice_run_bindings", ["organization_id", "workflow_run_id"])

    op.create_table(
        "langgraph_invocations",
        _id(),
        sa.Column("invocation_uuid", sa.String(64), nullable=False, unique=True),
        _org(),
        sa.Column("run_binding_id", sa.Integer(), sa.ForeignKey("langgraph_voice_run_bindings.id", ondelete="CASCADE"), nullable=False),
        sa.Column("operation", sa.String(32), nullable=False),
        sa.Column("active_node_id", sa.String(255), nullable=True),
        sa.Column("mode", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("terminal_outcome", sa.JSON(), nullable=True),
        sa.Column("first_event_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("terminal_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancellation_accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("trace_id", sa.String(64), nullable=True),
        *_timestamps(),
    )
    op.create_index("ix_langgraph_invocation_org_binding", "langgraph_invocations", ["organization_id", "run_binding_id"])

    op.create_table(
        "langgraph_invocation_attempts",
        _id(),
        sa.Column("attempt_uuid", sa.String(64), nullable=False, unique=True),
        _org(),
        sa.Column("invocation_id", sa.Integer(), sa.ForeignKey("langgraph_invocations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("dispatched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("transport_outcome", sa.String(64), nullable=True),
        sa.Column("accepted_event", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("error_category", sa.String(64), nullable=True),
        sa.UniqueConstraint("invocation_id", "ordinal", name="uq_langgraph_attempt_invocation_ordinal"),
    )
    op.create_index("ix_langgraph_attempt_org_invocation", "langgraph_invocation_attempts", ["organization_id", "invocation_id"])

    op.create_table(
        "langgraph_accepted_events",
        _id(),
        _org(),
        sa.Column("invocation_id", sa.Integer(), sa.ForeignKey("langgraph_invocations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("endpoint_event_id", sa.String(128), nullable=True),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("payload_digest", sa.String(64), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("mutation_outcome", sa.String(64), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("invocation_id", "sequence", name="uq_langgraph_event_invocation_sequence"),
        sa.UniqueConstraint("invocation_id", "endpoint_event_id", name="uq_langgraph_event_invocation_event_id"),
    )
    op.create_index("ix_langgraph_event_org_invocation", "langgraph_accepted_events", ["organization_id", "invocation_id"])

    op.create_table(
        "langgraph_tool_effects",
        _id(),
        _org(),
        sa.Column("invocation_id", sa.Integer(), sa.ForeignKey("langgraph_invocations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("tool_call_id", sa.String(128), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("argument_digest", sa.String(64), nullable=False),
        sa.Column("authorization_outcome", sa.String(64), nullable=False),
        sa.Column("execution_status", sa.String(64), nullable=False),
        sa.Column("result_digest", sa.String(64), nullable=True),
        sa.Column("cached_result", sa.JSON(), nullable=True),
        sa.Column("transition_target", sa.String(255), nullable=True),
        *_timestamps(),
        sa.UniqueConstraint("invocation_id", "tool_call_id", name="uq_langgraph_tool_effect_invocation_call"),
    )
    op.create_index("ix_langgraph_tool_effect_org_invocation", "langgraph_tool_effects", ["organization_id", "invocation_id"])

    op.create_table(
        "langgraph_security_events",
        _id(),
        _org(),
        sa.Column("registration_id", sa.Integer(), sa.ForeignKey("langgraph_endpoint_registrations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("workflow_run_id", sa.Integer(), sa.ForeignKey("workflow_runs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("invocation_id", sa.Integer(), sa.ForeignKey("langgraph_invocations.id", ondelete="SET NULL"), nullable=True),
        sa.Column("tool_call_id", sa.String(128), nullable=True),
        sa.Column("tool_name", sa.String(255), nullable=True),
        sa.Column("violation_category", sa.String(64), nullable=False),
        sa.Column("enforcement_decision", sa.String(64), nullable=False),
        sa.Column("trace_id", sa.String(64), nullable=True),
        *_timestamps(),
    )
    op.create_index("ix_langgraph_security_event_org_created", "langgraph_security_events", ["organization_id", "created_at"])

    op.create_table(
        "langgraph_retention_policies",
        _id(),
        _org(),
        sa.Column("invocation_metadata_days", sa.Integer(), nullable=False),
        sa.Column("external_identifier_days", sa.Integer(), nullable=False),
        sa.Column("checkpoint_days", sa.Integer(), nullable=False),
        sa.Column("payload_days", sa.Integer(), nullable=False),
        sa.Column("capture_payloads", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("policy", sa.JSON(), nullable=False),
        sa.Column("updated_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        *_timestamps(updated=True),
        sa.CheckConstraint("invocation_metadata_days >= 0 AND external_identifier_days >= 0 AND checkpoint_days >= 0 AND payload_days >= 0", name="ck_langgraph_retention_nonnegative"),
        sa.UniqueConstraint("organization_id"),
    )
    op.create_index("ix_langgraph_retention_org", "langgraph_retention_policies", ["organization_id"])

    op.create_table(
        "langgraph_rollout_states",
        _id(),
        _org(),
        sa.Column("feature_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("experimental_acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("experimental_acknowledged_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("rollout_stage", sa.String(64), nullable=False, server_default="internal_test_tenant"),
        sa.Column("private_network_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("private_network_decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("private_network_decided_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(f"rollout_stage IN ({ROLLOUT})", name="ck_langgraph_rollout_stage"),
        sa.CheckConstraint("feature_enabled = false OR experimental_acknowledged_at IS NOT NULL", name="ck_langgraph_feature_requires_ack"),
        sa.CheckConstraint("private_network_enabled = false OR (private_network_decided_at IS NOT NULL AND private_network_decided_by IS NOT NULL)", name="ck_langgraph_private_network_audit"),
        sa.UniqueConstraint("organization_id"),
    )
    op.create_index("ix_langgraph_rollout_org", "langgraph_rollout_states", ["organization_id"])

    op.execute(
        """CREATE FUNCTION reject_langgraph_immutable_mutation() RETURNS trigger AS $$
        BEGIN RAISE EXCEPTION 'immutable LangGraph record cannot be modified'; END;
        $$ LANGUAGE plpgsql"""
    )
    for table_name in IMMUTABLE_TABLES:
        op.execute(
            f"CREATE TRIGGER trg_{table_name}_immutable BEFORE UPDATE ON {table_name} "
            "FOR EACH ROW EXECUTE FUNCTION reject_langgraph_immutable_mutation()"
        )


def downgrade() -> None:
    for table_name in IMMUTABLE_TABLES:
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table_name}_immutable ON {table_name}")
    op.execute("DROP FUNCTION IF EXISTS reject_langgraph_immutable_mutation()")
    op.drop_constraint("fk_langgraph_endpoint_current_report", "langgraph_endpoint_registrations", type_="foreignkey")
    op.drop_constraint("fk_langgraph_endpoint_current_snapshot", "langgraph_endpoint_registrations", type_="foreignkey")
    for table_name in TABLES:
        op.drop_table(table_name)

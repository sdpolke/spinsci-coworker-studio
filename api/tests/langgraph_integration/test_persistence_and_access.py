from copy import deepcopy
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select

from api.db.models import (
    Base,
    ExternalCredentialModel,
    LangGraphCapabilitySnapshotModel,
    LangGraphCompatibilityMatrixModel,
    LangGraphEndpointRegistrationModel,
    LangGraphInvocationModel,
    LangGraphValidationReportModel,
    LangGraphVoiceRunBindingModel,
    OrganizationModel,
    UserModel,
    WorkflowDefinitionModel,
    WorkflowModel,
    WorkflowRunModel,
)
from api.db.workflow_client import (
    ImmutableWorkflowDefinitionError,
    WorkflowDefinitionConfigurationConflictError,
)
from api.services.langgraph_integration.access_control import (
    LangGraphPermission,
    LangGraphRole,
    is_langgraph_authorized,
)
from api.services.langgraph_integration.configuration import (
    LangGraphFeatureConfiguration,
)
from api.services.langgraph_integration.endpoint_registration import (
    FeatureDisabledError,
    create_endpoint,
)
from api.services.pipecat.run_pipeline import _resolve_live_langgraph_binding
from api.services.workflow.langgraph_binding import (
    LangGraphFeatureDisabledError,
    require_langgraph_feature_for_operation,
)

EXPECTED_TABLES = {
    "langgraph_endpoint_registrations",
    "langgraph_capability_snapshots",
    "langgraph_compatibility_matrices",
    "langgraph_validation_reports",
    "langgraph_validation_results",
    "langgraph_voice_run_bindings",
    "langgraph_invocations",
    "langgraph_invocation_attempts",
    "langgraph_accepted_events",
    "langgraph_tool_effects",
    "langgraph_security_events",
    "langgraph_retention_policies",
    "langgraph_rollout_states",
}


def test_models_are_additive_and_existing_workflow_tables_need_no_binding_column():
    assert EXPECTED_TABLES <= set(Base.metadata.tables)
    assert "langgraph_endpoint_id" not in Base.metadata.tables["workflows"].c
    assert "langgraph_endpoint_id" not in Base.metadata.tables["workflow_runs"].c
    assert Base.metadata.tables["langgraph_voice_run_bindings"].c.workflow_run_id.nullable is False


def test_feature_configuration_is_disabled_by_default_and_requires_acknowledgment():
    assert LangGraphFeatureConfiguration().enabled is False
    with pytest.raises(ValueError, match="acknowledgment"):
        LangGraphFeatureConfiguration(enabled=True)


def test_endpoint_and_interrupt_permissions_are_separate():
    assert is_langgraph_authorized(
        role=LangGraphRole.ENDPOINT_OPERATOR,
        permission=LangGraphPermission.ACTIVATE,
    )
    assert not is_langgraph_authorized(
        role=LangGraphRole.ENDPOINT_OPERATOR,
        permission=LangGraphPermission.REVIEW_INTERRUPT,
    )
    assert is_langgraph_authorized(
        role=LangGraphRole.INTERRUPT_REVIEWER,
        permission=LangGraphPermission.REVIEW_INTERRUPT,
    )


@pytest.fixture
async def langgraph_rows(async_session):
    org_a = OrganizationModel(provider_id="langgraph-org-a")
    org_b = OrganizationModel(provider_id="langgraph-org-b")
    async_session.add_all([org_a, org_b])
    await async_session.flush()
    user = UserModel(provider_id="langgraph-user", selected_organization_id=org_a.id)
    async_session.add(user)
    await async_session.flush()
    credential = ExternalCredentialModel(
        organization_id=org_a.id,
        name="endpoint credential",
        credential_type="bearer_token",
        credential_data={"token": "secret"},
        created_by=user.id,
    )
    async_session.add(credential)
    await async_session.flush()
    return org_a, org_b, user, credential


@pytest.mark.asyncio
async def test_endpoint_client_never_reads_or_mutates_across_organizations(
    db_session, langgraph_rows
):
    org_a, org_b, user, credential = langgraph_rows
    endpoint = await db_session.create_langgraph_endpoint(
        organization_id=org_a.id,
        name="endpoint",
        endpoint_url="https://example.com",
        credential_id=credential.id,
        selected_profile="chat",
        selected_capabilities=["streaming"],
        created_by=user.id,
    )
    assert await db_session.get_langgraph_endpoint(
        organization_id=org_b.id, endpoint_uuid=endpoint.endpoint_uuid
    ) is None
    changed = await db_session.compare_and_set_langgraph_lifecycle(
        organization_id=org_b.id,
        endpoint_uuid=endpoint.endpoint_uuid,
        expected_status="pending_validation",
        new_status="active",
    )
    assert changed is False
    owned = await db_session.get_langgraph_endpoint(
        organization_id=org_a.id, endpoint_uuid=endpoint.endpoint_uuid
    )
    assert owned.lifecycle_status == "pending_validation"


@pytest.mark.asyncio
async def test_event_ledger_deduplicates_exactly_once(db_session, async_session, langgraph_rows):
    org, _, user, credential = langgraph_rows
    endpoint = LangGraphEndpointRegistrationModel(
        organization_id=org.id,
        name="ledger endpoint",
        endpoint_url="https://example.com",
        credential_id=credential.id,
        selected_profile="chat",
        selected_capabilities=["streaming"],
        created_by=user.id,
    )
    workflow = WorkflowModel(
        name="workflow",
        organization_id=org.id,
        user_id=user.id,
        workflow_definition={},
    )
    async_session.add_all([endpoint, workflow])
    await async_session.flush()
    definition = WorkflowDefinitionModel(
        workflow_id=workflow.id,
        workflow_json={},
        workflow_configurations={},
        template_context_variables={},
    )
    async_session.add(definition)
    await async_session.flush()
    run = WorkflowRunModel(name="run", workflow_id=workflow.id, definition_id=definition.id, mode="textchat")
    async_session.add(run)
    await async_session.flush()
    binding = LangGraphVoiceRunBindingModel(
        organization_id=org.id,
        workflow_run_id=run.id,
        workflow_definition_id=definition.id,
        registration_id=endpoint.id,
        pinned_snapshot={},
        contract_version="1.1",
        compatibility_profile="chat",
        state_mode="mural_authoritative",
        invocation_modes=["streaming"],
        feature_enabled_at_creation=True,
    )
    async_session.add(binding)
    await async_session.flush()
    invocation = LangGraphInvocationModel(
        invocation_uuid="inv-ledger",
        organization_id=org.id,
        run_binding_id=binding.id,
        operation="invoke",
        mode="streaming",
        status="running",
    )
    async_session.add(invocation)
    await async_session.commit()

    first, first_inserted = await db_session.record_langgraph_event(
        organization_id=org.id,
        invocation_id=invocation.id,
        sequence=0,
        endpoint_event_id="evt-0",
        event_type="text_delta",
        payload_digest="a" * 64,
        metadata={},
        mutation_outcome="forwarded",
    )
    duplicate, duplicate_inserted = await db_session.record_langgraph_event(
        organization_id=org.id,
        invocation_id=invocation.id,
        sequence=0,
        endpoint_event_id="evt-0",
        event_type="text_delta",
        payload_digest="a" * 64,
        metadata={},
        mutation_outcome="forwarded",
    )
    assert first_inserted is True
    assert duplicate_inserted is False
    assert duplicate.id == first.id


def _retained_binding(endpoint_uuid: str, report_uuid: str, snapshot_uuid: str) -> dict:
    return {
        "registration_uuid": endpoint_uuid,
        "validation_report_uuid": report_uuid,
        "validation_report_digest": "r" * 64,
        "contract_version": "1.1",
        "compatibility_profile": "chat",
        "state_mode": "mural_authoritative",
        "live_invocation_mode": "streaming",
        "selected_capabilities": ["streaming"],
        "capability_snapshot_uuid": snapshot_uuid,
        "capability_snapshot_digest": "s" * 64,
        "capability_snapshot": {
            "contract_versions": ["1.1"],
            "compatibility_profiles": ["chat"],
            "invocation_modes": ["streaming"],
            "state_modes": ["mural_authoritative"],
            "data_regions": ["us-east"],
        },
        "data_sharing_policy": {"allow": ["messages"]},
        "data_region": "us-east",
        "first_event_deadline_ms": 1500,
        "first_event_action": "fallback_message",
        "terminal_failure_action": "transfer",
        "evidence": {
            "text_session_conformance": True,
            "accepted_transition": True,
            "cancellation_verified": True,
            "recording_verified": True,
        },
        "endpoint_url": "https://agent.example",
        "credential_reference": "credential-retained",
        "operations": {"invoke": "/v1/invocations"},
        "limits": {
            "request_bytes": 1000,
            "response_bytes": 1000,
            "event_bytes": 500,
            "tool_argument_bytes": 500,
        },
    }


@pytest.mark.asyncio
async def test_feature_disablement_preserves_history_and_diagnostics_while_all_new_entry_points_stay_blocked(
    async_session, db_session, langgraph_rows, monkeypatch
):
    org, _, user, credential = langgraph_rows
    organization_id = org.id
    actor_user_id = user.id
    credential_uuid = credential.credential_uuid
    now = datetime.now(UTC)
    endpoint = LangGraphEndpointRegistrationModel(
        organization_id=org.id,
        name="retained endpoint",
        endpoint_url="https://agent.example",
        credential_id=credential.id,
        selected_profile="chat",
        selected_capabilities=["streaming"],
        lifecycle_status="active",
        created_by=user.id,
    )
    matrix = LangGraphCompatibilityMatrixModel(
        matrix_version=f"preservation-{org.id}",
        effective_at=now,
        mural_release_version="test",
        matrix={"contract_versions": ["1.1"]},
    )
    workflow = WorkflowModel(
        name="retained workflow",
        organization_id=org.id,
        user_id=user.id,
        workflow_definition={},
    )
    async_session.add_all([endpoint, matrix, workflow])
    await async_session.flush()

    snapshot = LangGraphCapabilitySnapshotModel(
        organization_id=org.id,
        registration_id=endpoint.id,
        manifest={"contract_versions": ["1.1"]},
        manifest_digest="s" * 64,
        schema_version="1.1",
    )
    async_session.add(snapshot)
    await async_session.flush()
    report = LangGraphValidationReportModel(
        organization_id=org.id,
        registration_id=endpoint.id,
        capability_snapshot_id=snapshot.id,
        compatibility_matrix_id=matrix.id,
        suite_version="test",
        contract_version="1.1",
        selected_profile="chat",
        status="live_voice_eligible",
        started_at=now,
        completed_at=now,
        evidence={"text_session_conformance": True},
        report_digest="r" * 64,
    )
    async_session.add(report)
    await async_session.flush()
    endpoint.current_capability_snapshot_id = snapshot.id
    endpoint.current_validation_report_id = report.id

    binding_payload = _retained_binding(
        endpoint.endpoint_uuid, report.report_uuid, snapshot.snapshot_uuid
    )
    prior_definition = WorkflowDefinitionModel(
        workflow_id=workflow.id,
        workflow_json={"version": 1},
        workflow_configurations={},
        template_context_variables={},
    )
    published_definition = WorkflowDefinitionModel(
        workflow_id=workflow.id,
        workflow_json={"version": 2},
        workflow_configurations={"langgraph_endpoint": binding_payload},
        template_context_variables={},
    )
    async_session.add_all([prior_definition, published_definition])
    await async_session.flush()
    run = WorkflowRunModel(
        name="retained run",
        workflow_id=workflow.id,
        definition_id=published_definition.id,
        mode="textchat",
        logs={"status": "completed"},
    )
    async_session.add(run)
    await async_session.flush()
    run_binding = LangGraphVoiceRunBindingModel(
        organization_id=org.id,
        workflow_run_id=run.id,
        workflow_definition_id=published_definition.id,
        registration_id=endpoint.id,
        pinned_snapshot=binding_payload,
        contract_version="1.1",
        compatibility_profile="chat",
        state_mode="mural_authoritative",
        invocation_modes=["streaming"],
        feature_enabled_at_creation=True,
    )
    async_session.add(run_binding)
    await async_session.flush()
    invocation = LangGraphInvocationModel(
        invocation_uuid=f"retained-invocation-{org.id}",
        organization_id=org.id,
        run_binding_id=run_binding.id,
        operation="invoke",
        mode="streaming",
        status="completed",
        trace_id="retained-trace",
    )
    async_session.add(invocation)
    await async_session.commit()

    async def retained_state() -> tuple[int, str, tuple[int, ...], int, int]:
        registration_count = await async_session.scalar(
            select(func.count()).select_from(LangGraphEndpointRegistrationModel).where(
                LangGraphEndpointRegistrationModel.organization_id == org.id
            )
        )
        retained_report = await async_session.get(LangGraphValidationReportModel, report.id)
        definition_ids = tuple(
            (
                await async_session.scalars(
                    select(WorkflowDefinitionModel.id)
                    .where(WorkflowDefinitionModel.workflow_id == workflow.id)
                    .order_by(WorkflowDefinitionModel.id)
                )
            ).all()
        )
        run_count = await async_session.scalar(
            select(func.count()).select_from(WorkflowRunModel).where(
                WorkflowRunModel.id == run.id
            )
        )
        invocation_count = await async_session.scalar(
            select(func.count()).select_from(LangGraphInvocationModel).where(
                LangGraphInvocationModel.run_binding_id == run_binding.id
            )
        )
        return (
            int(registration_count or 0),
            retained_report.report_digest,
            definition_ids,
            int(run_count or 0),
            int(invocation_count or 0),
        )

    before = await retained_state()
    disabled = AsyncMock(return_value=LangGraphFeatureConfiguration(enabled=False))
    monkeypatch.setattr(
        "api.services.langgraph_integration.endpoint_registration.get_langgraph_feature_configuration",
        disabled,
    )
    monkeypatch.setattr(
        "api.services.langgraph_integration.configuration.get_langgraph_feature_configuration",
        disabled,
    )

    with pytest.raises(FeatureDisabledError):
        await create_endpoint(
            organization_id=organization_id,
            actor_user_id=actor_user_id,
            role=LangGraphRole.ORGANIZATION_ADMIN,
            name="blocked endpoint",
            endpoint_url="https://blocked.example",
            credential_uuid=credential_uuid,
            selected_profile="chat",
            selected_capabilities=["streaming"],
        )
    for operation in ("attach endpoint", "publish endpoint-backed workflow"):
        with pytest.raises(LangGraphFeatureDisabledError):
            require_langgraph_feature_for_operation(enabled=False, operation=operation)
    with pytest.raises(FeatureDisabledError):
        await _resolve_live_langgraph_binding(
            run_configs={"langgraph_endpoint": binding_payload},
            organization_id=org.id,
            is_realtime=False,
        )

    assert await retained_state() == before
    diagnostics = await db_session.get_langgraph_run_diagnostics(
        organization_id=org.id, workflow_run_id=run.id
    )
    assert diagnostics is not None
    assert diagnostics[0].id == run.id
    assert [item.invocation_uuid for item in diagnostics[3]] == [invocation.invocation_uuid]


@pytest.mark.asyncio
async def test_conditional_draft_binding_update_is_tenant_scoped_immutable_and_conflict_safe(
    async_session, db_session, langgraph_rows
):
    org_a, org_b, user, _ = langgraph_rows
    workflow = WorkflowModel(
        name="conditional topology workflow",
        organization_id=org_a.id,
        user_id=user.id,
        workflow_definition={},
    )
    async_session.add(workflow)
    await async_session.flush()
    original_configurations = {
        "langgraph_endpoint": {
            "capability_snapshot_uuid": "snapshot-old",
            "topology_snapshot": {
                "endpoint_binding_revision": "snapshot-old",
            },
        },
        "unrelated": {"preserve": True},
    }
    draft = WorkflowDefinitionModel(
        workflow_id=workflow.id,
        workflow_json={},
        status="draft",
        workflow_configurations=deepcopy(original_configurations),
        template_context_variables={},
    )
    published = WorkflowDefinitionModel(
        workflow_id=workflow.id,
        workflow_json={},
        status="published",
        workflow_configurations=deepcopy(original_configurations),
        template_context_variables={},
    )
    async_session.add_all([draft, published])
    await async_session.commit()

    desired_configurations = deepcopy(original_configurations)
    desired_binding = desired_configurations["langgraph_endpoint"]
    desired_binding["capability_snapshot_uuid"] = "snapshot-current"
    desired_binding["topology_snapshot"] = {
        "endpoint_binding_revision": "snapshot-current",
        "digest": "d" * 64,
        "topology": {"schema_version": "1.2"},
    }

    with pytest.raises(ValueError, match="not found"):
        await db_session.update_draft_workflow_definition_configurations_conditionally(
            organization_id=org_b.id,
            workflow_id=workflow.id,
            definition_id=draft.id,
            expected_binding_revision="snapshot-old",
            expected_workflow_configurations=original_configurations,
            workflow_configurations=desired_configurations,
        )
    with pytest.raises(ImmutableWorkflowDefinitionError):
        await db_session.update_draft_workflow_definition_configurations_conditionally(
            organization_id=org_a.id,
            workflow_id=workflow.id,
            definition_id=published.id,
            expected_binding_revision="snapshot-old",
            expected_workflow_configurations=original_configurations,
            workflow_configurations=desired_configurations,
        )
    with pytest.raises(WorkflowDefinitionConfigurationConflictError):
        await db_session.update_draft_workflow_definition_configurations_conditionally(
            organization_id=org_a.id,
            workflow_id=workflow.id,
            definition_id=draft.id,
            expected_binding_revision="snapshot-old",
            expected_workflow_configurations={
                **original_configurations,
                "concurrent": True,
            },
            workflow_configurations=desired_configurations,
        )

    await db_session.update_draft_workflow_definition_configurations_conditionally(
        organization_id=org_a.id,
        workflow_id=workflow.id,
        definition_id=draft.id,
        expected_binding_revision="snapshot-old",
        expected_workflow_configurations=original_configurations,
        workflow_configurations=desired_configurations,
    )
    stored = await db_session.get_workflow_definition(
        organization_id=org_a.id,
        workflow_id=workflow.id,
        definition_id=draft.id,
    )
    assert stored.workflow_configurations == desired_configurations
    assert stored.workflow_configurations["unrelated"] == {"preserve": True}

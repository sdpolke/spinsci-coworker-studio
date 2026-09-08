from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from api.schemas.langgraph_topology import (
    DraftBindingState,
    ExternalTopologyResponse,
)
from api.schemas.workflow_configurations import LangGraphEndpointBinding
from api.services.workflow.langgraph_binding import (
    build_candidate_langgraph_binding,
    classify_langgraph_draft_binding,
    pinned_run_snapshot,
    validate_binding_against_evidence,
)


def binding(**changes):
    values = {
        "registration_uuid": "endpoint-1",
        "validation_report_uuid": "report-1",
        "validation_report_digest": "report-digest",
        "contract_version": "1.0",
        "compatibility_profile": "chat",
        "state_mode": "mural_authoritative",
        "live_invocation_mode": "streaming",
        "selected_capabilities": ["cancellation"],
        "capability_snapshot_uuid": "snapshot-1",
        "capability_snapshot_digest": "snapshot-digest",
        "capability_snapshot": {
            "contract_versions": ["1.0"],
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
        "credential_reference": "credential-1",
        "operations": {"invoke": "/v1/invocations"},
        "limits": {"request_bytes": 1000, "response_bytes": 1000, "event_bytes": 500, "tool_argument_bytes": 500},
    }
    values.update(changes)
    return LangGraphEndpointBinding.model_validate(values)


def evidence(value):
    endpoint = SimpleNamespace(
        id=1,
        endpoint_uuid="endpoint-1",
        lifecycle_status="active",
        current_validation_report_id=2,
        current_capability_snapshot_id=3,
        selected_profile="chat",
        selected_capabilities=["cancellation"],
    )
    report = SimpleNamespace(
        id=2,
        status="live_voice_eligible",
        report_uuid="report-1",
        report_digest="report-digest",
        contract_version="1.0",
        selected_profile="chat",
        evidence=value.evidence.model_dump(),
    )
    snapshot = SimpleNamespace(
        id=3,
        snapshot_uuid="snapshot-1",
        manifest_digest="snapshot-digest",
        manifest=value.capability_snapshot,
    )
    return endpoint, report, snapshot


def test_valid_binding_matches_current_evidence_and_snapshot_is_detached():
    value = binding()
    endpoint, report, snapshot = evidence(value)
    assert validate_binding_against_evidence(value, endpoint=endpoint, report=report, snapshot=snapshot) == ()
    pinned = pinned_run_snapshot(value)
    pinned["capability_snapshot"]["contract_versions"].append("9.9")
    assert value.capability_snapshot["contract_versions"] == ["1.0"]


@pytest.mark.parametrize("deadline", [499, 3001])
def test_first_event_deadline_boundaries_reject_invalid_values(deadline):
    with pytest.raises(ValueError):
        binding(first_event_deadline_ms=deadline)


def test_changed_capabilities_and_incomplete_evidence_block_publication():
    value = binding(
        selected_capabilities=[],
        evidence={
            "text_session_conformance": True,
            "accepted_transition": False,
            "cancellation_verified": True,
            "recording_verified": True,
        },
    )
    endpoint, report, snapshot = evidence(value)
    endpoint.selected_capabilities = ["cancellation"]
    errors = validate_binding_against_evidence(
        value, endpoint=endpoint, report=report, snapshot=snapshot
    )
    assert "selected capabilities do not exactly match registration" in errors
    assert "workflow binding lacks complete live-eligibility evidence" in errors


@pytest.mark.asyncio
async def test_topology_status_and_candidate_rebind_use_current_evidence_without_selected_capability_changes():
    old_binding = binding()
    manifest = {
        "contract_versions": ["1.2"],
        "compatibility_profiles": ["chat"],
        "invocation_modes": ["streaming"],
        "state_modes": ["mural_authoritative"],
        "data_regions": ["us-east"],
        "operations": {
            "invoke": "/v1/invocations",
            "topology": "/v1/topology",
        },
        "limits": {
            "request_bytes": 1000,
            "response_bytes": 2000,
            "event_bytes": 500,
            "tool_argument_bytes": 500,
        },
        "ownership": {"tools": "mural"},
    }
    endpoint = SimpleNamespace(
        id=1,
        endpoint_uuid=old_binding.registration_uuid,
        lifecycle_status="active",
        current_validation_report_id=20,
        current_capability_snapshot_id=30,
        selected_profile=old_binding.compatibility_profile,
        selected_capabilities=list(old_binding.selected_capabilities),
    )
    report = SimpleNamespace(
        id=20,
        capability_snapshot_id=30,
        status="passed",
        report_uuid="report-current",
        report_digest="r" * 64,
        contract_version="1.2",
        selected_profile="chat",
        evidence=old_binding.evidence.model_dump(),
    )
    snapshot = SimpleNamespace(
        id=30,
        snapshot_uuid="snapshot-current",
        manifest_digest="s" * 64,
        manifest=manifest,
    )
    definition = SimpleNamespace(
        status="draft",
        workflow_configurations={
            "langgraph_endpoint": old_binding.model_dump(mode="json")
        },
    )
    evidence_loader = AsyncMock(return_value=(endpoint, report, snapshot))
    db_client = SimpleNamespace(
        get_current_langgraph_activation_evidence=evidence_loader
    )

    stale = await classify_langgraph_draft_binding(
        organization_id=41,
        definition=definition,
        db_client=db_client,
    )
    assert stale.state == DraftBindingState.BINDING_STALE
    assert stale.bound_validation_report_uuid == "report-1"
    assert stale.current_validation_report_uuid == "report-current"
    evidence_loader.assert_awaited_once_with(
        organization_id=41,
        endpoint_uuid=old_binding.registration_uuid,
    )

    candidate = build_candidate_langgraph_binding(
        old_binding,
        endpoint=endpoint,
        report=report,
        snapshot=snapshot,
    )
    assert candidate.validation_report_uuid == report.report_uuid
    assert candidate.capability_snapshot_uuid == snapshot.snapshot_uuid
    assert candidate.operations["topology"] == "/v1/topology"
    assert candidate.selected_capabilities == old_binding.selected_capabilities
    assert "topology" not in candidate.selected_capabilities
    for field_name in (
        "registration_uuid",
        "endpoint_url",
        "credential_reference",
        "compatibility_profile",
        "state_mode",
        "live_invocation_mode",
        "non_conversational_modes",
        "data_region",
        "data_sharing_policy",
        "redaction_policy_id",
        "compiled_policy_versions",
        "first_event_deadline_ms",
        "first_event_action",
        "terminal_failure_action",
    ):
        assert getattr(candidate, field_name) == getattr(old_binding, field_name)

    unsupported_snapshot = SimpleNamespace(
        id=snapshot.id,
        snapshot_uuid=snapshot.snapshot_uuid,
        manifest_digest=snapshot.manifest_digest,
        manifest={**manifest, "operations": {"invoke": "/v1/invocations"}},
    )
    db_client.get_current_langgraph_activation_evidence = AsyncMock(
        return_value=(endpoint, report, unsupported_snapshot)
    )
    unsupported = await classify_langgraph_draft_binding(
        organization_id=41,
        definition=definition,
        db_client=db_client,
    )
    assert unsupported.state == DraftBindingState.TOPOLOGY_UNSUPPORTED


def test_external_topology_response_remains_compatible_with_original_fields():
    response = ExternalTopologyResponse(
        status="unavailable",
        reason="snapshot_unavailable",
    )

    assert response.model_dump(mode="json", exclude_none=True) == {
        "status": "unavailable",
        "reason": "snapshot_unavailable",
    }

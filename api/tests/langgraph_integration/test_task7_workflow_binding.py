from types import SimpleNamespace

import pytest

from api.schemas.workflow_configurations import LangGraphEndpointBinding
from api.services.workflow.langgraph_binding import (
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

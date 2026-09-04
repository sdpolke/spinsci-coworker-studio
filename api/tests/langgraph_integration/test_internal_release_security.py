from __future__ import annotations

from copy import deepcopy

import pytest

from api.services.langgraph_integration.callbacks import CallbackScope, validate_callback_scope
from api.services.langgraph_integration.conformance import CHAT_BASELINE_FIXTURES, run_suite
from api.services.langgraph_integration.configuration import LangGraphFeatureConfiguration
from api.services.langgraph_integration.endpoint_registration import normalize_endpoint_url
from api.services.langgraph_integration.threat_model import (
    AgentRequirements,
    classify_agent_requirements,
)


def test_internal_release_conformance_suite_covers_required_chat_protocol_behaviors():
    result = run_suite()
    fixture_ids = {fixture.identifier for fixture in CHAT_BASELINE_FIXTURES}

    assert result.passed
    required_suffixes = {
        "plain_text",
        "single_tool_call",
        "tool_result",
        "authentication",
        "timeout",
        "disconnect",
        "cancellation",
        "post_terminal",
    }
    assert all(any(identifier.endswith(suffix) for identifier in fixture_ids) for suffix in required_suffixes)
    assert result.report_evidence()["required_fixture_count"] > 0


def test_authenticated_callback_rejects_every_cross_tenant_correlation_without_mutation():
    scope = CallbackScope(
        organization_id=7,
        registration_id="registration-a",
        voice_run_id="run-a",
        external_run_id="external-a",
    )
    target_state = {"status": "running", "events": []}
    before = deepcopy(target_state)

    attacks = (
        {"organization_id": 8, "registration_id": "registration-a", "voice_run_id": "run-a", "external_run_id": "external-a"},
        {"organization_id": 7, "registration_id": "registration-b", "voice_run_id": "run-a", "external_run_id": "external-a"},
        {"organization_id": 7, "registration_id": "registration-a", "voice_run_id": "run-b", "external_run_id": "external-a"},
        {"organization_id": 7, "registration_id": "registration-a", "voice_run_id": "run-a", "external_run_id": "external-b"},
    )
    for payload in attacks:
        with pytest.raises(PermissionError, match="scope mismatch"):
            validate_callback_scope(authenticated_scope=scope, payload=payload)
        assert target_state == before


def test_callback_uses_authenticated_tenant_scope_and_drops_endpoint_tenant_claim():
    scope = CallbackScope(7, "registration-a", "run-a", "external-a")
    accepted = validate_callback_scope(
        authenticated_scope=scope,
        payload={
            "organization_id": 7,
            "registration_id": "registration-a",
            "voice_run_id": "run-a",
            "external_run_id": "external-a",
            "status": "completed",
        },
    )
    assert "organization_id" not in accepted
    assert accepted["status"] == "completed"


def test_release_defaults_and_text_only_boundary_remain_closed():
    assert LangGraphFeatureConfiguration().enabled is False
    assert normalize_endpoint_url("HTTPS://Agent.Example/path/") == "https://agent.example/path"
    classification = classify_agent_requirements(
        AgentRequirements(
            direct_audio=True,
            in_process_object=True,
            executable_package=True,
            undocumented_payload=True,
        )
    )
    assert not classification.supported
    assert len(classification.reasons) == 4

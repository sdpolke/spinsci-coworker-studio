from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

import api.routes.langgraph_endpoints as routes
from api.routes.langgraph_endpoints import router
from api.services.auth.depends import get_user
from api.services.langgraph_integration.configuration import (
    LangGraphFeatureConfiguration,
)

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _client(organization_id=11):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_user] = lambda: SimpleNamespace(
        id=7, selected_organization_id=organization_id, langgraph_role="organization_admin"
    )
    return TestClient(app)


def test_feature_status_is_tenant_scoped_and_experimental(monkeypatch):
    feature = AsyncMock(
        return_value=LangGraphFeatureConfiguration(
            enabled=True,
            experimental_acknowledged_at=NOW,
            experimental_acknowledged_by=7,
        )
    )
    monkeypatch.setattr(routes, "get_langgraph_feature_configuration", feature)

    response = _client(22).get("/langgraph-feature")

    assert response.status_code == 200
    assert response.json() == {
        "enabled": True,
        "experimental": True,
        "acknowledged": True,
        "rollout_stage": "internal_test_tenant",
        "can_configure": True,
        "private_network_configurable": True,
        "private_network_enabled": False,
    }
    feature.assert_awaited_once_with(22)


def test_run_diagnostics_merge_causal_sources_and_redact(monkeypatch):
    run = SimpleNamespace(
        id=90,
        created_at=NOW,
        logs={
            "realtime_feedback_events": [
                {
                    "type": "rtf-user-transcription",
                    "timestamp": "2026-01-01T00:00:00Z",
                    "payload": {"transcript": "private words", "final": True},
                }
            ]
        },
    )
    binding = SimpleNamespace(
        id=4,
        contract_version="1.1",
        compatibility_profile="chat",
        state_mode="mural_authoritative",
        external_identifiers={"external_run_id": "run-opaque", "checkpoint": "secret"},
    )
    registration = SimpleNamespace(endpoint_uuid="endpoint-1")
    invocation = SimpleNamespace(id=8, invocation_uuid="inv-1", trace_id="abc123")
    attempt = SimpleNamespace(
        invocation_id=8,
        attempt_uuid="att-1",
        ordinal=1,
        dispatched_at=NOW.replace(microsecond=1000),
        error_category=None,
        http_status=200,
        transport_outcome="connected",
        accepted_event=True,
    )
    event = SimpleNamespace(
        id=10,
        invocation_id=8,
        sequence=0,
        endpoint_event_id="evt-1",
        event_type="text_delta",
        metadata_json={"prompt": "do not expose", "length": 4},
        mutation_outcome="forwarded",
        accepted_at=NOW.replace(microsecond=2000),
    )
    tool = SimpleNamespace(
        id=11,
        invocation_id=8,
        tool_call_id="tool-1",
        name="move_to_billing",
        argument_digest="digest",
        authorization_outcome="authorized",
        execution_status="completed",
        transition_target="billing",
        created_at=NOW.replace(microsecond=3000),
    )
    query = AsyncMock(
        return_value=(
            run,
            binding,
            registration,
            [invocation],
            [attempt],
            [event],
            [tool],
            [],
            [],
            [],
        )
    )
    monkeypatch.setattr(routes.db_client, "get_langgraph_run_diagnostics", query)

    response = _client().get("/workflow-runs/90/langgraph-diagnostics")

    assert response.status_code == 200
    body = response.json()
    assert [item["category"] for item in body["events"]] == [
        "pipecat",
        "attempt",
        "runtime_event",
        "transition",
    ]
    assert [item["order"] for item in body["events"]] == list(range(4))
    assert body["events"][2]["trace_url"] == "/traces/abc123"
    assert body["events"][0]["details"]["transcript"] == "[REDACTED]"
    assert body["events"][2]["details"]["metadata"]["prompt"] == "[REDACTED]"
    assert body["external_identifiers"]["checkpoint"] == "[REDACTED]"
    query.assert_awaited_once_with(organization_id=11, workflow_run_id=90)


def test_foreign_or_missing_run_is_non_enumerating(monkeypatch):
    query = AsyncMock(return_value=None)
    monkeypatch.setattr(routes.db_client, "get_langgraph_run_diagnostics", query)

    response = _client(99).get("/workflow-runs/90/langgraph-diagnostics")

    assert response.status_code == 404
    assert response.json() == {"detail": "Run diagnostics not found"}
    query.assert_awaited_once_with(organization_id=99, workflow_run_id=90)


def test_run_diagnostics_surface_causal_observations_and_security_decisions_only(monkeypatch):
    run = SimpleNamespace(id=90, created_at=NOW, logs={})
    binding = SimpleNamespace(
        id=4,
        contract_version="1.1",
        compatibility_profile="chat",
        state_mode="mural_authoritative",
        external_identifiers={
            "external_run_id": "r" * 600,
            "thread_id": "thread-opaque",
            "checkpoint_reference": "checkpoint-secret",
        },
    )
    registration = SimpleNamespace(endpoint_uuid="endpoint-1")
    invocation = SimpleNamespace(id=8, invocation_uuid="inv-1", trace_id="abc123")
    observation = SimpleNamespace(
        id=12,
        invocation_id=8,
        observation_type="dispatch",
        observed_at_ms=1767225600000,
        runtime_sequence=None,
        monotonic_order=0,
        attributes={"prompt": "private", "phase": "gateway"},
    )
    security = SimpleNamespace(
        id=13,
        invocation_id=8,
        created_at=NOW,
        violation_category="foreign_resource",
        enforcement_decision="denied",
        tool_call_id="tool-1",
        tool_name="lookup_account",
    )
    query = AsyncMock(
        return_value=(
            run,
            binding,
            registration,
            [invocation],
            [],
            [],
            [],
            [observation],
            [security],
            [SimpleNamespace(identifier_type="external_run_id", trace_id="abc123")],
        )
    )
    monkeypatch.setattr(routes.db_client, "get_langgraph_run_diagnostics", query)

    body = _client().get("/workflow-runs/90/langgraph-diagnostics").json()

    assert [event["category"] for event in body["events"]] == ["observation", "security"]
    assert body["events"][0]["details"]["attributes"]["prompt"] == "[REDACTED]"
    assert body["events"][1]["details"] == {
        "tool_call_id": "tool-1",
        "tool_name": "lookup_account",
        "violation_category": "foreign_resource",
        "enforcement_decision": "denied",
    }
    assert body["external_identifiers"]["checkpoint_reference"] == "[REDACTED]"
    assert len(body["external_identifiers"]["external_run_id"]) == 512
    assert "checkpoint-secret" not in repr(body)

    assert body["external_identifier_traces"] == [
        {
            "identifier_type": "external_run_id",
            "trace_id": "abc123",
            "trace_url": "/traces/abc123",
        }
    ]

import json
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from api.db.workflow_client import WorkflowDefinitionConfigurationConflictError
from api.schemas.langgraph_integration import v1_2
from api.schemas.workflow_configurations import LangGraphEndpointBinding
from api.services.langgraph_integration.gateway import (
    GatewayTraceContext,
    IntegrationGateway,
    RuntimeEndpointSnapshot,
    StaticCredentialResolver,
)
from api.services.langgraph_integration.protocol import (
    ProtocolViolation,
    canonical_digest,
)
from api.services.langgraph_integration.topology import (
    refresh_draft_topology,
    snapshot_from_binding,
    topology_for_definition,
    update_draft_binding_and_topology,
)


class _Response:
    def __init__(self, payload):
        self.status_code = 200
        self.headers = httpx.Headers({"content-type": "application/json"})
        self.payload = json.dumps(payload).encode()
        self.closed = False

    @property
    def is_redirect(self):
        return False

    async def aiter_bytes(self):
        yield self.payload

    async def aclose(self):
        self.closed = True


class _Transport:
    def __init__(self, payload):
        self.response = _Response(payload)
        self.calls = []

    async def request(self, method, url, *, headers, content, timeout, validate_connection):
        validate_connection("8.8.8.8")
        self.calls.append((method, url, dict(headers), content, timeout))
        return self.response, "8.8.8.8"


def _manifest(*, topology=True):
    operations = {"invoke": "/v1/invocations"}
    if topology:
        operations["topology"] = "/v1/topology"
    return {
        "contract_versions": ["1.2"],
        "compatibility_profiles": ["chat"],
        "invocation_modes": ["streaming"],
        "state_modes": ["mural_authoritative"],
        "data_regions": ["us-east-1"],
        "operations": operations,
        "limits": {
            "request_bytes": 1000,
            "response_bytes": 10000,
            "event_bytes": 1000,
            "tool_argument_bytes": 1000,
        },
        "ownership": {"tools": "mural"},
    }


def _binding(**changes):
    manifest = _manifest()
    value = {
        "registration_uuid": "endpoint-1",
        "validation_report_uuid": "report-1",
        "validation_report_digest": "a" * 64,
        "contract_version": "1.2",
        "compatibility_profile": "chat",
        "state_mode": "mural_authoritative",
        "live_invocation_mode": "streaming",
        "selected_capabilities": [],
        "capability_snapshot_uuid": "capability-1",
        "capability_snapshot_digest": "b" * 64,
        "capability_snapshot": manifest,
        "data_region": "us-east-1",
        "first_event_deadline_ms": 1500,
        "first_event_action": "fallback_message",
        "terminal_failure_action": "fallback_message",
        "evidence": {
            "text_session_conformance": True,
            "accepted_transition": True,
            "cancellation_verified": True,
            "recording_verified": True,
        },
        "endpoint_url": "https://agent.example",
        "credential_reference": "credential-1",
        "operations": manifest["operations"],
        "limits": manifest["limits"],
        "ownership": manifest["ownership"],
        "data_sharing_policy": {"context_fields": []},
    }
    value.update(changes)
    return LangGraphEndpointBinding.model_validate(value)


def _evidence(binding, *, current=True, topology=True):
    manifest = _manifest(topology=topology)
    report_uuid = binding.validation_report_uuid if current else "report-current"
    report_digest = binding.validation_report_digest if current else "c" * 64
    snapshot_uuid = binding.capability_snapshot_uuid if current else "capability-current"
    snapshot_digest = binding.capability_snapshot_digest if current else "d" * 64
    if current:
        manifest = binding.capability_snapshot
    endpoint = SimpleNamespace(
        id=1,
        endpoint_uuid=binding.registration_uuid,
        lifecycle_status="active",
        current_validation_report_id=2,
        current_capability_snapshot_id=3,
        selected_profile=binding.compatibility_profile,
        selected_capabilities=list(binding.selected_capabilities),
    )
    report = SimpleNamespace(
        id=2,
        capability_snapshot_id=3,
        status="passed",
        report_uuid=report_uuid,
        report_digest=report_digest,
        contract_version="1.2",
        selected_profile=binding.compatibility_profile,
        evidence=binding.evidence.model_dump(),
    )
    snapshot = SimpleNamespace(
        id=3,
        snapshot_uuid=snapshot_uuid,
        manifest_digest=snapshot_digest,
        manifest=manifest,
    )
    return endpoint, report, snapshot


def _definition(binding, *, status="draft"):
    return SimpleNamespace(
        id=19,
        workflow_id=7,
        status=status,
        workflow_configurations={
            "langgraph_endpoint": binding.model_dump(mode="json", exclude_none=True),
            "unrelated": {"preserved": True},
        },
    )


def _db(definition, evidence):
    return SimpleNamespace(
        get_workflow_definition=AsyncMock(return_value=definition),
        get_current_langgraph_activation_evidence=AsyncMock(return_value=evidence),
        update_draft_workflow_definition_configurations_conditionally=AsyncMock(),
    )


def _topology():
    return v1_2.EndpointTopology.model_validate(
        {
            "schema_version": "1.2",
            "graph_id": "support-graph",
            "revision": "rev-1",
            "view": "collapsed",
            "nodes": [{"id": "start", "label": "Start"}],
            "edges": [],
        }
    )


def _snapshot():
    return RuntimeEndpointSnapshot(
        organization_id=11,
        registration_id="endpoint-1",
        endpoint_url="https://agent.example",
        credential_reference="credential-1",
        contract_version="1.2",
        invocation_modes=frozenset(),
        operations={"topology": "/v1/topology"},
        request_bytes=1000,
        response_bytes=10000,
        event_bytes=1000,
        tool_argument_bytes=1000,
    )


@pytest.mark.asyncio
async def test_gateway_fetches_authenticated_collapsed_topology_through_secure_transport(monkeypatch):
    monkeypatch.setattr(
        "api.utils.url_security._resolve_hostname_ips",
        lambda *_: [__import__("ipaddress").ip_address("8.8.8.8")],
    )
    topology = _topology()
    transport = _Transport(topology.model_dump(mode="json"))
    gateway = IntegrationGateway(
        credential_resolver=StaticCredentialResolver({"Authorization": "Bearer secret"}),
        transport=transport,
    )

    result = await gateway.fetch_topology(
        _snapshot(),
        view=v1_2.TopologyView.COLLAPSED,
        trace_context=GatewayTraceContext(
            organization_id=11,
            registration_id="endpoint-1",
            contract_version="1.2",
            trace_id="1" * 32,
        ),
    )

    assert result == topology
    method, url, headers, content, timeout = transport.calls[0]
    assert (method, url, content, timeout) == (
        "GET",
        "https://agent.example/v1/topology?view=collapsed",
        None,
        300.0,
    )
    assert headers["Authorization"] == "Bearer secret"
    assert headers["traceparent"].startswith("00-" + "1" * 32)


@pytest.mark.asyncio
async def test_current_refresh_pins_atomically_without_replacing_evidence():
    topology = _topology()
    binding = _binding()
    definition = _definition(binding)
    db = _db(definition, _evidence(binding))
    gateway = SimpleNamespace(fetch_topology=AsyncMock(return_value=topology))

    refreshed = await refresh_draft_topology(
        organization_id=11,
        workflow_id=7,
        definition_id=19,
        db_client=db,
        private_network_enabled=False,
        gateway=gateway,
    )

    assert refreshed.status == "available"
    assert refreshed.digest == canonical_digest(topology)
    assert refreshed.binding_status.state == "binding_current"
    assert refreshed.stages.topology_refresh == "pinned"
    call = db.update_draft_workflow_definition_configurations_conditionally.await_args.kwargs
    pinned_config = call["workflow_configurations"]
    pinned_binding = LangGraphEndpointBinding.model_validate(
        pinned_config["langgraph_endpoint"]
    )
    assert pinned_binding.validation_report_uuid == binding.validation_report_uuid
    assert pinned_binding.validation_report_digest == binding.validation_report_digest
    assert pinned_binding.capability_snapshot_uuid == binding.capability_snapshot_uuid
    assert pinned_binding.capability_snapshot_digest == binding.capability_snapshot_digest
    assert pinned_binding.topology_snapshot.endpoint_binding_revision == binding.capability_snapshot_uuid
    assert pinned_config["unrelated"] == {"preserved": True}
    assert call["expected_binding_revision"] == binding.capability_snapshot_uuid
    assert call["expected_workflow_configurations"] == definition.workflow_configurations
    historical = snapshot_from_binding(pinned_binding)
    assert historical is not None and historical.topology == topology
    gateway.fetch_topology.assert_awaited_once()


@pytest.mark.asyncio
async def test_refresh_reports_stale_binding_without_external_call_or_write():
    binding = _binding(
        validation_report_uuid="report-old",
        validation_report_digest="e" * 64,
        capability_snapshot_uuid="capability-old",
        capability_snapshot_digest="f" * 64,
    )
    definition = _definition(binding)
    db = _db(definition, _evidence(binding, current=False))
    gateway = SimpleNamespace(fetch_topology=AsyncMock())

    result = await refresh_draft_topology(
        organization_id=11,
        workflow_id=7,
        definition_id=19,
        db_client=db,
        private_network_enabled=False,
        gateway=gateway,
    )

    assert result.reason == "binding_stale"
    assert result.binding_status.state == "binding_stale"
    gateway.fetch_topology.assert_not_awaited()
    db.update_draft_workflow_definition_configurations_conditionally.assert_not_awaited()


@pytest.mark.asyncio
async def test_explicit_update_recovers_stale_binding_and_pins_matching_revision():
    topology = _topology()
    old_manifest = _manifest(topology=False)
    binding = _binding(
        validation_report_uuid="report-old",
        validation_report_digest="e" * 64,
        capability_snapshot_uuid="capability-old",
        capability_snapshot_digest="f" * 64,
        capability_snapshot=old_manifest,
        operations=old_manifest["operations"],
        limits=old_manifest["limits"],
        ownership=old_manifest["ownership"],
    )
    definition = _definition(binding)
    current_evidence = _evidence(binding, current=False)
    db = _db(definition, current_evidence)
    gateway = SimpleNamespace(fetch_topology=AsyncMock(return_value=topology))

    result = await update_draft_binding_and_topology(
        organization_id=11,
        workflow_id=7,
        definition_id=19,
        db_client=db,
        private_network_enabled=False,
        gateway=gateway,
    )

    assert result.status == "available"
    assert result.binding_status.state == "binding_current"
    assert result.stages.binding_update == "updated"
    written = db.update_draft_workflow_definition_configurations_conditionally.await_args.kwargs[
        "workflow_configurations"
    ]
    updated = LangGraphEndpointBinding.model_validate(written["langgraph_endpoint"])
    _, report, snapshot = current_evidence
    assert updated.validation_report_uuid == report.report_uuid
    assert updated.capability_snapshot_uuid == snapshot.snapshot_uuid
    assert updated.topology_snapshot.endpoint_binding_revision == snapshot.snapshot_uuid
    assert updated.selected_capabilities == binding.selected_capabilities
    assert "topology" not in updated.selected_capabilities
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
        assert getattr(updated, field_name) == getattr(binding, field_name)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("failure", "reason"),
    [
        (
            ProtocolViolation("invalid_topology", "invalid topology"),
            "topology_schema_invalid",
        ),
        (PermissionError("credential unavailable"), "topology_auth_failed"),
    ],
)
async def test_external_failure_preserves_stale_binding_and_snapshot(failure, reason):
    topology = _topology()
    old_snapshot = {
        "endpoint_binding_revision": "capability-old",
        "digest": canonical_digest(topology),
        "topology": topology.model_dump(mode="json"),
    }
    old_manifest = _manifest(topology=False)
    binding = _binding(
        validation_report_uuid="report-old",
        validation_report_digest="e" * 64,
        capability_snapshot_uuid="capability-old",
        capability_snapshot_digest="f" * 64,
        capability_snapshot=old_manifest,
        operations=old_manifest["operations"],
        limits=old_manifest["limits"],
        ownership=old_manifest["ownership"],
        topology_snapshot=old_snapshot,
    )
    definition = _definition(binding)
    original = deepcopy(definition.workflow_configurations)
    db = _db(definition, _evidence(binding, current=False))
    gateway = SimpleNamespace(fetch_topology=AsyncMock(side_effect=failure))

    result = await update_draft_binding_and_topology(
        organization_id=11,
        workflow_id=7,
        definition_id=19,
        db_client=db,
        private_network_enabled=False,
        gateway=gateway,
    )

    assert result.reason == reason
    assert result.topology == topology
    assert definition.workflow_configurations == original
    db.update_draft_workflow_definition_configurations_conditionally.assert_not_awaited()


@pytest.mark.asyncio
async def test_conditional_conflict_returns_draft_changed_without_overwriting_state():
    binding = _binding()
    definition = _definition(binding)
    original = deepcopy(definition.workflow_configurations)
    db = _db(definition, _evidence(binding))
    db.update_draft_workflow_definition_configurations_conditionally.side_effect = (
        WorkflowDefinitionConfigurationConflictError("changed")
    )

    result = await refresh_draft_topology(
        organization_id=11,
        workflow_id=7,
        definition_id=19,
        db_client=db,
        private_network_enabled=False,
        gateway=SimpleNamespace(fetch_topology=AsyncMock(return_value=_topology())),
    )

    assert result.reason == "draft_changed"
    assert definition.workflow_configurations == original


@pytest.mark.asyncio
async def test_read_classification_is_side_effect_free_and_immutable_read_skips_current_evidence():
    binding = _binding()
    draft = _definition(binding)
    db = _db(draft, _evidence(binding))

    result = await topology_for_definition(
        organization_id=11,
        definition=draft,
        db_client=db,
        can_refresh_topology=True,
    )

    assert result.reason == "snapshot_unavailable"
    assert result.binding_status.state == "binding_current"
    assert result.actions.can_refresh_topology is True
    db.update_draft_workflow_definition_configurations_conditionally.assert_not_awaited()

    immutable = _definition(binding, status="published")
    immutable_db = _db(immutable, _evidence(binding))
    immutable_result = await topology_for_definition(
        organization_id=11,
        definition=immutable,
        db_client=immutable_db,
    )
    assert immutable_result.binding_status.state == "immutable_snapshot_only"
    assert immutable_result.actions.immutable is True
    immutable_db.get_current_langgraph_activation_evidence.assert_not_awaited()


@pytest.mark.asyncio
async def test_refresh_returns_unavailable_without_mutating_published_version():
    binding = _binding()
    definition = _definition(binding, status="published")
    db = _db(definition, _evidence(binding))
    gateway = SimpleNamespace(fetch_topology=AsyncMock())

    result = await refresh_draft_topology(
        organization_id=11,
        workflow_id=7,
        definition_id=19,
        db_client=db,
        private_network_enabled=False,
        gateway=gateway,
    )

    assert result.reason == "snapshot_required_for_immutable_version"
    gateway.fetch_topology.assert_not_awaited()
    db.update_draft_workflow_definition_configurations_conditionally.assert_not_awaited()


def test_workflow_router_exposes_explicit_update_binding_post():
    from api.routes.workflow import router

    matching = [
        route
        for route in router.routes
        if getattr(route, "path", "").endswith(
            "/{workflow_id}/versions/{definition_id}/langgraph-topology/update-binding"
        )
    ]
    assert len(matching) == 1
    assert matching[0].methods == {"POST"}


@pytest.mark.asyncio
async def test_update_binding_route_requires_endpoint_update_permission():
    from fastapi import HTTPException

    from api.routes.workflow import update_external_langgraph_topology_binding

    user = SimpleNamespace(
        selected_organization_id=11,
        langgraph_role="member",
    )
    with pytest.raises(HTTPException) as exc_info:
        await update_external_langgraph_topology_binding(
            workflow_id=7,
            definition_id=19,
            user=user,
        )

    assert exc_info.value.status_code == 403

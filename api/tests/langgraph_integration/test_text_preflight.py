import ipaddress
import json
from collections.abc import AsyncIterator

import httpx
import pytest

from api.schemas.langgraph_integration.common import InvocationMode, ToolOwner
from api.services.langgraph_integration.gateway import (
    IntegrationGateway,
    RuntimeEndpointSnapshot,
    StaticCredentialResolver,
)
from api.services.langgraph_integration.protocol import CancellationState, ProtocolViolation
from api.services.workflow.langgraph_adapter import PinnedReasoningState, WorkflowAdapter
from api.services.workflow.langgraph_text_preflight import execute_langgraph_text_preflight
from api.services.workflow.reasoning import ReasoningMessage, ReasoningToolDefinition


class EndpointResponse:
    status_code = 200
    headers = httpx.Headers({"content-type": "text/event-stream"})

    def __init__(self, events):
        self.events = events

    @property
    def is_redirect(self):
        return False

    async def aiter_bytes(self) -> AsyncIterator[bytes]:
        for event in self.events:
            yield b"data: " + json.dumps(event).encode() + b"\n\n"

    async def aclose(self):
        return None


class EndpointSimulator:
    def __init__(self, events):
        self.events = events
        self.calls = []

    async def request(self, method, url, *, headers, content, timeout, validate_connection):
        validate_connection("8.8.8.8")
        self.calls.append(json.loads(content))
        return EndpointResponse(self.events), "8.8.8.8"


def event(sequence, type_, data):
    return {
        "contract_version": "1.0",
        "invocation_id": "placeholder",
        "sequence": sequence,
        "event_id": f"event-{sequence}",
        "type": type_,
        "data": data,
    }


def state(tools=(), organization_id=7):
    return PinnedReasoningState(
        organization_id=organization_id,
        voice_run_id="run-1",
        workflow_version_id="version-1",
        registration_id="registration-1",
        contract_version="1.0",
        active_node_id="node-a",
        node_prompt="Help the user",
        history=(ReasoningMessage("user", "hello"),),
        tools=tools,
    )


def transition_tool(owner=ToolOwner.MURAL_TRANSITION.value, target="node-b"):
    return ReasoningToolDefinition(
        name="move_next",
        description="Move",
        input_schema={"type": "object", "properties": {}, "additionalProperties": False},
        owner=owner,
        node_id="node-a",
        workflow_version_id="version-1",
        organization_id=7,
        voice_run_id="run-1",
        registration_id="registration-1",
        transition_target=target,
    )


def snapshot(organization_id=7):
    return RuntimeEndpointSnapshot(
        organization_id=organization_id,
        registration_id="registration-1",
        endpoint_url="https://agent.example",
        credential_reference="credential-1",
        contract_version="1.0",
        invocation_modes=frozenset({InvocationMode.STREAMING}),
        operations={"invoke": "/invoke"},
        request_bytes=100_000,
        response_bytes=100_000,
        event_bytes=10_000,
        tool_argument_bytes=10_000,
    )


def gateway(monkeypatch, events):
    monkeypatch.setattr("api.utils.url_security.DEPLOYMENT_MODE", "saas")
    monkeypatch.setattr(
        "api.utils.url_security._resolve_hostname_ips",
        lambda *_: [ipaddress.ip_address("8.8.8.8")],
    )
    simulator = EndpointSimulator(events)
    return IntegrationGateway(
        credential_resolver=StaticCredentialResolver({"Authorization": "Bearer test"}),
        transport=simulator,
    ), simulator


def correlate(events, invocation_id):
    return [{**item, "invocation_id": invocation_id} for item in events]


@pytest.mark.asyncio
async def test_text_preflight_reports_text_and_invocation(monkeypatch):
    endpoint, simulator = gateway(monkeypatch, [])
    original = endpoint.invoke_stream

    async def stream(snapshot_, request, **kwargs):
        simulator.events = correlate(
            [event(0, "text_delta", {"text": "hello"}), event(1, "completed", {"status": "completed"})],
            request["invocation_id"],
        )
        async for item in original(snapshot_, request, **kwargs):
            yield item

    endpoint.invoke_stream = stream
    result = await execute_langgraph_text_preflight(
        state=state(), endpoint_snapshot=snapshot(), adapter=WorkflowAdapter(), gateway=endpoint
    )
    assert result.assistant_text == "hello"
    assert result.invocation_id.startswith("inv_")
    assert not result.observed_node_change
    assert simulator.calls[0]["messages"][0]["role"] == "system"


@pytest.mark.asyncio
async def test_tool_transition_reports_requested_source_target_and_change(monkeypatch):
    endpoint, simulator = gateway(monkeypatch, [])
    original = endpoint.invoke_stream

    async def stream(snapshot_, request, **kwargs):
        simulator.events = correlate(
            [
                event(0, "tool_call_start", {"tool_call_id": "call-1", "name": "move_next"}),
                event(1, "tool_call_delta", {"tool_call_id": "call-1", "fragment": "{}"}),
                event(2, "tool_call_end", {"tool_call_id": "call-1"}),
                event(3, "completed", {"status": "completed"}),
            ],
            request["invocation_id"],
        )
        async for item in original(snapshot_, request, **kwargs):
            yield item

    endpoint.invoke_stream = stream
    result = await execute_langgraph_text_preflight(
        state=state((transition_tool(),)), endpoint_snapshot=snapshot(), adapter=WorkflowAdapter(), gateway=endpoint
    )
    assert (result.requested_transition, result.source_node_id, result.target_node_id) == ("move_next", "node-a", "node-b")
    assert result.observed_node_change


@pytest.mark.asyncio
async def test_preflight_failure_and_cancellation_are_effect_free(monkeypatch):
    endpoint, simulator = gateway(monkeypatch, [])
    original = endpoint.invoke_stream

    async def malformed(snapshot_, request, **kwargs):
        simulator.events = correlate([event(1, "completed", {"status": "completed"})], request["invocation_id"])
        async for item in original(snapshot_, request, **kwargs):
            yield item

    endpoint.invoke_stream = malformed
    with pytest.raises(ProtocolViolation):
        await execute_langgraph_text_preflight(
            state=state(), endpoint_snapshot=snapshot(), adapter=WorkflowAdapter(), gateway=endpoint
        )

    endpoint, simulator = gateway(monkeypatch, [])
    cancellation = CancellationState()
    cancellation.accept("operator")
    original = endpoint.invoke_stream

    async def cancelled_stream(snapshot_, request, **kwargs):
        simulator.events = correlate(
            [event(0, "completed", {"status": "completed"})],
            request["invocation_id"],
        )
        async for item in original(snapshot_, request, **kwargs):
            yield item

    endpoint.invoke_stream = cancelled_stream
    result = await execute_langgraph_text_preflight(
        state=state(), endpoint_snapshot=snapshot(), adapter=WorkflowAdapter(), gateway=endpoint, cancellation=cancellation
    )
    assert result.assistant_text is None and not result.observed_node_change


@pytest.mark.asyncio
async def test_preflight_rejects_cross_tenant_snapshot_before_dispatch(monkeypatch):
    endpoint, simulator = gateway(monkeypatch, [])
    with pytest.raises(PermissionError, match="organization"):
        await execute_langgraph_text_preflight(
            state=state(organization_id=8), endpoint_snapshot=snapshot(organization_id=7), adapter=WorkflowAdapter(), gateway=endpoint
        )
    assert simulator.calls == []

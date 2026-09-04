import copy
import ipaddress
import json
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest

from api.schemas.langgraph_integration.common import InvocationMode
from api.schemas.langgraph_integration.examples import EXECUTABLE_EXAMPLES
from api.services.langgraph_integration.gateway import (
    GatewayTraceContext,
    IntegrationGateway,
    RuntimeEndpointSnapshot,
    StaticCredentialResolver,
)
from api.services.langgraph_integration.protocol import (
    AttemptResult,
    CancellationState,
    InMemoryAcceptedEventLedger,
    InvocationCoordinator,
    ProtocolViolation,
    ReductionDisposition,
    RuntimeEventReducer,
    validated_endpoint_trace_headers,
)


class ScriptedRuntimeResponse:
    def __init__(
        self,
        body: bytes | list[bytes],
        *,
        status: int = 200,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.body = [body] if isinstance(body, bytes) else body
        self.status_code = status
        self.headers = httpx.Headers(headers or {"content-type": "application/json"})
        self.closed = False

    @property
    def is_redirect(self) -> bool:
        return 300 <= self.status_code < 400

    async def aiter_bytes(self) -> AsyncIterator[bytes]:
        for chunk in self.body:
            yield chunk

    async def aclose(self) -> None:
        self.closed = True


class ScriptedRuntimeTransport:
    def __init__(self, responses: list[ScriptedRuntimeResponse]) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    async def request(
        self, method, url, *, headers, content, timeout, validate_connection
    ):
        validate_connection("8.8.8.8")
        self.calls.append(
            {
                "method": method,
                "url": url,
                "headers": dict(headers),
                "content": content,
                "timeout": timeout,
            }
        )
        return self.responses.pop(0), "8.8.8.8"


def _snapshot(**changes: Any) -> RuntimeEndpointSnapshot:
    values: dict[str, Any] = {
        "organization_id": 7,
        "registration_id": "endpoint-public-id",
        "endpoint_url": "https://agent.example",
        "credential_reference": "credential-public-id",
        "contract_version": "1.0",
        "invocation_modes": frozenset(InvocationMode),
        "operations": {
            "invoke": "/v1/invocations",
            "status": "/v1/runs/{external_run_id}",
            "cancel": "/v1/invocations/{invocation_id}/cancel",
        },
        "request_bytes": 1_048_576,
        "response_bytes": 2_097_152,
        "event_bytes": 65_536,
        "tool_argument_bytes": 262_144,
    }
    values.update(changes)
    return RuntimeEndpointSnapshot(**values)


def _request(mode: str = "synchronous") -> dict[str, Any]:
    payload = copy.deepcopy(EXECUTABLE_EXAMPLES["1.0"]["invocation"])
    payload["invocation_id"] = "inv_01JEXAMPLE"
    payload["attempt_id"] = "att_01JEXAMPLE"
    payload["mode"] = mode
    return payload


def _trace() -> GatewayTraceContext:
    return GatewayTraceContext(
        organization_id=7,
        registration_id="endpoint-public-id",
        contract_version="1.0",
        trace_id="1" * 32,
        voice_run_id="run-1",
        invocation_id="inv_01JEXAMPLE",
        attempt_id="att_01JEXAMPLE",
        workflow_version_id="workflow-1",
    )


def _public_dns(monkeypatch) -> None:
    monkeypatch.setattr("api.utils.url_security.DEPLOYMENT_MODE", "saas")
    monkeypatch.setattr(
        "api.utils.url_security._resolve_hostname_ips",
        lambda *_: [ipaddress.ip_address("8.8.8.8")],
    )


def _gateway(responses: list[ScriptedRuntimeResponse]):
    transport = ScriptedRuntimeTransport(responses)
    gateway = IntegrationGateway(
        credential_resolver=StaticCredentialResolver(
            {"Authorization": "Bearer test-secret"}
        ),
        transport=transport,
    )
    return gateway, transport


@pytest.mark.asyncio
async def test_sync_client_authenticates_pins_version_and_accepts_one_result(monkeypatch):
    _public_dns(monkeypatch)
    response = {
        "contract_version": "1.0",
        "invocation_id": "inv_01JEXAMPLE",
        "result": {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [{"type": "text", "text": "Done"}],
            },
            "status": "completed",
        },
    }
    gateway, transport = _gateway(
        [ScriptedRuntimeResponse(json.dumps(response).encode())]
    )

    result = await gateway.invoke_sync(_snapshot(), _request(), trace_context=_trace())

    assert result.result.message.content[0].text == "Done"
    sent = json.loads(transport.calls[0]["content"])
    assert sent["contract_version"] == "1.0"
    assert transport.calls[0]["headers"]["Authorization"] == "Bearer test-secret"
    assert transport.calls[0]["headers"]["traceparent"].startswith("00-" + "1" * 32)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {"contract_version": "1.0", "invocation_id": "inv_01JEXAMPLE"},
        {
            "contract_version": "1.0",
            "invocation_id": "inv_01JEXAMPLE",
            "result": [],
        },
    ],
)
async def test_sync_client_rejects_zero_or_multiple_cardinality(monkeypatch, payload):
    _public_dns(monkeypatch)
    gateway, _ = _gateway(
        [ScriptedRuntimeResponse(json.dumps(payload).encode())]
    )
    with pytest.raises(ProtocolViolation, match="exactly one"):
        await gateway.invoke_sync(_snapshot(), _request(), trace_context=_trace())


@pytest.mark.asyncio
async def test_stream_client_incrementally_reduces_text_tool_and_terminal(monkeypatch):
    _public_dns(monkeypatch)
    events = [
        {
            "contract_version": "1.0",
            "invocation_id": "inv_01JEXAMPLE",
            "sequence": 0,
            "event_id": "event-0",
            "type": "text_delta",
            "data": {"text": "Before tool"},
        },
        {
            "contract_version": "1.0",
            "invocation_id": "inv_01JEXAMPLE",
            "sequence": 1,
            "event_id": "event-1",
            "type": "tool_call_start",
            "data": {"tool_call_id": "call-1", "name": "lookup"},
        },
        {
            "contract_version": "1.0",
            "invocation_id": "inv_01JEXAMPLE",
            "sequence": 2,
            "event_id": "event-2",
            "type": "tool_call_delta",
            "data": {"tool_call_id": "call-1", "fragment": "{\"x\":"},
        },
        {
            "contract_version": "1.0",
            "invocation_id": "inv_01JEXAMPLE",
            "sequence": 3,
            "event_id": "event-3",
            "type": "tool_call_delta",
            "data": {"tool_call_id": "call-1", "fragment": "1}"},
        },
        {
            "contract_version": "1.0",
            "invocation_id": "inv_01JEXAMPLE",
            "sequence": 4,
            "event_id": "event-4",
            "type": "tool_call_end",
            "data": {"tool_call_id": "call-1"},
        },
        {
            "contract_version": "1.0",
            "invocation_id": "inv_01JEXAMPLE",
            "sequence": 5,
            "event_id": "event-5",
            "type": "completed",
            "data": {"status": "completed"},
        },
    ]
    wire = b"".join(
        b"data: " + json.dumps(event).encode() + b"\n\n" for event in events
    )
    gateway, _ = _gateway(
        [
            ScriptedRuntimeResponse(
                [wire[:37], wire[37:109], wire[109:]],
                headers={"content-type": "text/event-stream; charset=utf-8"},
            )
        ]
    )
    accepted = [
        event
        async for event in gateway.invoke_stream(
            _snapshot(),
            _request("streaming"),
            ledger=InMemoryAcceptedEventLedger(),
            cancellation=CancellationState(),
            trace_context=_trace(),
        )
    ]

    assert [event.event.type for event in accepted] == [item["type"] for item in events]
    assert accepted[0].speakable_text == "Before tool"
    assert accepted[4].tool_call.arguments == {"x": 1}
    assert accepted[-1].terminal


@pytest.mark.asyncio
async def test_stream_suppresses_forwarding_immediately_after_cancellation(monkeypatch):
    _public_dns(monkeypatch)
    events = [
        {
            "contract_version": "1.0",
            "invocation_id": "inv_01JEXAMPLE",
            "sequence": sequence,
            "event_id": f"event-{sequence}",
            "type": event_type,
            "data": data,
        }
        for sequence, event_type, data in [
            (0, "text_delta", {"text": "late"}),
            (1, "completed", {"status": "completed"}),
        ]
    ]
    wire = b"".join(b"data: " + json.dumps(e).encode() + b"\n\n" for e in events)
    gateway, _ = _gateway(
        [ScriptedRuntimeResponse(wire, headers={"content-type": "text/event-stream"})]
    )
    cancellation = CancellationState()
    cancellation.accept("caller_barge_in")
    accepted = [
        event
        async for event in gateway.invoke_stream(
            _snapshot(),
            _request("streaming"),
            ledger=InMemoryAcceptedEventLedger(),
            cancellation=cancellation,
            trace_context=_trace(),
        )
    ]
    assert accepted == []


@pytest.mark.asyncio
async def test_async_client_polls_authenticated_status_to_one_terminal(monkeypatch):
    _public_dns(monkeypatch)
    acceptance = {
        "contract_version": "1.0",
        "invocation_id": "inv_01JEXAMPLE",
        "status": "accepted",
        "external_run_id": "external-1",
    }
    running = {
        "contract_version": "1.0",
        "operation": "status",
        "invocation_id": "inv_01JEXAMPLE",
        "external_run_id": "external-1",
        "status": "running",
        "result": None,
    }
    completed = {
        **running,
        "status": "completed",
        "result": {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [{"type": "text", "text": "Complete"}],
            },
            "status": "completed",
        },
    }
    gateway, transport = _gateway(
        [
            ScriptedRuntimeResponse(json.dumps(acceptance).encode()),
            ScriptedRuntimeResponse(json.dumps(running).encode()),
            ScriptedRuntimeResponse(json.dumps(completed).encode()),
        ]
    )
    handle = await gateway.start_async(
        _snapshot(), _request("asynchronous"), trace_context=_trace()
    )
    result = await gateway.await_async(
        _snapshot(),
        handle,
        deadline_seconds=1,
        poll_interval_seconds=0,
        trace_context=_trace(),
    )
    assert result.status == "completed"
    assert [call["method"] for call in transport.calls] == ["POST", "GET", "GET"]
    assert all("Authorization" in call["headers"] for call in transport.calls)


@pytest.mark.asyncio
async def test_async_deadline_dispatches_cancel_before_timeout(monkeypatch):
    _public_dns(monkeypatch)
    acceptance_payload = {
        "contract_version": "1.0",
        "invocation_id": "inv_01JEXAMPLE",
        "status": "accepted",
        "external_run_id": "external-1",
    }
    cancelled = {
        "contract_version": "1.0",
        "invocation_id": "inv_01JEXAMPLE",
        "status": "cancelled",
    }
    gateway, transport = _gateway(
        [ScriptedRuntimeResponse(json.dumps(cancelled).encode())]
    )
    acceptance = __import__(
        "api.schemas.langgraph_integration.v1_0", fromlist=["AsynchronousAcceptance"]
    ).AsynchronousAcceptance.model_validate(acceptance_payload)
    with pytest.raises(ProtocolViolation, match="cancel,timeout_effect"):
        await gateway.await_async(
            _snapshot(cancellation_declared=True),
            acceptance,
            deadline_seconds=0,
            trace_context=_trace(),
        )
    assert transport.calls[0]["url"].endswith("/v1/invocations/inv_01JEXAMPLE/cancel")


@pytest.mark.asyncio
async def test_reducer_records_post_terminal_without_mutation():
    ledger = InMemoryAcceptedEventLedger()
    reducer = RuntimeEventReducer(
        contract_version="1.0",
        invocation_id="inv-1",
        ledger=ledger,
        event_bytes_limit=65_536,
        tool_argument_bytes_limit=1000,
    )
    terminal = {
        "contract_version": "1.0",
        "invocation_id": "inv-1",
        "sequence": 0,
        "event_id": "event-0",
        "type": "completed",
        "data": {"status": "completed"},
    }
    late = {
        "contract_version": "1.0",
        "invocation_id": "inv-1",
        "sequence": 1,
        "event_id": "event-1",
        "type": "text_delta",
        "data": {"text": "must not speak"},
    }
    assert (await reducer.reduce(terminal)).terminal
    result = await reducer.reduce(late)
    assert result.disposition is ReductionDisposition.POST_TERMINAL
    assert result.speakable_text is None
    assert 1 in ledger.rows


@pytest.mark.asyncio
async def test_reducer_fails_closed_when_durable_guard_cannot_be_written():
    class FailingLedger:
        async def record_event(self, **kwargs):
            raise OSError("database unavailable")

    reducer = RuntimeEventReducer(
        contract_version="1.0",
        invocation_id="inv-1",
        ledger=FailingLedger(),
        event_bytes_limit=65_536,
        tool_argument_bytes_limit=1000,
    )
    event = {
        "contract_version": "1.0",
        "invocation_id": "inv-1",
        "sequence": 0,
        "event_id": "event-0",
        "type": "text_delta",
        "data": {"text": "not forwarded"},
    }
    with pytest.raises(OSError, match="database unavailable"):
        await reducer.reduce(event)
    assert reducer.expected_sequence == 0


@pytest.mark.asyncio
async def test_runtime_limits_and_selected_capabilities_are_enforced(monkeypatch):
    _public_dns(monkeypatch)
    gateway, transport = _gateway([])
    oversized = _request()
    oversized["context"] = {"large": "x" * 100}
    with pytest.raises(ProtocolViolation, match="request exceeds"):
        await gateway.invoke_sync(
            _snapshot(request_bytes=10), oversized, trace_context=_trace()
        )
    assert transport.calls == []

    interrupt = {
        "contract_version": "1.0",
        "invocation_id": "inv-1",
        "sequence": 0,
        "event_id": "event-0",
        "type": "interrupt",
        "data": {
            "interrupt_type": "approval",
            "reason": "review",
            "allowed_decisions": ["approve"],
            "expires_at": "2030-01-01T00:00:00Z",
            "checkpoint_reference": "checkpoint-1",
        },
    }
    reducer = RuntimeEventReducer(
        contract_version="1.0",
        invocation_id="inv-1",
        ledger=InMemoryAcceptedEventLedger(),
        event_bytes_limit=65_536,
        tool_argument_bytes_limit=1000,
    )
    with pytest.raises(ProtocolViolation, match="not negotiated"):
        await reducer.reduce(interrupt)


def test_endpoint_trace_headers_cannot_replace_tenant_and_malformed_trace_is_ignored():
    mural = "00-" + "1" * 32 + "-" + "2" * 16 + "-01"
    headers, warnings = validated_endpoint_trace_headers(
        {
            "traceparent": "not-valid",
            "x-organization-id": "another-tenant",
            "authorization": "secret",
        },
        mural_traceparent=mural,
    )
    assert headers == {"traceparent": mural}
    assert len(warnings) == 2
    assert "authorization" not in headers


def test_metrics_contain_bounded_dimensions_and_no_payload_or_credentials():
    gateway, _ = _gateway([])
    gateway.metrics.increment(
        operation="invoke",
        registration_id="endpoint-public-id",
        contract_version="1.0",
    )
    rendered = repr(gateway.metrics)
    assert "endpoint-public-id" in rendered
    assert "test-secret" not in rendered
    assert "prompt" not in rendered


@pytest.mark.asyncio
async def test_invocation_coordinator_retries_once_before_event_with_same_identity():
    invocation_ids = iter(["invocation-1"])
    attempt_ids = iter(["attempt-1", "attempt-2", "attempt-3"])
    coordinator = InvocationCoordinator(
        invocation_id_factory=lambda: next(invocation_ids),
        attempt_id_factory=lambda: next(attempt_ids),
    )
    observed = []

    async def attempt(invocation_id, attempt_id, ordinal):
        observed.append((invocation_id, attempt_id, ordinal))
        if ordinal == 1:
            return AttemptResult(failure=503, accepted_event=False)
        return AttemptResult(value="completed")

    result = await coordinator.execute(
        attempt, remaining_ms=lambda: 1000, minimum_attempt_ms=100
    )
    assert result.value == "completed"
    assert observed == [
        ("invocation-1", "attempt-1", 1),
        ("invocation-1", "attempt-2", 2),
    ]


@pytest.mark.asyncio
async def test_invocation_coordinator_never_retries_after_an_accepted_event():
    coordinator = InvocationCoordinator(
        invocation_id_factory=lambda: "invocation-1",
        attempt_id_factory=lambda: "attempt-1",
    )
    calls = 0

    async def attempt(*_):
        nonlocal calls
        calls += 1
        return AttemptResult(failure="connection_failure", accepted_event=True)

    result = await coordinator.execute(
        attempt, remaining_ms=lambda: 1000, minimum_attempt_ms=100
    )
    assert result.failure == "connection_failure"
    assert calls == 1


@pytest.mark.asyncio
async def test_invocation_coordinator_suppresses_before_cancellation_dispatch():
    coordinator = InvocationCoordinator(
        invocation_id_factory=lambda: "invocation-1",
        attempt_id_factory=lambda: "attempt-1",
    )
    forwarding_during_dispatch = None

    async def dispatch():
        nonlocal forwarding_during_dispatch
        forwarding_during_dispatch = coordinator.cancellation.forwarding_allowed()

    accepted = await coordinator.accept_and_dispatch_cancellation("hangup", dispatch)
    assert accepted
    assert forwarding_during_dispatch is False
    assert not coordinator.cancellation.forwarding_allowed()
    assert not await coordinator.accept_and_dispatch_cancellation("hangup", dispatch)

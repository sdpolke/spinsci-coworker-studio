from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest

from api.schemas.langgraph_integration.common import InvocationMode
from api.services.langgraph_integration.conformance.live import (
    run_live_endpoint_evidence,
)
from api.services.langgraph_integration.conformance.platform import (
    run_platform_evidence,
)
from api.services.langgraph_integration.gateway import (
    IntegrationGateway,
    RuntimeEndpointSnapshot,
    StaticCredentialResolver,
)


class _Response:
    def __init__(self, events: list[dict[str, Any]]) -> None:
        self.status_code = 200
        self.headers = httpx.Headers({"content-type": "text/event-stream"})
        self._body = b"".join(
            b"data: " + json.dumps(event).encode() + b"\n\n" for event in events
        )
        self.closed = False

    @property
    def is_redirect(self) -> bool:
        return False

    async def aiter_bytes(self) -> AsyncIterator[bytes]:
        yield self._body

    async def aclose(self) -> None:
        self.closed = True


class _Transport:
    def __init__(self, responses: list[_Response]) -> None:
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
                "content": json.loads(content),
                "timeout": timeout,
            }
        )
        return self.responses.pop(0), "8.8.8.8"


def _event(invocation_id: str, sequence: int, event_type: str, data: dict) -> dict:
    return {
        "contract_version": "1.2",
        "invocation_id": invocation_id,
        "sequence": sequence,
        "event_id": f"event-{invocation_id}-{sequence}",
        "type": event_type,
        "data": data,
    }


def _successful_turn(
    invocation_id: str, *, thread_id: str, checkpoint_reference: str
) -> _Response:
    return _Response(
        [
            _event(invocation_id, 0, "text_delta", {"text": "validated"}),
            _event(
                invocation_id,
                1,
                "checkpoint",
                {
                    "thread_id": thread_id,
                    "checkpoint_reference": checkpoint_reference,
                },
            ),
            _event(invocation_id, 2, "completed", {"status": "completed"}),
        ]
    )


def _snapshot() -> RuntimeEndpointSnapshot:
    return RuntimeEndpointSnapshot(
        organization_id=7,
        registration_id="endpoint-1",
        endpoint_url="https://8.8.8.8",
        credential_reference="credential-1",
        contract_version="1.2",
        invocation_modes=frozenset({InvocationMode.STREAMING}),
        operations={"invoke": "/v1/invocations", "health": "/v1/health"},
        request_bytes=1_048_576,
        response_bytes=2_097_152,
        event_bytes=65_536,
        tool_argument_bytes=262_144,
        stateful_profile=True,
    )


@pytest.mark.asyncio
async def test_live_stateful_evidence_uses_and_rejects_endpoint_checkpoints():
    thread_id = "thread-validation"
    checkpoint_one = "checkpoint-one"
    checkpoint_two = "checkpoint-two"
    transport = _Transport([])
    gateway = IntegrationGateway(
        credential_resolver=StaticCredentialResolver(
            {"Authorization": "Bearer secret"}
        ),
        transport=transport,
    )

    original_request = transport.request

    async def request(*args, **kwargs):
        content = json.loads(kwargs["content"])
        invocation_id = content["invocation_id"]
        call_index = len(transport.calls)
        if call_index == 0:
            transport.responses.append(
                _successful_turn(
                    invocation_id,
                    thread_id=thread_id,
                    checkpoint_reference=checkpoint_one,
                )
            )
        elif call_index == 1:
            transport.responses.append(
                _successful_turn(
                    invocation_id,
                    thread_id=thread_id,
                    checkpoint_reference=checkpoint_two,
                )
            )
        else:
            transport.responses.append(
                _Response(
                    [
                        _event(
                            invocation_id,
                            0,
                            "error",
                            {
                                "category": "state_conflict",
                                "code": "stale_checkpoint",
                                "retryable": False,
                            },
                        )
                    ]
                )
            )
        return await original_request(*args, **kwargs)

    transport.request = request
    result = await run_live_endpoint_evidence(
        gateway=gateway,
        snapshot=_snapshot(),
        profile="stateful_run",
        first_event_ms=500,
        turn_ms=5_000,
    )

    assert result.text_session_conformance is True
    assert result.endpoint_state_continuity is True
    assert all(check.passed for check in result.checks)
    assert len(transport.calls) == 3
    first, second, stale = [call["content"] for call in transport.calls]
    assert "state" not in first
    assert second["state"] == {
        "thread_id": thread_id,
        "checkpoint_reference": checkpoint_one,
    }
    assert stale["state"] == second["state"]
    assert len({first["invocation_id"], second["invocation_id"], stale["invocation_id"]}) == 3
    assert first["voice_run_id"] == second["voice_run_id"] == stale["voice_run_id"]


@pytest.mark.asyncio
async def test_platform_evidence_executes_cancellation_and_recording_paths():
    result = await run_platform_evidence()

    assert result.cancellation_verified is True
    assert result.recording_verified is True
    assert [check.identifier for check in result.checks] == [
        "platform.cancellation_suppression",
        "platform.recording_artifact_pipeline",
    ]
    assert all(check.passed for check in result.checks)

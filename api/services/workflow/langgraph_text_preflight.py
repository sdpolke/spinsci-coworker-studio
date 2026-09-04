from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from api.services.langgraph_integration.gateway import (
    GatewayTraceContext,
    IntegrationGateway,
    RuntimeEndpointSnapshot,
)
from api.services.langgraph_integration.protocol import (
    CancellationState,
    InMemoryAcceptedEventLedger,
)
from api.services.workflow.langgraph_adapter import (
    PinnedReasoningState,
    ToolExecutionContext,
    WorkflowAdapter,
)


@dataclass(frozen=True)
class TextPreflightResult:
    invocation_id: str
    assistant_text: str | None
    requested_transition: str | None
    source_node_id: str
    target_node_id: str | None
    observed_node_change: bool
    events: tuple[dict[str, Any], ...]
    state: PinnedReasoningState


async def execute_langgraph_text_preflight(
    *,
    state: PinnedReasoningState,
    endpoint_snapshot: RuntimeEndpointSnapshot,
    adapter: WorkflowAdapter,
    gateway: IntegrationGateway,
    cancellation: CancellationState | None = None,
    first_event_deadline_ms: int = 1500,
    turn_deadline_ms: int = 10000,
) -> TextPreflightResult:
    """Exercise the same adapter/gateway/tool/state boundary used by live turns."""
    if endpoint_snapshot.organization_id != state.organization_id:
        raise PermissionError("endpoint snapshot is not owned by Voice Run organization")
    if endpoint_snapshot.registration_id != state.registration_id:
        raise PermissionError("endpoint snapshot does not match pinned registration")

    invocation_id = f"inv_{uuid.uuid4().hex}"
    attempt_id = f"att_{uuid.uuid4().hex}"
    trace_id = uuid.uuid4().hex
    reasoning_request = adapter.build_request(
        state=state,
        invocation_id=invocation_id,
    )
    request_messages = []
    for message in reasoning_request.messages:
        role = message.role
        if role == "tool":
            role = "tool_result"
        elif role == "assistant" and message.tool_call_id is not None:
            role = "tool_call"
        content = message.content
        if not isinstance(content, str):
            import json

            content = json.dumps(content, sort_keys=True, separators=(",", ":"))
        request_message = {
            "role": role,
            "content": [{"type": "text", "text": content}],
        }
        if message.tool_call_id is not None:
            request_message["tool_call_id"] = message.tool_call_id
        request_messages.append(request_message)
    request = {
        **reasoning_request.to_wire(),
        "messages": request_messages,
        "attempt_id": attempt_id,
        "deadlines": {
            "first_event_ms": first_event_deadline_ms,
            "turn_ms": turn_deadline_ms,
        },
        "trace": {},
    }
    trace = GatewayTraceContext(
        organization_id=state.organization_id,
        registration_id=state.registration_id,
        contract_version=state.contract_version,
        trace_id=trace_id,
        voice_run_id=state.voice_run_id,
        invocation_id=invocation_id,
        attempt_id=attempt_id,
        workflow_version_id=state.workflow_version_id,
    )
    cancellation = cancellation or CancellationState()
    texts: list[str] = []
    events: list[dict[str, Any]] = []
    current_state = state
    requested_transition: str | None = None
    target_node_id: str | None = None

    async for accepted in gateway.invoke_stream(
        endpoint_snapshot,
        request,
        ledger=InMemoryAcceptedEventLedger(),
        cancellation=cancellation,
        trace_context=trace,
    ):
        event = accepted.event.model_dump(mode="json")
        events.append(event)
        if accepted.speakable_text:
            texts.append(accepted.speakable_text)
            history = adapter.accept_endpoint_text(
                state=current_state,
                text=accepted.speakable_text,
                response_size_limit=endpoint_snapshot.response_bytes,
            )
            current_state = PinnedReasoningState(
                **{**current_state.__dict__, "history": history}
            )
        if accepted.tool_call is not None:
            call = accepted.tool_call
            outcome = await adapter.execute_tool(
                state=current_state,
                context=ToolExecutionContext(
                    invocation_id=invocation_id,
                    tool_call_id=call.tool_call_id,
                    active_node_id=current_state.active_node_id,
                    workflow_version_id=current_state.workflow_version_id,
                    organization_id=current_state.organization_id,
                    voice_run_id=current_state.voice_run_id,
                    registration_id=current_state.registration_id,
                    trace_id=trace_id,
                ),
                name=call.name,
                tool_call_id=call.tool_call_id,
                arguments=call.arguments,
            )
            if outcome.next_node_id != current_state.active_node_id:
                requested_transition = call.name
                target_node_id = outcome.next_node_id
            current_state = PinnedReasoningState(
                **{
                    **current_state.__dict__,
                    "history": outcome.history,
                    "active_node_id": outcome.next_node_id,
                }
            )

    return TextPreflightResult(
        invocation_id=invocation_id,
        assistant_text="".join(texts).strip() or None,
        requested_transition=requested_transition,
        source_node_id=state.active_node_id,
        target_node_id=target_node_id,
        observed_node_change=current_state.active_node_id != state.active_node_id,
        events=tuple(events),
        state=current_state,
    )

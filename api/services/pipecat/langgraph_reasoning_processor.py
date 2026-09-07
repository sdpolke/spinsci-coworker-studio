"""Pipecat reasoning service backed by the LangGraph integration contract."""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Literal

from loguru import logger

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
    DataSharingPolicy,
    PinnedReasoningState,
    RedactionPolicy,
    WorkflowAdapter,
)
from pipecat.frames.frames import (
    CancelFrame,
    EndFrame,
    Frame,
    InterruptionFrame,
    LLMContextFrame,
    LLMFullResponseEndFrame,
    LLMFullResponseStartFrame,
    LLMTextFrame,
)
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.frame_processor import FrameDirection
from pipecat.services.llm_service import LLMService

ReasoningStateFactory = Callable[[LLMContext], PinnedReasoningState]
CancellationReason = Literal[
    "caller_barge_in",
    "hangup",
    "node_change",
    "operator_action",
    "platform_shutdown",
]


@dataclass(frozen=True)
class _ActiveInvocation:
    invocation_id: str
    cancellation: CancellationState
    trace_context: GatewayTraceContext


def _frame_cancellation_reason(frame: Frame) -> CancellationReason | None:
    if isinstance(frame, InterruptionFrame):
        return "caller_barge_in"
    if isinstance(frame, CancelFrame):
        return "hangup" if frame.reason == "user_hangup" else "platform_shutdown"
    if isinstance(frame, EndFrame):
        return "hangup"
    return None


def _contract_messages(request_messages) -> list[dict]:
    messages: list[dict] = []
    for message in request_messages:
        role = message.role
        if role == "tool":
            role = "tool_result"
        elif role == "assistant" and message.tool_call_id is not None:
            role = "tool_call"
        content = message.content
        if not isinstance(content, str):
            content = json.dumps(content, sort_keys=True, separators=(",", ":"))
        wire_message = {
            "role": role,
            "content": [{"type": "text", "text": content}],
        }
        if message.tool_call_id is not None:
            wire_message["tool_call_id"] = message.tool_call_id
        messages.append(wire_message)
    return messages


class LangGraphReasoningProcessor(LLMService):
    """Invoke a pinned endpoint and expose accepted text as normal LLM frames.

    The service consumes only ``LLMContextFrame`` data, so audio, transport, and
    telephony objects cannot cross the contract boundary. All emitted text uses
    Pipecat's standard response lifecycle and therefore continues through the
    existing callback, recording, TTS, transport, and assistant aggregation
    processors.
    """

    def __init__(
        self,
        *,
        endpoint_snapshot: RuntimeEndpointSnapshot,
        gateway: IntegrationGateway,
        state_factory: ReasoningStateFactory,
        adapter: WorkflowAdapter | None = None,
        sharing_policy: DataSharingPolicy | None = None,
        redaction_policy: RedactionPolicy | None = None,
        first_event_deadline_ms: int = 1500,
        turn_deadline_ms: int = 10000,
        invocation_mode: Literal["streaming", "synchronous"] = "streaming",
    ) -> None:
        super().__init__()
        self.endpoint_snapshot = endpoint_snapshot
        self.gateway = gateway
        self.state_factory = state_factory
        self.adapter = adapter or WorkflowAdapter()
        self.sharing_policy = sharing_policy or DataSharingPolicy()
        self.redaction_policy = redaction_policy or RedactionPolicy()
        self.first_event_deadline_ms = first_event_deadline_ms
        self.turn_deadline_ms = turn_deadline_ms
        self.invocation_mode = invocation_mode
        self._active_invocation: _ActiveInvocation | None = None
        self._endpoint_state: dict[str, str] = {}

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        cancellation = self._accept_active_cancellation(
            _frame_cancellation_reason(frame)
        )
        await super().process_frame(frame, direction)
        if isinstance(frame, LLMContextFrame):
            await self._process_context(frame.context)
        else:
            # Interruption and terminal frames must reach TTS/transport before
            # waiting for the bounded endpoint cancellation response.
            await self.push_frame(frame, direction)
        if cancellation is not None:
            await self._dispatch_cancellation(cancellation)

    async def cleanup(self) -> None:
        await self.cancel_active_invocation("platform_shutdown")
        await super().cleanup()

    async def cancel_active_invocation(self, reason: CancellationReason) -> bool:
        """Suppress and cancel the active endpoint invocation at most once."""
        active = self._accept_active_cancellation(reason)
        if active is None:
            return False
        await self._dispatch_cancellation(active)
        return True

    def _accept_active_cancellation(
        self, reason: CancellationReason | None
    ) -> _ActiveInvocation | None:
        active = self._active_invocation
        if reason is None or active is None:
            return None
        requested_at = time.monotonic()
        if not active.cancellation.accept(reason, now=requested_at):
            return None
        self.gateway.metrics.timing(
            metric="cancellation_suppression_latency",
            registration_id=self.endpoint_snapshot.registration_id,
            contract_version=self.endpoint_snapshot.contract_version,
            milliseconds=(time.monotonic() - requested_at) * 1000,
        )
        return active

    async def _dispatch_cancellation(self, active: _ActiveInvocation) -> None:
        if not self.endpoint_snapshot.cancellation_declared:
            return
        try:
            await asyncio.wait_for(
                self.gateway.cancel(
                    self.endpoint_snapshot,
                    invocation_id=active.invocation_id,
                    reason=active.cancellation.reason,
                    trace_context=active.trace_context,
                ),
                timeout=0.25,
            )
        except TimeoutError:
            logger.warning(
                "LangGraph cancellation dispatch exceeded 250 ms for invocation {}",
                active.invocation_id,
            )
        except Exception:  # noqa: BLE001 - cancellation cannot block call teardown
            logger.exception(
                "LangGraph cancellation dispatch failed for invocation {}",
                active.invocation_id,
            )

    async def run_inference(
        self,
        context: LLMContext,
        *,
        system_instruction: str | None = None,
    ) -> str:
        """Execute a pinned text-only non-conversational operation synchronously."""
        if self.invocation_mode != "synchronous":
            raise RuntimeError("synchronous inference was not pinned for this processor")

        state = replace(
            self.state_factory(context),
            node_prompt=system_instruction or "Perform the requested text classification.",
            tools=(),
            mode="synchronous",
        )
        if state.organization_id != self.endpoint_snapshot.organization_id:
            raise PermissionError("endpoint snapshot is not owned by Voice Run organization")
        if state.registration_id != self.endpoint_snapshot.registration_id:
            raise PermissionError("endpoint snapshot does not match pinned registration")

        invocation_id = f"inv_{uuid.uuid4().hex}"
        attempt_id = f"att_{uuid.uuid4().hex}"
        reasoning_request = self.adapter.build_request(
            state=state,
            invocation_id=invocation_id,
            sharing=self.sharing_policy,
            redaction=self.redaction_policy,
        )
        request = {
            **reasoning_request.to_wire(),
            "messages": _contract_messages(reasoning_request.messages),
            "attempt_id": attempt_id,
            "deadlines": {
                "first_event_ms": self.first_event_deadline_ms,
                "turn_ms": self.turn_deadline_ms,
            },
            "trace": {},
        }
        trace_context = GatewayTraceContext(
            organization_id=state.organization_id,
            registration_id=state.registration_id,
            contract_version=state.contract_version,
            trace_id=uuid.uuid4().hex,
            voice_run_id=state.voice_run_id,
            invocation_id=invocation_id,
            attempt_id=attempt_id,
            workflow_version_id=state.workflow_version_id,
        )
        response = await self.gateway.invoke_sync(
            self.endpoint_snapshot,
            request,
            trace_context=trace_context,
        )
        result = response.result
        if result.type != "assistant":
            raise RuntimeError(
                f"synchronous endpoint inference failed: {result.error.category.value}"
            )
        return "".join(
            part.text
            for part in result.message.content
            if getattr(part, "type", None) == "text"
        )

    async def _process_context(self, context: LLMContext) -> None:
        if self.invocation_mode == "synchronous":
            await self.push_frame(LLMFullResponseStartFrame())
            text = await self.run_inference(context)
            if text:
                await self.push_frame(LLMTextFrame(text))
            await self.push_frame(LLMFullResponseEndFrame())
            return

        state = self.state_factory(context)
        if state.organization_id != self.endpoint_snapshot.organization_id:
            raise PermissionError("endpoint snapshot is not owned by Voice Run organization")
        if state.registration_id != self.endpoint_snapshot.registration_id:
            raise PermissionError("endpoint snapshot does not match pinned registration")
        if state.state_mode == "endpoint_checkpointed":
            state = replace(
                state,
                tools=(),
                endpoint_state={**state.endpoint_state, **self._endpoint_state},
            )

        invocation_id = f"inv_{uuid.uuid4().hex}"
        attempt_id = f"att_{uuid.uuid4().hex}"
        reasoning_request = self.adapter.build_request(
            state=state,
            invocation_id=invocation_id,
            sharing=self.sharing_policy,
            redaction=self.redaction_policy,
        )
        if (
            state.state_mode == "endpoint_checkpointed"
            and not reasoning_request.messages
        ):
            logger.debug(
                "Skipping endpoint-checkpointed LangGraph invocation until caller or "
                "tool input is available"
            )
            return
        request = {
            **reasoning_request.to_wire(),
            "messages": _contract_messages(reasoning_request.messages),
            "attempt_id": attempt_id,
            "deadlines": {
                "first_event_ms": self.first_event_deadline_ms,
                "turn_ms": self.turn_deadline_ms,
            },
            "trace": {},
        }
        trace_context = GatewayTraceContext(
            organization_id=state.organization_id,
            registration_id=state.registration_id,
            contract_version=state.contract_version,
            trace_id=uuid.uuid4().hex,
            voice_run_id=state.voice_run_id,
            invocation_id=invocation_id,
            attempt_id=attempt_id,
            workflow_version_id=state.workflow_version_id,
        )
        cancellation = CancellationState()
        active = _ActiveInvocation(
            invocation_id=invocation_id,
            cancellation=cancellation,
            trace_context=trace_context,
        )
        self._active_invocation = active

        await self.push_frame(LLMFullResponseStartFrame())
        await self.start_processing_metrics()
        await self.start_ttfb_metrics()
        first_text = True
        try:
            async for accepted in self.gateway.invoke_stream(
                self.endpoint_snapshot,
                request,
                ledger=InMemoryAcceptedEventLedger(),
                cancellation=cancellation,
                trace_context=trace_context,
            ):
                if (
                    getattr(accepted.event, "type", None) == "checkpoint"
                    and cancellation.forwarding_allowed()
                ):
                    identifiers = accepted.event.data.model_dump(
                        mode="json", exclude_none=True
                    )
                    await self.adapter.reconcile_endpoint_state(
                        state=replace(state, trace_id=trace_context.trace_id),
                        claimed_voice_run_id=state.voice_run_id,
                        identifiers=identifiers,
                    )
                    self._endpoint_state.update(identifiers)
                if not cancellation.forwarding_allowed() or not accepted.speakable_text:
                    continue
                if first_text:
                    await self.stop_ttfb_metrics()
                    first_text = False
                if cancellation.forwarding_allowed():
                    await self.push_frame(LLMTextFrame(accepted.speakable_text))
        finally:
            if self._active_invocation is active:
                self._active_invocation = None
            if first_text:
                await self.stop_ttfb_metrics()
            await self.stop_processing_metrics()
            await self.push_frame(LLMFullResponseEndFrame())

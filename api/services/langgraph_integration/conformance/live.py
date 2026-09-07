"""Executable conformance checks against a registered LangGraph endpoint."""

from __future__ import annotations

import asyncio
import time
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
    ProtocolViolation,
)

from .evidence import EligibilityCheckResult


@dataclass(frozen=True)
class _TurnObservation:
    text_seen: bool
    checkpoint: dict[str, str] | None
    terminal_type: str | None
    error_category: str | None
    error_code: str | None
    event_count: int
    duration_ms: int


@dataclass(frozen=True)
class LiveEndpointEvidence:
    text_session_conformance: bool
    endpoint_state_continuity: bool
    checks: tuple[EligibilityCheckResult, ...]


def _request(
    *,
    snapshot: RuntimeEndpointSnapshot,
    profile: str,
    voice_run_id: str,
    invocation_id: str,
    attempt_id: str,
    text: str,
    state: dict[str, str] | None,
    first_event_ms: int,
    turn_ms: int,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "contract_version": snapshot.contract_version,
        "operation": "invoke",
        "invocation_id": invocation_id,
        "attempt_id": attempt_id,
        "voice_run_id": voice_run_id,
        "workflow_version_id": "workflow_endpoint_validation",
        "mode": "streaming",
        "state_mode": (
            "endpoint_checkpointed" if profile == "stateful_run" else "mural_authoritative"
        ),
        "messages": [
            {"role": "user", "content": [{"type": "text", "text": text}]}
        ],
        "tools": [],
        "context": {},
        "deadlines": {"first_event_ms": first_event_ms, "turn_ms": turn_ms},
        "trace": {},
        "locale": "en-US",
    }
    if state is not None:
        payload["state"] = state
    return payload


async def _invoke_turn(
    *,
    gateway: IntegrationGateway,
    snapshot: RuntimeEndpointSnapshot,
    profile: str,
    voice_run_id: str,
    text: str,
    state: dict[str, str] | None = None,
    first_event_ms: int,
    turn_ms: int,
) -> _TurnObservation:
    invocation_id = f"inv_validation_{uuid.uuid4().hex}"
    attempt_id = f"att_validation_{uuid.uuid4().hex}"
    request = _request(
        snapshot=snapshot,
        profile=profile,
        voice_run_id=voice_run_id,
        invocation_id=invocation_id,
        attempt_id=attempt_id,
        text=text,
        state=state,
        first_event_ms=first_event_ms,
        turn_ms=turn_ms,
    )
    trace = GatewayTraceContext(
        organization_id=snapshot.organization_id,
        registration_id=snapshot.registration_id,
        contract_version=snapshot.contract_version,
        trace_id=uuid.uuid4().hex,
        voice_run_id=voice_run_id,
        invocation_id=invocation_id,
        attempt_id=attempt_id,
        workflow_version_id="workflow_endpoint_validation",
    )
    stream = gateway.invoke_stream(
        snapshot,
        request,
        ledger=InMemoryAcceptedEventLedger(),
        cancellation=CancellationState(),
        trace_context=trace,
    )
    started = time.monotonic()
    accepted_events = []
    try:
        first = await asyncio.wait_for(anext(stream), timeout=first_event_ms / 1000)
        accepted_events.append(first)
        elapsed = time.monotonic() - started
        remaining = max(0.001, turn_ms / 1000 - elapsed)
        async with asyncio.timeout(remaining):
            async for accepted in stream:
                accepted_events.append(accepted)
    finally:
        await stream.aclose()

    checkpoint: dict[str, str] | None = None
    terminal_type: str | None = None
    error_category: str | None = None
    error_code: str | None = None
    text_seen = False
    for accepted in accepted_events:
        event = accepted.event
        if accepted.speakable_text:
            text_seen = True
        if event.type == "checkpoint":
            checkpoint = event.data.model_dump(mode="json", exclude_none=True)
        if accepted.terminal:
            terminal_type = event.type
            if event.type == "error":
                error = event.data.model_dump(mode="json", exclude_none=True)
                category = error.get("category")
                error_category = getattr(category, "value", category)
                error_code = error.get("code")

    return _TurnObservation(
        text_seen=text_seen,
        checkpoint=checkpoint,
        terminal_type=terminal_type,
        error_category=error_category,
        error_code=error_code,
        event_count=len(accepted_events),
        duration_ms=round((time.monotonic() - started) * 1000),
    )


def _failure_code(exc: BaseException) -> str:
    if isinstance(exc, ProtocolViolation):
        return exc.code
    if isinstance(exc, TimeoutError):
        return "validation_timeout"
    return type(exc).__name__


async def run_live_endpoint_evidence(
    *,
    gateway: IntegrationGateway,
    snapshot: RuntimeEndpointSnapshot,
    profile: str,
    first_event_ms: int = 3000,
    turn_ms: int = 60_000,
) -> LiveEndpointEvidence:
    """Run payload-safe endpoint checks; never persist prompts, text, or checkpoints."""

    checks: list[EligibilityCheckResult] = []
    voice_run_id = f"voice_validation_{uuid.uuid4().hex}"
    started = time.monotonic()
    first: _TurnObservation | None = None
    second: _TurnObservation | None = None
    stale: _TurnObservation | None = None
    live_error: str | None = None

    try:
        first = await _invoke_turn(
            gateway=gateway,
            snapshot=snapshot,
            profile=profile,
            voice_run_id=voice_run_id,
            text="Reply with one short greeting.",
            first_event_ms=first_event_ms,
            turn_ms=turn_ms,
        )
        if profile == "stateful_run":
            if snapshot.contract_version != "1.2":
                raise ProtocolViolation(
                    "stateful_continuation_requires_1_2",
                    "endpoint checkpoint continuation requires contract 1.2",
                )
            if first.checkpoint is None:
                raise ProtocolViolation(
                    "checkpoint_missing", "stateful endpoint omitted its checkpoint"
                )
            second = await _invoke_turn(
                gateway=gateway,
                snapshot=snapshot,
                profile=profile,
                voice_run_id=voice_run_id,
                text="Continue this conversation with one short reply.",
                state=first.checkpoint,
                first_event_ms=first_event_ms,
                turn_ms=turn_ms,
            )
            stale = await _invoke_turn(
                gateway=gateway,
                snapshot=snapshot,
                profile=profile,
                voice_run_id=voice_run_id,
                text="Reject this stale continuation.",
                state=first.checkpoint,
                first_event_ms=first_event_ms,
                turn_ms=turn_ms,
            )
    except Exception as exc:  # noqa: BLE001 - persist safe endpoint/network failure code
        live_error = _failure_code(exc)

    successful_turns = [turn for turn in (first, second) if turn is not None]
    required_turn_count = 2 if profile == "stateful_run" else 1
    text_session_conformance = (
        live_error is None
        and len(successful_turns) == required_turn_count
        and all(turn.text_seen and turn.terminal_type == "completed" for turn in successful_turns)
    )
    checks.append(
        EligibilityCheckResult(
            identifier="live.text_session_conformance",
            passed=text_session_conformance,
            duration_ms=round((time.monotonic() - started) * 1000),
            measurements={
                "required_turns": required_turn_count,
                "completed_turns": sum(
                    turn.terminal_type == "completed" for turn in successful_turns
                ),
                "text_turns": sum(turn.text_seen for turn in successful_turns),
            },
            error_code=live_error or "text_session_conformance_failed",
        )
    )

    endpoint_state_continuity = False
    if profile == "stateful_run":
        first_checkpoint = first.checkpoint if first else None
        second_checkpoint = second.checkpoint if second else None
        thread_preserved = bool(
            first_checkpoint
            and second_checkpoint
            and second_checkpoint.get("thread_id") == first_checkpoint.get("thread_id")
        )
        checkpoint_advanced = bool(
            first_checkpoint
            and second_checkpoint
            and second_checkpoint.get("checkpoint_reference")
            != first_checkpoint.get("checkpoint_reference")
        )
        stale_rejected = bool(
            stale
            and not stale.text_seen
            and stale.checkpoint is None
            and stale.terminal_type == "error"
            and stale.error_category == "state_conflict"
            and stale.error_code == "stale_checkpoint"
        )
        endpoint_state_continuity = bool(
            text_session_conformance
            and thread_preserved
            and checkpoint_advanced
            and stale_rejected
        )
        checks.append(
            EligibilityCheckResult(
                identifier="live.endpoint_state_continuity",
                passed=endpoint_state_continuity,
                duration_ms=sum(
                    turn.duration_ms for turn in (first, second, stale) if turn is not None
                ),
                measurements={
                    "thread_preserved": thread_preserved,
                    "checkpoint_advanced": checkpoint_advanced,
                    "stale_checkpoint_rejected": stale_rejected,
                    "invocation_count": sum(
                        turn is not None for turn in (first, second, stale)
                    ),
                },
                error_code=live_error or "endpoint_state_continuity_failed",
            )
        )

    return LiveEndpointEvidence(
        text_session_conformance=text_session_conformance,
        endpoint_state_continuity=endpoint_state_continuity,
        checks=tuple(checks),
    )

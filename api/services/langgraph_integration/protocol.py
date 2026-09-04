"""Pure protocol state machines for the LangGraph Integration Gateway.

Endpoint data is untrusted.  This module deliberately contains no HTTP or
workflow mutation code so sequence, retry, cardinality, cancellation, and
idempotency decisions can be tested independently of the network.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol

from pydantic import BaseModel, ValidationError

from api.schemas.langgraph_integration import validate_payload
from api.schemas.langgraph_integration.common import ErrorCategory

TERMINAL_EVENT_TYPES = frozenset({"completed", "error"})
STATEFUL_EVENT_TYPES = frozenset({"checkpoint", "interrupt"})
RETRYABLE_HTTP_STATUSES = frozenset({408, 425, 429, 502, 503, 504})
RETRYABLE_FAILURES = frozenset({"connection_failure", "timeout"})
TRACEPARENT_RE = re.compile(
    r"^00-[0-9a-f]{32}-[0-9a-f]{16}-(?:0[01])$", re.IGNORECASE
)


def canonical_digest(value: Any) -> str:
    """Return a stable digest without retaining an endpoint payload."""
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class ProtocolViolation(RuntimeError):
    """Safe, structured failure for endpoint contract violations."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        category: ErrorCategory = ErrorCategory.INVALID_RESPONSE,
    ) -> None:
        super().__init__(message)
        self.category = category
        self.code = code
        self.safe_message = message


class ReductionDisposition(StrEnum):
    ACCEPTED = "accepted"
    DUPLICATE = "duplicate"
    POST_TERMINAL = "post_terminal"


@dataclass(frozen=True)
class AssembledToolCall:
    tool_call_id: str
    name: str
    arguments: dict[str, Any]
    argument_digest: str


@dataclass(frozen=True)
class AcceptedRuntimeEvent:
    event: BaseModel
    disposition: ReductionDisposition
    speakable_text: str | None = None
    tool_call: AssembledToolCall | None = None
    terminal: bool = False


class AcceptedEventLedger(Protocol):
    async def record_event(
        self,
        *,
        sequence: int,
        event_id: str,
        event_type: str,
        payload_digest: str,
        metadata: dict[str, Any],
        mutation_outcome: str,
    ) -> bool:
        """Persist an event and return True only when newly inserted."""


@dataclass
class InMemoryAcceptedEventLedger:
    """Deterministic ledger used by conformance and pure gateway tests."""

    rows: dict[int, tuple[str, str, str]] = field(default_factory=dict)

    async def record_event(
        self,
        *,
        sequence: int,
        event_id: str,
        event_type: str,
        payload_digest: str,
        metadata: dict[str, Any],
        mutation_outcome: str,
    ) -> bool:
        del metadata
        existing = self.rows.get(sequence)
        signature = (event_id, event_type, payload_digest)
        if existing is not None:
            if existing != signature:
                raise ProtocolViolation(
                    "sequence_reuse",
                    "a Runtime Event sequence was reused with different content",
                )
            return False
        if any(row[0] == event_id for row in self.rows.values()):
            raise ProtocolViolation(
                "event_id_reuse", "a Runtime Event ID was reused at another sequence"
            )
        self.rows[sequence] = signature
        return True


@dataclass
class _ToolAssembly:
    name: str
    fragments: list[str] = field(default_factory=list)
    byte_count: int = 0


class RuntimeEventReducer:
    """Validate and durably reduce one invocation's Runtime Events.

    The event is written to the accepted-event ledger before any speakable text
    or assembled tool call is returned.  If the guard cannot be written, the
    exception propagates and no effectful output is exposed.
    """

    def __init__(
        self,
        *,
        contract_version: str,
        invocation_id: str,
        ledger: AcceptedEventLedger,
        event_bytes_limit: int,
        tool_argument_bytes_limit: int,
        stateful_profile: bool = False,
        interrupts_selected: bool = False,
    ) -> None:
        self.contract_version = contract_version
        self.invocation_id = invocation_id
        self.ledger = ledger
        self.event_bytes_limit = event_bytes_limit
        self.tool_argument_bytes_limit = tool_argument_bytes_limit
        self.stateful_profile = stateful_profile
        self.interrupts_selected = interrupts_selected
        self.expected_sequence = 0
        self.terminal_sequence: int | None = None
        self._signatures: dict[int, str] = {}
        self._tools: dict[str, _ToolAssembly] = {}
        self._completed_tools: dict[str, tuple[str, str]] = {}

    async def reduce(self, payload: bytes | str | dict[str, Any]) -> AcceptedRuntimeEvent:
        raw_size = _payload_size(payload)
        if raw_size > self.event_bytes_limit:
            raise ProtocolViolation("event_too_large", "Runtime Event exceeds its configured size limit")
        parsed = _decode_object(payload)
        try:
            envelope = validate_payload(self.contract_version, "runtime_event", parsed)
        except (ValidationError, ValueError) as exc:
            raise ProtocolViolation("invalid_runtime_event", "Runtime Event does not match the pinned contract") from exc
        event = envelope.root
        if event.contract_version != self.contract_version:
            raise ProtocolViolation("version_mismatch", "Runtime Event contract version is not pinned version")
        if event.invocation_id != self.invocation_id:
            raise ProtocolViolation("invocation_mismatch", "Runtime Event belongs to another invocation")

        serialized = event.model_dump(mode="json")
        digest = canonical_digest(serialized)
        existing_digest = self._signatures.get(event.sequence)
        if existing_digest is not None:
            if existing_digest != digest:
                raise ProtocolViolation("sequence_reuse", "Runtime Event sequence was reused with different content")
            return AcceptedRuntimeEvent(event, ReductionDisposition.DUPLICATE)

        if self.terminal_sequence is not None:
            await self._record(event, digest, "post_terminal")
            self._signatures[event.sequence] = digest
            return AcceptedRuntimeEvent(event, ReductionDisposition.POST_TERMINAL)
        if event.sequence != self.expected_sequence:
            raise ProtocolViolation(
                "sequence_gap",
                f"expected Runtime Event sequence {self.expected_sequence}",
            )
        if event.type in STATEFUL_EVENT_TYPES and not self.stateful_profile:
            raise ProtocolViolation("capability_not_selected", "stateful Runtime Event was not negotiated")
        if event.type == "interrupt" and not self.interrupts_selected:
            raise ProtocolViolation("interrupt_not_selected", "interrupt capability was not negotiated")

        outcome = "terminal" if event.type in TERMINAL_EVENT_TYPES else "accepted"
        inserted = await self._record(event, digest, outcome)
        if not inserted:
            # A concurrent worker won the durable insert.  It is authoritative,
            # so this worker must not forward another effect.
            self._signatures[event.sequence] = digest
            self.expected_sequence += 1
            return AcceptedRuntimeEvent(event, ReductionDisposition.DUPLICATE)

        self._signatures[event.sequence] = digest
        self.expected_sequence += 1
        speakable: str | None = None
        tool_call: AssembledToolCall | None = None
        if event.type == "text_delta":
            speakable = event.data.text
        elif event.type == "tool_call_start":
            self._start_tool(event.data.tool_call_id, event.data.name)
        elif event.type == "tool_call_delta":
            self._add_tool_fragment(event.data.tool_call_id, event.data.fragment)
        elif event.type == "tool_call_end":
            tool_call = self._finish_tool(event.data.tool_call_id)
        if event.type in TERMINAL_EVENT_TYPES:
            self.terminal_sequence = event.sequence
        return AcceptedRuntimeEvent(
            event,
            ReductionDisposition.ACCEPTED,
            speakable_text=speakable,
            tool_call=tool_call,
            terminal=event.type in TERMINAL_EVENT_TYPES,
        )

    async def _record(self, event: BaseModel, digest: str, outcome: str) -> bool:
        return await self.ledger.record_event(
            sequence=event.sequence,
            event_id=event.event_id,
            event_type=event.type,
            payload_digest=digest,
            metadata={"contract_version": self.contract_version},
            mutation_outcome=outcome,
        )

    def _start_tool(self, call_id: str, name: str) -> None:
        if call_id in self._tools:
            if self._tools[call_id].name != name:
                raise ProtocolViolation("tool_call_reuse", "Tool Call ID was reused with another name")
            raise ProtocolViolation("tool_call_reuse", "Tool Call ID was started more than once")
        if call_id in self._completed_tools:
            raise ProtocolViolation("tool_call_reuse", "completed Tool Call ID was reused")
        self._tools[call_id] = _ToolAssembly(name=name)

    def _add_tool_fragment(self, call_id: str, fragment: str) -> None:
        assembly = self._tools.get(call_id)
        if assembly is None:
            raise ProtocolViolation("tool_fragment_without_start", "Tool Call fragment has no start event")
        size = len(fragment.encode("utf-8"))
        if assembly.byte_count + size > self.tool_argument_bytes_limit:
            raise ProtocolViolation("tool_arguments_too_large", "Tool Call arguments exceed their configured size limit")
        assembly.fragments.append(fragment)
        assembly.byte_count += size

    def _finish_tool(self, call_id: str) -> AssembledToolCall:
        assembly = self._tools.pop(call_id, None)
        if assembly is None:
            raise ProtocolViolation("tool_end_without_start", "Tool Call end has no start event")
        try:
            arguments = json.loads("".join(assembly.fragments) or "{}")
        except json.JSONDecodeError as exc:
            raise ProtocolViolation("invalid_tool_arguments", "Tool Call arguments are not valid JSON") from exc
        if not isinstance(arguments, dict):
            raise ProtocolViolation("invalid_tool_arguments", "Tool Call arguments must be one JSON object")
        digest = canonical_digest(arguments)
        previous = self._completed_tools.get(call_id)
        signature = (assembly.name, digest)
        if previous is not None and previous != signature:
            raise ProtocolViolation("tool_call_reuse", "Tool Call ID changed name or arguments")
        self._completed_tools[call_id] = signature
        return AssembledToolCall(call_id, assembly.name, arguments, digest)


def _payload_size(payload: bytes | str | dict[str, Any]) -> int:
    if isinstance(payload, bytes):
        return len(payload)
    if isinstance(payload, str):
        return len(payload.encode("utf-8"))
    return len(json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))


def _decode_object(payload: bytes | str | dict[str, Any]) -> dict[str, Any]:
    if isinstance(payload, dict):
        return payload
    if isinstance(payload, bytearray):
        payload = bytes(payload)
    try:
        decoded = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolViolation("invalid_json", "endpoint payload is not valid JSON") from exc
    if not isinstance(decoded, dict):
        raise ProtocolViolation("invalid_json", "endpoint payload must be one JSON object")
    return decoded


def validate_synchronous_result(
    payload: bytes | str | dict[str, Any], *, contract_version: str, invocation_id: str, response_bytes_limit: int
) -> BaseModel:
    """Validate exact synchronous cardinality and pinned identity."""
    if _payload_size(payload) > response_bytes_limit:
        raise ProtocolViolation("response_too_large", "synchronous response exceeds its configured size limit")
    parsed = _decode_object(payload)
    try:
        response = validate_payload(contract_version, "synchronous_response", parsed)
    except (ValidationError, ValueError) as exc:
        raise ProtocolViolation("invalid_synchronous_cardinality", "synchronous response must contain exactly one assistant or error result") from exc
    _validate_response_identity(response, contract_version, invocation_id)
    return response


def validate_asynchronous_acceptance(
    payload: bytes | str | dict[str, Any], *, contract_version: str, invocation_id: str, response_bytes_limit: int
) -> BaseModel:
    if _payload_size(payload) > response_bytes_limit:
        raise ProtocolViolation("response_too_large", "asynchronous acceptance exceeds its configured size limit")
    parsed = _decode_object(payload)
    try:
        response = validate_payload(contract_version, "asynchronous_acceptance", parsed)
    except (ValidationError, ValueError) as exc:
        raise ProtocolViolation("invalid_async_cardinality", "asynchronous acceptance must contain one non-empty External Run ID") from exc
    _validate_response_identity(response, contract_version, invocation_id)
    return response


def validate_status_result(
    payload: bytes | str | dict[str, Any], *, contract_version: str, invocation_id: str, external_run_id: str, response_bytes_limit: int
) -> BaseModel:
    if _payload_size(payload) > response_bytes_limit:
        raise ProtocolViolation("response_too_large", "status response exceeds its configured size limit")
    try:
        response = validate_payload(contract_version, "status", _decode_object(payload))
    except (ValidationError, ValueError) as exc:
        raise ProtocolViolation("invalid_status", "status response violates the pinned contract") from exc
    _validate_response_identity(response, contract_version, invocation_id)
    if response.external_run_id != external_run_id:
        raise ProtocolViolation("external_run_mismatch", "status response belongs to another external run")
    return response


def _validate_response_identity(response: BaseModel, contract_version: str, invocation_id: str) -> None:
    if response.contract_version != contract_version:
        raise ProtocolViolation("version_mismatch", "response contract version is not pinned version")
    if response.invocation_id != invocation_id:
        raise ProtocolViolation("invocation_mismatch", "response belongs to another invocation")


@dataclass(frozen=True)
class RetryState:
    accepted_event: bool
    attempts_used: int
    remaining_ms: int
    minimum_attempt_ms: int
    cancelled: bool = False


def should_retry(*, failure: str | int, state: RetryState) -> bool:
    """One retry is allowed only before the accepted-event boundary."""
    retryable = failure in RETRYABLE_FAILURES or failure in RETRYABLE_HTTP_STATUSES
    return bool(
        retryable
        and not state.accepted_event
        and not state.cancelled
        and state.attempts_used == 1
        and state.remaining_ms >= state.minimum_attempt_ms
    )


@dataclass
class InvocationIdentity:
    invocation_id: str
    attempt_ids: list[str] = field(default_factory=list)

    def new_attempt(self, attempt_id: str) -> str:
        if attempt_id in self.attempt_ids:
            raise ValueError("Attempt ID must be unique within an invocation")
        self.attempt_ids.append(attempt_id)
        return attempt_id


@dataclass(frozen=True)
class AttemptResult:
    value: Any = None
    failure: str | int | None = None
    accepted_event: bool = False

    @property
    def succeeded(self) -> bool:
        return self.failure is None


class InvocationCoordinator:
    """Coordinate one logical identity across at most two network attempts."""

    def __init__(
        self,
        *,
        invocation_id_factory: Callable[[], str],
        attempt_id_factory: Callable[[], str],
    ) -> None:
        self.identity = InvocationIdentity(invocation_id_factory())
        self._attempt_id_factory = attempt_id_factory
        self.cancellation = CancellationState()

    async def execute(
        self,
        attempt: Callable[[str, str, int], Awaitable[AttemptResult]],
        *,
        remaining_ms: Callable[[], int],
        minimum_attempt_ms: int,
    ) -> AttemptResult:
        last: AttemptResult | None = None
        for ordinal in (1, 2):
            attempt_id = self.identity.new_attempt(self._attempt_id_factory())
            last = await attempt(self.identity.invocation_id, attempt_id, ordinal)
            if last.succeeded:
                return last
            retry = should_retry(
                failure=last.failure if last.failure is not None else "invalid_response",
                state=RetryState(
                    accepted_event=last.accepted_event,
                    attempts_used=ordinal,
                    remaining_ms=remaining_ms(),
                    minimum_attempt_ms=minimum_attempt_ms,
                    cancelled=not self.cancellation.forwarding_allowed(),
                ),
            )
            if not retry:
                return last
        assert last is not None
        return last

    async def accept_and_dispatch_cancellation(
        self,
        reason: str,
        dispatch: Callable[[], Awaitable[Any]] | None,
    ) -> bool:
        """Suppress immediately, then bound declared cancellation dispatch to 250ms."""
        newly_accepted = self.cancellation.accept(reason)
        if not newly_accepted:
            return False
        if dispatch is not None:
            try:
                await asyncio.wait_for(dispatch(), timeout=0.25)
            except TimeoutError as exc:
                raise ProtocolViolation(
                    "cancellation_dispatch_timeout",
                    "endpoint cancellation was not dispatched within 250 milliseconds",
                ) from exc
        return True


@dataclass
class CancellationState:
    accepted_at: float | None = None
    reason: str | None = None

    def accept(self, reason: str, *, now: float | None = None) -> bool:
        if self.accepted_at is not None:
            return False
        self.accepted_at = time.monotonic() if now is None else now
        self.reason = reason
        return True

    def forwarding_allowed(self) -> bool:
        return self.accepted_at is None


@dataclass
class TerminalOutcomeGuard:
    outcome: Any | None = None
    failure_action: str | None = None

    def record(self, outcome: Any) -> tuple[Any, bool]:
        if self.outcome is not None:
            return self.outcome, False
        self.outcome = outcome
        return outcome, True

    def execute_failure_action(self, action: str) -> bool:
        if self.failure_action is not None:
            return False
        self.failure_action = action
        return True


@dataclass(frozen=True)
class AsyncDeadlineOutcome:
    operations: tuple[str, ...]


def asynchronous_deadline_outcome(*, cancellation_declared: bool) -> AsyncDeadlineOutcome:
    operations = ("cancel", "timeout_effect") if cancellation_declared else ("timeout_effect",)
    return AsyncDeadlineOutcome(operations)


def validated_endpoint_trace_headers(
    headers: dict[str, str], *, mural_traceparent: str
) -> tuple[dict[str, str], tuple[str, ...]]:
    """Accept valid trace continuation only; tenant scope is never imported."""
    lower = {key.lower(): value for key, value in headers.items()}
    candidate = lower.get("traceparent")
    warnings: list[str] = []
    traceparent = mural_traceparent
    if candidate:
        if TRACEPARENT_RE.fullmatch(candidate):
            traceparent = candidate.lower()
        else:
            warnings.append("malformed endpoint traceparent ignored")
    if "x-organization-id" in lower or "x-tenant-id" in lower:
        warnings.append("endpoint tenant claim ignored")
    result = {"traceparent": traceparent}
    if "tracestate" in lower and len(lower["tracestate"]) <= 512:
        result["tracestate"] = lower["tracestate"]
    return result, tuple(warnings)

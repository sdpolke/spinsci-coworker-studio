"""Contract-safe mapping between Mural workflow state and remote reasoning.

This module is deliberately independent of Pipecat and HTTP.  Mural-owned state
is supplied explicitly, endpoint content is treated as untrusted, and durable
stores are called before any tool or transition effect is exposed.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from api.schemas.langgraph_integration.common import ErrorCategory, StateMode, ToolOwner
from api.services.langgraph_integration.protocol import (
    ProtocolViolation,
    canonical_digest,
)
from api.services.workflow.reasoning import (
    JsonObject,
    ReasoningMessage,
    ReasoningRequest,
    ReasoningToolDefinition,
)
from api.services.workflow.workflow_graph import transition_tool_name

_BLOCKED_CONTEXT_KEYS = frozenset(
    {"audio", "raw_audio", "media", "media_socket", "transport", "processor", "pipecat_processor", "process_handle"}
)
_CONTROL_KEYS = frozenset(
    {"prompt", "system_prompt", "credential", "credential_reference", "tool_allowlist", "organization_id", "contract_version"}
)
_DEFAULT_SECRET_PATTERNS = (
    re.compile(r"(?i)\b(?:api[_-]?key|token|secret|password)\s*[:=]\s*[^\s,;]+"),
    re.compile(r"\b(?:sk|pk)-[A-Za-z0-9_-]{12,}\b"),
)


@dataclass(frozen=True)
class DataSharingPolicy:
    """Workflow-version-pinned outbound field allowlist."""

    context_fields: frozenset[str] = frozenset()


@dataclass(frozen=True)
class RedactionPolicy:
    fields: frozenset[str] = frozenset()
    replacement: str = "[REDACTED]"
    patterns: tuple[re.Pattern[str], ...] = ()


@dataclass(frozen=True)
class PinnedReasoningState:
    organization_id: int
    voice_run_id: str
    workflow_version_id: str
    registration_id: str
    contract_version: str
    active_node_id: str
    node_prompt: str
    history: tuple[ReasoningMessage, ...]
    tools: tuple[ReasoningToolDefinition, ...]
    state_mode: str = StateMode.MURAL_AUTHORITATIVE.value
    mode: str = "streaming"
    context: Mapping[str, Any] = field(default_factory=dict)
    endpoint_state: Mapping[str, str] = field(default_factory=dict)
    trace_id: str | None = None


@dataclass(frozen=True)
class ToolEffectReservation:
    inserted: bool
    cached_result: JsonObject | None = None
    name: str | None = None
    argument_digest: str | None = None


class ToolEffectStore(Protocol):
    async def reserve(
        self, *, organization_id: int, invocation_id: str, tool_call_id: str,
        name: str, argument_digest: str
    ) -> ToolEffectReservation: ...

    async def complete(
        self, *, organization_id: int, invocation_id: str, tool_call_id: str,
        result: JsonObject, transition_target: str | None
    ) -> None: ...

    async def reject(
        self, *, organization_id: int, invocation_id: str, tool_call_id: str,
        name: str, argument_digest: str, reason: str
    ) -> JsonObject: ...


class SecurityEventSink(Protocol):
    async def record_security_event(self, **event: Any) -> None: ...


class EndpointStateStore(Protocol):
    async def persist_identifiers(
        self, *, organization_id: int, voice_run_id: str, identifiers: Mapping[str, str],
        trace_id: str | None = None,
    ) -> None: ...


@dataclass
class InMemoryToolEffectStore:
    rows: dict[tuple[int, str, str], dict[str, Any]] = field(default_factory=dict)

    async def reserve(self, *, organization_id: int, invocation_id: str, tool_call_id: str,
                      name: str, argument_digest: str) -> ToolEffectReservation:
        key = (organization_id, invocation_id, tool_call_id)
        existing = self.rows.get(key)
        if existing is not None:
            if existing["name"] != name or existing["argument_digest"] != argument_digest:
                raise ProtocolViolation("tool_call_reuse", "Tool Call ID changed name or arguments")
            return ToolEffectReservation(False, existing.get("result"), name, argument_digest)
        self.rows[key] = {"name": name, "argument_digest": argument_digest, "status": "accepted"}
        return ToolEffectReservation(True, None, name, argument_digest)

    async def complete(self, *, organization_id: int, invocation_id: str, tool_call_id: str,
                       result: JsonObject, transition_target: str | None) -> None:
        row = self.rows[(organization_id, invocation_id, tool_call_id)]
        row.update(status="completed", result=dict(result), transition_target=transition_target)

    async def reject(self, *, organization_id: int, invocation_id: str, tool_call_id: str,
                     name: str, argument_digest: str, reason: str) -> JsonObject:
        result = {"ok": False, "error": {"category": "security_violation", "code": reason}}
        self.rows.setdefault(
            (organization_id, invocation_id, tool_call_id),
            {"name": name, "argument_digest": argument_digest, "status": "rejected", "result": result},
        )
        return result


@dataclass
class DatabaseToolEffectStore:
    """Durable adapter over ``LangGraphEndpointClient`` effect guards."""

    db_client: Any
    invocation_pk_by_uuid: Mapping[str, int]

    async def reserve(self, *, organization_id: int, invocation_id: str, tool_call_id: str,
                      name: str, argument_digest: str) -> ToolEffectReservation:
        invocation_pk = self.invocation_pk_by_uuid[invocation_id]
        row, inserted = await self.db_client.record_langgraph_tool_effect(
            organization_id=organization_id, invocation_id=invocation_pk,
            tool_call_id=tool_call_id, name=name, argument_digest=argument_digest,
            authorization_outcome="authorized", execution_status="accepted",
        )
        if not inserted and (row.name != name or row.argument_digest != argument_digest):
            raise ProtocolViolation("tool_call_reuse", "Tool Call ID changed name or arguments")
        return ToolEffectReservation(inserted, row.cached_result, row.name, row.argument_digest)

    async def complete(self, *, organization_id: int, invocation_id: str, tool_call_id: str,
                       result: JsonObject, transition_target: str | None) -> None:
        completed = await self.db_client.complete_langgraph_tool_effect(
            organization_id=organization_id,
            invocation_id=self.invocation_pk_by_uuid[invocation_id],
            tool_call_id=tool_call_id, result_digest=canonical_digest(result),
            cached_result=result, transition_target=transition_target,
        )
        if not completed:
            raise RuntimeError("accepted Tool Call could not be completed")

    async def reject(self, *, organization_id: int, invocation_id: str, tool_call_id: str,
                     name: str, argument_digest: str, reason: str) -> JsonObject:
        result = {"ok": False, "error": {"category": "security_violation", "code": reason}}
        await self.db_client.record_langgraph_tool_effect(
            organization_id=organization_id,
            invocation_id=self.invocation_pk_by_uuid[invocation_id],
            tool_call_id=tool_call_id, name=name, argument_digest=argument_digest,
            authorization_outcome=reason, execution_status="rejected", cached_result=result,
        )
        return result


@dataclass
class DatabaseEndpointStateStore:
    db_client: Any
    workflow_run_pk_by_id: Mapping[str, int]

    async def persist_identifiers(self, *, organization_id: int, voice_run_id: str,
                                  identifiers: Mapping[str, str], trace_id: str | None = None) -> None:
        await self.db_client.persist_langgraph_endpoint_identifiers(
            organization_id=organization_id,
            workflow_run_id=self.workflow_run_pk_by_id[voice_run_id],
            identifiers=dict(identifiers),
            trace_id=trace_id,
        )


@dataclass
class InMemorySecurityEventSink:
    events: list[dict[str, Any]] = field(default_factory=list)

    async def record_security_event(self, **event: Any) -> None:
        self.events.append(event)


@dataclass
class InMemoryEndpointStateStore:
    identifiers: dict[tuple[int, str], dict[str, str]] = field(default_factory=dict)

    async def persist_identifiers(self, *, organization_id: int, voice_run_id: str,
                                  identifiers: Mapping[str, str], trace_id: str | None = None) -> None:
        del trace_id
        self.identifiers[(organization_id, voice_run_id)] = dict(identifiers)


@dataclass(frozen=True)
class ToolExecutionContext:
    invocation_id: str
    tool_call_id: str
    active_node_id: str
    workflow_version_id: str
    organization_id: int
    voice_run_id: str
    registration_id: str
    confirmation_valid: bool = False
    trace_id: str | None = None


@dataclass(frozen=True)
class ToolExecutionOutcome:
    result: JsonObject
    history: tuple[ReasoningMessage, ...]
    next_node_id: str
    executed: bool
    duplicate: bool = False


def transition_tools_for_node(
    *, edges: Sequence[Any], node_id: str, workflow_version_id: str,
    organization_id: int, voice_run_id: str, registration_id: str,
) -> tuple[ReasoningToolDefinition, ...]:
    """Build a stable one-to-one transition mapping from existing edge names."""
    tools: list[ReasoningToolDefinition] = []
    names: set[str] = set()
    for edge in edges:
        if edge.source != node_id:
            continue
        name = transition_tool_name(edge.label)
        if name in names:
            raise ValueError(f'duplicate transition tool name "{name}" for node {node_id}')
        names.add(name)
        tools.append(
            ReasoningToolDefinition(
                name=name,
                description=edge.condition,
                input_schema={"type": "object", "properties": {}, "additionalProperties": False},
                owner=ToolOwner.MURAL_TRANSITION.value,
                node_id=node_id,
                workflow_version_id=workflow_version_id,
                organization_id=organization_id,
                voice_run_id=voice_run_id,
                registration_id=registration_id,
                transition_target=edge.target,
            )
        )
    return tuple(tools)


def _redact(value: Any, policy: RedactionPolicy, key: str | None = None) -> Any:
    if key is not None and key in policy.fields:
        return policy.replacement
    if isinstance(value, Mapping):
        return {str(k): _redact(v, policy, str(k)) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(item, policy) for item in value]
    if isinstance(value, tuple):
        return tuple(_redact(item, policy) for item in value)
    if isinstance(value, str):
        for pattern in policy.patterns:
            value = pattern.sub(policy.replacement, value)
    return value


def _validate_schema(value: Any, schema: Mapping[str, Any], path: str = "arguments") -> None:
    """Validate the contract subset used by workflow tool schemas."""
    expected = schema.get("type")
    type_map = {"object": dict, "array": list, "string": str, "integer": int,
                "number": (int, float), "boolean": bool, "null": type(None)}
    if expected in type_map and (not isinstance(value, type_map[expected]) or expected in {"integer", "number"} and isinstance(value, bool)):
        raise ValueError(f"{path} must be {expected}")
    if "enum" in schema and value not in schema["enum"]:
        raise ValueError(f"{path} is not an allowed value")
    if expected == "object" and isinstance(value, dict):
        properties = schema.get("properties", {})
        for required in schema.get("required", []):
            if required not in value:
                raise ValueError(f"{path}.{required} is required")
        if schema.get("additionalProperties") is False:
            unknown = set(value) - set(properties)
            if unknown:
                raise ValueError(f"{path} contains unknown properties")
        for key, item in value.items():
            if key in properties:
                _validate_schema(item, properties[key], f"{path}.{key}")
    if expected == "array" and isinstance(value, list) and "items" in schema:
        for index, item in enumerate(value):
            _validate_schema(item, schema["items"], f"{path}[{index}]")


class WorkflowAdapter:
    """State-safe adapter for one immutable workflow/run binding."""

    def __init__(self, *, effect_store: ToolEffectStore | None = None,
                 security_events: SecurityEventSink | None = None,
                 endpoint_state_store: EndpointStateStore | None = None,
                 secret_patterns: tuple[re.Pattern[str], ...] = _DEFAULT_SECRET_PATTERNS) -> None:
        self.effect_store = effect_store or InMemoryToolEffectStore()
        self.security_events = security_events or InMemorySecurityEventSink()
        self.endpoint_state_store = endpoint_state_store or InMemoryEndpointStateStore()
        self.secret_patterns = secret_patterns
        self._node_entries: set[tuple[str, str]] = set()

    def build_request(self, *, state: PinnedReasoningState, invocation_id: str,
                      sharing: DataSharingPolicy | None = None,
                      redaction: RedactionPolicy | None = None) -> ReasoningRequest:
        sharing = sharing or DataSharingPolicy()
        redaction = redaction or RedactionPolicy()
        prompt = ReasoningMessage("system", _redact(state.node_prompt, redaction))
        history = tuple(
            ReasoningMessage(
                message.role,
                _redact(message.content, redaction),
                message.tool_call_id,
                message.name,
            )
            for message in state.history
        )
        context = {
            key: _redact(value, redaction, key)
            for key, value in state.context.items()
            if key in sharing.context_fields and key.lower() not in _BLOCKED_CONTEXT_KEYS
        }
        tools = tuple(tool for tool in state.tools if tool.enabled and tool.owner != ToolOwner.ENDPOINT_INTERNAL.value)
        return ReasoningRequest(
            contract_version=state.contract_version,
            invocation_id=invocation_id,
            voice_run_id=state.voice_run_id,
            workflow_version_id=state.workflow_version_id,
            mode=state.mode,
            state_mode=state.state_mode,
            messages=(prompt, *history),
            tools=tools,
            context=context,
            state=dict(state.endpoint_state) if state.state_mode == StateMode.ENDPOINT_CHECKPOINTED.value else {},
        )

    def begin_node_entry(self, *, voice_run_id: str, node_entry_id: str) -> bool:
        """Return true exactly once for a distinct runtime node-entry identity."""
        key = (voice_run_id, node_entry_id)
        if key in self._node_entries:
            return False
        self._node_entries.add(key)
        return True

    async def execute_tool(self, *, state: PinnedReasoningState, context: ToolExecutionContext,
                           name: str, tool_call_id: str, arguments: JsonObject) -> ToolExecutionOutcome:
        definition = next((tool for tool in state.tools if tool.name == name), None)
        digest = canonical_digest(arguments)
        violation = self._authorize_tool(state, context, definition, arguments)
        if violation is not None:
            await self.security_events.record_security_event(
                organization_id=context.organization_id,
                registration_id=context.registration_id,
                voice_run_id=context.voice_run_id,
                invocation_id=context.invocation_id,
                tool_call_id=tool_call_id,
                tool_name=name,
                violation_category=violation,
                enforcement_decision="rejected",
                trace_id=context.trace_id,
            )
            result = await self.effect_store.reject(
                organization_id=context.organization_id, invocation_id=context.invocation_id,
                tool_call_id=tool_call_id, name=name, argument_digest=digest, reason=violation,
            )
            return self._tool_outcome(state, tool_call_id, name, arguments, result, state.active_node_id, False)

        assert definition is not None
        reservation = await self.effect_store.reserve(
            organization_id=context.organization_id, invocation_id=context.invocation_id,
            tool_call_id=tool_call_id, name=name, argument_digest=digest,
        )
        if not reservation.inserted:
            if reservation.cached_result is None:
                raise ProtocolViolation("tool_effect_in_progress", "Tool Call effect is already in progress")
            target = definition.transition_target or state.active_node_id
            return self._tool_outcome(state, tool_call_id, name, arguments, reservation.cached_result, target, False, True)

        if definition.owner == ToolOwner.MURAL_TRANSITION.value:
            result: JsonObject = {"ok": True, "transitioned_to": definition.transition_target}
            target = definition.transition_target or state.active_node_id
        else:
            if definition.handler is None:
                result = {"ok": False, "error": {"category": "invalid_request", "code": "handler_unavailable"}}
            else:
                result = await definition.handler(arguments)
            target = state.active_node_id
        await self.effect_store.complete(
            organization_id=context.organization_id, invocation_id=context.invocation_id,
            tool_call_id=tool_call_id, result=result, transition_target=definition.transition_target,
        )
        return self._tool_outcome(state, tool_call_id, name, arguments, result, target, True)

    def _authorize_tool(self, state: PinnedReasoningState, context: ToolExecutionContext,
                        definition: ReasoningToolDefinition | None, arguments: JsonObject) -> str | None:
        if definition is None or definition.owner == ToolOwner.ENDPOINT_INTERNAL.value:
            return "unknown_tool"
        checks = (
            (definition.enabled, "tool_disabled"),
            (definition.node_id == context.active_node_id == state.active_node_id, "wrong_node"),
            (definition.workflow_version_id == context.workflow_version_id == state.workflow_version_id, "wrong_workflow_version"),
            (definition.organization_id == context.organization_id == state.organization_id, "foreign_tenant"),
            (definition.voice_run_id == context.voice_run_id == state.voice_run_id, "wrong_voice_run"),
            (definition.registration_id == context.registration_id == state.registration_id, "wrong_registration"),
            (definition.resource_organization_id in (None, context.organization_id), "foreign_resource"),
            (not definition.high_impact or context.confirmation_valid, "confirmation_required"),
        )
        for accepted, reason in checks:
            if not accepted:
                return reason
        if len(json.dumps(arguments, separators=(",", ":"), ensure_ascii=False).encode()) > definition.argument_size_limit:
            return "arguments_too_large"
        try:
            _validate_schema(arguments, definition.input_schema)
        except ValueError:
            return "invalid_schema"
        return None

    @staticmethod
    def _tool_outcome(state: PinnedReasoningState, tool_call_id: str, name: str,
                      arguments: JsonObject, result: JsonObject, target: str,
                      executed: bool, duplicate: bool = False) -> ToolExecutionOutcome:
        history = (
            *state.history,
            ReasoningMessage("assistant", {"arguments": arguments}, tool_call_id, name),
            ReasoningMessage("tool", result, tool_call_id, name),
        )
        return ToolExecutionOutcome(result, history, target, executed, duplicate)

    async def reconcile_endpoint_state(self, *, state: PinnedReasoningState,
                                       claimed_organization_id: int | None = None,
                                       claimed_voice_run_id: str | None = None,
                                       claimed_node_id: str | None = None,
                                       claimed_history_digest: str | None = None,
                                       identifiers: Mapping[str, str] | None = None) -> None:
        conflict = (
            claimed_organization_id not in (None, state.organization_id)
            or claimed_voice_run_id not in (None, state.voice_run_id)
            or claimed_node_id not in (None, state.active_node_id)
            or claimed_history_digest not in (None, canonical_digest([m.to_wire() for m in state.history]))
        )
        if conflict:
            raise ProtocolViolation(
                "state_conflict", "endpoint state conflicts with Mural-authoritative state",
                category=ErrorCategory.STATE_CONFLICT,
            )
        safe_identifiers = {}
        for key, value in (identifiers or {}).items():
            if key not in {"thread_id", "external_run_id", "checkpoint_reference"} or not isinstance(value, str) or not value:
                raise ProtocolViolation("invalid_endpoint_identifier", "endpoint identifier is invalid")
            if self._contains_secret(value):
                raise ProtocolViolation("secret_detected", "endpoint continuation state contains a detected secret", category=ErrorCategory.SECURITY_VIOLATION)
            safe_identifiers[key] = value
        if safe_identifiers:
            await self.endpoint_state_store.persist_identifiers(
                organization_id=state.organization_id, voice_run_id=state.voice_run_id,
                identifiers=safe_identifiers, trace_id=state.trace_id,
            )

    def accept_endpoint_text(self, *, state: PinnedReasoningState, text: str,
                             response_size_limit: int) -> tuple[ReasoningMessage, ...]:
        if len(text.encode("utf-8")) > response_size_limit:
            raise ProtocolViolation("response_too_large", "endpoint text exceeds its configured size limit")
        if self._contains_secret(text):
            raise ProtocolViolation("secret_detected", "endpoint response contains a detected secret", category=ErrorCategory.SECURITY_VIOLATION)
        # Control-like prose remains ordinary assistant output; it has no path to pinned fields.
        return (*state.history, ReasoningMessage("assistant", text))

    def _contains_secret(self, value: str) -> bool:
        return any(pattern.search(value) for pattern in self.secret_patterns)


def pinned_controls(state: PinnedReasoningState) -> dict[str, Any]:
    """Expose a comparison snapshot; endpoint text can never write these fields."""
    return {key: getattr(state, key) for key in _CONTROL_KEYS if hasattr(state, key)}

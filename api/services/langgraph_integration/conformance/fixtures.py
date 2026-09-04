"""Versioned deterministic fixtures for the Chat Compatibility profile."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal

from api.schemas.langgraph_integration.common import MAX_EVENT_BYTES

SUITE_VERSION = "chat-1.0.0"
FIXTURE_VERSION = "1.0"
INVOCATION_ID = "inv-conformance"

JsonObject = dict[str, Any]
FixtureKind = Literal["valid", "malformed"]


@dataclass(frozen=True)
class FixtureOracle:
    """Complete observable Mural outcome for one deterministic fixture."""

    accepted_events: tuple[JsonObject, ...] = ()
    effects: tuple[JsonObject, ...] = ()
    terminal_outcome: JsonObject | None = None
    state_mutations: tuple[JsonObject, ...] = ()
    structured_error: JsonObject | None = None
    unauthorized_effects: tuple[JsonObject, ...] = ()

    def to_dict(self) -> JsonObject:
        return asdict(self)


@dataclass(frozen=True)
class ConformanceFixture:
    """An endpoint script and its declared, versioned result oracle."""

    identifier: str
    title: str
    kind: FixtureKind
    contract_version: str
    script: tuple[JsonObject, ...]
    oracle: FixtureOracle
    test_version: str = FIXTURE_VERSION
    required: bool = True

    def to_dict(self) -> JsonObject:
        return asdict(self)

    @property
    def invocation_id(self) -> str:
        """Return the logical invocation identifier declared by the script."""

        for step in self.script:
            invocation_id = step.get("invocation_id")
            if isinstance(invocation_id, str):
                return invocation_id
        return ""


def _event(sequence: int, event_type: str, data: JsonObject) -> JsonObject:
    return {
        "contract_version": "1.0",
        "invocation_id": INVOCATION_ID,
        "sequence": sequence,
        "event_id": f"evt-{sequence}",
        "type": event_type,
        "data": data,
    }


def _effect(effect_type: str, **details: Any) -> JsonObject:
    return {"type": effect_type, **details}


def _error(code: str, category: str = "invalid_response") -> JsonObject:
    return {"category": category, "code": code, "retryable": False}


def _fixture(
    identifier: str,
    title: str,
    kind: FixtureKind,
    script: tuple[JsonObject, ...],
    *,
    accepted_events: tuple[JsonObject, ...] = (),
    effects: tuple[JsonObject, ...] = (),
    terminal_outcome: JsonObject | None = None,
    state_mutations: tuple[JsonObject, ...] = (),
    structured_error: JsonObject | None = None,
) -> ConformanceFixture:
    return ConformanceFixture(
        identifier=identifier,
        title=title,
        kind=kind,
        contract_version="1.0",
        script=script,
        oracle=FixtureOracle(
            accepted_events=accepted_events,
            effects=effects,
            terminal_outcome=terminal_outcome,
            state_mutations=state_mutations,
            structured_error=structured_error,
        ),
    )


_TEXT = _event(0, "text_delta", {"text": "Hello"})
_TEXT_2 = _event(1, "text_delta", {"text": "world"})
_COMPLETE_0 = _event(0, "completed", {"status": "completed"})
_COMPLETE_1 = _event(1, "completed", {"status": "completed"})
_COMPLETE_2 = _event(2, "completed", {"status": "completed"})
_TOOL_START = _event(0, "tool_call_start", {"tool_call_id": "tool-1", "name": "lookup"})
_TOOL_DELTA = _event(1, "tool_call_delta", {"tool_call_id": "tool-1", "fragment": "{\"id\":1}"})
_TOOL_END = _event(2, "tool_call_end", {"tool_call_id": "tool-1"})
_TOOL_COMPLETE = _event(3, "completed", {"status": "completed"})

_MULTIPLE_TOOL_EVENTS = (
    _event(0, "tool_call_start", {"tool_call_id": "tool-1", "name": "lookup"}),
    _event(1, "tool_call_delta", {"tool_call_id": "tool-1", "fragment": "{}"}),
    _event(2, "tool_call_end", {"tool_call_id": "tool-1"}),
    _event(3, "tool_call_start", {"tool_call_id": "tool-2", "name": "transfer"}),
    _event(4, "tool_call_delta", {"tool_call_id": "tool-2", "fragment": "{\"queue\":\"sales\"}"}),
    _event(5, "tool_call_end", {"tool_call_id": "tool-2"}),
    _event(6, "completed", {"status": "completed"}),
)
_FRAGMENTED_JSON_EVENTS = (
    _TOOL_START,
    _event(1, "tool_call_delta", {"tool_call_id": "tool-1", "fragment": "{\"query\":"}),
    _event(2, "tool_call_delta", {"tool_call_id": "tool-1", "fragment": "\"status\"}"}),
    _event(3, "tool_call_end", {"tool_call_id": "tool-1"}),
    _event(4, "completed", {"status": "completed"}),
)
_USAGE = _event(0, "usage", {"input_tokens": 4, "output_tokens": 2})
_ERROR_EVENT = _event(0, "error", _error("capacity", "overloaded"))

CHAT_BASELINE_FIXTURES: tuple[ConformanceFixture, ...] = (
    _fixture(
        "chat.valid.plain_text",
        "Plain text completion",
        "valid",
        (_TEXT, _COMPLETE_1),
        accepted_events=(_TEXT, _COMPLETE_1),
        effects=(_effect("forward_text", sequence=0, text="Hello"),),
        terminal_outcome={"status": "completed"},
        state_mutations=(_effect("append_assistant", text="Hello"),),
    ),
    _fixture(
        "chat.valid.fragmented_text",
        "Fragmented text completion",
        "valid",
        (_TEXT, _TEXT_2, _COMPLETE_2),
        accepted_events=(_TEXT, _TEXT_2, _COMPLETE_2),
        effects=(
            _effect("forward_text", sequence=0, text="Hello"),
            _effect("forward_text", sequence=1, text="world"),
        ),
        terminal_outcome={"status": "completed"},
        state_mutations=(_effect("append_assistant", text="Helloworld"),),
    ),
    _fixture(
        "chat.valid.single_tool_call",
        "Single Tool Call",
        "valid",
        (_TOOL_START, _TOOL_DELTA, _TOOL_END, _TOOL_COMPLETE),
        accepted_events=(_TOOL_START, _TOOL_DELTA, _TOOL_END, _TOOL_COMPLETE),
        effects=(_effect("tool_call", tool_call_id="tool-1", name="lookup", arguments={"id": 1}),),
        terminal_outcome={"status": "completed"},
        state_mutations=(_effect("append_tool_call", tool_call_id="tool-1"),),
    ),
    _fixture(
        "chat.valid.multiple_tool_calls",
        "Multiple Tool Calls",
        "valid",
        _MULTIPLE_TOOL_EVENTS,
        accepted_events=_MULTIPLE_TOOL_EVENTS,
        effects=(
            _effect("tool_call", tool_call_id="tool-1", name="lookup", arguments={}),
            _effect("tool_call", tool_call_id="tool-2", name="transfer", arguments={"queue": "sales"}),
        ),
        terminal_outcome={"status": "completed"},
        state_mutations=(
            _effect("append_tool_call", tool_call_id="tool-1"),
            _effect("append_tool_call", tool_call_id="tool-2"),
        ),
    ),
    _fixture(
        "chat.valid.fragmented_json",
        "Fragmented JSON Tool Call arguments",
        "valid",
        _FRAGMENTED_JSON_EVENTS,
        accepted_events=_FRAGMENTED_JSON_EVENTS,
        effects=(_effect("tool_call", tool_call_id="tool-1", name="lookup", arguments={"query": "status"}),),
        terminal_outcome={"status": "completed"},
        state_mutations=(_effect("append_tool_call", tool_call_id="tool-1"),),
    ),
    _fixture(
        "chat.valid.tool_result",
        "Tool Result continuation",
        "valid",
        (
            {"type": "request", "messages": [{"role": "tool_result", "tool_call_id": "tool-1", "content": "found"}]},
            _TEXT,
            _COMPLETE_1,
        ),
        accepted_events=(_TEXT, _COMPLETE_1),
        effects=(_effect("forward_text", sequence=0, text="Hello"),),
        terminal_outcome={"status": "completed"},
        state_mutations=(_effect("append_assistant", text="Hello"),),
    ),
    _fixture(
        "chat.valid.usage",
        "Usage metadata",
        "valid",
        (_USAGE, _COMPLETE_1),
        accepted_events=(_USAGE, _COMPLETE_1),
        effects=(_effect("record_usage", input_tokens=4, output_tokens=2),),
        terminal_outcome={"status": "completed"},
    ),
    _fixture(
        "chat.valid.structured_error",
        "Structured terminal error",
        "valid",
        (_ERROR_EVENT,),
        accepted_events=(_ERROR_EVENT,),
        terminal_outcome={"status": "failed", "error": _error("capacity", "overloaded")},
    ),
    _fixture(
        "chat.valid.retry_before_event",
        "Idempotent retry before an accepted event",
        "valid",
        (
            {"type": "transport_error", "attempt": 1, "category": "connection"},
            {"type": "retry", "attempt": 2, "invocation_id": INVOCATION_ID},
            _TEXT,
            _COMPLETE_1,
        ),
        accepted_events=(_TEXT, _COMPLETE_1),
        effects=(
            _effect("retry", attempt=2, invocation_id=INVOCATION_ID),
            _effect("forward_text", sequence=0, text="Hello"),
        ),
        terminal_outcome={"status": "completed", "attempts": 2},
        state_mutations=(_effect("append_assistant", text="Hello"),),
    ),
    _fixture(
        "chat.valid.cancellation",
        "Declared cancellation reaches terminal cancelled",
        "valid",
        (
            {"type": "cancellation_request", "reason": "caller_barge_in"},
            {"type": "cancellation_response", "status": "cancelled", "elapsed_ms": 1200},
        ),
        effects=(_effect("dispatch_cancellation", reason="caller_barge_in"),),
        terminal_outcome={"status": "cancelled", "elapsed_ms": 1200},
    ),
    _fixture(
        "chat.valid.terminal",
        "Single terminal event",
        "valid",
        (_COMPLETE_0,),
        accepted_events=(_COMPLETE_0,),
        terminal_outcome={"status": "completed"},
    ),
    _fixture(
        "chat.valid.idempotent_replay",
        "Repeated Invocation ID has one logical result and Tool effect",
        "valid",
        (_TOOL_START, _TOOL_DELTA, _TOOL_END, _TOOL_COMPLETE, {"type": "replay", "invocation_id": INVOCATION_ID}),
        accepted_events=(_TOOL_START, _TOOL_DELTA, _TOOL_END, _TOOL_COMPLETE),
        effects=(_effect("tool_call", tool_call_id="tool-1", name="lookup", arguments={"id": 1}),),
        terminal_outcome={"status": "completed", "logical_results": 1},
        state_mutations=(_effect("append_tool_call", tool_call_id="tool-1"),),
    ),
    _fixture(
        "chat.malformed.invalid_schema",
        "Invalid Runtime Event schema",
        "malformed",
        ({"contract_version": "1.0", "type": "text_delta", "data": {}},),
        structured_error=_error("invalid_event_schema"),
    ),
    _fixture(
        "chat.malformed.unknown_event",
        "Unknown Runtime Event type",
        "malformed",
        (_event(0, "execute_code", {"source": "untrusted"}),),
        structured_error=_error("unknown_event_type"),
    ),
    _fixture(
        "chat.malformed.duplicate_event",
        "Duplicate sequence with changed payload",
        "malformed",
        (_TEXT, {**_TEXT, "data": {"text": "changed"}}),
        accepted_events=(_TEXT,),
        effects=(_effect("forward_text", sequence=0, text="Hello"),),
        structured_error=_error("duplicate_sequence_conflict"),
    ),
    _fixture(
        "chat.malformed.reordered_fragments",
        "Reordered Tool Call fragments",
        "malformed",
        (_TOOL_START, _event(2, "tool_call_end", {"tool_call_id": "tool-1"}), _TOOL_DELTA),
        accepted_events=(_TOOL_START,),
        structured_error=_error("non_contiguous_sequence"),
    ),
    _fixture(
        "chat.malformed.oversized_payload",
        "Oversized Runtime Event payload",
        "malformed",
        (_event(0, "text_delta", {"text": "x" * (MAX_EVENT_BYTES + 1)}),),
        structured_error=_error("event_too_large"),
    ),
    _fixture(
        "chat.malformed.authentication",
        "Authentication failure",
        "malformed",
        ({"type": "http_error", "status": 401},),
        structured_error=_error("endpoint_authentication_failed", "authentication"),
    ),
    _fixture(
        "chat.malformed.timeout",
        "Endpoint timeout",
        "malformed",
        ({"type": "timeout", "phase": "first_event"},),
        structured_error=_error("endpoint_timeout", "timeout"),
    ),
    _fixture(
        "chat.malformed.disconnect",
        "Disconnect after partial Tool Call",
        "malformed",
        (_TOOL_START, _TOOL_DELTA, {"type": "disconnect"}),
        accepted_events=(_TOOL_START, _TOOL_DELTA),
        structured_error=_error("stream_disconnected"),
    ),
    _fixture(
        "chat.malformed.post_terminal",
        "Data after terminal event",
        "malformed",
        (_COMPLETE_0, _event(1, "text_delta", {"text": "late"})),
        accepted_events=(_COMPLETE_0,),
        terminal_outcome={"status": "completed"},
        structured_error=_error("post_terminal_data"),
    ),
)

FIXTURES_BY_ID = {fixture.identifier: fixture for fixture in CHAT_BASELINE_FIXTURES}

if len(FIXTURES_BY_ID) != len(CHAT_BASELINE_FIXTURES):
    raise RuntimeError("conformance fixture identifiers must be unique")

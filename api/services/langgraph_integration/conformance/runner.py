"""Deterministic fixture execution, oracle comparison, and report metadata."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from typing import Any

from pydantic import ValidationError

from api.schemas.langgraph_integration.common import (
    MAX_EVENT_BYTES,
    MAX_TOOL_ARGUMENT_BYTES,
)
from api.schemas.langgraph_integration.v1_0 import RuntimeEventEnvelope

from .fixtures import (
    CHAT_BASELINE_FIXTURES,
    SUITE_VERSION,
    ConformanceFixture,
    FixtureOracle,
)

JsonObject = dict[str, Any]
_SYNTHETIC_STEPS = {
    "request",
    "transport_error",
    "retry",
    "cancellation_request",
    "cancellation_response",
    "http_error",
    "timeout",
    "disconnect",
    "replay",
}
_RUNTIME_EVENT_TYPES = {
    "text_delta",
    "tool_call_start",
    "tool_call_delta",
    "tool_call_end",
    "usage",
    "status",
    "checkpoint",
    "interrupt",
    "completed",
    "error",
}
_TERMINAL_EVENT_TYPES = {"completed", "error"}


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def deterministic_digest(value: Any) -> str:
    """Return a stable SHA-256 digest for JSON-compatible conformance data."""

    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _error(code: str, category: str = "invalid_response") -> JsonObject:
    return {"category": category, "code": code, "retryable": False}


@dataclass(frozen=True)
class ConformanceObservation:
    """All externally observable effects of executing one fixture."""

    accepted_events: tuple[JsonObject, ...] = ()
    effects: tuple[JsonObject, ...] = ()
    terminal_outcome: JsonObject | None = None
    state_mutations: tuple[JsonObject, ...] = ()
    structured_error: JsonObject | None = None
    unauthorized_effects: tuple[JsonObject, ...] = ()

    def to_dict(self) -> JsonObject:
        return asdict(self)


@dataclass(frozen=True)
class ConformanceResult:
    """Oracle comparison plus persistence-ready deterministic metadata."""

    fixture_identifier: str
    test_version: str
    suite_version: str
    required: bool
    passed: bool
    mismatches: tuple[str, ...]
    fixture_digest: str
    observation_digest: str
    result_digest: str

    def to_validation_result(self) -> JsonObject:
        """Shape the result for ``insert_langgraph_validation_report``."""

        return {
            "test_identifier": self.fixture_identifier,
            "test_version": self.test_version,
            "required": self.required,
            "outcome": "passed" if self.passed else "failed",
            "duration_ms": 0,
            "measurements": {
                "suite_version": self.suite_version,
                "fixture_digest": self.fixture_digest,
                "observation_digest": self.observation_digest,
                "result_digest": self.result_digest,
            },
            "redacted_error": None if self.passed else {"mismatches": list(self.mismatches)},
        }


@dataclass(frozen=True)
class ConformanceSuiteResult:
    """A complete suite run that can be persisted in a Validation Report."""

    suite_version: str
    fixture_digest: str
    result_digest: str
    passed: bool
    results: tuple[ConformanceResult, ...]

    def report_evidence(self) -> JsonObject:
        return {
            "suite_version": self.suite_version,
            "fixture_digest": self.fixture_digest,
            "result_digest": self.result_digest,
            "required_fixture_count": sum(result.required for result in self.results),
            "passed_fixture_count": sum(result.passed for result in self.results),
        }

    def persistence_results(self) -> list[JsonObject]:
        return [result.to_validation_result() for result in self.results]


class _ObservationBuilder:
    def __init__(self, fixture: ConformanceFixture) -> None:
        self.fixture = fixture
        self.accepted_events: list[JsonObject] = []
        self.accepted_by_sequence: dict[int, JsonObject] = {}
        self.effects: list[JsonObject] = []
        self.state_mutations: list[JsonObject] = []
        self.structured_error: JsonObject | None = None
        self.terminal_outcome: JsonObject | None = None
        self.next_sequence = 0
        self.terminal_seen = False
        self.text_fragments: list[str] = []
        self.tool_calls: dict[str, dict[str, Any]] = {}
        self.attempts = 1
        self.pending_retryable_failure = False

    def fail(self, code: str, category: str = "invalid_response") -> None:
        if self.structured_error is None:
            self.structured_error = _error(code, category)

    def observation(self) -> ConformanceObservation:
        return ConformanceObservation(
            accepted_events=tuple(self.accepted_events),
            effects=tuple(self.effects),
            terminal_outcome=self.terminal_outcome,
            state_mutations=tuple(self.state_mutations),
            structured_error=self.structured_error,
        )

    def accept_runtime_event(self, step: JsonObject) -> None:
        if len(_canonical_bytes(step)) > MAX_EVENT_BYTES:
            self.fail("event_too_large")
            return
        event_type = step.get("type")
        if event_type not in _RUNTIME_EVENT_TYPES:
            self.fail("unknown_event_type")
            return
        if self.terminal_seen:
            self.fail("post_terminal_data")
            return
        try:
            event = RuntimeEventEnvelope.model_validate(step).root.model_dump(mode="json", exclude_none=True)
        except ValidationError:
            self.fail("invalid_event_schema")
            return
        if event["contract_version"] != self.fixture.contract_version:
            self.fail("invalid_event_schema")
            return

        sequence = event["sequence"]
        if sequence < self.next_sequence:
            prior = self.accepted_by_sequence.get(sequence)
            if prior != event:
                self.fail("duplicate_sequence_conflict")
            return
        if sequence != self.next_sequence:
            self.fail("non_contiguous_sequence")
            return

        self.accepted_events.append(event)
        self.accepted_by_sequence[sequence] = event
        self.next_sequence += 1
        data = event["data"]

        if event_type == "text_delta":
            text = data["text"]
            self.text_fragments.append(text)
            self.effects.append({"type": "forward_text", "sequence": sequence, "text": text})
        elif event_type == "tool_call_start":
            tool_call_id = data["tool_call_id"]
            if tool_call_id in self.tool_calls:
                self.fail("duplicate_tool_call_id")
                return
            self.tool_calls[tool_call_id] = {"name": data["name"], "fragments": []}
        elif event_type == "tool_call_delta":
            tool = self.tool_calls.get(data["tool_call_id"])
            if tool is None:
                self.fail("unknown_tool_call_id")
                return
            tool["fragments"].append(data["fragment"])
            if len("".join(tool["fragments"]).encode("utf-8")) > MAX_TOOL_ARGUMENT_BYTES:
                self.fail("tool_arguments_too_large")
        elif event_type == "tool_call_end":
            self._finish_tool_call(data["tool_call_id"])
        elif event_type == "usage":
            self.effects.append({"type": "record_usage", **data})
        elif event_type in {"checkpoint", "interrupt"}:
            self.fail("undeclared_chat_event")
        elif event_type == "completed":
            self.terminal_seen = True
            self.terminal_outcome = {"status": "completed"}
            if self.attempts > 1:
                self.terminal_outcome["attempts"] = self.attempts
            if self.text_fragments:
                self.state_mutations.append({"type": "append_assistant", "text": "".join(self.text_fragments)})
        elif event_type == "error":
            self.terminal_seen = True
            self.terminal_outcome = {"status": "failed", "error": data}

    def _finish_tool_call(self, tool_call_id: str) -> None:
        tool = self.tool_calls.get(tool_call_id)
        if tool is None:
            self.fail("unknown_tool_call_id")
            return
        try:
            arguments = json.loads("".join(tool["fragments"]))
        except json.JSONDecodeError:
            self.fail("invalid_tool_arguments")
            return
        if not isinstance(arguments, dict):
            self.fail("invalid_tool_arguments")
            return
        self.effects.append(
            {
                "type": "tool_call",
                "tool_call_id": tool_call_id,
                "name": tool["name"],
                "arguments": arguments,
            }
        )
        self.state_mutations.append({"type": "append_tool_call", "tool_call_id": tool_call_id})

    def accept_synthetic_step(self, step: JsonObject) -> None:
        step_type = step.get("type")
        if step_type == "request":
            return
        if step_type == "transport_error":
            self.pending_retryable_failure = True
        elif step_type == "retry":
            if (
                not self.pending_retryable_failure
                or self.accepted_events
                or step.get("attempt") != 2
                or step.get("invocation_id") != self.fixture.invocation_id
            ):
                self.fail("invalid_retry")
                return
            self.attempts = 2
            self.pending_retryable_failure = False
            self.effects.append({"type": "retry", "attempt": 2, "invocation_id": step["invocation_id"]})
        elif step_type == "cancellation_request":
            self.effects.append({"type": "dispatch_cancellation", "reason": step.get("reason")})
        elif step_type == "cancellation_response":
            if step.get("status") != "cancelled" or not isinstance(step.get("elapsed_ms"), int):
                self.fail("invalid_cancellation_response")
                return
            if step["elapsed_ms"] > 2000:
                self.fail("cancellation_timeout", "timeout")
                return
            self.terminal_outcome = {"status": "cancelled", "elapsed_ms": step["elapsed_ms"]}
            self.terminal_seen = True
        elif step_type == "http_error":
            status = step.get("status")
            if status in {401, 403}:
                self.fail("endpoint_authentication_failed", "authentication")
            else:
                self.fail("endpoint_http_error")
        elif step_type == "timeout":
            self.fail("endpoint_timeout", "timeout")
        elif step_type == "disconnect":
            self.fail("stream_disconnected")
        elif step_type == "replay":
            if step.get("invocation_id") != self.fixture.invocation_id or self.terminal_outcome is None:
                self.fail("invalid_replay")
                return
            self.terminal_outcome = {**self.terminal_outcome, "logical_results": 1}


def observe_script(fixture: ConformanceFixture, steps: Iterable[JsonObject] | None = None) -> ConformanceObservation:
    """Reduce a deterministic endpoint script into its observable Mural outcome."""

    builder = _ObservationBuilder(fixture)
    for step in fixture.script if steps is None else steps:
        if builder.structured_error is not None:
            break
        step_type = step.get("type")
        if step_type in _SYNTHETIC_STEPS:
            builder.accept_synthetic_step(step)
        else:
            builder.accept_runtime_event(step)
    return builder.observation()


def _oracle_mismatches(oracle: FixtureOracle, observation: ConformanceObservation) -> tuple[str, ...]:
    expected = oracle.to_dict()
    observed = observation.to_dict()
    return tuple(field for field in expected if expected[field] != observed[field])


def run_fixture(
    fixture: ConformanceFixture,
    observation: ConformanceObservation | None = None,
) -> ConformanceResult:
    """Execute or compare one fixture and return deterministic result metadata."""

    observed = observation if observation is not None else observe_script(fixture)
    mismatches = _oracle_mismatches(fixture.oracle, observed)
    fixture_digest = deterministic_digest(fixture.to_dict())
    observation_digest = deterministic_digest(observed.to_dict())
    result_body = {
        "suite_version": SUITE_VERSION,
        "fixture_identifier": fixture.identifier,
        "test_version": fixture.test_version,
        "required": fixture.required,
        "passed": not mismatches,
        "mismatches": mismatches,
        "fixture_digest": fixture_digest,
        "observation_digest": observation_digest,
    }
    return ConformanceResult(
        fixture_identifier=fixture.identifier,
        test_version=fixture.test_version,
        suite_version=SUITE_VERSION,
        required=fixture.required,
        passed=not mismatches,
        mismatches=mismatches,
        fixture_digest=fixture_digest,
        observation_digest=observation_digest,
        result_digest=deterministic_digest(result_body),
    )


def suite_digest(fixtures: Iterable[ConformanceFixture] = CHAT_BASELINE_FIXTURES) -> str:
    """Digest suite version and ordered fixture definitions for immutable evidence."""

    return deterministic_digest(
        {
            "suite_version": SUITE_VERSION,
            "fixtures": [fixture.to_dict() for fixture in fixtures],
        }
    )


def run_suite(fixtures: Iterable[ConformanceFixture] = CHAT_BASELINE_FIXTURES) -> ConformanceSuiteResult:
    """Run a fixture collection and build Validation Report persistence data."""

    fixture_tuple = tuple(fixtures)
    results = tuple(run_fixture(fixture) for fixture in fixture_tuple)
    fixtures_digest = suite_digest(fixture_tuple)
    result_digest = deterministic_digest(
        {
            "suite_version": SUITE_VERSION,
            "fixture_digest": fixtures_digest,
            "results": [asdict(result) for result in results],
        }
    )
    return ConformanceSuiteResult(
        suite_version=SUITE_VERSION,
        fixture_digest=fixtures_digest,
        result_digest=result_digest,
        passed=all(result.passed for result in results if result.required),
        results=results,
    )

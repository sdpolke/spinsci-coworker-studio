from __future__ import annotations

from copy import deepcopy
from typing import Any

SUPPORTED_EXAMPLE_VERSIONS = ("1.0", "1.1", "1.2")


def _invocation(
    version: str, mode: str, *, tools: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "contract_version": version,
        "operation": "invoke",
        "invocation_id": "inv_example",
        "attempt_id": "att_example",
        "voice_run_id": "run_example",
        "workflow_version_id": "wf_1",
        "mode": mode,
        "state_mode": "mural_authoritative",
        "messages": [
            {"role": "system", "content": [{"type": "text", "text": "Help the caller"}]}
        ],
        "tools": tools or [],
        "deadlines": {"first_event_ms": 1500, "turn_ms": 10000},
    }
    if version in {"1.1", "1.2"}:
        payload["locale"] = "en-US"
    return payload


def _event(
    version: str, sequence: int, event_id: str, event_type: str, data: dict[str, Any]
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "contract_version": version,
        "invocation_id": "inv_example",
        "sequence": sequence,
        "event_id": event_id,
        "type": event_type,
        "data": data,
    }
    if version in {"1.1", "1.2"}:
        payload["timestamp_ms"] = sequence
    return payload


def _assistant_result(version: str) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "contract_version": version,
        "invocation_id": "inv_example",
        "result": {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [{"type": "text", "text": "I can help."}],
            },
            "status": "completed",
        },
    }
    if version in {"1.1", "1.2"}:
        payload["response_id"] = "response_example"
    return payload


def _manifest(version: str) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": version,
        "endpoint_id": "support-agent",
        "display_name": "Support Agent",
        "data_regions": ["us-east"],
        "contract_versions": list(SUPPORTED_EXAMPLE_VERSIONS),
        "compatibility_profiles": ["chat"],
        "invocation_modes": ["streaming", "synchronous", "asynchronous"],
        "state_modes": ["mural_authoritative"],
        "operations": {
            "invoke": "/v1/invocations",
            "status": "/v1/runs/{external_run_id}",
            "cancel": "/v1/invocations/{invocation_id}/cancel",
            "health": "/v1/health",
        },
    }
    if version in {"1.1", "1.2"}:
        payload["metadata"] = {"deployment": "example"}
    return payload


EXECUTABLE_EXAMPLES: dict[str, dict[str, dict[str, Any]]] = {
    version: {
        "manifest": _manifest(version),
        "invocation": _invocation(version, "streaming"),
        "health": {
            "contract_version": version,
            "operation": "health",
            "status": "healthy",
            "endpoint_id": "support-agent",
            "observed_at": "2026-01-15T00:00:00Z",
            **({"checks": {"runtime": "healthy"}} if version == "1.1" else {}),
        },
        "runtime_event": _event(
            version, 0, "evt_example", "text_delta", {"text": "Hello"}
        ),
    }
    for version in SUPPORTED_EXAMPLE_VERSIONS
}


def _example_steps(version: str, category: str) -> list[dict[str, Any]]:
    if category == "sync":
        return [
            {"schema": "invocation", "payload": _invocation(version, "synchronous")},
            {"schema": "synchronous_response", "payload": _assistant_result(version)},
        ]
    if category == "stream":
        return [
            {"schema": "invocation", "payload": _invocation(version, "streaming")},
            {
                "schema": "runtime_event",
                "payload": _event(
                    version, 0, "evt_text", "text_delta", {"text": "Hello"}
                ),
            },
            {
                "schema": "runtime_event",
                "payload": _event(
                    version, 1, "evt_done", "completed", {"status": "completed"}
                ),
            },
        ]
    if category == "async":
        acceptance: dict[str, Any] = {
            "contract_version": version,
            "invocation_id": "inv_example",
            "status": "accepted",
            "external_run_id": "external_run_example",
        }
        if version in {"1.1", "1.2"}:
            acceptance["poll_after_ms"] = 250
        return [
            {"schema": "invocation", "payload": _invocation(version, "asynchronous")},
            {"schema": "asynchronous_acceptance", "payload": acceptance},
            {
                "schema": "status",
                "payload": {
                    "contract_version": version,
                    "operation": "status",
                    "invocation_id": "inv_example",
                    "external_run_id": "external_run_example",
                    "status": "completed",
                    "result": _assistant_result(version)["result"],
                },
            },
        ]
    if category == "tool":
        tool = {
            "name": "lookup_account",
            "description": "Look up an account owned by the current tenant.",
            "input_schema": {
                "type": "object",
                "properties": {"account_id": {"type": "string"}},
                "required": ["account_id"],
                "additionalProperties": False,
            },
            "owner": "mural_platform",
            "authorization": "current_node",
        }
        follow_up = _invocation(version, "streaming", tools=[tool])
        follow_up["attempt_id"] = "att_example_after_tool"
        follow_up["messages"] = [
            {
                "role": "system",
                "content": [{"type": "text", "text": "Help the caller"}],
            },
            {
                "role": "tool_call",
                "tool_call_id": "call_1",
                "content": [{"type": "text", "text": '{"account_id":"A-1"}'}],
            },
            {
                "role": "tool_result",
                "tool_call_id": "call_1",
                "content": [{"type": "text", "text": '{"status":"found"}'}],
            },
        ]
        return [
            {
                "schema": "invocation",
                "payload": _invocation(version, "streaming", tools=[tool]),
            },
            {
                "schema": "runtime_event",
                "payload": _event(
                    version,
                    0,
                    "evt_tool_start",
                    "tool_call_start",
                    {"tool_call_id": "call_1", "name": "lookup_account"},
                ),
            },
            {
                "schema": "runtime_event",
                "payload": _event(
                    version,
                    1,
                    "evt_tool_delta",
                    "tool_call_delta",
                    {"tool_call_id": "call_1", "fragment": '{"account_id":"A-1"}'},
                ),
            },
            {
                "schema": "runtime_event",
                "payload": _event(
                    version,
                    2,
                    "evt_tool_end",
                    "tool_call_end",
                    {"tool_call_id": "call_1"},
                ),
            },
            {
                "schema": "runtime_event",
                "payload": _event(
                    version, 3, "evt_tool_done", "completed", {"status": "completed"}
                ),
            },
            {"schema": "invocation", "payload": follow_up},
        ]
    if category == "error":
        return [
            {"schema": "invocation", "payload": _invocation(version, "streaming")},
            {
                "schema": "runtime_event",
                "payload": _event(
                    version,
                    0,
                    "evt_error",
                    "error",
                    {"category": "overloaded", "code": "capacity", "retryable": True},
                ),
            },
        ]
    if category == "cancel":
        return [
            {
                "schema": "cancellation_request",
                "payload": {
                    "contract_version": version,
                    "operation": "cancel",
                    "invocation_id": "inv_example",
                    "reason": "caller_barge_in",
                    **(
                        {"detail": "A newer caller turn superseded this invocation."}
                        if version == "1.1"
                        else {}
                    ),
                },
            },
            {
                "schema": "cancellation_response",
                "payload": {
                    "contract_version": version,
                    "invocation_id": "inv_example",
                    "status": "cancelled",
                },
            },
        ]
    if category == "interrupt":
        return [
            {"schema": "invocation", "payload": _invocation(version, "streaming")},
            {
                "schema": "runtime_event",
                "payload": _event(
                    version,
                    0,
                    "evt_interrupt",
                    "interrupt",
                    {
                        "interrupt_type": "approval",
                        "reason": "Approve the high-impact action.",
                        "allowed_decisions": ["approve", "reject"],
                        "expires_at": "2026-01-15T00:05:00Z",
                        "checkpoint_reference": "checkpoint_example",
                    },
                ),
            },
        ]
    if category == "resume":
        return [
            {
                "schema": "resume",
                "payload": {
                    "contract_version": version,
                    "operation": "resume",
                    "invocation_id": "inv_resume_example",
                    "prior_invocation_id": "inv_example",
                    "voice_run_id": "run_example",
                    "state": {
                        "thread_id": "thread_example",
                        "checkpoint_reference": "checkpoint_example",
                    },
                    "decision": {"type": "approve", "value": None},
                    **(
                        {"metadata": {"review_source": "operator"}}
                        if version == "1.1"
                        else {}
                    ),
                },
            }
        ]
    raise ValueError(f"unknown executable example category: {category}")


_EXAMPLE_OBSERVABLE_RESULTS = {
    "sync": "Exactly one completed assistant result is accepted.",
    "stream": "One text event is accepted before exactly one terminal completion.",
    "async": "One non-empty external run ID is accepted and authenticated status reaches one terminal assistant result.",
    "tool": "One declared Tool Call is assembled from ordered fragments before terminal completion.",
    "error": "One structured overloaded error terminates the invocation without state progression.",
    "cancel": "The idempotent cancellation request returns a cancelled terminal status.",
    "interrupt": "A complete Endpoint Interrupt pauses execution with allowed decisions and an expiring checkpoint reference.",
    "resume": "A new Invocation ID resumes the prior invocation from its opaque checkpoint using an allowed decision.",
}

PUBLICATION_EXAMPLES: tuple[dict[str, Any], ...] = tuple(
    {
        "id": f"{category}-example",
        "category": category,
        "claimed_contract_versions": SUPPORTED_EXAMPLE_VERSIONS,
        "steps_by_version": {
            version: _example_steps(version, category)
            for version in SUPPORTED_EXAMPLE_VERSIONS
        },
        "expected_observable_result": observable,
    }
    for category, observable in _EXAMPLE_OBSERVABLE_RESULTS.items()
)


def copy_publication_examples() -> list[dict[str, Any]]:
    """Return mutable example data for validators and negative publication tests."""

    return deepcopy(PUBLICATION_EXAMPLES)

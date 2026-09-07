"""Canonical publishable LangGraph contract and compatibility catalog.

This module is the non-schema source of truth used by runtime compatibility
selection and generated documentation. Keep policy statements here so docs do
not duplicate protocol behavior in hand-written prose.
"""

from __future__ import annotations

from datetime import date

from api.schemas.langgraph_integration.common import (
    CompatibilityProfile,
    InvocationMode,
    StateMode,
)

from .models import MatrixVersion, ProfileRequirements

DOCUMENTATION_VERSION = "2026-02"
DOCUMENTATION_PUBLISHED_AT = "2026-02-15T00:00:00Z"

COMPATIBILITY_MATRICES = (
    MatrixVersion(
        matrix_version="2026-01",
        effective_date=date(2026, 1, 15),
        mural_release_version="1.44.0",
        supported_contract_versions=("1.0", "1.1"),
        profiles=(
            ProfileRequirements(
                profile=CompatibilityProfile.CHAT,
                required_invocation_modes=frozenset({InvocationMode.STREAMING}),
                allowed_state_modes=frozenset({StateMode.MURAL_AUTHORITATIVE}),
                limitations=(
                    "Live voice requires streaming mode.",
                    "The endpoint receives chat-oriented requests, never raw audio or Pipecat processors.",
                ),
            ),
            ProfileRequirements(
                profile=CompatibilityProfile.STATEFUL_RUN,
                required_invocation_modes=frozenset({InvocationMode.STREAMING}),
                allowed_state_modes=frozenset({StateMode.ENDPOINT_CHECKPOINTED}),
                required_features=frozenset({"interrupts"}),
                limitations=(
                    "Stateful Run and human review remain an optional post-Chat expansion.",
                ),
            ),
        ),
        limitations=(
            "The integration is experimental.",
            "Realtime speech-to-speech workflows bypass the chat integration.",
            "Compatibility is based on contract behavior, not a specific LangGraph package version.",
        ),
    ),
    MatrixVersion(
        matrix_version="2026-02",
        effective_date=date(2026, 2, 15),
        mural_release_version="1.44.0",
        supported_contract_versions=("1.0", "1.1", "1.2"),
        profiles=(
            ProfileRequirements(
                profile=CompatibilityProfile.CHAT,
                required_invocation_modes=frozenset({InvocationMode.STREAMING}),
                allowed_state_modes=frozenset({StateMode.MURAL_AUTHORITATIVE}),
                limitations=(
                    "Live voice requires streaming mode.",
                    "The endpoint receives chat-oriented requests, never raw audio or Pipecat processors.",
                ),
            ),
            ProfileRequirements(
                profile=CompatibilityProfile.STATEFUL_RUN,
                required_invocation_modes=frozenset({InvocationMode.STREAMING}),
                allowed_state_modes=frozenset({StateMode.ENDPOINT_CHECKPOINTED}),
                limitations=(
                    "The endpoint owns graph orchestration and checkpoint state.",
                    "Interrupt and resume behavior is optional and must be selected explicitly.",
                ),
            ),
        ),
        limitations=(
            "The integration is experimental.",
            "Realtime speech-to-speech workflows bypass the text integration.",
            "Compatibility is based on contract behavior, not a specific LangGraph package version.",
        ),
    ),
)

AUTHENTICATION_METHODS = (
    {
        "id": "credential_reference",
        "description": "Mural resolves the tenant-owned encrypted credential reference and authenticates every endpoint operation.",
        "secret_projection": "Credentials never appear in workflow definitions, generated examples, logs, traces, or client responses.",
        "operations": (
            "discovery",
            "invoke",
            "status",
            "resume",
            "cancel",
            "health",
            "callback",
        ),
    },
)

TIMEOUT_POLICIES = (
    {"id": "discovery", "maximum_ms": 5_000, "outcome": "discovery_timeout"},
    {
        "id": "first_event",
        "minimum_ms": 500,
        "maximum_ms": 3_000,
        "source": "InvocationRequest.deadlines.first_event_ms",
    },
    {
        "id": "turn",
        "minimum_ms": 1,
        "maximum_ms": 300_000,
        "source": "InvocationRequest.deadlines.turn_ms",
    },
    {
        "id": "cancellation_dispatch",
        "maximum_ms": 250,
        "outcome": "forwarding_suppressed_and_cancel_dispatched_when_declared",
    },
)

RETRY_CONDITIONS = (
    {
        "maximum_retries": 1,
        "eligible": (
            "connection_failure",
            "timeout",
            "http_408",
            "http_425",
            "http_429",
            "http_502",
            "http_503",
            "http_504",
        ),
        "conditions": (
            "no_runtime_event_accepted",
            "remaining_deadline_permits_attempt",
        ),
        "identity": "Reuse Invocation ID and create a new Attempt ID.",
    },
)

CANCELLATION_RULES = (
    {
        "reasons": (
            "caller_barge_in",
            "hangup",
            "node_change",
            "operator_action",
            "platform_shutdown",
            "deadline",
        ),
        "idempotency_key": "invocation_id",
        "forwarding_suppression_ms": 250,
        "dispatch_ms": 250,
        "terminal_statuses": ("cancelled", "already_terminal"),
    },
)

OWNERSHIP_INVENTORY = (
    {"field": "prompts", "owner": "mural"},
    {"field": "conversation_history", "owner": "mural"},
    {"field": "frontend_workflow_state", "owner": "mural"},
    {"field": "langgraph_internal_state", "owner": "endpoint"},
    {"field": "checkpoints", "owner": "endpoint_issued_mural_scoped_storage"},
    {"field": "thread_id", "owner": "endpoint_issued_mural_scoped_storage"},
    {"field": "external_run_id", "owner": "endpoint_issued_mural_scoped_storage"},
    {"field": "tool_definitions", "owner": "mural"},
    {"field": "tool_calls", "owner": "endpoint_requested_mural_authorized"},
    {"field": "tool_results", "owner": "mural"},
    {"field": "telephony_controls", "owner": "mural"},
    {"field": "recordings", "owner": "mural"},
)

OPERATOR_CHECKLIST = (
    "endpoint_reachability",
    "credentials",
    "tenant_authorization",
    "privacy_policy",
    "data_region",
    "latency",
    "health",
    "conformance",
    "rollout",
    "rollback",
)

CALLER_VISIBLE_CONSEQUENCES = (
    {
        "condition": "slow_first_event",
        "effect": "The pinned fallback, transfer, or end-call action runs after the configured deadline.",
    },
    {
        "condition": "long_running_tool_call",
        "effect": "The caller may hear silence until the tool completes and the endpoint emits more text.",
    },
    {
        "condition": "asynchronous_wait",
        "effect": "The turn remains bounded by its deadline and then applies the pinned timeout action.",
    },
    {
        "condition": "endpoint_error",
        "effect": "Mural applies the pinned terminal-failure action without switching to an unpinned model.",
    },
    {
        "condition": "human_review_pause",
        "effect": "Stateful profiles apply the pinned speak-and-wait, transfer, or end-call policy.",
    },
)

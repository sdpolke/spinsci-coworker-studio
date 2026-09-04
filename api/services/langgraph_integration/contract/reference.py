"""Generate and validate the versioned LangGraph contract reference."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from typing import Any

from pydantic import ValidationError

from api.schemas.langgraph_integration import (
    SUPPORTED_SCHEMA_VERSIONS,
    schema_for,
    schema_operations,
)
from api.schemas.langgraph_integration.common import ErrorCategory
from api.schemas.langgraph_integration.examples import PUBLICATION_EXAMPLES

from .catalog import (
    AUTHENTICATION_METHODS,
    CALLER_VISIBLE_CONSEQUENCES,
    CANCELLATION_RULES,
    COMPATIBILITY_MATRICES,
    DOCUMENTATION_PUBLISHED_AT,
    DOCUMENTATION_VERSION,
    OPERATOR_CHECKLIST,
    OWNERSHIP_INVENTORY,
    RETRY_CONDITIONS,
    TIMEOUT_POLICIES,
)

EXAMPLE_CATEGORIES = frozenset(
    {"sync", "stream", "async", "tool", "error", "cancel", "interrupt", "resume"}
)

_OPERATION_DETAILS = {
    "manifest": {"operation": "discovery", "method": "GET", "authenticated": True},
    "invocation": {"operation": "invoke", "method": "POST", "authenticated": True},
    "synchronous_response": {"operation": "invoke", "direction": "response"},
    "asynchronous_acceptance": {"operation": "invoke", "direction": "response"},
    "status": {"operation": "status", "method": "GET", "authenticated": True},
    "runtime_event": {
        "operation": "stream",
        "transport": "text/event-stream",
        "authenticated": True,
    },
    "cancellation_request": {
        "operation": "cancel",
        "method": "POST",
        "authenticated": True,
    },
    "cancellation_response": {"operation": "cancel", "direction": "response"},
    "resume": {"operation": "resume", "method": "POST", "authenticated": True},
    "health": {"operation": "health", "method": "GET", "authenticated": True},
}


class ExamplePublicationError(ValueError):
    """Raised when any claimed example/version association cannot be published."""

    def __init__(self, failures: list[dict[str, str]]):
        self.failures = failures
        super().__init__(
            f"contract reference publication blocked by {len(failures)} failing example association(s)"
        )


def _jsonable(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, Mapping):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list, set, frozenset)):
        return [_jsonable(item) for item in value]
    return value


def validate_publication_examples(
    examples: Iterable[Mapping[str, Any]] = PUBLICATION_EXAMPLES,
) -> list[dict[str, Any]]:
    """Execute every example against every claimed contract version.

    The returned records are safe publication metadata. Any invalid association
    raises once with all failures, preventing partial artifact publication.
    """

    results: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    for example in examples:
        example_id = str(example.get("id", "missing-id"))
        category = str(example.get("category", ""))
        claimed_versions = tuple(example.get("claimed_contract_versions", ()))
        steps_by_version = example.get("steps_by_version", {})
        observable = str(example.get("expected_observable_result", ""))
        if category not in EXAMPLE_CATEGORIES:
            failures.append(
                {
                    "example_id": example_id,
                    "version": "*",
                    "error": f"unknown category: {category}",
                }
            )
        if not claimed_versions:
            failures.append(
                {
                    "example_id": example_id,
                    "version": "*",
                    "error": "no claimed contract versions",
                }
            )
        if not observable:
            failures.append(
                {
                    "example_id": example_id,
                    "version": "*",
                    "error": "missing expected observable result",
                }
            )
        for version in claimed_versions:
            try:
                if version not in SUPPORTED_SCHEMA_VERSIONS:
                    raise ValueError(f"unsupported claimed contract version: {version}")
                steps = steps_by_version[version]
                if not steps:
                    raise ValueError("example has no executable steps")
                validated_steps = []
                for step in steps:
                    schema_name = step["schema"]
                    validated = schema_for(version, schema_name).model_validate(
                        step["payload"]
                    )
                    validated_steps.append(
                        {
                            "schema": schema_name,
                            "payload": validated.model_dump(
                                mode="json", exclude_none=True
                            ),
                        }
                    )
                results.append(
                    {
                        "example_id": example_id,
                        "category": category,
                        "contract_version": version,
                        "validated_at": DOCUMENTATION_PUBLISHED_AT,
                        "expected_observable_result": observable,
                        "steps": validated_steps,
                    }
                )
            except (KeyError, TypeError, ValueError, ValidationError) as exc:
                failures.append(
                    {
                        "example_id": example_id,
                        "version": str(version),
                        "error": str(exc),
                    }
                )
    if failures:
        raise ExamplePublicationError(failures)
    return results


def _matrix_inventory() -> list[dict[str, Any]]:
    return [
        {
            **matrix.model_dump(mode="json"),
            "profiles": [
                profile.model_dump(mode="json") for profile in matrix.profiles
            ],
        }
        for matrix in COMPATIBILITY_MATRICES
    ]


def build_contract_reference(
    examples: Iterable[Mapping[str, Any]] = PUBLICATION_EXAMPLES,
) -> dict[str, Any]:
    """Build the complete publishable inventory after executable validation."""

    matrix_versions = {
        version
        for matrix in COMPATIBILITY_MATRICES
        for version in matrix.supported_contract_versions
    }
    schema_versions = set(SUPPORTED_SCHEMA_VERSIONS)
    if matrix_versions != schema_versions:
        raise ValueError(
            "compatibility matrix and canonical schema versions differ: "
            f"matrix={sorted(matrix_versions)}, schemas={sorted(schema_versions)}"
        )

    validated_examples = validate_publication_examples(examples)
    contracts = []
    for version in SUPPORTED_SCHEMA_VERSIONS:
        schemas = {
            operation: schema_for(version, operation).model_json_schema(
                mode="validation"
            )
            for operation in schema_operations(version)
        }
        contracts.append(
            {
                "contract_version": version,
                "documentation_version": DOCUMENTATION_VERSION,
                "mural_release_versions": [
                    matrix.mural_release_version
                    for matrix in COMPATIBILITY_MATRICES
                    if matrix.supports(version)
                ],
                "operations": [
                    {"schema": operation, **_OPERATION_DETAILS[operation]}
                    for operation in schema_operations(version)
                ],
                "schemas": schemas,
            }
        )

    profiles = []
    seen_profiles: set[tuple[str, str]] = set()
    for matrix in COMPATIBILITY_MATRICES:
        for profile in matrix.profiles:
            key = (matrix.matrix_version, profile.profile.value)
            if key not in seen_profiles:
                profiles.append(
                    {
                        "matrix_version": matrix.matrix_version,
                        **profile.model_dump(mode="json"),
                    }
                )
                seen_profiles.add(key)

    return _jsonable(
        {
            "documentation": {
                "version": DOCUMENTATION_VERSION,
                "published_at": DOCUMENTATION_PUBLISHED_AT,
                "experimental": True,
                "retention_rule": "Prior documentation versions and contract-version associations are retained.",
            },
            "contracts": contracts,
            "compatibility_matrices": _matrix_inventory(),
            "profiles": profiles,
            "authentication": AUTHENTICATION_METHODS,
            "timeouts": TIMEOUT_POLICIES,
            "retries": RETRY_CONDITIONS,
            "cancellation": CANCELLATION_RULES,
            "errors": [category.value for category in ErrorCategory],
            "ownership": OWNERSHIP_INVENTORY,
            "deployment_shapes": {
                "supported": "Remote chat-oriented services implementing a listed contract/profile and passing conformance.",
                "unsupported": (
                    "raw_phone_calls",
                    "raw_telephony_events",
                    "direct_pipecat_access",
                    "realtime_speech_to_speech",
                ),
            },
            "caller_visible_consequences": CALLER_VISIBLE_CONSEQUENCES,
            "operator_checklist": OPERATOR_CHECKLIST,
            "examples": validated_examples,
        }
    )


def render_contract_reference_json(reference: Mapping[str, Any]) -> str:
    return json.dumps(reference, indent=2, sort_keys=True) + "\n"


def render_contract_reference_mdx(reference: Mapping[str, Any]) -> str:
    """Render a concise Mintlify page backed by the machine-readable artifact."""

    contract_rows = "\n".join(
        f"| `{contract['contract_version']}` | `{contract['documentation_version']}` | "
        f"{', '.join(f'`{release}`' for release in contract['mural_release_versions'])} |"
        for contract in reference["contracts"]
    )
    profile_rows = "\n".join(
        f"| `{profile['profile']}` | {', '.join(f'`{mode}`' for mode in profile['required_invocation_modes'])} | "
        f"{', '.join(f'`{mode}`' for mode in profile['allowed_state_modes'])} |"
        for profile in reference["profiles"]
    )
    ownership_rows = "\n".join(
        f"| `{item['field']}` | `{item['owner']}` |" for item in reference["ownership"]
    )
    example_sections = []
    for example in reference["examples"]:
        payload = json.dumps(example["steps"], indent=2, sort_keys=True)
        example_sections.append(
            f"### {example['category'].title()} — contract {example['contract_version']}\n\n"
            f"Validated at `{example['validated_at']}`. Expected result: {example['expected_observable_result']}\n\n"
            f"```json\n{payload}\n```"
        )

    return f"""---
title: LangGraph contract reference
description: Generated version, profile, operation, policy, ownership, and executable example reference for remote reasoning endpoints.
---

<!-- Generated by python -m scripts.dump_langgraph_contract_reference. Do not edit manually. -->

This experimental integration accepts remote **chat-oriented** requests. It does not send phone calls, raw telephony events, audio, or Pipecat processor access. Realtime speech-to-speech workflows bypass this integration.

The complete generated schema and policy inventory is available in [`langgraph-contract-reference.json`](./generated/langgraph-contract-reference.json).

## Version associations

| Contract | Documentation | Mural releases |
| --- | --- | --- |
{contract_rows}

Prior contract versions remain present in this artifact when a compatible minor is added.

## Compatibility profiles

| Profile | Required invocation modes | Allowed state modes |
| --- | --- | --- |
{profile_rows}

Compatibility describes observable contract behavior, not support for every LangGraph package, server, cloud, or application version.

## Authentication and runtime policy

Every discovery, invocation, status, resume, cancellation, health, and callback operation uses the tenant-owned encrypted credential reference. Credentials never appear in examples or client-visible output. Timeouts, retry conditions, cancellation rules, error categories, complete JSON schemas, and compatibility matrix versions are generated in the linked JSON inventory.

## Ownership

| Field | Owner |
| --- | --- |
{ownership_rows}

## Caller-visible behavior

Slow first events apply the pinned fallback, transfer, or end-call action. Long-running tools can create silence until another text event. Asynchronous waits remain deadline-bounded. Endpoint errors apply the pinned terminal action without an unpinned fallback. Human-review pauses use the pinned Stateful Run policy.

## Operator checklist

Before rollout, verify endpoint reachability, credentials, tenant authorization, privacy policy, data region, latency, health, conformance, rollout, and rollback.

## Validated executable examples

Publication is blocked unless every example below validates against every contract version it claims.

{chr(10).join(example_sections)}
"""

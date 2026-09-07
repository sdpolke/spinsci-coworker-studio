from __future__ import annotations

from typing import Any, TypeVar

from pydantic import BaseModel

from . import v1_0, v1_1, v1_2

SUPPORTED_SCHEMA_VERSIONS = (v1_0.V1_0, v1_1.V1_1, v1_2.V1_2)

_SCHEMA_REGISTRY: dict[str, dict[str, type[BaseModel]]] = {
    "1.0": {
        "manifest": v1_0.CapabilityManifest,
        "invocation": v1_0.InvocationRequest,
        "synchronous_response": v1_0.SynchronousResponse,
        "asynchronous_acceptance": v1_0.AsynchronousAcceptance,
        "status": v1_0.StatusResponse,
        "runtime_event": v1_0.RuntimeEventEnvelope,
        "cancellation_request": v1_0.CancellationRequest,
        "cancellation_response": v1_0.CancellationResponse,
        "resume": v1_0.ResumeRequest,
        "health": v1_0.HealthResponse,
    },
    "1.1": {
        "manifest": v1_1.CapabilityManifest,
        "invocation": v1_1.InvocationRequest,
        "synchronous_response": v1_1.SynchronousResponse,
        "asynchronous_acceptance": v1_1.AsynchronousAcceptance,
        "status": v1_1.StatusResponse,
        "runtime_event": v1_1.RuntimeEventEnvelope,
        "cancellation_request": v1_1.CancellationRequest,
        "cancellation_response": v1_1.CancellationResponse,
        "resume": v1_1.ResumeRequest,
        "health": v1_1.HealthResponse,
    },
    "1.2": {
        "manifest": v1_2.CapabilityManifest,
        "invocation": v1_2.InvocationRequest,
        "synchronous_response": v1_2.SynchronousResponse,
        "asynchronous_acceptance": v1_2.AsynchronousAcceptance,
        "status": v1_2.StatusResponse,
        "runtime_event": v1_2.RuntimeEventEnvelope,
        "cancellation_request": v1_2.CancellationRequest,
        "cancellation_response": v1_2.CancellationResponse,
        "resume": v1_2.ResumeRequest,
        "health": v1_2.HealthResponse,
    },
}

ModelT = TypeVar("ModelT", bound=BaseModel)


def schema_for(version: str, operation: str) -> type[BaseModel]:
    try:
        return _SCHEMA_REGISTRY[version][operation]
    except KeyError as exc:
        raise ValueError(f"unsupported contract schema: {version}/{operation}") from exc


def schema_operations(version: str) -> tuple[str, ...]:
    """Return the canonical operation/schema names for a contract version."""

    try:
        return tuple(_SCHEMA_REGISTRY[version])
    except KeyError as exc:
        raise ValueError(f"unsupported contract version: {version}") from exc


def validate_payload(version: str, operation: str, payload: Any) -> BaseModel:
    return schema_for(version, operation).model_validate(payload)


__all__ = [
    "SUPPORTED_SCHEMA_VERSIONS",
    "schema_for",
    "schema_operations",
    "v1_0",
    "v1_1",
    "v1_2",
    "validate_payload",
]

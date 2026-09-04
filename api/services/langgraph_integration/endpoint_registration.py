"""Reusable orchestration for endpoint registration and lifecycle management."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit, urlunsplit

from api.db import db_client
from api.services.langgraph_integration.access_control import (
    LangGraphAuthorizationError,
    LangGraphPermission,
    LangGraphRole,
    is_langgraph_authorized,
)
from api.services.langgraph_integration.configuration import (
    get_langgraph_feature_configuration,
    invalidate_langgraph_credential_cache,
)
from api.services.langgraph_integration.lifecycle import (
    PASSING_REPORT_STATUSES,
    InvalidLifecycleTransition,
    require_transition,
)

KNOWN_CAPABILITIES = frozenset(
    {
        "synchronous",
        "streaming",
        "asynchronous",
        "mural_authoritative",
        "endpoint_checkpointed",
        "interrupts",
        "idempotent_invocations",
        "cancellation",
        "health",
    }
)


class FeatureDisabledError(RuntimeError):
    pass


class EndpointNotFoundError(LookupError):
    pass


class CredentialOwnershipError(PermissionError):
    pass


class InvalidEndpointConfiguration(ValueError):
    pass


class ActivationEvidenceError(ValueError):
    pass


def normalize_endpoint_url(value: str) -> str:
    if len(value) > 2048:
        raise InvalidEndpointConfiguration(
            "endpoint URL must contain at most 2048 characters"
        )
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise InvalidEndpointConfiguration(
            "endpoint URL must be an absolute HTTP(S) URL"
        )
    if parsed.username is not None or parsed.password is not None:
        raise InvalidEndpointConfiguration(
            "endpoint URL must not contain user information"
        )
    if parsed.query or parsed.fragment:
        raise InvalidEndpointConfiguration(
            "endpoint URL must not contain a query or fragment"
        )
    host = parsed.hostname.lower()
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    netloc = host
    if parsed.port is not None:
        netloc = f"{host}:{parsed.port}"
    path = parsed.path.rstrip("/")
    return urlunsplit((parsed.scheme.lower(), netloc, path, "", ""))


def validate_selected_capabilities(capabilities: list[str]) -> list[str]:
    unknown = sorted(set(capabilities) - KNOWN_CAPABILITIES)
    if unknown:
        raise InvalidEndpointConfiguration(
            f"unsupported selected capabilities: {', '.join(unknown)}"
        )
    return sorted(capabilities)


def require_permission(role: LangGraphRole, permission: LangGraphPermission) -> None:
    if not is_langgraph_authorized(role=role, permission=permission):
        raise LangGraphAuthorizationError(f"{role.value} lacks {permission.value}")


async def require_feature_enabled(organization_id: int) -> None:
    configuration = await get_langgraph_feature_configuration(organization_id)
    if not configuration.enabled:
        raise FeatureDisabledError(
            "LangGraph integration is disabled for this organization"
        )


async def create_endpoint(
    *,
    organization_id: int,
    actor_user_id: int,
    role: LangGraphRole,
    name: str,
    endpoint_url: str,
    credential_uuid: str,
    selected_profile: str,
    selected_capabilities: list[str],
):
    require_permission(role, LangGraphPermission.CREATE)
    await require_feature_enabled(organization_id)
    normalized_url = normalize_endpoint_url(endpoint_url)
    capabilities = validate_selected_capabilities(selected_capabilities)
    credential = await db_client.get_credential_by_uuid(
        credential_uuid, organization_id
    )
    if credential is None:
        raise CredentialOwnershipError("credential is not owned by organization")
    try:
        return await db_client.create_langgraph_endpoint(
            organization_id=organization_id,
            name=name,
            endpoint_url=normalized_url,
            credential_id=credential.id,
            selected_profile=selected_profile,
            selected_capabilities=capabilities,
            created_by=actor_user_id,
        )
    except PermissionError as exc:
        raise CredentialOwnershipError(str(exc)) from exc


async def update_endpoint(
    *,
    organization_id: int,
    endpoint_uuid: str,
    role: LangGraphRole,
    changes: dict[str, Any],
):
    require_permission(role, LangGraphPermission.UPDATE)
    await require_feature_enabled(organization_id)
    if changes.get("endpoint_url") is not None:
        changes["endpoint_url"] = normalize_endpoint_url(changes["endpoint_url"])
    if changes.get("selected_capabilities") is not None:
        changes["selected_capabilities"] = validate_selected_capabilities(
            changes["selected_capabilities"]
        )
    try:
        endpoint = await db_client.update_langgraph_endpoint(
            organization_id=organization_id,
            endpoint_uuid=endpoint_uuid,
            **changes,
        )
    except PermissionError as exc:
        raise CredentialOwnershipError(str(exc)) from exc
    if endpoint is None:
        raise EndpointNotFoundError("endpoint not found")
    if changes.get("credential_uuid") is not None:
        await invalidate_langgraph_credential_cache(organization_id)
    return endpoint


async def transition_endpoint(
    *,
    organization_id: int,
    endpoint_uuid: str,
    role: LangGraphRole,
    target_status: str,
    permission: LangGraphPermission,
):
    require_permission(role, permission)
    await require_feature_enabled(organization_id)
    endpoint = await db_client.get_langgraph_endpoint(
        organization_id=organization_id, endpoint_uuid=endpoint_uuid
    )
    if endpoint is None:
        raise EndpointNotFoundError("endpoint not found")
    if endpoint.lifecycle_status == target_status:
        return endpoint
    require_transition(endpoint.lifecycle_status, target_status)
    changed = await db_client.compare_and_set_langgraph_lifecycle(
        organization_id=organization_id,
        endpoint_uuid=endpoint_uuid,
        expected_status=endpoint.lifecycle_status,
        new_status=target_status,
    )
    if not changed:
        raise InvalidLifecycleTransition("endpoint lifecycle changed concurrently")
    return await db_client.get_langgraph_endpoint(
        organization_id=organization_id, endpoint_uuid=endpoint_uuid
    )


async def _dispatch_validation(organization_id: int, endpoint_uuid: str) -> None:
    # Lazy import avoids a circular import (arq imports task modules at load time,
    # matching the existing pattern in run_integrations.py).
    from api.tasks.arq import enqueue_job
    from api.tasks.function_names import FunctionNames

    await enqueue_job(
        FunctionNames.VALIDATE_LANGGRAPH_ENDPOINT,
        organization_id,
        endpoint_uuid,
        _job_id=f"langgraph_validate:{endpoint_uuid}",
    )


async def request_validation(
    *, organization_id: int, endpoint_uuid: str, role: LangGraphRole
):
    endpoint = await db_client.get_langgraph_endpoint(
        organization_id=organization_id, endpoint_uuid=endpoint_uuid
    )
    if endpoint is None:
        raise EndpointNotFoundError("endpoint not found")
    if endpoint.lifecycle_status == "pending_validation":
        require_permission(role, LangGraphPermission.VALIDATE)
        await require_feature_enabled(organization_id)
        await _dispatch_validation(organization_id, endpoint_uuid)
        return endpoint
    result = await transition_endpoint(
        organization_id=organization_id,
        endpoint_uuid=endpoint_uuid,
        role=role,
        target_status="pending_validation",
        permission=LangGraphPermission.VALIDATE,
    )
    await _dispatch_validation(organization_id, endpoint_uuid)
    return result


async def activate_endpoint(
    *, organization_id: int, endpoint_uuid: str, role: LangGraphRole
):
    require_permission(role, LangGraphPermission.ACTIVATE)
    await require_feature_enabled(organization_id)
    evidence = await db_client.get_current_langgraph_activation_evidence(
        organization_id=organization_id, endpoint_uuid=endpoint_uuid
    )
    if evidence is None:
        raise EndpointNotFoundError("endpoint not found")
    endpoint, report, snapshot = evidence
    if endpoint.lifecycle_status not in {
        "pending_validation",
        "validation_only",
        "degraded",
    }:
        require_transition(endpoint.lifecycle_status, "active")
    if report is None or snapshot is None:
        raise ActivationEvidenceError("current validation evidence is required")
    if report.status not in PASSING_REPORT_STATUSES or report.completed_at is None:
        raise ActivationEvidenceError("current validation report is not passing")
    if report.capability_snapshot_id != snapshot.id:
        raise ActivationEvidenceError(
            "validation report does not cover current capabilities"
        )
    if report.selected_profile != endpoint.selected_profile:
        raise ActivationEvidenceError(
            "validation report does not cover selected profile"
        )
    if endpoint.lifecycle_status == "degraded" and not report.evidence.get(
        "current_health_healthy", False
    ):
        raise ActivationEvidenceError("current successful health evidence is required")
    changed = await db_client.compare_and_set_langgraph_lifecycle(
        organization_id=organization_id,
        endpoint_uuid=endpoint_uuid,
        expected_status=endpoint.lifecycle_status,
        new_status="active",
    )
    if not changed:
        raise InvalidLifecycleTransition("endpoint lifecycle changed concurrently")
    return await db_client.get_langgraph_endpoint(
        organization_id=organization_id, endpoint_uuid=endpoint_uuid
    )


async def delete_or_retire_endpoint(
    *, organization_id: int, endpoint_uuid: str, role: LangGraphRole
) -> str:
    require_permission(role, LangGraphPermission.DELETE)
    await require_feature_enabled(organization_id)
    outcome = await db_client.retire_or_delete_langgraph_endpoint(
        organization_id=organization_id, endpoint_uuid=endpoint_uuid
    )
    if outcome is None:
        raise EndpointNotFoundError("endpoint not found")
    return outcome

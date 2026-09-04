"""Tenant-scoped LangGraph endpoint registration and lifecycle APIs."""

from datetime import UTC, datetime
from typing import Annotated, Any, Never

from fastapi import APIRouter, Depends, HTTPException, status

from api.constants import DEPLOYMENT_MODE
from api.db import db_client
from api.db.models import UserModel
from api.schemas.langgraph_integration.endpoints import (
    CapabilitySnapshotSummary,
    CompatibilityMatrixResponse,
    CredentialProjection,
    DeleteEndpointResponse,
    EndpointCreateRequest,
    EndpointResponse,
    EndpointUpdateRequest,
    LangGraphFeatureStatusResponse,
    LangGraphFeatureUpdateRequest,
    LifecycleActionResponse,
    RunDiagnosticEventResponse,
    RunDiagnosticsResponse,
    ValidationReportResponse,
    ValidationResultResponse,
)
from api.services.auth.depends import get_user
from api.services.langgraph_integration.access_control import (
    LangGraphAuthorizationError,
    LangGraphPermission,
    LangGraphRole,
    is_langgraph_authorized,
)
from api.services.langgraph_integration.configuration import (
    LangGraphFeatureConfiguration,
    get_langgraph_feature_configuration,
    update_langgraph_feature_configuration,
)
from api.services.langgraph_integration.endpoint_registration import (
    ActivationEvidenceError,
    CredentialOwnershipError,
    EndpointNotFoundError,
    FeatureDisabledError,
    InvalidEndpointConfiguration,
    activate_endpoint,
    create_endpoint,
    delete_or_retire_endpoint,
    request_validation,
    require_permission,
    transition_endpoint,
    update_endpoint,
)
from api.services.langgraph_integration.lifecycle import InvalidLifecycleTransition

router = APIRouter(tags=["langgraph-endpoints"])
User = Annotated[UserModel, Depends(get_user)]
ROUTE_ERRORS = (
    LangGraphAuthorizationError,
    FeatureDisabledError,
    CredentialOwnershipError,
    EndpointNotFoundError,
    ValueError,
)


def _organization_id(user: UserModel) -> int:
    if not user.selected_organization_id:
        raise HTTPException(status_code=400, detail="No organization selected for the user")
    return user.selected_organization_id


def _role(user: UserModel) -> LangGraphRole:
    """Resolve the integration role supplied by the authentication adapter.

    Current authentication providers expose organization membership but no role
    column. They therefore retain administrator-compatible behavior until a
    provider supplies the separately testable ``langgraph_role`` attribute.
    """
    value = getattr(user, "langgraph_role", LangGraphRole.ORGANIZATION_ADMIN.value)
    try:
        return LangGraphRole(value)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail="Invalid LangGraph role") from exc


def _raise_http(exc: Exception) -> Never:
    if isinstance(exc, LangGraphAuthorizationError):
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    if isinstance(exc, FeatureDisabledError):
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    if isinstance(exc, CredentialOwnershipError):
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    if isinstance(exc, EndpointNotFoundError):
        raise HTTPException(status_code=404, detail="Endpoint not found") from exc
    if isinstance(
        exc,
        (
            InvalidEndpointConfiguration,
            InvalidLifecycleTransition,
            ActivationEvidenceError,
            ValueError,
        ),
    ):
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    raise HTTPException(status_code=500, detail="Unexpected endpoint error") from exc


def _endpoint_response(view: tuple[Any, Any, Any, Any]) -> EndpointResponse:
    endpoint, credential, snapshot, report = view
    snapshot_summary = None
    if snapshot is not None:
        snapshot_summary = CapabilitySnapshotSummary(
            snapshot_uuid=snapshot.snapshot_uuid,
            manifest_digest=snapshot.manifest_digest,
            schema_version=snapshot.schema_version,
            manifest=snapshot.manifest,
            discovered_at=snapshot.discovered_at,
        )
    return EndpointResponse(
        endpoint_uuid=endpoint.endpoint_uuid,
        name=endpoint.name,
        endpoint_url=endpoint.endpoint_url,
        selected_profile=endpoint.selected_profile,
        selected_capabilities=endpoint.selected_capabilities,
        lifecycle_status=endpoint.lifecycle_status,
        credential=CredentialProjection(
            credential_type=credential.credential_type,
            reference_id=credential.credential_uuid,
            last_updated_at=credential.updated_at,
        ),
        current_validation_report_uuid=report.report_uuid if report else None,
        current_capability_snapshot=snapshot_summary,
        private_network_enabled=endpoint.private_network_enabled,
        created_at=endpoint.created_at,
        updated_at=endpoint.updated_at,
        retired_at=endpoint.retired_at,
    )


async def _load_response(organization_id: int, endpoint_uuid: str) -> EndpointResponse:
    view = await db_client.get_langgraph_endpoint_management_view(
        organization_id=organization_id, endpoint_uuid=endpoint_uuid
    )
    if view is None:
        raise HTTPException(status_code=404, detail="Endpoint not found")
    return _endpoint_response(view)


@router.post(
    "/langgraph-endpoints",
    response_model=EndpointResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_langgraph_endpoint(request: EndpointCreateRequest, user: User):
    organization_id = _organization_id(user)
    try:
        endpoint = await create_endpoint(
            organization_id=organization_id,
            actor_user_id=user.id,
            role=_role(user),
            name=request.name,
            endpoint_url=str(request.endpoint_url),
            credential_uuid=request.credential_uuid,
            selected_profile=request.selected_profile.value,
            selected_capabilities=request.selected_capabilities,
        )
    except ROUTE_ERRORS as exc:
        _raise_http(exc)
    return await _load_response(organization_id, endpoint.endpoint_uuid)


@router.get("/langgraph-endpoints", response_model=list[EndpointResponse])
async def list_langgraph_endpoints(user: User):
    organization_id = _organization_id(user)
    try:
        require_permission(_role(user), LangGraphPermission.LIST)
    except ROUTE_ERRORS as exc:
        _raise_http(exc)
    views = await db_client.list_langgraph_endpoint_management_views(
        organization_id=organization_id
    )
    return [_endpoint_response(view) for view in views]


@router.get("/langgraph-endpoints/{endpoint_uuid}", response_model=EndpointResponse)
async def get_langgraph_endpoint(endpoint_uuid: str, user: User):
    organization_id = _organization_id(user)
    try:
        require_permission(_role(user), LangGraphPermission.READ)
    except ROUTE_ERRORS as exc:
        _raise_http(exc)
    return await _load_response(organization_id, endpoint_uuid)


@router.patch("/langgraph-endpoints/{endpoint_uuid}", response_model=EndpointResponse)
async def update_langgraph_endpoint(
    endpoint_uuid: str, request: EndpointUpdateRequest, user: User
):
    organization_id = _organization_id(user)
    changes = request.model_dump(exclude_unset=True, mode="json")
    try:
        await update_endpoint(
            organization_id=organization_id,
            endpoint_uuid=endpoint_uuid,
            role=_role(user),
            changes=changes,
        )
    except ROUTE_ERRORS as exc:
        _raise_http(exc)
    return await _load_response(organization_id, endpoint_uuid)


@router.delete(
    "/langgraph-endpoints/{endpoint_uuid}", response_model=DeleteEndpointResponse
)
async def delete_langgraph_endpoint(endpoint_uuid: str, user: User):
    organization_id = _organization_id(user)
    try:
        outcome = await delete_or_retire_endpoint(
            organization_id=organization_id,
            endpoint_uuid=endpoint_uuid,
            role=_role(user),
        )
    except ROUTE_ERRORS as exc:
        _raise_http(exc)
    return DeleteEndpointResponse(endpoint_uuid=endpoint_uuid, outcome=outcome)


@router.post(
    "/langgraph-endpoints/{endpoint_uuid}/validate",
    response_model=LifecycleActionResponse,
)
async def validate_langgraph_endpoint(endpoint_uuid: str, user: User):
    organization_id = _organization_id(user)
    try:
        endpoint = await request_validation(
            organization_id=organization_id,
            endpoint_uuid=endpoint_uuid,
            role=_role(user),
        )
    except ROUTE_ERRORS as exc:
        _raise_http(exc)
    return LifecycleActionResponse(
        endpoint_uuid=endpoint.endpoint_uuid,
        lifecycle_status=endpoint.lifecycle_status,
    )


@router.post(
    "/langgraph-endpoints/{endpoint_uuid}/activate",
    response_model=LifecycleActionResponse,
)
async def activate_langgraph_endpoint(endpoint_uuid: str, user: User):
    organization_id = _organization_id(user)
    try:
        endpoint = await activate_endpoint(
            organization_id=organization_id,
            endpoint_uuid=endpoint_uuid,
            role=_role(user),
        )
    except ROUTE_ERRORS as exc:
        _raise_http(exc)
    return LifecycleActionResponse(
        endpoint_uuid=endpoint.endpoint_uuid,
        lifecycle_status=endpoint.lifecycle_status,
    )


@router.post(
    "/langgraph-endpoints/{endpoint_uuid}/deactivate",
    response_model=LifecycleActionResponse,
)
async def deactivate_langgraph_endpoint(endpoint_uuid: str, user: User):
    organization_id = _organization_id(user)
    try:
        endpoint = await transition_endpoint(
            organization_id=organization_id,
            endpoint_uuid=endpoint_uuid,
            role=_role(user),
            target_status="disabled",
            permission=LangGraphPermission.DEACTIVATE,
        )
    except ROUTE_ERRORS as exc:
        _raise_http(exc)
    return LifecycleActionResponse(
        endpoint_uuid=endpoint.endpoint_uuid,
        lifecycle_status=endpoint.lifecycle_status,
    )


@router.get(
    "/langgraph-endpoints/{endpoint_uuid}/validation-reports",
    response_model=list[ValidationReportResponse],
)
async def list_langgraph_validation_reports(endpoint_uuid: str, user: User):
    organization_id = _organization_id(user)
    try:
        require_permission(_role(user), LangGraphPermission.READ)
    except ROUTE_ERRORS as exc:
        _raise_http(exc)
    history = await db_client.list_langgraph_validation_history(
        organization_id=organization_id, endpoint_uuid=endpoint_uuid
    )
    if history is None:
        raise HTTPException(status_code=404, detail="Endpoint not found")
    return [
        ValidationReportResponse(
            report_uuid=report.report_uuid,
            capability_snapshot_uuid=(snapshot.snapshot_uuid if snapshot else None),
            matrix_version=matrix.matrix_version,
            suite_version=report.suite_version,
            contract_version=report.contract_version,
            selected_profile=report.selected_profile,
            status=report.status,
            started_at=report.started_at,
            completed_at=report.completed_at,
            evidence=report.evidence,
            report_digest=report.report_digest,
            created_at=report.created_at,
            results=[
                ValidationResultResponse(
                    test_identifier=result.test_identifier,
                    test_version=result.test_version,
                    required=result.required,
                    outcome=result.outcome,
                    duration_ms=result.duration_ms,
                    measurements=result.measurements,
                    redacted_error=result.redacted_error,
                )
                for result in results
            ],
        )
        for report, snapshot, matrix, results in history
    ]


@router.get(
    "/langgraph-compatibility-matrices",
    response_model=list[CompatibilityMatrixResponse],
)
async def list_langgraph_compatibility_matrices(user: User):
    _organization_id(user)
    matrices = await db_client.list_langgraph_compatibility_matrices()
    return [
        CompatibilityMatrixResponse(
            matrix_uuid=matrix.matrix_uuid,
            matrix_version=matrix.matrix_version,
            effective_at=matrix.effective_at,
            mural_release_version=matrix.mural_release_version,
            matrix=matrix.matrix,
            published_at=matrix.published_at,
            current=index == 0,
        )
        for index, matrix in enumerate(matrices)
    ]


_SENSITIVE_DIAGNOSTIC_KEYS = frozenset(
    {
        "authorization",
        "credential",
        "credentials",
        "secret",
        "token",
        "api_key",
        "prompt",
        "transcript",
        "arguments",
        "result",
        "checkpoint",
        "checkpoint_reference",
    }
)


def _redact_diagnostic_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): (
                "[REDACTED]"
                if str(key).lower() in _SENSITIVE_DIAGNOSTIC_KEYS
                else _redact_diagnostic_value(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact_diagnostic_value(item) for item in value[:100]]
    if isinstance(value, str):
        return value if len(value) <= 512 else f"{value[:509]}..."
    return value


def _diagnostic_timestamp(value: Any, fallback: datetime) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
        except ValueError:
            pass
    return fallback


def _feature_status_response(
    configuration: LangGraphFeatureConfiguration, *, role: LangGraphRole
) -> LangGraphFeatureStatusResponse:
    return LangGraphFeatureStatusResponse(
        enabled=configuration.enabled,
        acknowledged=configuration.experimental_acknowledged_at is not None,
        rollout_stage=configuration.rollout_stage,
        can_configure=is_langgraph_authorized(
            role=role, permission=LangGraphPermission.CONFIGURE_FEATURE
        ),
        private_network_configurable=DEPLOYMENT_MODE == "oss",
        private_network_enabled=configuration.private_network_enabled,
    )


@router.get("/langgraph-feature", response_model=LangGraphFeatureStatusResponse)
async def get_langgraph_feature_status(user: User):
    organization_id = _organization_id(user)
    role = _role(user)
    configuration = await get_langgraph_feature_configuration(organization_id)
    return _feature_status_response(configuration, role=role)


@router.patch("/langgraph-feature", response_model=LangGraphFeatureStatusResponse)
async def update_langgraph_feature_status(
    request: LangGraphFeatureUpdateRequest, user: User
):
    organization_id = _organization_id(user)
    role = _role(user)
    try:
        require_permission(role, LangGraphPermission.CONFIGURE_FEATURE)
        configuration = await update_langgraph_feature_configuration(
            organization_id=organization_id,
            actor_user_id=user.id,
            enabled=request.enabled,
            acknowledged=request.experimental_risk_acknowledged,
            private_network_enabled=request.private_network_enabled,
            private_network_risk_acknowledged=(
                request.private_network_risk_acknowledged
            ),
        )
    except ROUTE_ERRORS as exc:
        _raise_http(exc)
    return _feature_status_response(configuration, role=role)


@router.get(
    "/workflow-runs/{workflow_run_id}/langgraph-diagnostics",
    response_model=RunDiagnosticsResponse,
)
async def get_langgraph_run_diagnostics(workflow_run_id: int, user: User):
    organization_id = _organization_id(user)
    bundle = await db_client.get_langgraph_run_diagnostics(
        organization_id=organization_id, workflow_run_id=workflow_run_id
    )
    # The same response is used for absent, non-LangGraph, and foreign-tenant runs.
    if bundle is None:
        raise HTTPException(status_code=404, detail="Run diagnostics not found")

    run, binding, registration, invocations, attempts, accepted_events, tools, observations, security_events, external_identifier_rows = bundle
    invocation_by_id = {invocation.id: invocation for invocation in invocations}
    timeline: list[tuple[datetime, int, RunDiagnosticEventResponse]] = []
    insertion_order = 0

    def add_event(
        *,
        occurred_at: datetime,
        category: str,
        title: str,
        event_id: str,
        invocation: Any = None,
        attempt_id: str | None = None,
        sequence: int | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        nonlocal insertion_order
        trace_id = invocation.trace_id if invocation is not None else None
        event = RunDiagnosticEventResponse(
            id=event_id,
            category=category,
            occurred_at=occurred_at,
            order=0,
            title=title,
            invocation_id=(invocation.invocation_uuid if invocation is not None else None),
            attempt_id=attempt_id,
            sequence=sequence,
            trace_id=trace_id,
            trace_url=(f"/traces/{trace_id}" if trace_id else None),
            details=_redact_diagnostic_value(details or {}),
        )
        timeline.append((occurred_at, insertion_order, event))
        insertion_order += 1

    logs = run.logs if isinstance(run.logs, dict) else {}
    pipecat_events = logs.get("realtime_feedback_events", [])
    if isinstance(pipecat_events, list):
        for index, event in enumerate(pipecat_events[:1000]):
            if not isinstance(event, dict):
                continue
            payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
            title = str(event.get("type") or "Pipecat event")
            category = "error" if "error" in title.lower() else "pipecat"
            add_event(
                occurred_at=_diagnostic_timestamp(event.get("timestamp"), run.created_at),
                category=category,
                title=title,
                event_id=f"pipecat-{index}",
                details=payload,
            )

    for attempt in attempts:
        invocation = invocation_by_id.get(attempt.invocation_id)
        category = "error" if attempt.error_category else "attempt"
        add_event(
            occurred_at=attempt.dispatched_at,
            category=category,
            title=(f"Attempt {attempt.ordinal} dispatched" if not attempt.error_category else f"Attempt {attempt.ordinal} failed"),
            event_id=f"attempt-{attempt.attempt_uuid}",
            invocation=invocation,
            attempt_id=attempt.attempt_uuid,
            details={
                "http_status": attempt.http_status,
                "transport_outcome": attempt.transport_outcome,
                "accepted_event": attempt.accepted_event,
                "error_category": attempt.error_category,
            },
        )

    for accepted in accepted_events:
        invocation = invocation_by_id.get(accepted.invocation_id)
        add_event(
            occurred_at=accepted.accepted_at,
            category="error" if accepted.event_type == "error" else "runtime_event",
            title=f"Runtime event: {accepted.event_type}",
            event_id=f"runtime-{accepted.id}",
            invocation=invocation,
            sequence=accepted.sequence,
            details={
                "event_id": accepted.endpoint_event_id,
                "mutation_outcome": accepted.mutation_outcome,
                "metadata": accepted.metadata_json,
            },
        )

    for tool in tools:
        invocation = invocation_by_id.get(tool.invocation_id)
        is_transition = tool.transition_target is not None
        add_event(
            occurred_at=tool.created_at,
            category="transition" if is_transition else "tool_call",
            title=(f"Transition to {tool.transition_target}" if is_transition else f"Tool call: {tool.name}"),
            event_id=f"tool-{tool.id}",
            invocation=invocation,
            details={
                "tool_call_id": tool.tool_call_id,
                "name": tool.name,
                "authorization_outcome": tool.authorization_outcome,
                "execution_status": tool.execution_status,
                "transition_target": tool.transition_target,
            },
        )

    for observation in observations:
        invocation = invocation_by_id.get(observation.invocation_id)
        add_event(
            occurred_at=datetime.fromtimestamp(observation.observed_at_ms / 1000, tz=UTC),
            category="observation",
            title=f"Observation: {observation.observation_type}",
            event_id=f"observation-{observation.id}",
            invocation=invocation,
            sequence=observation.runtime_sequence,
            details={
                "monotonic_order": observation.monotonic_order,
                "attributes": observation.attributes,
            },
        )

    for security_event in security_events:
        invocation = invocation_by_id.get(security_event.invocation_id)
        add_event(
            occurred_at=security_event.created_at,
            category="security",
            title=f"Security enforcement: {security_event.violation_category}",
            event_id=f"security-{security_event.id}",
            invocation=invocation,
            details={
                "tool_call_id": security_event.tool_call_id,
                "tool_name": security_event.tool_name,
                "violation_category": security_event.violation_category,
                "enforcement_decision": security_event.enforcement_decision,
            },
        )

    timeline.sort(key=lambda item: (item[0], item[1]))
    ordered_events = [event.model_copy(update={"order": index}) for index, (_, _, event) in enumerate(timeline)]
    return RunDiagnosticsResponse(
        workflow_run_id=run.id,
        endpoint_registration_uuid=registration.endpoint_uuid,
        contract_version=binding.contract_version,
        compatibility_profile=binding.compatibility_profile,
        state_mode=binding.state_mode,
        external_identifiers=_redact_diagnostic_value(binding.external_identifiers or {}),
        external_identifier_traces=[
            {
                "identifier_type": row.identifier_type,
                "trace_id": row.trace_id,
                "trace_url": f"/traces/{row.trace_id}",
            }
            for row in external_identifier_rows
        ],
        events=ordered_events,
    )

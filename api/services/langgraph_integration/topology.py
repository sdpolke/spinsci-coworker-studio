"""Secure retrieval and version-pinning of external endpoint topology."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, replace
from typing import Any, Literal
from uuid import uuid4

import httpx
from pydantic import ValidationError

from api.db.workflow_client import (
    ImmutableWorkflowDefinitionError,
    WorkflowDefinitionConfigurationConflictError,
)
from api.schemas.langgraph_integration import v1_2
from api.schemas.langgraph_integration.common import ErrorCategory
from api.schemas.langgraph_topology import (
    BindingUpdateStage,
    DraftBindingState,
    DraftBindingStatus,
    TopologyActionAvailability,
    TopologyLifecycleStages,
    TopologyReasonCode,
    TopologyRefreshStage,
    ValidationStage,
)
from api.schemas.workflow_configurations import (
    LangGraphEndpointBinding,
    LangGraphTopologySnapshot,
)
from api.services.langgraph_integration.gateway import (
    DatabaseCredentialResolver,
    GatewayTraceContext,
    IntegrationGateway,
    RuntimeEndpointSnapshot,
    UnsafeDestinationError,
)
from api.services.langgraph_integration.protocol import (
    ProtocolViolation,
    canonical_digest,
)
from api.services.workflow.langgraph_binding import (
    LangGraphBindingCompatibilityError,
    build_candidate_langgraph_binding,
    classify_langgraph_draft_binding,
)


class TopologyDefinitionNotFoundError(LookupError):
    """The selected workflow definition is unavailable in the active tenant."""


@dataclass(frozen=True)
class TopologyResult:
    status: Literal["available", "unavailable"]
    reason: TopologyReasonCode | None = None
    topology: v1_2.EndpointTopology | None = None
    digest: str | None = None
    endpoint_binding_revision: str | None = None
    binding_status: DraftBindingStatus | None = None
    actions: TopologyActionAvailability | None = None
    stages: TopologyLifecycleStages | None = None


def unavailable(
    reason: TopologyReasonCode,
    *,
    binding_status: DraftBindingStatus | None = None,
    actions: TopologyActionAvailability | None = None,
    stages: TopologyLifecycleStages | None = None,
) -> TopologyResult:
    """Return a non-fatal state suitable for the separate topology UI."""
    return TopologyResult(
        status="unavailable",
        reason=reason,
        binding_status=binding_status,
        actions=actions,
        stages=stages,
    )


def snapshot_from_binding(binding: LangGraphEndpointBinding) -> TopologyResult | None:
    snapshot = binding.topology_snapshot
    if snapshot is None:
        return None
    try:
        topology = v1_2.EndpointTopology.model_validate(snapshot.topology)
    except ValidationError:
        return unavailable(TopologyReasonCode.SNAPSHOT_INVALID)
    if snapshot.endpoint_binding_revision != binding.capability_snapshot_uuid:
        return unavailable(TopologyReasonCode.SNAPSHOT_BINDING_MISMATCH)
    if snapshot.digest != canonical_digest(topology):
        return unavailable(TopologyReasonCode.SNAPSHOT_DIGEST_MISMATCH)
    return TopologyResult(
        status="available",
        topology=topology,
        digest=snapshot.digest,
        endpoint_binding_revision=snapshot.endpoint_binding_revision,
    )


def runtime_snapshot(
    *,
    organization_id: int,
    binding: LangGraphEndpointBinding,
    private_network_enabled: bool,
) -> RuntimeEndpointSnapshot:
    limits = binding.limits
    return RuntimeEndpointSnapshot(
        organization_id=organization_id,
        registration_id=binding.registration_uuid,
        endpoint_url=binding.endpoint_url,
        credential_reference=binding.credential_reference,
        contract_version=binding.contract_version,
        invocation_modes=frozenset(),
        operations=binding.operations,
        request_bytes=int(limits.get("request_bytes", 1_048_576)),
        response_bytes=int(limits.get("response_bytes", 2_097_152)),
        event_bytes=int(limits.get("event_bytes", 65_536)),
        tool_argument_bytes=int(limits.get("tool_argument_bytes", 262_144)),
        private_network_enabled=private_network_enabled,
    )


def _actions_for_status(
    status: DraftBindingStatus,
    *,
    can_revalidate: bool,
    can_update_binding: bool,
    can_refresh_topology: bool,
) -> TopologyActionAvailability:
    immutable = status.state == DraftBindingState.IMMUTABLE_SNAPSHOT_ONLY
    return TopologyActionAvailability(
        can_revalidate=(
            can_revalidate
            and status.state
            in {
                DraftBindingState.ENDPOINT_UNAVAILABLE,
                DraftBindingState.ENDPOINT_REVALIDATION_REQUIRED,
                DraftBindingState.ENDPOINT_VALIDATION_FAILED,
            }
        ),
        can_update_binding=(
            can_update_binding and status.state == DraftBindingState.BINDING_STALE
        ),
        can_refresh_topology=(
            can_refresh_topology and status.state == DraftBindingState.BINDING_CURRENT
        ),
        immutable=immutable,
    )


def _stages_for_status(status: DraftBindingStatus) -> TopologyLifecycleStages:
    if status.state == DraftBindingState.ENDPOINT_VALIDATION_FAILED:
        validation = ValidationStage.FAILED
    elif status.state in {
        DraftBindingState.ENDPOINT_UNAVAILABLE,
        DraftBindingState.ENDPOINT_REVALIDATION_REQUIRED,
    }:
        validation = ValidationStage.REQUIRED
    elif status.state in {
        DraftBindingState.TOPOLOGY_UNSUPPORTED,
        DraftBindingState.BINDING_STALE,
        DraftBindingState.BINDING_CURRENT,
    }:
        validation = ValidationStage.PASSED
    else:
        validation = ValidationStage.NOT_REQUIRED
    return TopologyLifecycleStages(validation=validation)


def _updated_stages(
    stages: TopologyLifecycleStages,
    *,
    binding_update: BindingUpdateStage | None = None,
    topology_refresh: TopologyRefreshStage | None = None,
) -> TopologyLifecycleStages:
    updates: dict[str, Any] = {}
    if binding_update is not None:
        updates["binding_update"] = binding_update
    if topology_refresh is not None:
        updates["topology_refresh"] = topology_refresh
    return stages.model_copy(update=updates)


def _binding_from_definition(definition: Any) -> LangGraphEndpointBinding | None:
    try:
        return LangGraphEndpointBinding.model_validate(
            (definition.workflow_configurations or {}).get("langgraph_endpoint")
        )
    except ValidationError:
        return None


def _preserved_result(
    binding: LangGraphEndpointBinding | None,
    *,
    reason: TopologyReasonCode,
    binding_status: DraftBindingStatus,
    actions: TopologyActionAvailability,
    stages: TopologyLifecycleStages,
) -> TopologyResult:
    pinned = snapshot_from_binding(binding) if binding is not None else None
    if pinned is None:
        return unavailable(
            reason,
            binding_status=binding_status,
            actions=actions,
            stages=stages,
        )
    return replace(
        pinned,
        reason=reason,
        binding_status=binding_status,
        actions=actions,
        stages=stages,
    )


def _missing_snapshot_reason(
    binding_status: DraftBindingStatus,
) -> TopologyReasonCode:
    """Explain why no snapshot is pinned using the most actionable known cause.

    ``snapshot_unavailable`` tells the caller to update or refresh the draft, which
    is only true advice when the binding is otherwise current. For every other
    state the classifier already knows the blocking cause (for example
    ``topology_unsupported``), and reporting ``snapshot_unavailable`` instead would
    point the caller at an action the response does not offer.
    """
    if binding_status.state == DraftBindingState.BINDING_CURRENT:
        return TopologyReasonCode.SNAPSHOT_UNAVAILABLE
    if binding_status.state == DraftBindingState.IMMUTABLE_SNAPSHOT_ONLY:
        return TopologyReasonCode.SNAPSHOT_REQUIRED_FOR_IMMUTABLE_VERSION
    return binding_status.reason or TopologyReasonCode.SNAPSHOT_UNAVAILABLE


async def topology_for_definition(
    *,
    organization_id: int,
    definition: Any,
    db_client: Any,
    can_revalidate: bool = False,
    can_update_binding: bool = False,
    can_refresh_topology: bool = False,
) -> TopologyResult:
    """Read pinned topology and classify a draft without changing any state."""
    binding = _binding_from_definition(definition)
    binding_status = await classify_langgraph_draft_binding(
        organization_id=organization_id,
        definition=definition,
        db_client=db_client,
    )
    actions = _actions_for_status(
        binding_status,
        can_revalidate=can_revalidate,
        can_update_binding=can_update_binding,
        can_refresh_topology=can_refresh_topology,
    )
    stages = _stages_for_status(binding_status)
    pinned = snapshot_from_binding(binding) if binding is not None else None
    if pinned is None:
        return unavailable(
            _missing_snapshot_reason(binding_status),
            binding_status=binding_status,
            actions=actions,
            stages=stages,
        )
    return replace(
        pinned,
        binding_status=binding_status,
        actions=actions,
        stages=stages,
    )


def _gateway_failure_reason(exc: Exception) -> TopologyReasonCode:
    if isinstance(exc, PermissionError):
        return TopologyReasonCode.TOPOLOGY_AUTH_FAILED
    if isinstance(exc, ProtocolViolation):
        if exc.category in {
            ErrorCategory.AUTHENTICATION,
            ErrorCategory.AUTHORIZATION,
        }:
            return TopologyReasonCode.TOPOLOGY_AUTH_FAILED
        if exc.category in {
            ErrorCategory.TIMEOUT,
            ErrorCategory.OVERLOADED,
            ErrorCategory.RATE_LIMITED,
        }:
            return TopologyReasonCode.TOPOLOGY_NETWORK_FAILED
        return TopologyReasonCode.TOPOLOGY_SCHEMA_INVALID
    if isinstance(
        exc,
        (UnsafeDestinationError, httpx.HTTPError, TimeoutError, OSError),
    ):
        return TopologyReasonCode.TOPOLOGY_NETWORK_FAILED
    return TopologyReasonCode.TOPOLOGY_UNAVAILABLE


def _current_status(
    binding: LangGraphEndpointBinding,
    previous: DraftBindingStatus,
) -> DraftBindingStatus:
    return DraftBindingStatus(
        state=DraftBindingState.BINDING_CURRENT,
        reason=TopologyReasonCode.BINDING_CURRENT,
        bound_validation_report_uuid=binding.validation_report_uuid,
        bound_capability_snapshot_uuid=binding.capability_snapshot_uuid,
        current_validation_report_uuid=(
            previous.current_validation_report_uuid
            or binding.validation_report_uuid
        ),
        current_capability_snapshot_uuid=(
            previous.current_capability_snapshot_uuid
            or binding.capability_snapshot_uuid
        ),
    )


async def _update_draft_topology(
    *,
    organization_id: int,
    workflow_id: int,
    definition_id: int,
    db_client: Any,
    private_network_enabled: bool,
    allow_binding_update: bool,
    can_revalidate: bool = False,
    can_update_binding: bool = False,
    can_refresh_topology: bool = True,
    gateway: IntegrationGateway | None = None,
) -> TopologyResult:
    definition = await db_client.get_workflow_definition(
        organization_id=organization_id,
        workflow_id=workflow_id,
        definition_id=definition_id,
    )
    if definition is None:
        raise TopologyDefinitionNotFoundError("workflow version not found")

    binding = _binding_from_definition(definition)
    binding_status = await classify_langgraph_draft_binding(
        organization_id=organization_id,
        definition=definition,
        db_client=db_client,
    )
    actions = _actions_for_status(
        binding_status,
        can_revalidate=can_revalidate,
        can_update_binding=can_update_binding,
        can_refresh_topology=can_refresh_topology,
    )
    stages = _stages_for_status(binding_status)

    if definition.status != "draft":
        return _preserved_result(
            binding,
            reason=TopologyReasonCode.SNAPSHOT_REQUIRED_FOR_IMMUTABLE_VERSION,
            binding_status=binding_status,
            actions=actions,
            stages=stages,
        )
    if binding is None:
        return unavailable(
            TopologyReasonCode.ENDPOINT_NOT_CONFIGURED,
            binding_status=binding_status,
            actions=actions,
            stages=stages,
        )

    chosen_binding = binding
    binding_will_change = binding_status.state == DraftBindingState.BINDING_STALE
    if binding_will_change:
        if not allow_binding_update:
            return _preserved_result(
                binding,
                reason=TopologyReasonCode.BINDING_STALE,
                binding_status=binding_status,
                actions=actions,
                stages=stages,
            )
        current = await db_client.get_current_langgraph_activation_evidence(
            organization_id=organization_id,
            endpoint_uuid=binding.registration_uuid,
        )
        if current is None:
            return _preserved_result(
                binding,
                reason=TopologyReasonCode.ENDPOINT_UNAVAILABLE,
                binding_status=binding_status,
                actions=actions,
                stages=_updated_stages(
                    stages, binding_update=BindingUpdateStage.FAILED
                ),
            )
        endpoint, report, snapshot = current
        try:
            chosen_binding = build_candidate_langgraph_binding(
                binding,
                endpoint=endpoint,
                report=report,
                snapshot=snapshot,
            )
        except LangGraphBindingCompatibilityError:
            return _preserved_result(
                binding,
                reason=TopologyReasonCode.BINDING_INCOMPATIBLE,
                binding_status=binding_status,
                actions=actions,
                stages=_updated_stages(
                    stages, binding_update=BindingUpdateStage.FAILED
                ),
            )
    elif binding_status.state != DraftBindingState.BINDING_CURRENT:
        reason = binding_status.reason or TopologyReasonCode.TOPOLOGY_UNAVAILABLE
        return _preserved_result(
            binding,
            reason=reason,
            binding_status=binding_status,
            actions=actions,
            stages=stages,
        )

    snapshot = runtime_snapshot(
        organization_id=organization_id,
        binding=chosen_binding,
        private_network_enabled=private_network_enabled,
    )
    gateway = gateway or IntegrationGateway(
        credential_resolver=DatabaseCredentialResolver(db_client)
    )
    active_stages = _updated_stages(
        stages,
        binding_update=(
            BindingUpdateStage.PENDING
            if binding_will_change
            else BindingUpdateStage.NOT_REQUIRED
        ),
        topology_refresh=TopologyRefreshStage.PENDING,
    )
    try:
        topology_payload = await gateway.fetch_topology(
            snapshot,
            view=v1_2.TopologyView.COLLAPSED,
            trace_context=GatewayTraceContext(
                organization_id=organization_id,
                registration_id=chosen_binding.registration_uuid,
                contract_version=chosen_binding.contract_version,
                trace_id=uuid4().hex,
                workflow_version_id=str(definition.id),
            ),
        )
        if topology_payload is None:
            return _preserved_result(
                binding,
                reason=TopologyReasonCode.TOPOLOGY_UNSUPPORTED,
                binding_status=binding_status,
                actions=actions,
                stages=_updated_stages(
                    active_stages,
                    binding_update=(
                        BindingUpdateStage.FAILED
                        if binding_will_change
                        else BindingUpdateStage.NOT_REQUIRED
                    ),
                    topology_refresh=TopologyRefreshStage.FAILED,
                ),
            )
        topology = v1_2.EndpointTopology.model_validate(topology_payload)
    except (ValidationError, ProtocolViolation, PermissionError, UnsafeDestinationError, httpx.HTTPError, TimeoutError, OSError, ValueError) as exc:
        return _preserved_result(
            binding,
            reason=_gateway_failure_reason(exc),
            binding_status=binding_status,
            actions=actions,
            stages=_updated_stages(
                active_stages,
                binding_update=(
                    BindingUpdateStage.FAILED
                    if binding_will_change
                    else BindingUpdateStage.NOT_REQUIRED
                ),
                topology_refresh=TopologyRefreshStage.FAILED,
            ),
        )

    digest = canonical_digest(topology)
    pinned_binding = chosen_binding.model_copy(
        update={
            "topology_snapshot": LangGraphTopologySnapshot(
                endpoint_binding_revision=chosen_binding.capability_snapshot_uuid,
                digest=digest,
                topology=topology.model_dump(mode="json"),
            )
        }
    )
    expected_configurations = deepcopy(definition.workflow_configurations or {})
    configurations = deepcopy(expected_configurations)
    configurations["langgraph_endpoint"] = pinned_binding.model_dump(
        mode="json", exclude_none=True
    )
    try:
        await db_client.update_draft_workflow_definition_configurations_conditionally(
            organization_id=organization_id,
            workflow_id=workflow_id,
            definition_id=definition_id,
            expected_binding_revision=binding.capability_snapshot_uuid,
            expected_workflow_configurations=expected_configurations,
            workflow_configurations=configurations,
        )
    except WorkflowDefinitionConfigurationConflictError:
        return _preserved_result(
            binding,
            reason=TopologyReasonCode.DRAFT_CHANGED,
            binding_status=binding_status,
            actions=actions,
            stages=_updated_stages(
                active_stages,
                binding_update=(
                    BindingUpdateStage.FAILED
                    if binding_will_change
                    else BindingUpdateStage.NOT_REQUIRED
                ),
                topology_refresh=TopologyRefreshStage.FAILED,
            ),
        )
    except ImmutableWorkflowDefinitionError:
        return _preserved_result(
            binding,
            reason=TopologyReasonCode.SNAPSHOT_REQUIRED_FOR_IMMUTABLE_VERSION,
            binding_status=binding_status,
            actions=actions.model_copy(
                update={
                    "immutable": True,
                    "can_update_binding": False,
                    "can_refresh_topology": False,
                }
            ),
            stages=_updated_stages(
                active_stages,
                binding_update=(
                    BindingUpdateStage.FAILED
                    if binding_will_change
                    else BindingUpdateStage.NOT_REQUIRED
                ),
                topology_refresh=TopologyRefreshStage.FAILED,
            ),
        )
    except ValueError:
        return _preserved_result(
            binding,
            reason=TopologyReasonCode.DRAFT_CHANGED,
            binding_status=binding_status,
            actions=actions,
            stages=_updated_stages(
                active_stages,
                binding_update=(
                    BindingUpdateStage.FAILED
                    if binding_will_change
                    else BindingUpdateStage.NOT_REQUIRED
                ),
                topology_refresh=TopologyRefreshStage.FAILED,
            ),
        )

    current_status = _current_status(pinned_binding, binding_status)
    current_actions = _actions_for_status(
        current_status,
        can_revalidate=can_revalidate,
        can_update_binding=can_update_binding,
        can_refresh_topology=can_refresh_topology,
    )
    return TopologyResult(
        status="available",
        topology=topology,
        digest=digest,
        endpoint_binding_revision=pinned_binding.capability_snapshot_uuid,
        binding_status=current_status,
        actions=current_actions,
        stages=TopologyLifecycleStages(
            validation=ValidationStage.PASSED,
            binding_update=(
                BindingUpdateStage.UPDATED
                if binding_will_change
                else BindingUpdateStage.NOT_REQUIRED
            ),
            topology_refresh=TopologyRefreshStage.PINNED,
        ),
    )


async def refresh_draft_topology(
    *,
    organization_id: int,
    workflow_id: int,
    definition_id: int,
    db_client: Any,
    private_network_enabled: bool,
    can_revalidate: bool = False,
    can_refresh_topology: bool = True,
    gateway: IntegrationGateway | None = None,
) -> TopologyResult:
    """Refresh topology only when the selected draft binding is already current."""
    return await _update_draft_topology(
        organization_id=organization_id,
        workflow_id=workflow_id,
        definition_id=definition_id,
        db_client=db_client,
        private_network_enabled=private_network_enabled,
        allow_binding_update=False,
        can_revalidate=can_revalidate,
        can_refresh_topology=can_refresh_topology,
        gateway=gateway,
    )


async def update_draft_binding_and_topology(
    *,
    organization_id: int,
    workflow_id: int,
    definition_id: int,
    db_client: Any,
    private_network_enabled: bool,
    can_revalidate: bool = False,
    can_update_binding: bool = True,
    can_refresh_topology: bool = True,
    gateway: IntegrationGateway | None = None,
) -> TopologyResult:
    """Explicitly adopt current passing evidence and atomically pin topology."""
    return await _update_draft_topology(
        organization_id=organization_id,
        workflow_id=workflow_id,
        definition_id=definition_id,
        db_client=db_client,
        private_network_enabled=private_network_enabled,
        allow_binding_update=True,
        can_revalidate=can_revalidate,
        can_update_binding=can_update_binding,
        can_refresh_topology=can_refresh_topology,
        gateway=gateway,
    )

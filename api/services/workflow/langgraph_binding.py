from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import ValidationError

from api.schemas.langgraph_topology import (
    DraftBindingState,
    DraftBindingStatus,
    TopologyReasonCode,
)
from api.schemas.workflow_configurations import (
    LangGraphEligibilityEvidence,
    LangGraphEndpointBinding,
)
from api.services.langgraph_integration.configuration import (
    get_langgraph_feature_configuration,
)
from api.services.langgraph_integration.endpoint_registration import (
    FeatureDisabledError,
)
from api.services.langgraph_integration.lifecycle import PASSING_REPORT_STATUSES


class LangGraphWorkflowBindingError(ValueError):
    """A draft endpoint binding is unsafe or no longer publication-eligible."""


class LangGraphFeatureDisabledError(RuntimeError):
    pass


_DIRECT_MEDIA_NAMES = frozenset(
    {
        "audio",
        "audio_input",
        "raw_audio",
        "audio_frames",
        "direct_audio",
        "direct_audio_required",
        "media_socket",
        "telephony_media_socket",
        "processor",
        "processor_access",
        "processor_access_required",
        "pipecat_processor",
    }
)


def _normalized_name(value: object) -> str:
    return str(value).strip().lower().replace("-", "_").replace(" ", "_")


def validate_langgraph_chat_boundary(binding: LangGraphEndpointBinding) -> None:
    """Reject endpoint requests that would cross Mural's text-only boundary."""
    requested = {
        _normalized_name(value) for value in binding.selected_capabilities
    }
    context_fields = binding.data_sharing_policy.get("context_fields", ())
    if isinstance(context_fields, (list, tuple, set, frozenset)):
        requested.update(_normalized_name(value) for value in context_fields)

    features = binding.capability_snapshot.get("features", {})
    if isinstance(features, Mapping):
        requested.update(
            _normalized_name(name) for name, enabled in features.items() if enabled
        )

    endpoint_owned = {
        _normalized_name(name)
        for name, owner in binding.ownership.items()
        if _normalized_name(owner) in {"endpoint", "langgraph_endpoint"}
    }
    prohibited = sorted((requested | endpoint_owned) & _DIRECT_MEDIA_NAMES)
    if prohibited:
        raise LangGraphWorkflowBindingError(
            "LangGraph chat endpoints cannot request raw audio, media sockets, "
            f"or Pipecat processor access: {', '.join(prohibited)}"
        )


async def validate_langgraph_runtime_path(
    *, workflow_configurations: Mapping[str, Any] | None, organization_id: int
) -> LangGraphEndpointBinding | None:
    """Reject endpoint-backed realtime speech-to-speech workflow paths."""
    binding = parse_langgraph_binding(workflow_configurations)
    if binding is None:
        return None

    from api.services.configuration.ai_model_configuration import (
        get_effective_ai_model_configuration_for_workflow,
    )

    configuration = await get_effective_ai_model_configuration_for_workflow(
        organization_id=organization_id,
        workflow_configurations=dict(workflow_configurations or {}),
    )
    if configuration.is_realtime and configuration.realtime is not None:
        raise LangGraphWorkflowBindingError(
            "LangGraph chat endpoints are unavailable for realtime speech-to-speech workflows"
        )
    return binding


def require_langgraph_feature_for_operation(*, enabled: bool, operation: str) -> None:
    if not enabled:
        raise LangGraphFeatureDisabledError(
            f"LangGraph integration is disabled; cannot {operation}"
        )


def live_eligibility_evidence_complete(
    evidence: LangGraphEligibilityEvidence | Mapping[str, Any],
    *,
    profile: str = "chat",
) -> bool:
    if not isinstance(evidence, LangGraphEligibilityEvidence):
        try:
            evidence = LangGraphEligibilityEvidence.model_validate(evidence)
        except ValidationError:
            return False
    if profile not in {"chat", "stateful_run"}:
        return False
    return evidence.complete_for(profile)


def parse_langgraph_binding(
    workflow_configurations: Mapping[str, Any] | None,
) -> LangGraphEndpointBinding | None:
    raw = (workflow_configurations or {}).get("langgraph_endpoint")
    if raw is None:
        return None
    try:
        binding = LangGraphEndpointBinding.model_validate(raw)
    except ValidationError as exc:
        raise LangGraphWorkflowBindingError(
            f"Invalid LangGraph endpoint binding: {exc.errors(include_url=False)}"
        ) from exc
    validate_langgraph_chat_boundary(binding)
    return binding


def _manifest_values(manifest: Mapping[str, Any], key: str) -> set[str]:
    value = manifest.get(key, ())
    return {str(item) for item in value} if isinstance(value, (list, tuple, set)) else set()


def validate_binding_against_evidence(
    binding: LangGraphEndpointBinding,
    *,
    endpoint: Any,
    report: Any,
    snapshot: Any,
) -> tuple[str, ...]:
    """Compare every mutable control-plane fact with the proposed immutable copy."""
    errors: list[str] = []
    if endpoint.lifecycle_status != "active":
        errors.append("endpoint registration is not active")
    if endpoint.endpoint_uuid != binding.registration_uuid:
        errors.append("registration identity does not match")
    if report is None or endpoint.current_validation_report_id != report.id:
        errors.append("current validation report is required")
    if snapshot is None or endpoint.current_capability_snapshot_id != snapshot.id:
        errors.append("current capability snapshot is required")
    if report is not None:
        if report.status not in PASSING_REPORT_STATUSES:
            errors.append("validation report is not live-voice eligible")
        if report.report_uuid != binding.validation_report_uuid:
            errors.append("validation report identity does not match")
        if report.report_digest != binding.validation_report_digest:
            errors.append("validation report digest does not match")
        if report.contract_version != binding.contract_version:
            errors.append("contract version does not match validation report")
        if report.selected_profile != binding.compatibility_profile:
            errors.append("compatibility profile does not match validation report")
        report_evidence = report.evidence or {}
        if report_evidence and not live_eligibility_evidence_complete(
            report_evidence, profile=binding.compatibility_profile
        ):
            errors.append("validation report lacks required live-eligibility evidence")
    if snapshot is not None:
        manifest = snapshot.manifest or {}
        if snapshot.snapshot_uuid != binding.capability_snapshot_uuid:
            errors.append("capability snapshot identity does not match")
        if snapshot.manifest_digest != binding.capability_snapshot_digest:
            errors.append("capability snapshot digest does not match")
        if manifest != binding.capability_snapshot:
            errors.append("capability snapshot payload does not match")
        if binding.contract_version not in _manifest_values(manifest, "contract_versions"):
            errors.append("contract version is not declared")
        if binding.compatibility_profile not in _manifest_values(
            manifest, "compatibility_profiles"
        ):
            errors.append("compatibility profile is not declared")
        modes = _manifest_values(manifest, "invocation_modes")
        selected_modes = {binding.live_invocation_mode, *binding.non_conversational_modes.values()}
        if not selected_modes <= modes:
            errors.append("invocation mode is not declared")
        if binding.state_mode not in _manifest_values(manifest, "state_modes"):
            errors.append("state mode is not declared")
        regions = _manifest_values(manifest, "data_regions")
        if binding.data_region not in regions:
            errors.append("data region is not declared")
        declared_capabilities = set(endpoint.selected_capabilities or ())
        if set(binding.selected_capabilities) != declared_capabilities:
            errors.append("selected capabilities do not exactly match registration")
    if endpoint.selected_profile != binding.compatibility_profile:
        errors.append("selected profile does not exactly match registration")
    expected_state_mode = (
        "endpoint_checkpointed"
        if binding.compatibility_profile == "stateful_run"
        else "mural_authoritative"
    )
    if binding.state_mode != expected_state_mode:
        errors.append(
            f"{binding.compatibility_profile} profile requires {expected_state_mode} state"
        )
    if not live_eligibility_evidence_complete(
        binding.evidence, profile=binding.compatibility_profile
    ):
        errors.append("workflow binding lacks complete live-eligibility evidence")
    if not binding.data_sharing_policy:
        errors.append("data-sharing policy is required")
    return tuple(dict.fromkeys(errors))


class LangGraphBindingCompatibilityError(LangGraphWorkflowBindingError):
    """Current endpoint evidence cannot safely replace a draft binding."""

    reason_code = TopologyReasonCode.BINDING_INCOMPATIBLE


def _binding_status(
    binding: LangGraphEndpointBinding,
    *,
    state: DraftBindingState,
    reason: TopologyReasonCode,
    report: Any | None = None,
    snapshot: Any | None = None,
) -> DraftBindingStatus:
    return DraftBindingStatus(
        state=state,
        reason=reason,
        bound_validation_report_uuid=binding.validation_report_uuid,
        bound_capability_snapshot_uuid=binding.capability_snapshot_uuid,
        current_validation_report_uuid=(
            getattr(report, "report_uuid", None) if report is not None else None
        ),
        current_capability_snapshot_uuid=(
            getattr(snapshot, "snapshot_uuid", None) if snapshot is not None else None
        ),
    )


def _manifest_supports_topology(snapshot: Any) -> bool:
    manifest = getattr(snapshot, "manifest", None)
    if not isinstance(manifest, Mapping):
        return False
    operations = manifest.get("operations")
    return (
        isinstance(operations, Mapping)
        and isinstance(operations.get("topology"), str)
        and bool(operations["topology"].strip())
    )


async def classify_langgraph_draft_binding(
    *,
    organization_id: int,
    definition: Any,
    db_client: Any,
) -> DraftBindingStatus:
    """Classify one binding without mutating workflow or endpoint state."""
    try:
        binding = parse_langgraph_binding(definition.workflow_configurations)
    except LangGraphWorkflowBindingError:
        binding = None
    if binding is None:
        return DraftBindingStatus(
            state=DraftBindingState.ENDPOINT_NOT_CONFIGURED,
            reason=TopologyReasonCode.ENDPOINT_NOT_CONFIGURED,
        )
    if definition.status != "draft":
        return _binding_status(
            binding,
            state=DraftBindingState.IMMUTABLE_SNAPSHOT_ONLY,
            reason=TopologyReasonCode.IMMUTABLE_SNAPSHOT_ONLY,
        )

    current = await db_client.get_current_langgraph_activation_evidence(
        organization_id=organization_id,
        endpoint_uuid=binding.registration_uuid,
    )
    if current is None:
        return _binding_status(
            binding,
            state=DraftBindingState.ENDPOINT_UNAVAILABLE,
            reason=TopologyReasonCode.ENDPOINT_UNAVAILABLE,
        )
    endpoint, report, snapshot = current
    if report is None or snapshot is None:
        return _binding_status(
            binding,
            state=DraftBindingState.ENDPOINT_REVALIDATION_REQUIRED,
            reason=TopologyReasonCode.ENDPOINT_REVALIDATION_REQUIRED,
            report=report,
            snapshot=snapshot,
        )
    report_covers_snapshot = (
        getattr(endpoint, "current_validation_report_id", None)
        == getattr(report, "id", None)
        and getattr(endpoint, "current_capability_snapshot_id", None)
        == getattr(snapshot, "id", None)
        and getattr(report, "capability_snapshot_id", None)
        == getattr(snapshot, "id", None)
    )
    if not report_covers_snapshot:
        return _binding_status(
            binding,
            state=DraftBindingState.ENDPOINT_REVALIDATION_REQUIRED,
            reason=TopologyReasonCode.ENDPOINT_REVALIDATION_REQUIRED,
            report=report,
            snapshot=snapshot,
        )
    if report.status not in PASSING_REPORT_STATUSES:
        state = (
            DraftBindingState.ENDPOINT_VALIDATION_FAILED
            if report.status == "failed"
            else DraftBindingState.ENDPOINT_REVALIDATION_REQUIRED
        )
        reason = (
            TopologyReasonCode.ENDPOINT_VALIDATION_FAILED
            if state == DraftBindingState.ENDPOINT_VALIDATION_FAILED
            else TopologyReasonCode.ENDPOINT_REVALIDATION_REQUIRED
        )
        return _binding_status(
            binding,
            state=state,
            reason=reason,
            report=report,
            snapshot=snapshot,
        )

    # Genuine current non-support takes precedence over stale bound evidence.
    if not _manifest_supports_topology(snapshot):
        return _binding_status(
            binding,
            state=DraftBindingState.TOPOLOGY_UNSUPPORTED,
            reason=TopologyReasonCode.TOPOLOGY_UNSUPPORTED,
            report=report,
            snapshot=snapshot,
        )

    evidence_matches = all(
        (
            binding.validation_report_uuid == report.report_uuid,
            binding.validation_report_digest == report.report_digest,
            binding.capability_snapshot_uuid == snapshot.snapshot_uuid,
            binding.capability_snapshot_digest == snapshot.manifest_digest,
        )
    )
    return _binding_status(
        binding,
        state=(
            DraftBindingState.BINDING_CURRENT
            if evidence_matches
            else DraftBindingState.BINDING_STALE
        ),
        reason=(
            TopologyReasonCode.BINDING_CURRENT
            if evidence_matches
            else TopologyReasonCode.BINDING_STALE
        ),
        report=report,
        snapshot=snapshot,
    )


def _manifest_mapping(manifest: Mapping[str, Any], key: str) -> dict[str, Any]:
    value = manifest.get(key, {})
    if not isinstance(value, Mapping):
        raise LangGraphBindingCompatibilityError(
            f"current capability snapshot has invalid {key} data; revalidate the endpoint"
        )
    return {str(name): item for name, item in value.items() if item is not None}


def build_candidate_langgraph_binding(
    binding: LangGraphEndpointBinding,
    *,
    endpoint: Any,
    report: Any,
    snapshot: Any,
) -> LangGraphEndpointBinding:
    """Build a detached candidate using only one current passing evidence set."""
    if endpoint.endpoint_uuid != binding.registration_uuid:
        raise LangGraphBindingCompatibilityError(
            "endpoint registration does not match the draft binding"
        )
    if endpoint.lifecycle_status != "active":
        raise LangGraphBindingCompatibilityError(
            "activate the endpoint before updating the draft binding"
        )
    if (
        endpoint.current_validation_report_id != report.id
        or endpoint.current_capability_snapshot_id != snapshot.id
        or getattr(report, "capability_snapshot_id", None) != snapshot.id
    ):
        raise LangGraphBindingCompatibilityError(
            "current validation report and capability snapshot do not form one evidence set; revalidate the endpoint"
        )
    if report.status not in PASSING_REPORT_STATUSES:
        raise LangGraphBindingCompatibilityError(
            "current endpoint validation is not passing; revalidate the endpoint"
        )
    if (
        endpoint.selected_profile != binding.compatibility_profile
        or report.selected_profile != binding.compatibility_profile
    ):
        raise LangGraphBindingCompatibilityError(
            "compatibility profile changed; explicitly reconfigure the workflow endpoint"
        )
    endpoint_capabilities = set(endpoint.selected_capabilities or ())
    bound_capabilities = set(binding.selected_capabilities)
    if endpoint_capabilities != bound_capabilities:
        raise LangGraphBindingCompatibilityError(
            "selected capabilities changed; explicitly reconfigure the workflow endpoint"
        )
    if "topology" in {
        _normalized_name(capability)
        for capability in endpoint_capabilities | bound_capabilities
    }:
        raise LangGraphBindingCompatibilityError(
            "topology is a manifest operation and cannot be a selected capability"
        )

    manifest = snapshot.manifest
    if not isinstance(manifest, Mapping):
        raise LangGraphBindingCompatibilityError(
            "current capability snapshot is invalid; revalidate the endpoint"
        )
    report_evidence = report.evidence or {}
    if not isinstance(report_evidence, Mapping):
        raise LangGraphBindingCompatibilityError(
            "current validation evidence is invalid; revalidate the endpoint"
        )
    evidence = {
        field_name: report_evidence.get(field_name, False)
        for field_name in LangGraphEligibilityEvidence.model_fields
    }
    candidate_data = binding.model_dump(mode="python")
    candidate_data.update(
        validation_report_uuid=report.report_uuid,
        validation_report_digest=report.report_digest,
        capability_snapshot_uuid=snapshot.snapshot_uuid,
        capability_snapshot_digest=snapshot.manifest_digest,
        capability_snapshot=dict(manifest),
        contract_version=report.contract_version,
        operations=_manifest_mapping(manifest, "operations"),
        limits=_manifest_mapping(manifest, "limits"),
        ownership=_manifest_mapping(manifest, "ownership"),
        evidence=evidence,
        topology_snapshot=None,
    )
    try:
        candidate = LangGraphEndpointBinding.model_validate(candidate_data)
    except ValidationError as exc:
        raise LangGraphBindingCompatibilityError(
            "current endpoint evidence cannot form a valid binding; revalidate or reconfigure the endpoint"
        ) from exc
    errors = validate_binding_against_evidence(
        candidate,
        endpoint=endpoint,
        report=report,
        snapshot=snapshot,
    )
    if errors:
        raise LangGraphBindingCompatibilityError(
            "current endpoint evidence is incompatible: " + "; ".join(errors)
        )
    return candidate


async def validate_langgraph_workflow_binding(
    *,
    workflow_configurations: Mapping[str, Any] | None,
    organization_id: int,
    db_client: Any,
) -> LangGraphEndpointBinding | None:
    binding = await validate_langgraph_runtime_path(
        workflow_configurations=workflow_configurations,
        organization_id=organization_id,
    )
    if binding is None:
        return None
    feature = await get_langgraph_feature_configuration(organization_id)
    if not feature.enabled:
        raise FeatureDisabledError(
            "LangGraph integration is disabled for this organization"
        )
    evidence = await db_client.get_current_langgraph_activation_evidence(
        organization_id=organization_id,
        endpoint_uuid=binding.registration_uuid,
    )
    if evidence is None:
        raise LangGraphWorkflowBindingError("endpoint registration is unavailable")
    endpoint, report, snapshot = evidence
    errors = validate_binding_against_evidence(
        binding, endpoint=endpoint, report=report, snapshot=snapshot
    )
    if errors:
        raise LangGraphWorkflowBindingError("; ".join(errors))
    return binding


def pinned_run_snapshot(binding: LangGraphEndpointBinding) -> dict[str, Any]:
    """Return a detached JSON snapshot; callers must never consult mutable behavior."""
    return binding.model_dump(mode="json", exclude_none=True)

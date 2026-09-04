from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import ValidationError

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
) -> bool:
    if not isinstance(evidence, LangGraphEligibilityEvidence):
        try:
            evidence = LangGraphEligibilityEvidence.model_validate(evidence)
        except ValidationError:
            return False
    return evidence.complete


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
        if report_evidence and not live_eligibility_evidence_complete(report_evidence):
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
    if not live_eligibility_evidence_complete(binding.evidence):
        errors.append("workflow binding lacks complete live-eligibility evidence")
    if not binding.data_sharing_policy:
        errors.append("data-sharing policy is required")
    return tuple(dict.fromkeys(errors))


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

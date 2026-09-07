"""ARQ job that runs LangGraph endpoint discovery, negotiation, and conformance.

Dispatched by ``request_validation`` in
``api/services/langgraph_integration/endpoint_registration.py``. Every branch
(discovery failure, negotiation failure, and the success path) persists a
``Validation_Report`` before returning, so ``get_current_langgraph_activation_evidence``
always has a report to evaluate once this job has run.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from loguru import logger

from api.db import db_client
from api.schemas.langgraph_integration.common import InvocationMode, StateMode
from api.schemas.workflow_configurations import LangGraphEligibilityEvidence
from api.services.langgraph_integration.configuration import (
    get_langgraph_feature_configuration,
)
from api.services.langgraph_integration.conformance import SUITE_VERSION, run_suite
from api.services.langgraph_integration.conformance.evidence import (
    ELIGIBILITY_SUITE_VERSION,
)
from api.services.langgraph_integration.conformance.live import (
    run_live_endpoint_evidence,
)
from api.services.langgraph_integration.conformance.platform import (
    run_platform_evidence,
)
from api.services.langgraph_integration.conformance.runner import deterministic_digest
from api.services.langgraph_integration.contract.models import MatrixVersion
from api.services.langgraph_integration.discovery import (
    CapabilitySelectionError,
    negotiate_capabilities,
    record_capability_snapshot,
)
from api.services.langgraph_integration.gateway import (
    DiscoveryError,
    IntegrationGateway,
    RuntimeEndpointSnapshot,
    StaticCredentialResolver,
    discover_manifest,
)
from api.utils.credential_auth import build_auth_header

_KNOWN_INVOCATION_MODES = frozenset(mode.value for mode in InvocationMode)
_KNOWN_STATE_MODES = frozenset(mode.value for mode in StateMode)


def _select_negotiation_inputs(
    *, endpoint: Any, matrix: MatrixVersion
) -> tuple[frozenset[str], str, frozenset[str]]:
    """Derive negotiation selections from the endpoint's stored capability choices."""
    selected_capabilities = frozenset(endpoint.selected_capabilities or ())
    selected_invocation_modes = selected_capabilities & _KNOWN_INVOCATION_MODES
    selected_features = (
        selected_capabilities - _KNOWN_INVOCATION_MODES - _KNOWN_STATE_MODES
    )

    profile_rule = next(
        (
            rule
            for rule in matrix.profiles
            if str(rule.profile.value) == endpoint.selected_profile
        ),
        None,
    )
    if profile_rule is not None and profile_rule.allowed_state_modes:
        selected_state_mode = min(
            str(mode.value) for mode in profile_rule.allowed_state_modes
        )
    else:
        state_modes_selected = sorted(selected_capabilities & _KNOWN_STATE_MODES)
        selected_state_mode = state_modes_selected[0] if state_modes_selected else ""
    return selected_invocation_modes, selected_state_mode, selected_features


async def _persist_report(
    *,
    organization_id: int,
    registration_id: int,
    capability_snapshot_id: int | None,
    compatibility_matrix_id: int,
    suite_version: str,
    contract_version: str,
    selected_profile: str,
    status: str,
    started_at: datetime,
    completed_at: datetime | None,
    evidence: dict[str, Any],
    results: list[dict[str, Any]],
) -> None:
    report_digest = deterministic_digest(
        {
            "capability_snapshot_id": capability_snapshot_id,
            "compatibility_matrix_id": compatibility_matrix_id,
            "suite_version": suite_version,
            "contract_version": contract_version,
            "selected_profile": selected_profile,
            "status": status,
            "started_at": started_at.isoformat(),
            "completed_at": completed_at.isoformat() if completed_at else None,
            "evidence": evidence,
            "results": results,
        }
    )
    await db_client.insert_langgraph_validation_report(
        organization_id=organization_id,
        registration_id=registration_id,
        capability_snapshot_id=capability_snapshot_id,
        compatibility_matrix_id=compatibility_matrix_id,
        suite_version=suite_version,
        contract_version=contract_version,
        selected_profile=selected_profile,
        status=status,
        started_at=started_at,
        completed_at=completed_at,
        evidence=evidence,
        report_digest=report_digest,
        results=results,
    )


async def validate_langgraph_endpoint(
    ctx: dict[str, Any], organization_id: int, endpoint_uuid: str
) -> None:
    """Run discovery, negotiation, and conformance for one endpoint and persist a report.

    Every branch (discovery failure, negotiation failure, and the success path) persists
    a Validation_Report before returning. Unexpected exceptions (e.g. a DB error while
    loading the endpoint) are not caught here; they propagate uncaught so ARQ's normal
    failure/retry visibility applies, since no attempt was actually made against the
    endpoint in that case.
    """
    del ctx
    endpoint = await db_client.get_langgraph_endpoint(
        organization_id=organization_id, endpoint_uuid=endpoint_uuid
    )
    if endpoint is None:
        logger.info(
            f"LangGraph endpoint {endpoint_uuid} no longer exists for organization "
            f"{organization_id}; skipping validation"
        )
        return

    started_at = datetime.now(UTC)
    matrices = await db_client.list_langgraph_compatibility_matrices()
    if not matrices:
        raise RuntimeError("no LangGraph compatibility matrix is published")
    # Matches the `current=index==0` convention in routes/langgraph_endpoints.py.
    matrix_row = matrices[0]
    matrix = MatrixVersion.model_validate(matrix_row.matrix)

    credential = await db_client.get_langgraph_endpoint_credential(
        organization_id=organization_id, credential_id=endpoint.credential_id
    )
    if credential is None:
        raise RuntimeError("endpoint credential is unavailable for organization")
    auth_headers = build_auth_header(credential)
    feature_configuration = await get_langgraph_feature_configuration(organization_id)

    try:
        discovery_result = await discover_manifest(
            endpoint_url=endpoint.endpoint_url,
            auth_headers=auth_headers,
            feature_configuration=feature_configuration,
        )
    except DiscoveryError as exc:
        await _persist_report(
            organization_id=organization_id,
            registration_id=endpoint.id,
            capability_snapshot_id=None,
            compatibility_matrix_id=matrix_row.id,
            suite_version=SUITE_VERSION,
            contract_version="",
            selected_profile=endpoint.selected_profile,
            status="failed",
            started_at=started_at,
            completed_at=datetime.now(UTC),
            evidence={
                "discovery_failed": True,
                "error_type": type(exc).__name__,
                "error_message": str(exc),
            },
            results=[],
        )
        return

    recorded_snapshot = await record_capability_snapshot(
        store=db_client,
        organization_id=organization_id,
        registration_id=endpoint.id,
        manifest=discovery_result.manifest,
    )
    snapshot_id = recorded_snapshot.snapshot.id

    (
        selected_invocation_modes,
        selected_state_mode,
        selected_features,
    ) = _select_negotiation_inputs(endpoint=endpoint, matrix=matrix)

    try:
        negotiated = negotiate_capabilities(
            manifest=discovery_result.manifest,
            matrix=matrix,
            selected_profile=endpoint.selected_profile,
            selected_invocation_modes=selected_invocation_modes,
            selected_state_mode=selected_state_mode,
            selected_features=selected_features,
        )
    except CapabilitySelectionError as exc:
        await _persist_report(
            organization_id=organization_id,
            registration_id=endpoint.id,
            capability_snapshot_id=snapshot_id,
            compatibility_matrix_id=matrix_row.id,
            suite_version=SUITE_VERSION,
            contract_version="",
            selected_profile=endpoint.selected_profile,
            status="failed",
            started_at=started_at,
            completed_at=datetime.now(UTC),
            evidence={"negotiation_failed": True, "reasons": list(exc.reasons)},
            results=[],
        )
        return

    suite_result = run_suite()
    manifest = discovery_result.manifest
    limits = manifest.limits.model_dump(mode="json")
    operations = manifest.operations.model_dump(mode="json", exclude_none=True)
    runtime_snapshot = RuntimeEndpointSnapshot(
        organization_id=organization_id,
        registration_id=endpoint.endpoint_uuid,
        endpoint_url=endpoint.endpoint_url,
        credential_reference=str(getattr(credential, "credential_uuid", credential.id)),
        contract_version=negotiated.contract_version,
        invocation_modes=frozenset(
            InvocationMode(mode) for mode in negotiated.invocation_modes
        ),
        operations=operations,
        request_bytes=limits["request_bytes"],
        response_bytes=limits["response_bytes"],
        event_bytes=limits["event_bytes"],
        tool_argument_bytes=limits["tool_argument_bytes"],
        stateful_profile=endpoint.selected_profile == "stateful_run",
        interrupts_selected="interrupts" in negotiated.features,
        cancellation_declared="cancellation" in negotiated.features,
        distributed_tracing="distributed_tracing" in negotiated.features,
        private_network_enabled=feature_configuration.private_network_enabled,
    )
    live_evidence = await run_live_endpoint_evidence(
        gateway=IntegrationGateway(
            credential_resolver=StaticCredentialResolver(auth_headers)
        ),
        snapshot=runtime_snapshot,
        profile=endpoint.selected_profile,
    )
    platform_evidence = await run_platform_evidence()
    eligibility = LangGraphEligibilityEvidence(
        text_session_conformance=live_evidence.text_session_conformance,
        accepted_transition=False,
        endpoint_state_continuity=live_evidence.endpoint_state_continuity,
        cancellation_verified=platform_evidence.cancellation_verified,
        recording_verified=platform_evidence.recording_verified,
    )
    profile_runtime_passed = (
        live_evidence.endpoint_state_continuity
        if endpoint.selected_profile == "stateful_run"
        else live_evidence.text_session_conformance
    )
    passed = all(
        (
            suite_result.passed,
            profile_runtime_passed,
            platform_evidence.cancellation_verified,
            platform_evidence.recording_verified,
        )
    )
    executable_results = [
        check.to_validation_result()
        for check in (*live_evidence.checks, *platform_evidence.checks)
    ]
    await _persist_report(
        organization_id=organization_id,
        registration_id=endpoint.id,
        capability_snapshot_id=snapshot_id,
        compatibility_matrix_id=matrix_row.id,
        suite_version=f"{suite_result.suite_version}+{ELIGIBILITY_SUITE_VERSION}",
        contract_version=negotiated.contract_version,
        selected_profile=endpoint.selected_profile,
        status="passed" if passed else "failed",
        started_at=started_at,
        completed_at=datetime.now(UTC),
        evidence=eligibility.model_dump(mode="json"),
        results=[*suite_result.persistence_results(), *executable_results],
    )

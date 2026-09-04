from copy import deepcopy
from datetime import date
from typing import Any

import pytest

from api.schemas.langgraph_integration import v1_0
from api.schemas.langgraph_integration.examples import EXECUTABLE_EXAMPLES
from api.services.langgraph_integration.contract import (
    MatrixVersion,
    ProfileRequirements,
    validate_manifest,
)
from api.services.langgraph_integration.discovery import (
    CapabilitySelectionError,
    negotiate_capabilities,
    normalize_manifest,
    record_capability_snapshot,
)


def _manifest(**overrides: Any) -> v1_0.CapabilityManifest:
    payload = deepcopy(EXECUTABLE_EXAMPLES["1.0"]["manifest"])
    payload.update(overrides)
    return v1_0.CapabilityManifest.model_validate(payload)


def _matrix(*versions: str) -> MatrixVersion:
    return MatrixVersion(
        matrix_version="2026-01",
        effective_date=date(2026, 1, 1),
        mural_release_version="1.44.0",
        supported_contract_versions=versions,
        profiles=(
            ProfileRequirements(
                profile="chat",
                required_invocation_modes=frozenset({"streaming"}),
                allowed_state_modes=frozenset({"mural_authoritative"}),
            ),
            ProfileRequirements(
                profile="stateful_run",
                required_invocation_modes=frozenset({"streaming"}),
                allowed_state_modes=frozenset({"endpoint_checkpointed"}),
                required_features=frozenset({"interrupts"}),
            ),
        ),
    )


def _negotiate(manifest: v1_0.CapabilityManifest, **overrides: Any):
    arguments = {
        "manifest": manifest,
        "matrix": _matrix("1.0", "1.1"),
        "selected_profile": "chat",
        "selected_invocation_modes": {"streaming"},
        "selected_state_mode": "mural_authoritative",
    }
    arguments.update(overrides)
    return negotiate_capabilities(**arguments)


def test_negotiation_selects_highest_exact_minor_across_multi_major_offers():
    manifest = _manifest(contract_versions=["1.0", "1.1", "2.0", "2.1"])

    result = _negotiate(
        manifest,
        matrix=_matrix("1.0", "1.1", "2.0", "2.1"),
    )

    assert result.contract_version == "2.1"
    assert result.invocation_modes == frozenset({"streaming"})
    assert result.features == frozenset()


def test_no_common_version_exposes_offered_and_supported_details():
    manifest = _manifest(contract_versions=["2.0", "2.1"])

    with pytest.raises(CapabilitySelectionError) as exc_info:
        _negotiate(manifest, matrix=_matrix("1.0", "1.1"))

    assert exc_info.value.reasons == ("no mutually supported contract version",)
    assert exc_info.value.details["version_incompatibility"] == {
        "offered_versions": ["2.0", "2.1"],
        "supported_versions": ["1.0", "1.1"],
        "offered_majors": [2],
        "supported_majors": [1],
    }


def test_undeclared_selected_behavior_is_rejected_completely():
    manifest = _manifest(
        compatibility_profiles=["chat"],
        invocation_modes=["streaming"],
        state_modes=["mural_authoritative"],
        features={
            "interrupts": False,
            "idempotent_invocations": False,
            "distributed_tracing": False,
        },
    )

    with pytest.raises(CapabilitySelectionError) as exc_info:
        _negotiate(
            manifest,
            selected_profile="stateful_run",
            selected_invocation_modes={"streaming", "asynchronous"},
            selected_state_mode="endpoint_checkpointed",
            selected_features={"interrupts"},
        )

    assert set(exc_info.value.reasons) == {
        "undeclared profile: stateful_run",
        "undeclared invocation modes: ['asynchronous']",
        "undeclared state mode: endpoint_checkpointed",
        "undeclared features: ['interrupts']",
    }


def test_missing_data_region_is_rejected_during_manifest_parsing():
    payload = deepcopy(EXECUTABLE_EXAMPLES["1.0"]["manifest"])
    payload.pop("data_regions")

    validation = validate_manifest(payload, "1.0")

    assert validation.manifest is None
    assert any(violation.startswith("data_regions:") for violation in validation.violations)


def test_live_voice_requires_streaming_to_be_selected():
    manifest = _manifest(invocation_modes=["streaming", "synchronous"])

    with pytest.raises(CapabilitySelectionError) as exc_info:
        _negotiate(
            manifest,
            selected_invocation_modes={"synchronous"},
            require_live_voice=True,
        )

    assert "streaming invocation mode is required for live voice" in exc_info.value.reasons


def test_declared_operation_capabilities_can_be_selected_without_enabling_others():
    manifest = _manifest(
        operations={
            "invoke": "/v1/invocations",
            "status": "/v1/runs/{external_run_id}",
            "cancel": "/v1/invocations/{invocation_id}/cancel",
            "health": "/v1/health",
        }
    )

    result = _negotiate(
        manifest,
        selected_features={"cancellation", "health"},
    )

    assert result.features == frozenset({"cancellation", "health"})
    assert "idempotent_invocations" not in result.features


def test_normalization_ignores_declaration_order_but_preserves_operational_limits():
    manifest = _manifest(
        contract_versions=["1.1", "1.0"],
        invocation_modes=["synchronous", "streaming"],
    )

    normalized = normalize_manifest(manifest)

    assert normalized["contract_versions"] == ["1.0", "1.1"]
    assert normalized["invocation_modes"] == ["streaming", "synchronous"]
    assert normalized["limits"]["event_bytes"] == manifest.limits.event_bytes


class _SnapshotStore:
    def __init__(self) -> None:
        self.current_digest: str | None = None
        self.snapshots: dict[str, dict[str, Any]] = {}

    async def insert_langgraph_capability_snapshot(self, **values: Any):
        digest = values["manifest_digest"]
        changed = self.current_digest is not None and self.current_digest != digest
        snapshot = self.snapshots.setdefault(digest, values["manifest"])
        self.current_digest = digest
        return snapshot, changed


@pytest.mark.asyncio
async def test_operational_limit_change_records_a_changed_immutable_snapshot():
    store = _SnapshotStore()
    original = _manifest()
    changed_payload = original.model_dump(mode="json")
    changed_payload["limits"]["event_bytes"] -= 1
    changed = v1_0.CapabilityManifest.model_validate(changed_payload)

    first = await record_capability_snapshot(
        store=store,
        organization_id=7,
        registration_id=11,
        manifest=original,
    )
    repeated = await record_capability_snapshot(
        store=store,
        organization_id=7,
        registration_id=11,
        manifest=original,
    )
    updated = await record_capability_snapshot(
        store=store,
        organization_id=7,
        registration_id=11,
        manifest=changed,
    )

    assert first.changed is False
    assert repeated.changed is False
    assert updated.changed is True
    assert updated.digest != first.digest
    assert len(store.snapshots) == 2

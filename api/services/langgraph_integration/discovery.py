"""Capability normalization, selection, and discovery negotiation."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Protocol

from api.services.langgraph_integration.contract.models import MatrixVersion
from api.services.langgraph_integration.contract.negotiation import (
    VersionIncompatibilityError,
    negotiate_contract_version,
)
from api.services.langgraph_integration.lifecycle import capability_digest


class CapabilitySelectionError(ValueError):
    def __init__(
        self,
        reasons: Iterable[str],
        *,
        incompatibility: VersionIncompatibilityError | None = None,
    ):
        self.reasons = tuple(sorted(set(reasons)))
        self.incompatibility = incompatibility
        super().__init__("; ".join(self.reasons))

    @property
    def details(self) -> dict[str, Any]:
        details: dict[str, Any] = {"reasons": list(self.reasons)}
        if self.incompatibility is not None:
            details["version_incompatibility"] = self.incompatibility.details
        return details


@dataclass(frozen=True)
class NegotiatedCapabilities:
    contract_version: str
    profile: str
    invocation_modes: frozenset[str]
    state_mode: str
    features: frozenset[str]
    live_voice_eligible: bool
    data_regions: tuple[str, ...]
    snapshot_digest: str
    normalized_manifest: dict[str, Any]


@dataclass(frozen=True)
class RecordedCapabilitySnapshot:
    snapshot: Any
    changed: bool
    digest: str
    normalized_manifest: dict[str, Any]


class CapabilitySnapshotStore(Protocol):
    async def insert_langgraph_capability_snapshot(
        self,
        *,
        organization_id: int,
        registration_id: int,
        manifest: dict[str, Any],
        manifest_digest: str,
        schema_version: str,
    ) -> tuple[Any, bool]: ...


def _values(items: Iterable[Any]) -> frozenset[str]:
    return frozenset(str(getattr(item, "value", item)) for item in items)


def normalize_manifest(manifest: Any) -> dict[str, Any]:
    """Produce a deterministic, persistence-safe manifest snapshot."""
    payload = manifest.model_dump(mode="json", exclude_none=True)
    for field in (
        "contract_versions",
        "compatibility_profiles",
        "invocation_modes",
        "state_modes",
        "data_regions",
    ):
        payload[field] = sorted(set(payload.get(field, ())))
    payload["features"] = dict(sorted(payload.get("features", {}).items()))
    payload["limits"] = dict(sorted(payload.get("limits", {}).items()))
    payload["operations"] = dict(sorted(payload.get("operations", {}).items()))
    return payload


def _declared_features(manifest: Any) -> frozenset[str]:
    """Project wire-visible optional behavior from flags and operations."""
    feature_values = manifest.features.model_dump()
    declared = {name for name, enabled in feature_values.items() if enabled}
    operations = manifest.operations.model_dump()
    if operations.get("cancel"):
        declared.add("cancellation")
    if operations.get("health"):
        declared.add("health")
    return frozenset(declared)


async def record_capability_snapshot(
    *,
    store: CapabilitySnapshotStore,
    organization_id: int,
    registration_id: int,
    manifest: Any,
) -> RecordedCapabilitySnapshot:
    """Persist one normalized immutable snapshot and report semantic change."""
    normalized = normalize_manifest(manifest)
    digest = capability_digest(normalized)
    snapshot, changed = await store.insert_langgraph_capability_snapshot(
        organization_id=organization_id,
        registration_id=registration_id,
        manifest=normalized,
        manifest_digest=digest,
        schema_version=str(manifest.schema_version),
    )
    return RecordedCapabilitySnapshot(snapshot, changed, digest, normalized)


def negotiate_capabilities(
    *,
    manifest: Any,
    matrix: MatrixVersion,
    selected_profile: str,
    selected_invocation_modes: Iterable[str],
    selected_state_mode: str,
    selected_features: Iterable[str] = (),
    require_live_voice: bool = False,
) -> NegotiatedCapabilities:
    """Enable only selected behavior declared by both manifest and matrix."""
    declared_profiles = _values(manifest.compatibility_profiles)
    declared_modes = _values(manifest.invocation_modes)
    declared_states = _values(manifest.state_modes)
    declared_features = _declared_features(manifest)
    selected_modes = frozenset(selected_invocation_modes)
    requested_features = frozenset(selected_features)
    reasons: list[str] = []

    profile_rule = next(
        (rule for rule in matrix.profiles if str(rule.profile.value) == selected_profile),
        None,
    )
    if selected_profile not in declared_profiles:
        reasons.append(f"undeclared profile: {selected_profile}")
    if profile_rule is None:
        reasons.append(f"profile absent from matrix: {selected_profile}")
    if not selected_modes <= declared_modes:
        reasons.append(
            f"undeclared invocation modes: {sorted(selected_modes - declared_modes)}"
        )
    if selected_state_mode not in declared_states:
        reasons.append(f"undeclared state mode: {selected_state_mode}")
    if not requested_features <= declared_features:
        reasons.append(
            f"undeclared features: {sorted(requested_features - declared_features)}"
        )
    if not manifest.data_regions:
        reasons.append("endpoint data region is required")
    if require_live_voice and "streaming" not in selected_modes:
        reasons.append("streaming invocation mode is required for live voice")
    if profile_rule is not None:
        required_modes = _values(profile_rule.required_invocation_modes)
        allowed_states = _values(profile_rule.allowed_state_modes)
        if not required_modes <= selected_modes:
            reasons.append(
                f"profile requires invocation modes: {sorted(required_modes - selected_modes)}"
            )
        if selected_state_mode not in allowed_states:
            reasons.append(f"state mode not allowed by profile: {selected_state_mode}")
        if not set(profile_rule.required_features) <= requested_features:
            reasons.append(
                "profile required features not selected: "
                f"{sorted(set(profile_rule.required_features) - requested_features)}"
            )
    if reasons:
        raise CapabilitySelectionError(reasons)

    try:
        version = negotiate_contract_version(manifest.contract_versions, matrix)
    except VersionIncompatibilityError as exc:
        raise CapabilitySelectionError(
            ("no mutually supported contract version",),
            incompatibility=exc,
        ) from exc

    normalized = normalize_manifest(manifest)
    return NegotiatedCapabilities(
        contract_version=version,
        profile=selected_profile,
        invocation_modes=selected_modes,
        state_mode=selected_state_mode,
        features=requested_features,
        live_voice_eligible="streaming" in selected_modes,
        data_regions=tuple(normalized["data_regions"]),
        snapshot_digest=capability_digest(normalized),
        normalized_manifest=normalized,
    )

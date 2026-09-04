from __future__ import annotations

from datetime import date
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from api.schemas.langgraph_integration.common import CompatibilityProfile, InvocationMode, StateMode


class SemanticVersion(BaseModel):
    model_config = ConfigDict(frozen=True, order=False)
    major: int = Field(ge=0)
    minor: int = Field(ge=0)

    @classmethod
    def parse(cls, value: str) -> "SemanticVersion":
        parts = value.split(".")
        if len(parts) != 2 or not all(part.isdigit() for part in parts):
            raise ValueError(f"invalid contract version: {value}")
        return cls(major=int(parts[0]), minor=int(parts[1]))

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}"


class ProfileRequirements(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    profile: CompatibilityProfile
    required_invocation_modes: frozenset[InvocationMode]
    allowed_state_modes: frozenset[StateMode]
    required_features: frozenset[str] = frozenset()
    limitations: tuple[str, ...] = ()


class MatrixVersion(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    matrix_version: str = Field(min_length=1, max_length=64)
    effective_date: date
    mural_release_version: str = Field(min_length=1, max_length=64)
    supported_contract_versions: tuple[str, ...]
    profiles: tuple[ProfileRequirements, ...]
    limitations: tuple[str, ...] = ()

    @field_validator("supported_contract_versions")
    @classmethod
    def versions_are_unique_and_normalized(cls, versions: tuple[str, ...]) -> tuple[str, ...]:
        parsed = tuple(str(SemanticVersion.parse(version)) for version in versions)
        if len(set(parsed)) != len(parsed):
            raise ValueError("supported contract versions must be unique")
        return parsed

    def supports(self, version: str) -> bool:
        return version in self.supported_contract_versions


class NormalizedCapabilities(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    contract_versions: frozenset[str]
    profiles: frozenset[CompatibilityProfile]
    invocation_modes: frozenset[InvocationMode]
    state_modes: frozenset[StateMode]
    features: tuple[tuple[str, bool], ...]
    limits: tuple[tuple[str, int], ...]

    @classmethod
    def from_manifest(cls, manifest: Any) -> "NormalizedCapabilities":
        feature_data = manifest.features.model_dump()
        limit_data = manifest.limits.model_dump()
        return cls(
            contract_versions=frozenset(manifest.contract_versions),
            profiles=frozenset(manifest.compatibility_profiles),
            invocation_modes=frozenset(manifest.invocation_modes),
            state_modes=frozenset(manifest.state_modes),
            features=tuple(sorted(feature_data.items())),
            limits=tuple(sorted(limit_data.items())),
        )

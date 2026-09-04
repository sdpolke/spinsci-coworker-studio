"""HTTP schemas for tenant-scoped LangGraph endpoint management."""

from datetime import datetime
from typing import Any, Literal

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, field_validator

from api.schemas.langgraph_integration.common import CompatibilityProfile

LifecycleStatus = Literal[
    "pending_validation",
    "validation_only",
    "active",
    "degraded",
    "disabled",
    "incompatible",
    "retired",
]


class EndpointCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=255)
    endpoint_url: AnyHttpUrl = Field(max_length=2048)
    credential_uuid: str = Field(min_length=1, max_length=36)
    selected_profile: CompatibilityProfile
    selected_capabilities: list[str] = Field(min_length=1, max_length=64)

    @field_validator("selected_capabilities")
    @classmethod
    def capabilities_are_unique(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("selected capabilities must be unique")
        return values


class EndpointUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=255)
    endpoint_url: AnyHttpUrl | None = Field(default=None, max_length=2048)
    credential_uuid: str | None = Field(default=None, min_length=1, max_length=36)
    selected_profile: CompatibilityProfile | None = None
    selected_capabilities: list[str] | None = Field(default=None, min_length=1, max_length=64)

    @field_validator("selected_capabilities")
    @classmethod
    def capabilities_are_unique(cls, values: list[str] | None) -> list[str] | None:
        if values is not None and len(values) != len(set(values)):
            raise ValueError("selected capabilities must be unique")
        return values


class CredentialProjection(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    credential_type: str
    reference_id: str
    last_updated_at: datetime | None


class CapabilitySnapshotSummary(BaseModel):
    snapshot_uuid: str
    manifest_digest: str
    schema_version: str
    manifest: dict[str, Any]
    discovered_at: datetime


class EndpointResponse(BaseModel):
    endpoint_uuid: str
    name: str
    endpoint_url: str
    selected_profile: str
    selected_capabilities: list[str]
    lifecycle_status: LifecycleStatus
    credential: CredentialProjection
    current_validation_report_uuid: str | None = None
    current_capability_snapshot: CapabilitySnapshotSummary | None = None
    private_network_enabled: bool
    created_at: datetime
    updated_at: datetime
    retired_at: datetime | None = None


class ValidationResultResponse(BaseModel):
    test_identifier: str
    test_version: str
    required: bool
    outcome: str
    duration_ms: int | None
    measurements: dict[str, Any]
    redacted_error: dict[str, Any] | None


class ValidationReportResponse(BaseModel):
    report_uuid: str
    capability_snapshot_uuid: str | None
    matrix_version: str
    suite_version: str
    contract_version: str
    selected_profile: str
    status: str
    started_at: datetime
    completed_at: datetime | None
    evidence: dict[str, Any]
    report_digest: str
    created_at: datetime
    results: list[ValidationResultResponse]


class CompatibilityMatrixResponse(BaseModel):
    matrix_uuid: str
    matrix_version: str
    effective_at: datetime
    mural_release_version: str
    matrix: dict[str, Any]
    published_at: datetime
    current: bool


class LifecycleActionResponse(BaseModel):
    endpoint_uuid: str
    lifecycle_status: LifecycleStatus


class DeleteEndpointResponse(BaseModel):
    endpoint_uuid: str
    outcome: Literal["deleted", "retired"]


class LangGraphFeatureUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool
    experimental_risk_acknowledged: bool = False
    private_network_enabled: bool | None = None
    private_network_risk_acknowledged: bool = False


class LangGraphFeatureStatusResponse(BaseModel):
    enabled: bool
    experimental: bool = True
    acknowledged: bool
    rollout_stage: str
    can_configure: bool
    private_network_configurable: bool
    private_network_enabled: bool


class RunDiagnosticEventResponse(BaseModel):
    id: str
    category: Literal[
        "pipecat",
        "attempt",
        "runtime_event",
        "tool_call",
        "transition",
        "observation",
        "security",
        "error",
    ]
    occurred_at: datetime
    order: int
    title: str
    invocation_id: str | None = None
    attempt_id: str | None = None
    sequence: int | None = None
    trace_id: str | None = None
    trace_url: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class RunDiagnosticsResponse(BaseModel):
    workflow_run_id: int
    endpoint_registration_uuid: str
    contract_version: str
    compatibility_profile: str
    state_mode: str
    external_identifiers: dict[str, Any] = Field(default_factory=dict)
    external_identifier_traces: list[dict[str, str]] = Field(default_factory=list)
    events: list[RunDiagnosticEventResponse]

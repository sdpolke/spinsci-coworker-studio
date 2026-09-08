"""API models for version-local external LangGraph topology state."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class TopologyReasonCode(StrEnum):
    """Stable, non-secret reason codes returned by topology APIs."""

    SNAPSHOT_UNAVAILABLE = "snapshot_unavailable"
    SNAPSHOT_INVALID = "snapshot_invalid"
    SNAPSHOT_BINDING_MISMATCH = "snapshot_binding_mismatch"
    SNAPSHOT_DIGEST_MISMATCH = "snapshot_digest_mismatch"
    SNAPSHOT_REQUIRED_FOR_IMMUTABLE_VERSION = "snapshot_required_for_immutable_version"
    ENDPOINT_NOT_CONFIGURED = "endpoint_not_configured"
    IMMUTABLE_SNAPSHOT_ONLY = "immutable_snapshot_only"
    ENDPOINT_UNAVAILABLE = "endpoint_unavailable"
    ENDPOINT_REVALIDATION_REQUIRED = "endpoint_revalidation_required"
    ENDPOINT_VALIDATION_FAILED = "endpoint_validation_failed"
    TOPOLOGY_UNSUPPORTED = "topology_unsupported"
    BINDING_STALE = "binding_stale"
    BINDING_CURRENT = "binding_current"
    BINDING_INCOMPATIBLE = "binding_incompatible"
    TOPOLOGY_UNAVAILABLE = "topology_unavailable"
    TOPOLOGY_AUTH_FAILED = "topology_auth_failed"
    TOPOLOGY_NETWORK_FAILED = "topology_network_failed"
    TOPOLOGY_SCHEMA_INVALID = "topology_schema_invalid"
    DRAFT_CHANGED = "draft_changed"


class DraftBindingState(StrEnum):
    ENDPOINT_NOT_CONFIGURED = "endpoint_not_configured"
    IMMUTABLE_SNAPSHOT_ONLY = "immutable_snapshot_only"
    ENDPOINT_UNAVAILABLE = "endpoint_unavailable"
    ENDPOINT_REVALIDATION_REQUIRED = "endpoint_revalidation_required"
    ENDPOINT_VALIDATION_FAILED = "endpoint_validation_failed"
    TOPOLOGY_UNSUPPORTED = "topology_unsupported"
    BINDING_STALE = "binding_stale"
    BINDING_CURRENT = "binding_current"


class DraftBindingStatus(BaseModel):
    """Read-only comparison of a version binding with current endpoint evidence."""

    model_config = ConfigDict(extra="forbid")

    state: DraftBindingState
    reason: TopologyReasonCode | None = None
    bound_validation_report_uuid: str | None = Field(default=None, max_length=64)
    bound_capability_snapshot_uuid: str | None = Field(default=None, max_length=64)
    current_validation_report_uuid: str | None = Field(default=None, max_length=64)
    current_capability_snapshot_uuid: str | None = Field(default=None, max_length=64)


class TopologyActionAvailability(BaseModel):
    """Server-derived presentation hints; mutation routes still authorize independently."""

    model_config = ConfigDict(extra="forbid")

    can_revalidate: bool = False
    can_update_binding: bool = False
    can_refresh_topology: bool = False
    immutable: bool = False


class ValidationStage(StrEnum):
    NOT_REQUIRED = "not_required"
    REQUIRED = "required"
    PENDING = "pending"
    PASSED = "passed"
    FAILED = "failed"


class BindingUpdateStage(StrEnum):
    NOT_REQUIRED = "not_required"
    PENDING = "pending"
    UPDATED = "updated"
    FAILED = "failed"


class TopologyRefreshStage(StrEnum):
    NOT_STARTED = "not_started"
    PENDING = "pending"
    PINNED = "pinned"
    FAILED = "failed"


class TopologyLifecycleStages(BaseModel):
    model_config = ConfigDict(extra="forbid")

    validation: ValidationStage = ValidationStage.NOT_REQUIRED
    binding_update: BindingUpdateStage = BindingUpdateStage.NOT_REQUIRED
    topology_refresh: TopologyRefreshStage = TopologyRefreshStage.NOT_STARTED


class ExternalTopologyResponse(BaseModel):
    """Backward-compatible topology payload with additive draft lifecycle metadata."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["available", "unavailable"]
    reason: TopologyReasonCode | None = None
    topology: dict[str, Any] | None = None
    digest: str | None = None
    endpoint_binding_revision: str | None = None
    binding_status: DraftBindingStatus | None = None
    actions: TopologyActionAvailability | None = None
    stages: TopologyLifecycleStages | None = None

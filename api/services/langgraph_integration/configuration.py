"""Experimental organization configuration for LangGraph endpoints."""

from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, model_validator

from api.constants import DEPLOYMENT_MODE
from api.db import db_client
from api.enums import OrganizationConfigurationKey
from api.services.langgraph_integration.rollout import (
    InvalidRolloutTransition,
    RolloutStage,
    require_valid_stage_transition,
)
from api.services.worker_sync.manager import get_worker_sync_manager
from api.services.worker_sync.protocol import WorkerSyncEventType


class LangGraphFeatureConfiguration(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    experimental_acknowledged_at: datetime | None = None
    experimental_acknowledged_by: int | None = None
    rollout_stage: str = "internal_test_tenant"
    internal_tenant_ids: tuple[int, ...] = ()
    allowlisted_tenant_ids: tuple[int, ...] = ()
    percentage_cohort: int = 0
    cohort_salt: str = "langgraph-rollout-v1"
    disabled_at: datetime | None = None
    expansion_halted: bool = False
    expansion_halted_at: datetime | None = None
    private_network_enabled: bool = False
    private_network_decided_at: datetime | None = None
    private_network_decided_by: int | None = None

    @model_validator(mode="after")
    def validate_audited_decisions(self):
        try:
            RolloutStage(self.rollout_stage)
        except ValueError as exc:
            raise ValueError("unsupported rollout stage") from exc
        if not 0 <= self.percentage_cohort <= 100:
            raise ValueError("percentage cohort must be between 0 and 100")
        if not self.cohort_salt:
            raise ValueError("cohort salt is required")
        if any(tenant_id <= 0 for tenant_id in (*self.internal_tenant_ids, *self.allowlisted_tenant_ids)):
            raise ValueError("rollout tenant identifiers must be positive")
        if self.enabled and not (
            self.experimental_acknowledged_at and self.experimental_acknowledged_by
        ):
            raise ValueError("feature enablement requires experimental acknowledgment")
        if self.private_network_enabled and not (
            self.private_network_decided_at and self.private_network_decided_by
        ):
            raise ValueError("private-network enablement requires an audited decision")
        return self


async def get_langgraph_feature_configuration(
    organization_id: int,
) -> LangGraphFeatureConfiguration:
    value = await db_client.get_configuration_value(
        organization_id,
        OrganizationConfigurationKey.LANGGRAPH_INTEGRATION.value,
        {},
    )
    return LangGraphFeatureConfiguration.model_validate(value or {})


async def update_langgraph_feature_configuration(
    *,
    organization_id: int,
    actor_user_id: int,
    enabled: bool,
    acknowledged: bool,
    rollout_stage: str | None = None,
    internal_tenant_ids: tuple[int, ...] | None = None,
    allowlisted_tenant_ids: tuple[int, ...] | None = None,
    percentage_cohort: int | None = None,
    cohort_salt: str | None = None,
    private_network_enabled: bool | None = None,
    private_network_risk_acknowledged: bool = False,
) -> LangGraphFeatureConfiguration:
    """Update the selected organization's feature gate without resetting rollout state."""
    if enabled and not acknowledged:
        raise ValueError("feature enablement requires explicit experimental acknowledgment")
    if DEPLOYMENT_MODE != "oss" and private_network_enabled is True:
        raise ValueError("private-network endpoint access is unavailable in hosted deployments")

    now = datetime.now(UTC)
    current_state = await db_client.get_langgraph_rollout_state(
        organization_id=organization_id
    )
    defaults = LangGraphFeatureConfiguration()

    def current(name: str):
        return getattr(current_state, name, getattr(defaults, name))

    resolved_rollout_stage = rollout_stage or current("rollout_stage")
    target_stage = RolloutStage(resolved_rollout_stage)
    if current_state is not None:
        require_valid_stage_transition(
            RolloutStage(current_state.rollout_stage), target_stage
        )
        current_index = tuple(RolloutStage).index(RolloutStage(current_state.rollout_stage))
        target_index = tuple(RolloutStage).index(target_stage)
        if current_state.expansion_halted and target_index > current_index:
            raise InvalidRolloutTransition(
                "rollout expansion is halted by the current evaluation window"
            )

    current_private_network_enabled = bool(current("private_network_enabled"))
    resolved_private_network_enabled = (
        current_private_network_enabled
        if private_network_enabled is None
        else private_network_enabled
    )
    if (
        resolved_private_network_enabled
        and not current_private_network_enabled
        and not private_network_risk_acknowledged
    ):
        raise ValueError(
            "private-network enablement requires explicit risk acknowledgment"
        )

    if acknowledged:
        experimental_acknowledged_at = now
        experimental_acknowledged_by = actor_user_id
    else:
        experimental_acknowledged_at = current("experimental_acknowledged_at")
        experimental_acknowledged_by = current("experimental_acknowledged_by")

    private_network_changed = (
        private_network_enabled is not None
        and private_network_enabled != current_private_network_enabled
    )
    if private_network_changed:
        private_network_decided_at = now
        private_network_decided_by = actor_user_id
    else:
        private_network_decided_at = current("private_network_decided_at")
        private_network_decided_by = current("private_network_decided_by")

    disabled_at = (
        None
        if enabled
        else (
            current_state.disabled_at
            if current_state is not None and not current_state.feature_enabled
            else now
        )
    )
    resolved_internal_tenant_ids = tuple(
        sorted(
            set(
                current("internal_tenant_ids")
                if internal_tenant_ids is None
                else internal_tenant_ids
            )
        )
    )
    if DEPLOYMENT_MODE == "oss" and enabled:
        # Self-hosted installations are organization-local: enabling the feature
        # must also select that organization for the initial rollout stage.
        # Otherwise the settings UI reports enabled while every run is rejected.
        resolved_internal_tenant_ids = tuple(
            sorted({*resolved_internal_tenant_ids, organization_id})
        )

    config = LangGraphFeatureConfiguration(
        enabled=enabled,
        experimental_acknowledged_at=experimental_acknowledged_at,
        experimental_acknowledged_by=experimental_acknowledged_by,
        rollout_stage=target_stage.value,
        internal_tenant_ids=resolved_internal_tenant_ids,
        allowlisted_tenant_ids=tuple(
            sorted(set(current("allowlisted_tenant_ids") if allowlisted_tenant_ids is None else allowlisted_tenant_ids))
        ),
        percentage_cohort=(
            current("percentage_cohort") if percentage_cohort is None else percentage_cohort
        ),
        cohort_salt=current("cohort_salt") if cohort_salt is None else cohort_salt,
        disabled_at=disabled_at,
        expansion_halted=bool(current("expansion_halted")),
        expansion_halted_at=current("expansion_halted_at"),
        private_network_enabled=resolved_private_network_enabled,
        private_network_decided_at=private_network_decided_at,
        private_network_decided_by=private_network_decided_by,
    )
    await db_client.upsert_langgraph_rollout_state(
        organization_id=organization_id,
        feature_enabled=config.enabled,
        experimental_acknowledged_at=config.experimental_acknowledged_at,
        experimental_acknowledged_by=config.experimental_acknowledged_by,
        rollout_stage=config.rollout_stage,
        internal_tenant_ids=list(config.internal_tenant_ids),
        allowlisted_tenant_ids=list(config.allowlisted_tenant_ids),
        percentage_cohort=config.percentage_cohort,
        cohort_salt=config.cohort_salt,
        private_network_enabled=config.private_network_enabled,
        private_network_decided_at=config.private_network_decided_at,
        private_network_decided_by=config.private_network_decided_by,
        changed_at=now,
    )
    await db_client.upsert_configuration(
        organization_id,
        OrganizationConfigurationKey.LANGGRAPH_INTEGRATION.value,
        config.model_dump(mode="json"),
    )
    try:
        manager = get_worker_sync_manager()
    except RuntimeError:
        manager = None
    if manager is not None:
        await manager.broadcast(
            WorkerSyncEventType.LANGGRAPH_CONFIGURATION.value,
            "update",
            str(organization_id),
        )
    return config


async def invalidate_langgraph_credential_cache(organization_id: int) -> None:
    """Notify every worker to re-resolve endpoint credential references."""
    try:
        manager = get_worker_sync_manager()
    except RuntimeError:
        return
    await manager.broadcast(
        WorkerSyncEventType.LANGGRAPH_CREDENTIALS.value,
        "update",
        str(organization_id),
    )

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import api.routes.langgraph_endpoints as routes
import api.services.langgraph_integration.configuration as configuration
from api.routes.langgraph_endpoints import router
from api.services.auth.depends import get_user
from api.services.langgraph_integration.configuration import (
    LangGraphFeatureConfiguration,
    update_langgraph_feature_configuration,
)
from api.services.worker_sync.protocol import WorkerSyncEventType

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _client(*, organization_id=11, role="organization_admin") -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_user] = lambda: SimpleNamespace(
        id=7,
        selected_organization_id=organization_id,
        langgraph_role=role,
    )
    return TestClient(app)


def _configuration(**changes) -> LangGraphFeatureConfiguration:
    values = {
        "enabled": False,
        "rollout_stage": "internal_test_tenant",
    }
    values.update(changes)
    return LangGraphFeatureConfiguration(**values)


def _rollout_state(**changes) -> SimpleNamespace:
    values = {
        "feature_enabled": True,
        "experimental_acknowledged_at": NOW,
        "experimental_acknowledged_by": 5,
        "rollout_stage": "selected_tenant_allowlist",
        "internal_tenant_ids": [11, 12],
        "allowlisted_tenant_ids": [21, 22],
        "percentage_cohort": 37,
        "cohort_salt": "preserved-salt",
        "disabled_at": None,
        "expansion_halted": True,
        "expansion_halted_at": NOW,
        "private_network_enabled": False,
        "private_network_decided_at": None,
        "private_network_decided_by": None,
    }
    values.update(changes)
    return SimpleNamespace(**values)


def test_admin_patch_uses_only_selected_organization_and_returns_safe_status(monkeypatch):
    updated = _configuration(
        enabled=True,
        experimental_acknowledged_at=NOW,
        experimental_acknowledged_by=7,
    )
    mutation = AsyncMock(return_value=updated)
    monkeypatch.setattr(routes, "update_langgraph_feature_configuration", mutation)
    monkeypatch.setattr(routes, "DEPLOYMENT_MODE", "oss")

    response = _client(organization_id=44).patch(
        "/langgraph-feature",
        json={"enabled": True, "experimental_risk_acknowledged": True},
    )

    assert response.status_code == 200
    assert response.json() == {
        "enabled": True,
        "experimental": True,
        "acknowledged": True,
        "rollout_stage": "internal_test_tenant",
        "can_configure": True,
        "private_network_configurable": True,
        "private_network_enabled": False,
    }
    mutation.assert_awaited_once_with(
        organization_id=44,
        actor_user_id=7,
        enabled=True,
        acknowledged=True,
        private_network_enabled=None,
        private_network_risk_acknowledged=False,
    )


def test_non_admin_patch_is_forbidden_without_mutation(monkeypatch):
    mutation = AsyncMock()
    monkeypatch.setattr(routes, "update_langgraph_feature_configuration", mutation)

    response = _client(role="endpoint_operator").patch(
        "/langgraph-feature",
        json={"enabled": False},
    )

    assert response.status_code == 403
    mutation.assert_not_awaited()


def test_missing_organization_context_is_rejected_without_mutation(monkeypatch):
    mutation = AsyncMock()
    monkeypatch.setattr(routes, "update_langgraph_feature_configuration", mutation)

    response = _client(organization_id=None).patch(
        "/langgraph-feature",
        json={"enabled": False},
    )

    assert response.status_code == 400
    mutation.assert_not_awaited()


def test_caller_selected_foreign_organization_is_non_enumerating_and_mutation_free(
    monkeypatch,
):
    mutation = AsyncMock()
    monkeypatch.setattr(routes, "update_langgraph_feature_configuration", mutation)

    response = _client(organization_id=11).patch(
        "/langgraph-feature",
        json={"enabled": False, "organization_id": 99},
    )

    assert response.status_code == 422
    assert "organization" not in response.text.lower() or "extra_forbidden" in response.text
    mutation.assert_not_awaited()


@pytest.mark.asyncio
async def test_enable_requires_acknowledgment_before_any_database_mutation(monkeypatch):
    state_lookup = AsyncMock()
    state_upsert = AsyncMock()
    config_upsert = AsyncMock()
    monkeypatch.setattr(configuration.db_client, "get_langgraph_rollout_state", state_lookup)
    monkeypatch.setattr(configuration.db_client, "upsert_langgraph_rollout_state", state_upsert)
    monkeypatch.setattr(configuration.db_client, "upsert_configuration", config_upsert)

    with pytest.raises(ValueError, match="explicit experimental acknowledgment"):
        await update_langgraph_feature_configuration(
            organization_id=11,
            actor_user_id=7,
            enabled=True,
            acknowledged=False,
        )

    state_lookup.assert_not_awaited()
    state_upsert.assert_not_awaited()
    config_upsert.assert_not_awaited()


@pytest.mark.asyncio
async def test_disable_preserves_rollout_acknowledgment_and_halt_state(monkeypatch):
    state = _rollout_state()
    state_upsert = AsyncMock()
    config_upsert = AsyncMock()
    manager = SimpleNamespace(broadcast=AsyncMock())
    monkeypatch.setattr(
        configuration.db_client,
        "get_langgraph_rollout_state",
        AsyncMock(return_value=state),
    )
    monkeypatch.setattr(configuration.db_client, "upsert_langgraph_rollout_state", state_upsert)
    monkeypatch.setattr(configuration.db_client, "upsert_configuration", config_upsert)
    monkeypatch.setattr(configuration, "get_worker_sync_manager", lambda: manager)

    result = await update_langgraph_feature_configuration(
        organization_id=11,
        actor_user_id=7,
        enabled=False,
        acknowledged=False,
    )

    assert result.enabled is False
    assert result.experimental_acknowledged_at == NOW
    assert result.experimental_acknowledged_by == 5
    assert result.rollout_stage == "selected_tenant_allowlist"
    assert result.internal_tenant_ids == (11, 12)
    assert result.allowlisted_tenant_ids == (21, 22)
    assert result.percentage_cohort == 37
    assert result.cohort_salt == "preserved-salt"
    assert result.expansion_halted is True
    assert result.expansion_halted_at == NOW
    assert result.disabled_at is not None
    state_upsert.assert_awaited_once()
    config_upsert.assert_awaited_once()
    manager.broadcast.assert_awaited_once_with(
        WorkerSyncEventType.LANGGRAPH_CONFIGURATION.value,
        "update",
        "11",
    )


@pytest.mark.asyncio
async def test_self_hosted_private_network_enablement_requires_distinct_audit(monkeypatch):
    state = _rollout_state(feature_enabled=False, experimental_acknowledged_at=None, experimental_acknowledged_by=None)
    state_upsert = AsyncMock()
    monkeypatch.setattr(configuration, "DEPLOYMENT_MODE", "oss")
    monkeypatch.setattr(
        configuration.db_client,
        "get_langgraph_rollout_state",
        AsyncMock(return_value=state),
    )
    monkeypatch.setattr(configuration.db_client, "upsert_langgraph_rollout_state", state_upsert)
    monkeypatch.setattr(configuration.db_client, "upsert_configuration", AsyncMock())
    monkeypatch.setattr(configuration, "get_worker_sync_manager", lambda: None)

    with pytest.raises(ValueError, match="explicit risk acknowledgment"):
        await update_langgraph_feature_configuration(
            organization_id=11,
            actor_user_id=7,
            enabled=False,
            acknowledged=False,
            private_network_enabled=True,
        )
    state_upsert.assert_not_awaited()

    result = await update_langgraph_feature_configuration(
        organization_id=11,
        actor_user_id=7,
        enabled=False,
        acknowledged=False,
        private_network_enabled=True,
        private_network_risk_acknowledged=True,
    )

    assert result.private_network_enabled is True
    assert result.private_network_decided_by == 7
    assert result.private_network_decided_at is not None
    persisted = state_upsert.await_args.kwargs
    assert persisted["private_network_decided_by"] == 7
    assert persisted["private_network_decided_at"] == result.private_network_decided_at


@pytest.mark.asyncio
async def test_hosted_private_network_enablement_is_rejected_before_mutation(monkeypatch):
    state_lookup = AsyncMock()
    state_upsert = AsyncMock()
    monkeypatch.setattr(configuration, "DEPLOYMENT_MODE", "saas")
    monkeypatch.setattr(configuration.db_client, "get_langgraph_rollout_state", state_lookup)
    monkeypatch.setattr(configuration.db_client, "upsert_langgraph_rollout_state", state_upsert)

    with pytest.raises(ValueError, match="unavailable in hosted deployments"):
        await update_langgraph_feature_configuration(
            organization_id=11,
            actor_user_id=7,
            enabled=False,
            acknowledged=False,
            private_network_enabled=True,
            private_network_risk_acknowledged=True,
        )

    state_lookup.assert_not_awaited()
    state_upsert.assert_not_awaited()


def test_safe_defaults_are_disabled_and_private_network_closed():
    defaults = LangGraphFeatureConfiguration()
    assert defaults.enabled is False
    assert defaults.private_network_enabled is False

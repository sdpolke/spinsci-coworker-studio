from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from api.routes import organization_usage
from api.services import local_credits


@pytest.mark.asyncio
async def test_get_billing_credits_local_ledger(monkeypatch):
    monkeypatch.setattr(organization_usage, "LOCAL_CREDITS_ENABLED", True)

    snapshot = local_credits.LocalBillingSnapshot(
        balance=150.0,
        total_debits=30.0,
        entries=[
            SimpleNamespace(
                id=1,
                entry_type="grant",
                origin="admin_topup",
                credits_delta=150.0,
                balance_after=150.0,
                metric_code=None,
                idempotency_key=None,
                workflow_run_id=None,
                workflow_id=None,
                billable_quantity=None,
                quantity_unit=None,
                metadata_json={"note": "seed"},
                created_at=SimpleNamespace(isoformat=lambda: "2026-08-10T00:00:00Z"),
            )
        ],
        total_count=1,
        page=1,
        limit=50,
    )
    monkeypatch.setattr(
        local_credits,
        "get_billing_snapshot",
        AsyncMock(return_value=snapshot),
    )

    user = SimpleNamespace(provider_id="provider-123", selected_organization_id=7)
    response = await organization_usage.get_billing_credits(
        page=1,
        limit=50,
        user=user,
    )

    assert response.remaining_credits == 150.0
    assert response.total_credits_used == 30.0
    assert response.total_quota == 180.0
    assert response.account is not None
    assert response.account.billing_mode == "local"
    assert len(response.ledger_entries) == 1
    assert response.ledger_entries[0].origin == "admin_topup"


@pytest.mark.asyncio
async def test_grant_billing_credits(monkeypatch):
    monkeypatch.setattr(organization_usage, "LOCAL_CREDITS_ENABLED", True)
    monkeypatch.setattr(organization_usage, "DOGRAH_DEVOPS_SECRET", "secret")

    monkeypatch.setattr(
        organization_usage.db_client,
        "get_organization_by_id",
        AsyncMock(return_value=SimpleNamespace(id=7)),
    )
    monkeypatch.setattr(
        organization_usage.local_credits,
        "grant_credits",
        AsyncMock(return_value=1500.0),
    )

    response = await organization_usage.grant_billing_credits(
        organization_usage.GrantCreditsRequest(
            credits=1500,
            organization_id=7,
            note="initial grant",
        ),
        authorization=None,
        x_api_key=None,
        x_dograh_devops_secret="secret",
    )

    assert response.organization_id == 7
    assert response.credits_granted == 1500
    assert response.balance_after == 1500.0

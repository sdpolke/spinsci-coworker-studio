from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from api.services import local_credits
from api.services.workflow_run_billing import report_workflow_run_platform_usage


@pytest.mark.asyncio
async def test_debit_platform_usage_settles_idempotently(monkeypatch):
    settle = AsyncMock(
        return_value=SimpleNamespace(credits_delta=-15.0, balance_after=985.0)
    )
    release = AsyncMock()

    monkeypatch.setattr(local_credits.db_client, "settle_platform_usage", settle)
    monkeypatch.setattr(local_credits.db_client, "release_run_hold", release)

    workflow_run = SimpleNamespace(
        id=101,
        mode="webrtc",
        is_completed=True,
        workflow_id=5,
        usage_info={"call_duration_seconds": 60},
        workflow=SimpleNamespace(organization_id=7),
    )

    await local_credits.debit_platform_usage(workflow_run)
    await local_credits.debit_platform_usage(workflow_run)

    assert settle.await_count == 2
    kwargs = settle.await_args.kwargs
    assert kwargs["credits"] == 15.0
    assert kwargs["billable_minutes"] == 1.0
    assert kwargs["workflow_run_id"] == 101
    release.assert_not_awaited()


@pytest.mark.asyncio
async def test_debit_releases_hold_when_no_duration(monkeypatch):
    release = AsyncMock()
    settle = AsyncMock()
    monkeypatch.setattr(local_credits.db_client, "release_run_hold", release)
    monkeypatch.setattr(local_credits.db_client, "settle_platform_usage", settle)

    workflow_run = SimpleNamespace(
        id=101,
        mode="webrtc",
        is_completed=True,
        workflow_id=5,
        usage_info={},
        workflow=SimpleNamespace(organization_id=7),
    )

    await local_credits.debit_platform_usage(workflow_run)

    release.assert_awaited_once_with(organization_id=7, workflow_run_id=101)
    settle.assert_not_awaited()


@pytest.mark.asyncio
async def test_report_workflow_run_platform_usage_uses_local_credits(monkeypatch):
    debit = AsyncMock()
    monkeypatch.setattr("api.services.workflow_run_billing.LOCAL_CREDITS_ENABLED", True)
    monkeypatch.setattr(
        "api.services.workflow_run_billing.local_credits.debit_platform_usage",
        debit,
    )

    workflow_run = SimpleNamespace(id=1)
    await report_workflow_run_platform_usage(workflow_run)

    debit.assert_awaited_once_with(workflow_run)

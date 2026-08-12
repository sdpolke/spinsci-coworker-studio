import pytest

from api.db.local_credits_client import LocalCreditsClient
from api.services import local_credits


@pytest.mark.parametrize(
    ("duration_seconds", "expected_minutes"),
    [
        (0, 0),
        (1, 1),
        (59, 1),
        (60, 1),
        (61, 2),
        (120, 2),
        (121, 3),
    ],
)
def test_billable_minutes_ceil(duration_seconds, expected_minutes):
    assert LocalCreditsClient.billable_minutes(duration_seconds) == expected_minutes


@pytest.mark.parametrize(
    ("duration_seconds", "expected_credits"),
    [
        (0, 0.0),
        (1, 15.0),
        (60, 15.0),
        (61, 30.0),
    ],
)
def test_credits_for_duration(duration_seconds, expected_credits):
    assert local_credits.credits_for_duration(duration_seconds) == expected_credits


@pytest.mark.asyncio
async def test_authorize_run_blocks_when_balance_too_low(monkeypatch):
    async def fake_balance(_organization_id: int) -> float:
        return 0.0

    monkeypatch.setattr(local_credits.db_client, "get_credit_balance", fake_balance)

    result = await local_credits.authorize_run(42)
    assert result.has_quota is False
    assert result.error_code == "insufficient_credits"


@pytest.mark.asyncio
async def test_authorize_run_allows_when_balance_sufficient(monkeypatch):
    async def fake_balance(_organization_id: int) -> float:
        return 15.0

    monkeypatch.setattr(local_credits.db_client, "get_credit_balance", fake_balance)

    result = await local_credits.authorize_run(42)
    assert result.has_quota is True


@pytest.mark.asyncio
async def test_authorize_run_places_hold_when_run_id_present(monkeypatch):
    place_hold = pytest.importorskip("unittest.mock").AsyncMock()
    monkeypatch.setattr(local_credits.db_client, "place_run_hold", place_hold)

    result = await local_credits.authorize_run(
        42,
        workflow_run_id=99,
        workflow_id=7,
    )

    assert result.has_quota is True
    place_hold.assert_awaited_once_with(
        organization_id=42,
        workflow_run_id=99,
        workflow_id=7,
    )

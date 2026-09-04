"""Idempotent tenant-scoped LangGraph retention sweep."""

from datetime import UTC, datetime
from typing import Any

from api.db import db_client


async def sweep_langgraph_retention(ctx: dict[str, Any], organization_id: int | None = None) -> dict[int, dict[str, int]]:
    """Expire governed records within the daily window; safe to replay."""
    del ctx
    organization_ids = (
        [organization_id]
        if organization_id is not None
        else await db_client.list_langgraph_retention_organizations()
    )
    now = datetime.now(UTC)
    results: dict[int, dict[str, int]] = {}
    for scoped_organization_id in organization_ids:
        results[scoped_organization_id] = await db_client.sweep_langgraph_retention(
            organization_id=scoped_organization_id,
            now=now,
        )
    return results

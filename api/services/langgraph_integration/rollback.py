"""Authorized rollback of new-run selection to a prior non-LangGraph version."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Awaitable, Callable, Protocol, TypeVar

from api.services.langgraph_integration.access_control import (
    LangGraphAuthorizationError,
    LangGraphPermission,
    LangGraphRole,
    is_langgraph_resource_authorized,
)

ROLLBACK_DEADLINE = timedelta(seconds=60)


class RollbackError(ValueError):
    pass


class RollbackDeadlineExceeded(RollbackError):
    pass


@dataclass(frozen=True)
class RollbackSelection:
    workflow_id: int
    definition_id: int
    organization_id: int
    started_at: datetime


class RollbackClient(Protocol):
    async def select_prior_non_langgraph_version(
        self, *, workflow_id: int, definition_id: int, organization_id: int
    ): ...


def is_non_langgraph_configuration(configuration: dict | None) -> bool:
    return not bool((configuration or {}).get("langgraph_endpoint"))


T = TypeVar("T")


async def execute_prior_version_rollback(
    *,
    client: RollbackClient,
    selection: RollbackSelection,
    actor_role: LangGraphRole,
    actor_organization_id: int,
    now: Callable[[], datetime],
) -> T:
    """Change only the workflow's new-run pointer within the rollback SLO."""
    if not is_langgraph_resource_authorized(
        role=actor_role,
        permission=LangGraphPermission.ROLLBACK,
        actor_organization_id=actor_organization_id,
        resource_organization_id=selection.organization_id,
    ):
        raise LangGraphAuthorizationError("rollback is not authorized")
    if now() - selection.started_at > ROLLBACK_DEADLINE:
        raise RollbackDeadlineExceeded("rollback exceeded the 60-second deadline")
    result = await client.select_prior_non_langgraph_version(
        workflow_id=selection.workflow_id,
        definition_id=selection.definition_id,
        organization_id=selection.organization_id,
    )
    if now() - selection.started_at > ROLLBACK_DEADLINE:
        raise RollbackDeadlineExceeded("rollback exceeded the 60-second deadline")
    return result

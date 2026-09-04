"""Pure LangGraph integration RBAC decisions.

Routes/services must authorize before invoking a mutation callback. Keeping the
policy pure makes denied-state non-mutation independently testable.
"""

from collections.abc import Awaitable, Callable
from enum import Enum
from typing import TypeVar


class LangGraphRole(str, Enum):
    ORGANIZATION_ADMIN = "organization_admin"
    ENDPOINT_OPERATOR = "endpoint_operator"
    INTERRUPT_REVIEWER = "interrupt_reviewer"
    MEMBER = "member"


class LangGraphPermission(str, Enum):
    CREATE = "langgraph_endpoint:create"
    READ = "langgraph_endpoint:read"
    LIST = "langgraph_endpoint:list"
    UPDATE = "langgraph_endpoint:update"
    VALIDATE = "langgraph_endpoint:validate"
    ACTIVATE = "langgraph_endpoint:activate"
    DEACTIVATE = "langgraph_endpoint:deactivate"
    DELETE = "langgraph_endpoint:delete"
    RETIRE = "langgraph_endpoint:retire"
    CONFIGURE_FEATURE = "langgraph_feature:configure"
    ROLLBACK = "langgraph_rollout:rollback"
    REVIEW_INTERRUPT = "langgraph_interrupt:review"


_ENDPOINT_LIFECYCLE = frozenset(
    {
        LangGraphPermission.CREATE,
        LangGraphPermission.READ,
        LangGraphPermission.LIST,
        LangGraphPermission.UPDATE,
        LangGraphPermission.VALIDATE,
        LangGraphPermission.ACTIVATE,
        LangGraphPermission.DEACTIVATE,
        LangGraphPermission.DELETE,
        LangGraphPermission.RETIRE,
    }
)
_ROLE_PERMISSIONS = {
    LangGraphRole.ORGANIZATION_ADMIN: frozenset(LangGraphPermission),
    LangGraphRole.ENDPOINT_OPERATOR: _ENDPOINT_LIFECYCLE,
    LangGraphRole.INTERRUPT_REVIEWER: frozenset(
        {LangGraphPermission.READ, LangGraphPermission.REVIEW_INTERRUPT}
    ),
    LangGraphRole.MEMBER: frozenset(
        {LangGraphPermission.READ, LangGraphPermission.LIST}
    ),
}


def is_langgraph_authorized(
    *, role: LangGraphRole, permission: LangGraphPermission
) -> bool:
    return permission in _ROLE_PERMISSIONS[role]


def is_langgraph_resource_authorized(
    *,
    role: LangGraphRole,
    permission: LangGraphPermission,
    actor_organization_id: int,
    resource_organization_id: int,
) -> bool:
    return (
        actor_organization_id == resource_organization_id
        and is_langgraph_authorized(role=role, permission=permission)
    )


class LangGraphAuthorizationError(PermissionError):
    pass


T = TypeVar("T")


async def execute_authorized(
    *,
    role: LangGraphRole,
    permission: LangGraphPermission,
    mutation: Callable[[], Awaitable[T]],
) -> T:
    """Run a mutation only after authorization succeeds."""
    if not is_langgraph_authorized(role=role, permission=permission):
        raise LangGraphAuthorizationError(f"{role.value} lacks {permission.value}")
    return await mutation()

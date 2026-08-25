"""Shared parse/validate/persist pipeline for workflow authoring.

Used by MCP tools and the local agentic workflow generator so both paths
share the same validation authority.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from loguru import logger
from pydantic import ValidationError as PydanticValidationError

from api.db import db_client
from api.db.agent_trigger_client import TriggerPathConflictError
from api.db.models import WorkflowModel
from api.enums import PostHogEvent
from api.services.posthog_client import capture_event
from api.services.workflow.dto import ReactFlowDTO
from api.services.workflow.layout import reconcile_positions
from api.services.workflow.tool_name_validation import (
    validate_workflow_tool_name_collisions,
)
from api.services.workflow.trigger_paths import (
    extract_trigger_paths,
    validate_trigger_paths,
)
from api.services.workflow.workflow_graph import WorkflowGraph

AuthoringErrorCode = Literal[
    "parse_error",
    "validation_error",
    "schema_validation",
    "graph_validation",
    "missing_name",
    "trigger_path_conflict",
    "bridge_error",
]


@dataclass(frozen=True)
class WorkflowAuthoringActor:
    user_id: int
    organization_id: int | None
    provider_id: str


@dataclass(frozen=True)
class PreparedWorkflow:
    name: str
    payload: dict[str, Any]
    trigger_paths: list[str]


@dataclass(frozen=True)
class AuthoringFailure:
    error_code: AuthoringErrorCode
    message: str
    errors: list[dict[str, Any]] | None = None
    trigger_paths: list[str] | None = None


def format_authoring_errors(errors: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for error in errors:
        loc = ""
        line = error.get("line")
        col = error.get("column")
        if line is not None:
            loc = f" (line {line}" + (f", col {col}" if col is not None else "") + ")"
        parts.append(f"{error.get('message', '')}{loc}")
    return "\n".join(parts)


async def prepare_workflow_from_code(
    code: str,
    *,
    previous_workflow_json: dict[str, Any] | None = None,
    organization_id: int | None,
) -> PreparedWorkflow | AuthoringFailure:
    """Parse SDK TypeScript and run graph/DTO validation."""
    from api.mcp_server.ts_bridge import TsBridgeError, parse_code

    try:
        parsed = await parse_code(code)
    except TsBridgeError as exc:
        logger.warning(f"ts_bridge failure: {exc}")
        return AuthoringFailure(error_code="bridge_error", message=str(exc))

    if not parsed.get("ok"):
        stage = parsed.get("stage", "parse")
        errors = parsed.get("errors") or []
        code_key: AuthoringErrorCode = (
            "parse_error" if stage == "parse" else "validation_error"
        )
        return AuthoringFailure(
            error_code=code_key,
            message=format_authoring_errors(errors),
            errors=errors,
        )

    payload = parsed["workflow"]
    name = (parsed.get("workflowName") or "").strip()
    if not name:
        return AuthoringFailure(
            error_code="missing_name",
            message=(
                'Workflow name is required. Add `new Workflow({ name: "..." })` '
                "to the source."
            ),
        )

    payload = reconcile_positions(payload, previous_workflow_json)
    trigger_path_issues = validate_trigger_paths(payload)
    if trigger_path_issues:
        return AuthoringFailure(
            error_code="validation_error",
            message="\n".join(issue.message for issue in trigger_path_issues),
        )

    try:
        ReactFlowDTO.model_validate(payload)
    except PydanticValidationError as exc:
        return AuthoringFailure(error_code="schema_validation", message=str(exc))

    try:
        WorkflowGraph(ReactFlowDTO.model_validate(payload))
    except (ValueError, Exception) as exc:
        return AuthoringFailure(error_code="graph_validation", message=str(exc))

    tool_name_errors = await validate_workflow_tool_name_collisions(
        payload,
        organization_id,
    )
    if tool_name_errors:
        return AuthoringFailure(
            error_code="graph_validation",
            message="\n".join(error["message"] for error in tool_name_errors),
            errors=tool_name_errors,
        )

    return PreparedWorkflow(
        name=name,
        payload=payload,
        trigger_paths=extract_trigger_paths(payload),
    )


async def create_prepared_workflow(
    prepared: PreparedWorkflow,
    *,
    actor: WorkflowAuthoringActor,
    source: str,
    extra_event_properties: dict[str, Any] | None = None,
) -> WorkflowModel | AuthoringFailure:
    """Persist a validated workflow as version 1 published."""
    if prepared.trigger_paths:
        try:
            await db_client.assert_trigger_paths_available(
                trigger_paths=prepared.trigger_paths,
            )
        except TriggerPathConflictError as exc:
            return AuthoringFailure(
                error_code="trigger_path_conflict",
                message=str(exc),
                trigger_paths=exc.trigger_paths,
            )

    workflow = await db_client.create_workflow(
        prepared.name,
        prepared.payload,
        actor.user_id,
        actor.organization_id,
    )

    properties: dict[str, Any] = {
        "workflow_id": workflow.id,
        "workflow_name": workflow.name,
        "source": source,
        "organization_id": actor.organization_id,
    }
    if extra_event_properties:
        properties.update(extra_event_properties)

    capture_event(
        distinct_id=actor.provider_id,
        event=PostHogEvent.WORKFLOW_CREATED,
        properties=properties,
    )

    if prepared.trigger_paths:
        await db_client.sync_triggers_for_workflow(
            workflow_id=workflow.id,
            organization_id=actor.organization_id,
            trigger_paths=prepared.trigger_paths,
        )

    return workflow

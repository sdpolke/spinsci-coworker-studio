"""Orchestration for local agentic workflow generation."""

from __future__ import annotations

from loguru import logger

from api.db.models import UserModel, WorkflowModel
from api.services.configuration.masking import (
    mask_workflow_configurations,
    mask_workflow_definition,
)
from api.services.workflow.authoring import (
    AuthoringFailure,
    WorkflowAuthoringActor,
    create_prepared_workflow,
)
from api.services.workflow.generation.catalog import load_catalog_snapshot
from api.services.workflow.generation.compiler import (
    WorkflowCompilationError,
    compile_workflow_typescript,
)
from api.services.workflow.generation.model_client import (
    WorkflowGeneratorModelClient,
    WorkflowGeneratorModelError,
)
from api.services.workflow.generation.models import (
    GenerationBrief,
    GenerationMessage,
    GenerationMessageRole,
    GenerationSession,
    GenerationSessionStatus,
)
from api.services.workflow.generation.planner import plan_next_step
from api.services.workflow.generation.session_store import session_store


class WorkflowGenerationError(Exception):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


def _actor_from_user(user: UserModel) -> WorkflowAuthoringActor:
    return WorkflowAuthoringActor(
        user_id=user.id,
        organization_id=user.selected_organization_id,
        provider_id=str(user.provider_id),
    )


def _assert_session_owner(session: GenerationSession, user: UserModel) -> None:
    if session.user_id != user.id:
        raise WorkflowGenerationError("Generation session not found.", status_code=404)
    if session.organization_id != user.selected_organization_id:
        raise WorkflowGenerationError("Generation session not found.", status_code=404)


async def create_generation_session(
    *,
    user: UserModel,
    brief: GenerationBrief,
    model_client: WorkflowGeneratorModelClient | None = None,
) -> GenerationSession:
    client = model_client or WorkflowGeneratorModelClient()
    if not client.is_configured:
        raise WorkflowGenerationError(
            "Workflow generator model is not configured.",
            status_code=503,
        )

    catalog = await load_catalog_snapshot(
        organization_id=user.selected_organization_id,
    )
    try:
        planner_response = await plan_next_step(
            brief=brief,
            messages=[],
            catalog=catalog,
            model_client=client,
        )
    except WorkflowGeneratorModelError as exc:
        raise WorkflowGenerationError(str(exc), status_code=503) from exc

    session = GenerationSession(
        user_id=user.id,
        organization_id=user.selected_organization_id,
        provider_id=str(user.provider_id),
        brief=brief,
    )

    if planner_response.status == "ready":
        session.status = GenerationSessionStatus.READY
        session.summary = planner_response.summary or brief.activity_description
        session.plan = planner_response.plan or brief.use_case
    else:
        question = planner_response.question or (
            "Could you share any business rules or data fields this agent must collect?"
        )
        session.messages.append(
            GenerationMessage(
                role=GenerationMessageRole.ASSISTANT,
                content=question,
            )
        )

    await session_store.save(session)
    return session


async def submit_generation_message(
    *,
    user: UserModel,
    session_id: str,
    content: str,
    model_client: WorkflowGeneratorModelClient | None = None,
) -> GenerationSession:
    session = await session_store.get(session_id)
    if session is None:
        raise WorkflowGenerationError("Generation session expired.", status_code=404)

    _assert_session_owner(session, user)

    if session.status != GenerationSessionStatus.CLARIFYING:
        raise WorkflowGenerationError(
            f"Session is {session.status.value}; cannot accept messages.",
            status_code=409,
        )

    trimmed = content.strip()
    if not trimmed:
        raise WorkflowGenerationError("Message content is required.")

    session.messages.append(
        GenerationMessage(role=GenerationMessageRole.USER, content=trimmed)
    )
    session.touch()

    catalog = await load_catalog_snapshot(
        organization_id=user.selected_organization_id,
    )
    client = model_client or WorkflowGeneratorModelClient()

    try:
        planner_response = await plan_next_step(
            brief=session.brief,
            messages=session.messages,
            catalog=catalog,
            model_client=client,
        )
    except WorkflowGeneratorModelError as exc:
        raise WorkflowGenerationError(str(exc), status_code=503) from exc

    if planner_response.status == "ready":
        session.status = GenerationSessionStatus.READY
        session.summary = planner_response.summary or session.brief.activity_description
        session.plan = planner_response.plan or session.brief.use_case
    else:
        question = planner_response.question or (
            "Anything else the agent should ask or decide during the call?"
        )
        session.messages.append(
            GenerationMessage(
                role=GenerationMessageRole.ASSISTANT,
                content=question,
            )
        )

    await session_store.save(session)
    return session


async def finalize_generation_session(
    *,
    user: UserModel,
    session_id: str,
    model_client: WorkflowGeneratorModelClient | None = None,
) -> tuple[GenerationSession, WorkflowModel]:
    session = await session_store.get(session_id)
    if session is None:
        raise WorkflowGenerationError("Generation session expired.", status_code=404)

    _assert_session_owner(session, user)

    if session.status == GenerationSessionStatus.COMPLETED and session.workflow_id:
        raise WorkflowGenerationError("Workflow already generated for this session.")

    if session.status != GenerationSessionStatus.READY:
        raise WorkflowGenerationError(
            "Session is not ready for generation.",
            status_code=409,
        )

    session.status = GenerationSessionStatus.GENERATING
    session.error = None
    session.touch()
    await session_store.save(session)

    catalog = await load_catalog_snapshot(
        organization_id=user.selected_organization_id,
    )
    client = model_client or WorkflowGeneratorModelClient()
    actor = _actor_from_user(user)

    try:
        prepared, _typescript = await compile_workflow_typescript(
            brief=session.brief,
            summary=session.summary or session.brief.activity_description,
            plan=session.plan or session.brief.use_case,
            messages=session.messages,
            catalog=catalog,
            organization_id=user.selected_organization_id,
            model_client=client,
        )
        workflow_result = await create_prepared_workflow(
            prepared,
            actor=actor,
            source="generation_session",
            extra_event_properties={"generation_session_id": session.session_id},
        )
    except WorkflowGeneratorModelError as exc:
        session.status = GenerationSessionStatus.FAILED
        session.error = str(exc)
        session.touch()
        await session_store.save(session)
        raise WorkflowGenerationError(str(exc), status_code=503) from exc
    except WorkflowCompilationError as exc:
        session.status = GenerationSessionStatus.FAILED
        session.error = str(exc)
        session.touch()
        await session_store.save(session)
        logger.error(f"Workflow compilation failed: {exc}")
        raise WorkflowGenerationError(
            f"Failed to generate a valid workflow: {exc}",
            status_code=422,
        ) from exc
    except Exception as exc:
        session.status = GenerationSessionStatus.FAILED
        session.error = "Unexpected workflow generation failure."
        session.touch()
        await session_store.save(session)
        logger.exception("Unexpected workflow generation failure")
        raise WorkflowGenerationError(
            "Unexpected workflow generation failure.",
            status_code=500,
        ) from exc

    if isinstance(workflow_result, AuthoringFailure):
        session.status = GenerationSessionStatus.FAILED
        session.error = workflow_result.message
        session.touch()
        await session_store.save(session)
        raise WorkflowGenerationError(workflow_result.message, status_code=422)

    workflow = workflow_result
    session.status = GenerationSessionStatus.COMPLETED
    session.workflow_id = workflow.id
    session.touch()
    await session_store.save(session)
    return session, workflow


async def generate_workflow_one_shot(
    *,
    user: UserModel,
    brief: GenerationBrief,
    model_client: WorkflowGeneratorModelClient | None = None,
) -> WorkflowModel:
    """Compatibility path for POST /workflow/create/template."""
    client = model_client or WorkflowGeneratorModelClient()
    if not client.is_configured:
        raise WorkflowGenerationError(
            "Workflow generator model is not configured.",
            status_code=503,
        )

    catalog = await load_catalog_snapshot(
        organization_id=user.selected_organization_id,
    )
    summary = (
        f"{brief.use_case}: {brief.activity_description} "
        f"({brief.call_type} call)."
    )
    plan = (
        "Build a simple voice workflow with startCall, a few agentNode steps "
        "to collect required information, and endCall. Use only available tools."
    )

    try:
        prepared, _typescript = await compile_workflow_typescript(
            brief=brief,
            summary=summary,
            plan=plan,
            messages=[],
            catalog=catalog,
            organization_id=user.selected_organization_id,
            model_client=client,
        )
    except WorkflowGeneratorModelError as exc:
        raise WorkflowGenerationError(str(exc), status_code=503) from exc
    except WorkflowCompilationError as exc:
        logger.error(f"One-shot workflow compilation failed: {exc}")
        raise WorkflowGenerationError(
            "Failed to generate a valid workflow.",
            status_code=422,
        ) from exc

    actor = _actor_from_user(user)
    workflow_result = await create_prepared_workflow(
        prepared,
        actor=actor,
        source="template",
        extra_event_properties={"call_type": brief.call_type},
    )
    if isinstance(workflow_result, AuthoringFailure):
        raise WorkflowGenerationError(workflow_result.message, status_code=422)
    return workflow_result


def workflow_response_payload(
    workflow: WorkflowModel,
    *,
    workflow_definition: dict,
) -> dict:
    return {
        "id": workflow.id,
        "name": workflow.name,
        "status": workflow.status,
        "created_at": workflow.created_at,
        "workflow_definition": mask_workflow_definition(workflow_definition),
        "current_definition_id": workflow.current_definition_id,
        "template_context_variables": workflow.template_context_variables,
        "call_disposition_codes": workflow.call_disposition_codes,
        "workflow_configurations": mask_workflow_configurations(
            workflow.workflow_configurations
        ),
    }


def session_to_api_dict(session: GenerationSession) -> dict:
    return {
        "session_id": session.session_id,
        "status": session.status.value,
        "brief": session.brief.model_dump(),
        "messages": [
            {
                "role": message.role.value,
                "content": message.content,
                "created_at": message.created_at,
            }
            for message in session.messages
        ],
        "summary": session.summary,
        "plan": session.plan,
        "workflow_id": session.workflow_id,
        "error": session.error,
        "created_at": session.created_at,
        "updated_at": session.updated_at,
    }

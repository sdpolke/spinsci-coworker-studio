"""REST API for multi-turn agentic workflow generation."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.constants import WORKFLOW_GENERATION_MAX_MESSAGE_LENGTH
from api.db.models import UserModel
from api.routes.workflow import WorkflowResponse
from api.services.auth.depends import get_user
from api.services.workflow.generation.harness import (
    WorkflowGenerationError,
    create_generation_session,
    finalize_generation_session,
    session_to_api_dict,
    submit_generation_message,
    workflow_response_payload,
)
from api.services.workflow.generation.models import GenerationBrief

router = APIRouter(prefix="/workflow/generation", tags=["workflow-generation"])


class CreateGenerationSessionRequest(BaseModel):
    call_type: Literal["inbound", "outbound"]
    use_case: str = Field(min_length=1, max_length=200)
    activity_description: str = Field(min_length=1, max_length=4000)


class GenerationMessageResponse(BaseModel):
    role: Literal["assistant", "user"]
    content: str
    created_at: datetime


class GenerationSessionResponse(BaseModel):
    session_id: str
    status: Literal["clarifying", "ready", "generating", "completed", "failed"]
    brief: CreateGenerationSessionRequest
    messages: list[GenerationMessageResponse]
    summary: str | None = None
    plan: str | None = None
    workflow_id: int | None = None
    error: str | None = None
    created_at: datetime
    updated_at: datetime


class SubmitGenerationMessageRequest(BaseModel):
    content: str = Field(min_length=1, max_length=WORKFLOW_GENERATION_MAX_MESSAGE_LENGTH)


class GenerateWorkflowResponse(BaseModel):
    session: GenerationSessionResponse
    workflow: WorkflowResponse


def _to_session_response(data: dict) -> GenerationSessionResponse:
    return GenerationSessionResponse.model_validate(data)


def _handle_generation_error(exc: WorkflowGenerationError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=str(exc))


@router.post("/sessions", response_model=GenerationSessionResponse)
async def start_generation_session(
    request: CreateGenerationSessionRequest,
    user: UserModel = Depends(get_user),
) -> GenerationSessionResponse:
    if not user.selected_organization_id:
        raise HTTPException(status_code=400, detail="No organization selected")

    brief = GenerationBrief(
        call_type=request.call_type,
        use_case=request.use_case.strip(),
        activity_description=request.activity_description.strip(),
    )
    try:
        session = await create_generation_session(user=user, brief=brief)
    except WorkflowGenerationError as exc:
        raise _handle_generation_error(exc) from exc

    return _to_session_response(session_to_api_dict(session))


@router.post("/sessions/{session_id}/messages", response_model=GenerationSessionResponse)
async def post_generation_message(
    session_id: str,
    request: SubmitGenerationMessageRequest,
    user: UserModel = Depends(get_user),
) -> GenerationSessionResponse:
    try:
        session = await submit_generation_message(
            user=user,
            session_id=session_id,
            content=request.content.strip(),
        )
    except WorkflowGenerationError as exc:
        raise _handle_generation_error(exc) from exc

    return _to_session_response(session_to_api_dict(session))


@router.post("/sessions/{session_id}/generate", response_model=GenerateWorkflowResponse)
async def generate_workflow_from_session(
    session_id: str,
    user: UserModel = Depends(get_user),
) -> GenerateWorkflowResponse:
    try:
        session, workflow = await finalize_generation_session(
            user=user,
            session_id=session_id,
        )
    except WorkflowGenerationError as exc:
        raise _handle_generation_error(exc) from exc

    workflow_def = workflow.workflow_definition or {}
    return GenerateWorkflowResponse(
        session=_to_session_response(session_to_api_dict(session)),
        workflow=WorkflowResponse.model_validate(
            workflow_response_payload(workflow, workflow_definition=workflow_def)
        ),
    )

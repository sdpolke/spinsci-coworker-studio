from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routes.workflow import router as workflow_router
from api.routes.workflow_generation import router as generation_router
from api.services.auth.depends import get_user
from api.services.workflow.generation.models import (
    GenerationBrief,
    GenerationMessage,
    GenerationMessageRole,
    GenerationSession,
    GenerationSessionStatus,
    PlannerResponse,
)
from api.services.workflow.generation.model_client import WorkflowGeneratorModelClient


def _user(org_id: int = 11, user_id: int = 1) -> SimpleNamespace:
    return SimpleNamespace(
        id=user_id,
        provider_id="provider-1",
        selected_organization_id=org_id,
    )


def _make_generation_app(user: SimpleNamespace | None = None) -> FastAPI:
    app = FastAPI()
    app.include_router(generation_router)
    app.dependency_overrides[get_user] = lambda: user or _user()
    return app


@pytest.mark.asyncio
async def test_create_generation_session_returns_clarifying_question():
    from api.services.workflow.generation import harness

    user = _user()
    brief = GenerationBrief(
        call_type="inbound",
        use_case="Lead intake",
        activity_description="Collect contact details from callers.",
    )
    mock_client = MagicMock(spec=WorkflowGeneratorModelClient)
    mock_client.is_configured = True

    with (
        patch.object(
            harness,
            "load_catalog_snapshot",
            AsyncMock(return_value=MagicMock(node_types=[], tools=[], documents=[], credentials=[])),
        ),
        patch.object(
            harness,
            "plan_next_step",
            AsyncMock(
                return_value=PlannerResponse(
                    status="clarifying",
                    question="What fields are required?",
                )
            ),
        ),
        patch.object(harness.session_store, "save", AsyncMock()) as save_mock,
    ):
        session = await harness.create_generation_session(
            user=user,
            brief=brief,
            model_client=mock_client,
        )

    assert session.status == GenerationSessionStatus.CLARIFYING
    assert session.messages[-1].content == "What fields are required?"
    save_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_finalize_generation_session_persists_workflow():
    from api.services.workflow.generation import harness
    from api.services.workflow.authoring import PreparedWorkflow

    user = _user()
    session = GenerationSession(
        session_id="sess-1",
        user_id=user.id,
        organization_id=user.selected_organization_id,
        provider_id=str(user.provider_id),
        status=GenerationSessionStatus.READY,
        brief=GenerationBrief(
            call_type="outbound",
            use_case="Lead intake",
            activity_description="Collect contact details.",
        ),
        summary="Collect lead details",
        plan="start -> collect -> end",
    )
    prepared = PreparedWorkflow(
        name="lead_intake",
        payload={
            "nodes": [{"id": "1", "type": "startCall", "position": {"x": 0, "y": 0}, "data": {"name": "Start", "prompt": "Hi"}}],
            "edges": [],
        },
        trigger_paths=[],
    )
    workflow = SimpleNamespace(
        id=42,
        name="lead_intake",
        status="active",
        created_at=datetime.now(UTC),
        workflow_definition=prepared.payload,
        current_definition_id=1,
        template_context_variables=None,
        call_disposition_codes=None,
        workflow_configurations=None,
    )

    mock_client = MagicMock(spec=WorkflowGeneratorModelClient)

    with (
        patch.object(harness.session_store, "get", AsyncMock(return_value=session)),
        patch.object(harness.session_store, "save", AsyncMock()),
        patch.object(
            harness,
            "load_catalog_snapshot",
            AsyncMock(return_value=MagicMock(node_types=[], tools=[], documents=[], credentials=[])),
        ),
        patch.object(
            harness,
            "compile_workflow_typescript",
            AsyncMock(return_value=(prepared, "const wf = ...")),
        ),
        patch.object(
            harness,
            "create_prepared_workflow",
            AsyncMock(return_value=workflow),
        ),
    ):
        updated, created = await harness.finalize_generation_session(
            user=user,
            session_id=session.session_id,
            model_client=mock_client,
        )

    assert created.id == 42
    assert updated.status == GenerationSessionStatus.COMPLETED
    assert updated.workflow_id == 42


def test_generation_session_routes_reject_unconfigured_model():
    app = _make_generation_app()
    client = TestClient(app)

    with patch(
        "api.routes.workflow_generation.create_generation_session",
        side_effect=__import__(
            "api.services.workflow.generation.harness",
            fromlist=["WorkflowGenerationError"],
        ).WorkflowGenerationError(
            "Workflow generator model is not configured.",
            status_code=503,
        ),
    ):
        response = client.post(
            "/workflow/generation/sessions",
            json={
                "call_type": "inbound",
                "use_case": "Support",
                "activity_description": "Handle support calls.",
            },
        )

    assert response.status_code == 503


def test_generation_session_routes_enforce_owner_on_message():
    app = _make_generation_app(_user(user_id=99))
    client = TestClient(app)

    with patch(
        "api.routes.workflow_generation.submit_generation_message",
        side_effect=__import__(
            "api.services.workflow.generation.harness",
            fromlist=["WorkflowGenerationError"],
        ).WorkflowGenerationError(
            "Generation session not found.",
            status_code=404,
        ),
    ):
        response = client.post(
            "/workflow/generation/sessions/other-session/messages",
            json={"content": "Required fields are name and email."},
        )

    assert response.status_code == 404


def test_create_template_route_uses_local_generator_not_mps():
    app = FastAPI()
    app.include_router(workflow_router)
    app.dependency_overrides[get_user] = lambda: _user()

    client = TestClient(app)
    workflow = SimpleNamespace(
        id=7,
        name="lead_intake",
        status="active",
        created_at=datetime.now(UTC),
        workflow_definition={"nodes": [], "edges": []},
        current_definition_id=1,
        template_context_variables=None,
        call_disposition_codes=None,
        workflow_configurations=None,
    )

    with patch(
        "api.routes.workflow.generate_workflow_one_shot",
        AsyncMock(return_value=workflow),
    ) as one_shot_mock:
        response = client.post(
            "/workflow/create/template",
            json={
                "call_type": "inbound",
                "use_case": "Lead intake",
                "activity_description": "Collect contact details.",
            },
        )

    assert response.status_code == 200
    assert response.json()["id"] == 7
    one_shot_mock.assert_awaited_once()

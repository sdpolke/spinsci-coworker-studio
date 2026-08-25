from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from api.mcp_server.tools.create_workflow import create_workflow
from api.services.workflow.authoring import AuthoringFailure


@pytest.mark.asyncio
async def test_create_workflow_rejects_duplicate_api_triggers():
    user = MagicMock()
    user.id = 1
    user.selected_organization_id = 1
    user.provider_id = "provider-1"

    with (
        patch(
            "api.mcp_server.tools.create_workflow.authenticate_mcp_request",
            AsyncMock(return_value=user),
        ),
        patch(
            "api.mcp_server.tools.create_workflow.prepare_workflow_from_code",
            AsyncMock(
                return_value=AuthoringFailure(
                    error_code="graph_validation",
                    message="Workflow may contain at most one API Trigger node.",
                )
            ),
        ),
        patch(
            "api.mcp_server.tools.create_workflow.create_prepared_workflow",
            AsyncMock(),
        ) as create_mock,
    ):
        result = await create_workflow(code="ignored")

    assert result["created"] is False
    assert result["error_code"] == "graph_validation"
    assert "at most one API Trigger" in result["error"]
    create_mock.assert_not_awaited()

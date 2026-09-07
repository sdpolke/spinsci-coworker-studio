"""Unit tests for the `validate_langgraph_endpoint` ARQ job.

Covers design.md's "Fix Implementation" step 4/5: every branch (discovery
failure, negotiation failure, and the success path) persists a
Validation_Report before returning, and an endpoint that no longer exists
returns early without writing one.
"""

from copy import deepcopy
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import api.tasks.langgraph_validation as job_module
from api.schemas.langgraph_integration import v1_0
from api.schemas.langgraph_integration.examples import EXECUTABLE_EXAMPLES
from api.services.langgraph_integration.configuration import (
    LangGraphFeatureConfiguration,
)
from api.services.langgraph_integration.conformance import ConformanceSuiteResult
from api.services.langgraph_integration.conformance.live import LiveEndpointEvidence
from api.services.langgraph_integration.conformance.platform import PlatformEvidence
from api.services.langgraph_integration.contract import (
    MatrixVersion,
    ProfileRequirements,
)
from api.services.langgraph_integration.discovery import CapabilitySelectionError
from api.services.langgraph_integration.gateway import (
    DiscoveryTimeoutError,
    InvalidManifestError,
    UnsafeDestinationError,
)

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _manifest(**overrides):
    payload = deepcopy(EXECUTABLE_EXAMPLES["1.0"]["manifest"])
    payload.update(overrides)
    return v1_0.CapabilityManifest.model_validate(payload)


def _matrix_row():
    matrix = MatrixVersion(
        matrix_version="2026-01",
        effective_date=NOW.date(),
        mural_release_version="1.44.0",
        supported_contract_versions=("1.0", "1.1"),
        profiles=(
            ProfileRequirements(
                profile="chat",
                required_invocation_modes=frozenset({"streaming"}),
                allowed_state_modes=frozenset({"mural_authoritative"}),
            ),
        ),
    )
    return SimpleNamespace(
        id=9,
        matrix_uuid="matrix-uuid",
        matrix=matrix.model_dump(mode="json"),
    )


def _endpoint(**overrides):
    values = {
        "id": 3,
        "endpoint_uuid": "endpoint-uuid",
        "organization_id": 11,
        "endpoint_url": "https://example.com",
        "credential_id": 4,
        "selected_profile": "chat",
        "selected_capabilities": ["streaming"],
        "lifecycle_status": "pending_validation",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _credential():
    return SimpleNamespace(
        id=4,
        organization_id=11,
        credential_type="bearer_token",
        credential_data={"token": "secret"},
    )


def _patch_common(monkeypatch, *, endpoint=None, matrix_row=None):
    monkeypatch.setattr(
        job_module.db_client,
        "get_langgraph_endpoint",
        AsyncMock(return_value=endpoint if endpoint is not None else _endpoint()),
    )
    monkeypatch.setattr(
        job_module.db_client,
        "list_langgraph_compatibility_matrices",
        AsyncMock(return_value=[matrix_row or _matrix_row()]),
    )
    monkeypatch.setattr(
        job_module.db_client,
        "get_langgraph_endpoint_credential",
        AsyncMock(return_value=_credential()),
    )
    monkeypatch.setattr(
        job_module,
        "get_langgraph_feature_configuration",
        AsyncMock(return_value=LangGraphFeatureConfiguration()),
    )
    insert_report = AsyncMock()
    monkeypatch.setattr(
        job_module.db_client, "insert_langgraph_validation_report", insert_report
    )
    return insert_report


@pytest.mark.asyncio
async def test_endpoint_not_found_returns_early_without_a_report(monkeypatch):
    monkeypatch.setattr(
        job_module.db_client, "get_langgraph_endpoint", AsyncMock(return_value=None)
    )
    insert_report = AsyncMock()
    monkeypatch.setattr(
        job_module.db_client, "insert_langgraph_validation_report", insert_report
    )

    await job_module.validate_langgraph_endpoint(
        {}, organization_id=11, endpoint_uuid="missing"
    )

    insert_report.assert_not_awaited()


@pytest.mark.parametrize(
    "exception",
    [
        DiscoveryTimeoutError("timed out"),
        InvalidManifestError(("body: invalid JSON",)),
        UnsafeDestinationError("unsafe destination"),
    ],
)
@pytest.mark.asyncio
async def test_discovery_failure_persists_a_failing_report_without_a_snapshot(
    monkeypatch, exception
):
    insert_report = _patch_common(monkeypatch)
    monkeypatch.setattr(
        job_module, "discover_manifest", AsyncMock(side_effect=exception)
    )

    await job_module.validate_langgraph_endpoint(
        {}, organization_id=11, endpoint_uuid="endpoint-uuid"
    )

    insert_report.assert_awaited_once()
    kwargs = insert_report.await_args.kwargs
    assert kwargs["capability_snapshot_id"] is None
    assert kwargs["status"] == "failed"
    assert kwargs["completed_at"] is not None
    assert kwargs["evidence"]["error_type"] == type(exception).__name__


@pytest.mark.asyncio
async def test_negotiation_failure_persists_a_failing_report_referencing_the_snapshot(
    monkeypatch,
):
    insert_report = _patch_common(monkeypatch)
    manifest = _manifest()
    monkeypatch.setattr(
        job_module,
        "discover_manifest",
        AsyncMock(
            return_value=SimpleNamespace(
                manifest=manifest,
                final_url="https://example.com",
                redirects=(),
                peer_address="1.2.3.4",
            )
        ),
    )
    snapshot = SimpleNamespace(id=55)
    monkeypatch.setattr(
        job_module,
        "record_capability_snapshot",
        AsyncMock(
            return_value=SimpleNamespace(
                snapshot=snapshot, changed=True, digest="d" * 64, normalized_manifest={}
            )
        ),
    )
    monkeypatch.setattr(
        job_module,
        "negotiate_capabilities",
        lambda **_: (_ for _ in ()).throw(
            CapabilitySelectionError(("undeclared profile: chat",))
        ),
    )

    await job_module.validate_langgraph_endpoint(
        {}, organization_id=11, endpoint_uuid="endpoint-uuid"
    )

    insert_report.assert_awaited_once()
    kwargs = insert_report.await_args.kwargs
    assert kwargs["capability_snapshot_id"] == 55
    assert kwargs["status"] == "failed"
    assert kwargs["evidence"]["negotiation_failed"] is True
    assert kwargs["evidence"]["reasons"] == ["undeclared profile: chat"]


def _suite_result(*, passed: bool) -> ConformanceSuiteResult:
    return ConformanceSuiteResult(
        suite_version="chat-1.0.0",
        fixture_digest="f" * 64,
        result_digest="r" * 64,
        passed=passed,
        results=(),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "passed,expected_status", [(True, "passed"), (False, "failed")]
)
async def test_successful_negotiation_persists_report_from_conformance_suite_result(
    monkeypatch, passed, expected_status
):
    insert_report = _patch_common(monkeypatch)
    manifest = _manifest()
    monkeypatch.setattr(
        job_module,
        "discover_manifest",
        AsyncMock(
            return_value=SimpleNamespace(
                manifest=manifest,
                final_url="https://example.com",
                redirects=(),
                peer_address="1.2.3.4",
            )
        ),
    )
    snapshot = SimpleNamespace(id=77)
    monkeypatch.setattr(
        job_module,
        "record_capability_snapshot",
        AsyncMock(
            return_value=SimpleNamespace(
                snapshot=snapshot, changed=True, digest="d" * 64, normalized_manifest={}
            )
        ),
    )
    negotiated = SimpleNamespace(
        contract_version="1.1",
        invocation_modes=frozenset({"streaming"}),
        features=frozenset(),
    )
    monkeypatch.setattr(job_module, "negotiate_capabilities", lambda **_: negotiated)
    suite_result = _suite_result(passed=passed)
    monkeypatch.setattr(job_module, "run_suite", lambda: suite_result)
    monkeypatch.setattr(
        job_module,
        "run_live_endpoint_evidence",
        AsyncMock(
            return_value=LiveEndpointEvidence(
                text_session_conformance=True,
                endpoint_state_continuity=False,
                checks=(),
            )
        ),
    )
    monkeypatch.setattr(
        job_module,
        "run_platform_evidence",
        AsyncMock(
            return_value=PlatformEvidence(
                cancellation_verified=True,
                recording_verified=True,
                checks=(),
            )
        ),
    )

    await job_module.validate_langgraph_endpoint(
        {}, organization_id=11, endpoint_uuid="endpoint-uuid"
    )

    insert_report.assert_awaited_once()
    kwargs = insert_report.await_args.kwargs
    assert kwargs["capability_snapshot_id"] == 77
    assert kwargs["status"] == expected_status
    assert kwargs["contract_version"] == "1.1"
    expected_suite_version = "chat-1.0.0+eligibility-1.0.0"
    expected_evidence = {
        "text_session_conformance": True,
        "accepted_transition": False,
        "endpoint_state_continuity": False,
        "cancellation_verified": True,
        "recording_verified": True,
    }
    assert kwargs["suite_version"] == expected_suite_version
    assert kwargs["evidence"] == expected_evidence
    assert kwargs["results"] == suite_result.persistence_results()
    assert kwargs["report_digest"] == job_module.deterministic_digest(
        {
            "capability_snapshot_id": 77,
            "compatibility_matrix_id": 9,
            "suite_version": expected_suite_version,
            "contract_version": "1.1",
            "selected_profile": "chat",
            "status": expected_status,
            "started_at": kwargs["started_at"].isoformat(),
            "completed_at": kwargs["completed_at"].isoformat(),
            "evidence": expected_evidence,
            "results": suite_result.persistence_results(),
        }
    )


def test_validate_langgraph_endpoint_registered_in_worker_functions():
    """The on-demand validation job must be registered in WorkerSettings.functions.

    Covers bugfix.md 3.7 / design.md step 7: `validate_langgraph_endpoint` is
    registered alongside the pre-existing functions, and the previously
    registered entries (including `sweep_langgraph_retention`) remain present.
    It must NOT be scheduled as a cron job.
    """
    from api.tasks.arq import WorkerSettings
    from api.tasks.campaign_tasks import process_campaign_batch, sync_campaign_source
    from api.tasks.function_names import FunctionNames
    from api.tasks.knowledge_base_processing import process_knowledge_base_document
    from api.tasks.langgraph_retention import sweep_langgraph_retention
    from api.tasks.langgraph_validation import validate_langgraph_endpoint
    from api.tasks.run_integrations import run_integrations_post_workflow_run
    from api.tasks.text_chat_inactivity import complete_inactive_text_chat_session
    from api.tasks.webhook_delivery import deliver_webhook
    from api.tasks.workflow_completion import process_workflow_completion

    functions = WorkerSettings.functions

    # The on-demand job uses ARQ's native per-function result policy: the
    # deterministic job ID deduplicates queued/running work, while completed
    # or failed validation attempts do not block an explicit retry.
    from arq.worker import Function

    validation_registrations = [
        entry
        for entry in functions
        if isinstance(entry, Function)
        and entry.coroutine is validate_langgraph_endpoint
    ]
    assert len(validation_registrations) == 1
    validation_registration = validation_registrations[0]
    assert validation_registration.name == FunctionNames.VALIDATE_LANGGRAPH_ENDPOINT
    assert validation_registration.keep_result_s == 0
    assert validation_registration.keep_result_forever is None

    # All pre-existing entries remain present and unchanged.
    expected_preexisting = [
        run_integrations_post_workflow_run,
        process_workflow_completion,
        sync_campaign_source,
        process_campaign_batch,
        process_knowledge_base_document,
        deliver_webhook,
        complete_inactive_text_chat_session,
        sweep_langgraph_retention,
    ]
    for fn in expected_preexisting:
        assert fn in functions

    # On-demand, not scheduled: it must not be wired into cron_jobs.
    from arq.cron import CronJob

    cron_coroutines = {
        job.coroutine for job in WorkerSettings.cron_jobs if isinstance(job, CronJob)
    }
    assert validate_langgraph_endpoint not in cron_coroutines

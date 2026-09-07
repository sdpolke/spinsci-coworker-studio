from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from hypothesis import given
from hypothesis import strategies as st

import api.routes.langgraph_endpoints as endpoint_routes
from api.routes.langgraph_endpoints import router
from api.services.auth.depends import get_user
from api.services.langgraph_integration.access_control import (
    LangGraphAuthorizationError,
    LangGraphPermission,
    LangGraphRole,
)
from api.services.langgraph_integration.configuration import (
    LangGraphFeatureConfiguration,
)
from api.services.langgraph_integration.endpoint_registration import (
    ActivationEvidenceError,
    FeatureDisabledError,
    activate_endpoint,
    request_validation,
    transition_endpoint,
)
from api.services.langgraph_integration.lifecycle import (
    EndpointLifecycle,
    InvalidLifecycleTransition,
    can_transition,
    permits_new_runs,
    require_transition,
)
from api.tasks.function_names import FunctionNames

NOW = datetime(2026, 1, 1, tzinfo=UTC)
EXPECTED_TRANSITIONS = {
    "pending_validation": {"validation_only", "active", "incompatible", "retired"},
    "validation_only": {
        "pending_validation",
        "active",
        "disabled",
        "incompatible",
        "retired",
    },
    "active": {"pending_validation", "degraded", "disabled", "incompatible", "retired"},
    "degraded": {"pending_validation", "active", "disabled", "incompatible", "retired"},
    "disabled": {"pending_validation", "retired"},
    "incompatible": {"pending_validation", "retired"},
    "retired": set(),
}


def _user():
    return SimpleNamespace(
        id=7,
        selected_organization_id=11,
        langgraph_role="organization_admin",
    )


def _client():
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_user] = _user
    return TestClient(app)


def test_lifecycle_transition_table_is_explicit_and_closed():
    statuses = {status.value for status in EndpointLifecycle}
    for current in statuses:
        for target in statuses:
            assert can_transition(current, target) is (
                target in EXPECTED_TRANSITIONS[current]
            )
    with pytest.raises(InvalidLifecycleTransition):
        require_transition("retired", "active")


def test_only_active_endpoints_permit_new_runs():
    for status in EndpointLifecycle:
        assert permits_new_runs(status.value) is (status is EndpointLifecycle.ACTIVE)


@pytest.mark.asyncio
async def test_activation_requires_current_passing_snapshot_evidence(monkeypatch):
    endpoint = SimpleNamespace(
        endpoint_uuid="endpoint-uuid",
        lifecycle_status="validation_only",
        selected_profile="chat",
    )
    snapshot = SimpleNamespace(id=9)
    report = SimpleNamespace(
        status="failed",
        completed_at=NOW,
        capability_snapshot_id=9,
        selected_profile="chat",
        evidence={},
    )
    cas = AsyncMock()
    monkeypatch.setattr(
        "api.services.langgraph_integration.endpoint_registration.get_langgraph_feature_configuration",
        AsyncMock(
            return_value=LangGraphFeatureConfiguration(
                enabled=True,
                experimental_acknowledged_at=NOW,
                experimental_acknowledged_by=7,
            )
        ),
    )
    monkeypatch.setattr(
        "api.services.langgraph_integration.endpoint_registration.db_client.get_current_langgraph_activation_evidence",
        AsyncMock(return_value=(endpoint, report, snapshot)),
    )
    monkeypatch.setattr(
        "api.services.langgraph_integration.endpoint_registration.db_client.compare_and_set_langgraph_lifecycle",
        cas,
    )

    with pytest.raises(ActivationEvidenceError, match="not passing"):
        await activate_endpoint(
            organization_id=11,
            endpoint_uuid="endpoint-uuid",
            role=endpoint_routes.LangGraphRole.ORGANIZATION_ADMIN,
        )
    cas.assert_not_awaited()


@pytest.mark.asyncio
async def test_degraded_reactivation_requires_current_health(monkeypatch):
    endpoint = SimpleNamespace(
        endpoint_uuid="endpoint-uuid",
        lifecycle_status="degraded",
        selected_profile="chat",
    )
    snapshot = SimpleNamespace(id=9)
    report = SimpleNamespace(
        status="passed",
        completed_at=NOW,
        capability_snapshot_id=9,
        selected_profile="chat",
        evidence={"current_health_healthy": False},
    )
    monkeypatch.setattr(
        "api.services.langgraph_integration.endpoint_registration.get_langgraph_feature_configuration",
        AsyncMock(
            return_value=LangGraphFeatureConfiguration(
                enabled=True,
                experimental_acknowledged_at=NOW,
                experimental_acknowledged_by=7,
            )
        ),
    )
    monkeypatch.setattr(
        "api.services.langgraph_integration.endpoint_registration.db_client.get_current_langgraph_activation_evidence",
        AsyncMock(return_value=(endpoint, report, snapshot)),
    )

    with pytest.raises(ActivationEvidenceError, match="health"):
        await activate_endpoint(
            organization_id=11,
            endpoint_uuid="endpoint-uuid",
            role=endpoint_routes.LangGraphRole.ORGANIZATION_ADMIN,
        )


@pytest.mark.asyncio
async def test_request_validation_dispatches_when_transition_needed_fix_check(
    monkeypatch,
):
    """Fix-checking test (task 7, Property 1) — repurposed from the task-1 exploration test.

    This is the SAME test case that, on unfixed code, encoded the *defect* (asserting
    `enqueue_job` was never awaited). Its assertions are now INVERTED to match the fixed
    behavior per design.md's "Fix Checking" pseudocode: for an endpoint in
    `validation_only`, the fixed `request_validation()` transitions to `pending_validation`
    AND enqueues the validation job exactly once with the deterministic job id
    `f"langgraph_validate:{endpoint_uuid}"` (bugfix.md 2.1).
    """
    endpoint = SimpleNamespace(
        endpoint_uuid="endpoint-uuid",
        lifecycle_status="validation_only",
        selected_profile="chat",
    )
    get_endpoint = AsyncMock(return_value=endpoint)
    cas = AsyncMock(return_value=True)
    insert_report = AsyncMock()
    enqueue_job = AsyncMock()
    monkeypatch.setattr(
        "api.services.langgraph_integration.endpoint_registration.db_client.get_langgraph_endpoint",
        get_endpoint,
    )
    monkeypatch.setattr(
        "api.services.langgraph_integration.endpoint_registration.db_client.compare_and_set_langgraph_lifecycle",
        cas,
    )
    monkeypatch.setattr(
        "api.services.langgraph_integration.endpoint_registration.db_client.insert_langgraph_validation_report",
        insert_report,
    )
    monkeypatch.setattr(
        "api.services.langgraph_integration.endpoint_registration.get_langgraph_feature_configuration",
        AsyncMock(
            return_value=LangGraphFeatureConfiguration(
                enabled=True,
                experimental_acknowledged_at=NOW,
                experimental_acknowledged_by=7,
            )
        ),
    )
    monkeypatch.setattr("api.tasks.arq.enqueue_job", enqueue_job)

    await request_validation(
        organization_id=11,
        endpoint_uuid="endpoint-uuid",
        role=endpoint_routes.LangGraphRole.ORGANIZATION_ADMIN,
    )

    enqueue_job.assert_awaited_once_with(
        FunctionNames.VALIDATE_LANGGRAPH_ENDPOINT,
        11,
        "endpoint-uuid",
        _job_id="langgraph_validate:endpoint-uuid",
    )


@pytest.mark.asyncio
async def test_request_validation_dispatches_when_already_pending_fix_check(
    monkeypatch,
):
    """Fix-checking test (task 7, Property 1) — repurposed from the task-1 exploration test.

    This is the SAME test case that, on unfixed code, encoded the *defect* (asserting
    `enqueue_job` was never awaited for an already-`pending_validation` endpoint). Its
    assertions are now INVERTED per design.md's "Fix Checking" pseudocode: a retry against
    an endpoint already in `pending_validation` (re-)dispatches the validation job again
    with the same deterministic job id `f"langgraph_validate:{endpoint_uuid}"`
    (bugfix.md 2.2, re-dispatch on retry).
    """
    endpoint = SimpleNamespace(
        endpoint_uuid="endpoint-uuid",
        lifecycle_status="pending_validation",
        selected_profile="chat",
    )
    get_endpoint = AsyncMock(return_value=endpoint)
    cas = AsyncMock(return_value=True)
    insert_report = AsyncMock()
    enqueue_job = AsyncMock()
    monkeypatch.setattr(
        "api.services.langgraph_integration.endpoint_registration.db_client.get_langgraph_endpoint",
        get_endpoint,
    )
    monkeypatch.setattr(
        "api.services.langgraph_integration.endpoint_registration.db_client.compare_and_set_langgraph_lifecycle",
        cas,
    )
    monkeypatch.setattr(
        "api.services.langgraph_integration.endpoint_registration.db_client.insert_langgraph_validation_report",
        insert_report,
    )
    monkeypatch.setattr(
        "api.services.langgraph_integration.endpoint_registration.get_langgraph_feature_configuration",
        AsyncMock(
            return_value=LangGraphFeatureConfiguration(
                enabled=True,
                experimental_acknowledged_at=NOW,
                experimental_acknowledged_by=7,
            )
        ),
    )
    monkeypatch.setattr("api.tasks.arq.enqueue_job", enqueue_job)

    await request_validation(
        organization_id=11,
        endpoint_uuid="endpoint-uuid",
        role=endpoint_routes.LangGraphRole.ORGANIZATION_ADMIN,
    )

    enqueue_job.assert_awaited_once_with(
        FunctionNames.VALIDATE_LANGGRAPH_ENDPOINT,
        11,
        "endpoint-uuid",
        _job_id="langgraph_validate:endpoint-uuid",
    )


@pytest.mark.asyncio
async def test_request_validation_denies_role_without_validate_permission(monkeypatch):
    """Preservation test (task 2, Property 2; bugfix.md 3.1).

    Observed on unfixed code: a role lacking `LangGraphPermission.VALIDATE`
    (e.g. `member`) calling `request_validation` raises `LangGraphAuthorizationError`
    before touching the DB or enqueueing any work.
    """
    endpoint = SimpleNamespace(
        endpoint_uuid="endpoint-uuid",
        lifecycle_status="validation_only",
        selected_profile="chat",
    )
    get_endpoint = AsyncMock(return_value=endpoint)
    cas = AsyncMock()
    insert_report = AsyncMock()
    enqueue_job = AsyncMock()
    monkeypatch.setattr(
        "api.services.langgraph_integration.endpoint_registration.db_client.get_langgraph_endpoint",
        get_endpoint,
    )
    monkeypatch.setattr(
        "api.services.langgraph_integration.endpoint_registration.db_client.compare_and_set_langgraph_lifecycle",
        cas,
    )
    monkeypatch.setattr(
        "api.services.langgraph_integration.endpoint_registration.db_client.insert_langgraph_validation_report",
        insert_report,
    )
    monkeypatch.setattr("api.tasks.arq.enqueue_job", enqueue_job)

    with pytest.raises(LangGraphAuthorizationError):
        await request_validation(
            organization_id=11,
            endpoint_uuid="endpoint-uuid",
            role=LangGraphRole.MEMBER,
        )

    cas.assert_not_awaited()
    insert_report.assert_not_awaited()
    enqueue_job.assert_not_awaited()


@pytest.mark.asyncio
async def test_request_validation_denies_disabled_feature_before_lifecycle_work(
    monkeypatch,
):
    """Preservation test (task 2, Property 2; bugfix.md 3.2).

    Observed on unfixed code: `require_feature_enabled` raising `FeatureDisabledError`
    short-circuits `request_validation` before any lifecycle transition or dispatch work.
    """
    endpoint = SimpleNamespace(
        endpoint_uuid="endpoint-uuid",
        lifecycle_status="validation_only",
        selected_profile="chat",
    )
    get_endpoint = AsyncMock(return_value=endpoint)
    cas = AsyncMock()
    insert_report = AsyncMock()
    enqueue_job = AsyncMock()
    monkeypatch.setattr(
        "api.services.langgraph_integration.endpoint_registration.db_client.get_langgraph_endpoint",
        get_endpoint,
    )
    monkeypatch.setattr(
        "api.services.langgraph_integration.endpoint_registration.db_client.compare_and_set_langgraph_lifecycle",
        cas,
    )
    monkeypatch.setattr(
        "api.services.langgraph_integration.endpoint_registration.db_client.insert_langgraph_validation_report",
        insert_report,
    )
    monkeypatch.setattr(
        "api.services.langgraph_integration.endpoint_registration.get_langgraph_feature_configuration",
        AsyncMock(
            return_value=LangGraphFeatureConfiguration(
                enabled=False,
                experimental_acknowledged_at=None,
                experimental_acknowledged_by=None,
            )
        ),
    )
    monkeypatch.setattr("api.tasks.arq.enqueue_job", enqueue_job)

    with pytest.raises(FeatureDisabledError):
        await request_validation(
            organization_id=11,
            endpoint_uuid="endpoint-uuid",
            role=LangGraphRole.ORGANIZATION_ADMIN,
        )

    cas.assert_not_awaited()
    insert_report.assert_not_awaited()
    enqueue_job.assert_not_awaited()


# Feature: langgraph-validate-endpoint-noop, Property 2: Preservation - lifecycle
# transition table is unaffected by the validate-endpoint dispatch fix (bugfix.md 3.3).
@given(
    role=st.sampled_from(list(LangGraphRole)),
    target_status=st.sampled_from(sorted(EndpointLifecycle)),
)
def test_property_2_lifecycle_transition_table_matches_expected_transitions(
    role, target_status
):
    for current in sorted(EndpointLifecycle):
        expected_allowed = target_status.value in EXPECTED_TRANSITIONS[current.value]
        assert can_transition(current.value, target_status.value) is expected_allowed
        if current.value == target_status.value:
            continue
        if expected_allowed:
            continue
        with pytest.raises(InvalidLifecycleTransition):
            require_transition(current.value, target_status.value)


@pytest.mark.asyncio
async def test_transition_endpoint_lost_compare_and_set_race_raises(monkeypatch):
    """Preservation test (task 2, Property 2; bugfix.md 3.4).

    A lost `compare_and_set_langgraph_lifecycle` race (mocked to return `False`)
    still raises `InvalidLifecycleTransition` from `transition_endpoint`, unchanged
    from today's behavior.
    """
    endpoint = SimpleNamespace(
        endpoint_uuid="endpoint-uuid",
        lifecycle_status="validation_only",
        selected_profile="chat",
    )
    monkeypatch.setattr(
        "api.services.langgraph_integration.endpoint_registration.db_client.get_langgraph_endpoint",
        AsyncMock(return_value=endpoint),
    )
    monkeypatch.setattr(
        "api.services.langgraph_integration.endpoint_registration.db_client.compare_and_set_langgraph_lifecycle",
        AsyncMock(return_value=False),
    )
    monkeypatch.setattr(
        "api.services.langgraph_integration.endpoint_registration.get_langgraph_feature_configuration",
        AsyncMock(
            return_value=LangGraphFeatureConfiguration(
                enabled=True,
                experimental_acknowledged_at=NOW,
                experimental_acknowledged_by=7,
            )
        ),
    )

    with pytest.raises(InvalidLifecycleTransition):
        await transition_endpoint(
            organization_id=11,
            endpoint_uuid="endpoint-uuid",
            role=LangGraphRole.ORGANIZATION_ADMIN,
            target_status="pending_validation",
            permission=LangGraphPermission.VALIDATE,
        )


def test_validation_history_and_matrix_apis_return_immutable_ordered_records(
    monkeypatch,
):
    client = _client()
    report = SimpleNamespace(
        report_uuid="report-2",
        suite_version="suite-1",
        contract_version="1.1",
        selected_profile="chat",
        status="passed",
        started_at=NOW,
        completed_at=NOW,
        evidence={"all_required_passed": True},
        report_digest="a" * 64,
        created_at=NOW,
    )
    snapshot = SimpleNamespace(snapshot_uuid="snapshot-2")
    matrix = SimpleNamespace(
        id=2,
        matrix_uuid="matrix-2",
        matrix_version="2",
        effective_at=NOW,
        mural_release_version="2.0",
        matrix={"versions": ["1.1"]},
        published_at=NOW,
    )
    result = SimpleNamespace(
        test_identifier="streaming",
        test_version="1",
        required=True,
        outcome="passed",
        duration_ms=10,
        measurements={},
        redacted_error=None,
    )
    prior_matrix = SimpleNamespace(
        id=1,
        matrix_uuid="matrix-1",
        matrix_version="1",
        effective_at=datetime(2025, 1, 1, tzinfo=UTC),
        mural_release_version="1.0",
        matrix={"versions": ["1.0"]},
        published_at=datetime(2025, 1, 1, tzinfo=UTC),
    )
    history = [(report, snapshot, matrix, [result])]
    history_mock = AsyncMock(return_value=history)
    matrix_mock = AsyncMock(return_value=[matrix, prior_matrix])
    monkeypatch.setattr(
        endpoint_routes.db_client, "list_langgraph_validation_history", history_mock
    )
    monkeypatch.setattr(
        endpoint_routes.db_client, "list_langgraph_compatibility_matrices", matrix_mock
    )

    reports_response = client.get(
        "/langgraph-endpoints/endpoint-uuid/validation-reports"
    )
    assert reports_response.status_code == 200
    assert reports_response.json()[0]["report_uuid"] == "report-2"
    assert reports_response.json()[0]["results"][0]["outcome"] == "passed"
    assert history == [(report, snapshot, matrix, [result])]

    matrices_response = client.get("/langgraph-compatibility-matrices")
    assert matrices_response.status_code == 200
    matrices = matrices_response.json()
    assert [item["matrix_version"] for item in matrices] == ["2", "1"]
    assert [item["current"] for item in matrices] == [True, False]


def test_delete_api_surfaces_reference_aware_retirement(monkeypatch):
    client = _client()
    retire = AsyncMock(return_value="retired")
    monkeypatch.setattr(endpoint_routes, "delete_or_retire_endpoint", retire)

    response = client.delete("/langgraph-endpoints/referenced")

    assert response.status_code == 200
    assert response.json() == {
        "endpoint_uuid": "referenced",
        "outcome": "retired",
    }


# ---------------------------------------------------------------------------
# Task 6 unit tests: `_dispatch_validation` and its wiring into
# `request_validation` (design.md "Fix Implementation" steps 1-2; bugfix.md
# 2.1, 2.2).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dispatch_validation_enqueues_with_deterministic_job_id(monkeypatch):
    """`_dispatch_validation` enqueues the validate job with an endpoint-scoped id."""
    from api.services.langgraph_integration.endpoint_registration import (
        _dispatch_validation,
    )
    from api.tasks.function_names import FunctionNames

    enqueue_job = AsyncMock()
    monkeypatch.setattr("api.tasks.arq.enqueue_job", enqueue_job)

    await _dispatch_validation(11, "endpoint-uuid")

    enqueue_job.assert_awaited_once_with(
        FunctionNames.VALIDATE_LANGGRAPH_ENDPOINT,
        11,
        "endpoint-uuid",
        _job_id="langgraph_validate:endpoint-uuid",
    )


@pytest.mark.asyncio
async def test_request_validation_dispatches_when_transition_needed(monkeypatch):
    """Fix (bugfix.md 2.1): the transition branch dispatches validation work."""
    endpoint = SimpleNamespace(
        endpoint_uuid="endpoint-uuid",
        lifecycle_status="validation_only",
        selected_profile="chat",
    )
    monkeypatch.setattr(
        "api.services.langgraph_integration.endpoint_registration.db_client.get_langgraph_endpoint",
        AsyncMock(return_value=endpoint),
    )
    monkeypatch.setattr(
        "api.services.langgraph_integration.endpoint_registration.db_client.compare_and_set_langgraph_lifecycle",
        AsyncMock(return_value=True),
    )
    monkeypatch.setattr(
        "api.services.langgraph_integration.endpoint_registration.get_langgraph_feature_configuration",
        AsyncMock(
            return_value=LangGraphFeatureConfiguration(
                enabled=True,
                experimental_acknowledged_at=NOW,
                experimental_acknowledged_by=7,
            )
        ),
    )
    dispatch = AsyncMock()
    monkeypatch.setattr(
        "api.services.langgraph_integration.endpoint_registration._dispatch_validation",
        dispatch,
    )

    await request_validation(
        organization_id=11,
        endpoint_uuid="endpoint-uuid",
        role=LangGraphRole.ORGANIZATION_ADMIN,
    )

    dispatch.assert_awaited_once_with(11, "endpoint-uuid")


@pytest.mark.asyncio
async def test_request_validation_dispatches_when_already_pending(monkeypatch):
    """Fix (bugfix.md 2.2): the already-pending branch (re-)dispatches on retry."""
    endpoint = SimpleNamespace(
        endpoint_uuid="endpoint-uuid",
        lifecycle_status="pending_validation",
        selected_profile="chat",
    )
    monkeypatch.setattr(
        "api.services.langgraph_integration.endpoint_registration.db_client.get_langgraph_endpoint",
        AsyncMock(return_value=endpoint),
    )
    monkeypatch.setattr(
        "api.services.langgraph_integration.endpoint_registration.get_langgraph_feature_configuration",
        AsyncMock(
            return_value=LangGraphFeatureConfiguration(
                enabled=True,
                experimental_acknowledged_at=NOW,
                experimental_acknowledged_by=7,
            )
        ),
    )
    dispatch = AsyncMock()
    monkeypatch.setattr(
        "api.services.langgraph_integration.endpoint_registration._dispatch_validation",
        dispatch,
    )

    await request_validation(
        organization_id=11,
        endpoint_uuid="endpoint-uuid",
        role=LangGraphRole.ORGANIZATION_ADMIN,
    )

    dispatch.assert_awaited_once_with(11, "endpoint-uuid")


@pytest.mark.asyncio
async def test_request_validation_no_dispatch_when_permission_denied(monkeypatch):
    """Fix preserves 3.1: no dispatch when `require_permission` raises."""
    endpoint = SimpleNamespace(
        endpoint_uuid="endpoint-uuid",
        lifecycle_status="validation_only",
        selected_profile="chat",
    )
    monkeypatch.setattr(
        "api.services.langgraph_integration.endpoint_registration.db_client.get_langgraph_endpoint",
        AsyncMock(return_value=endpoint),
    )
    monkeypatch.setattr(
        "api.services.langgraph_integration.endpoint_registration.get_langgraph_feature_configuration",
        AsyncMock(
            return_value=LangGraphFeatureConfiguration(
                enabled=True,
                experimental_acknowledged_at=NOW,
                experimental_acknowledged_by=7,
            )
        ),
    )
    dispatch = AsyncMock()
    monkeypatch.setattr(
        "api.services.langgraph_integration.endpoint_registration._dispatch_validation",
        dispatch,
    )

    with pytest.raises(LangGraphAuthorizationError):
        await request_validation(
            organization_id=11,
            endpoint_uuid="endpoint-uuid",
            role=LangGraphRole.MEMBER,
        )

    dispatch.assert_not_awaited()


@pytest.mark.asyncio
async def test_request_validation_no_dispatch_when_feature_disabled(monkeypatch):
    """Fix preserves 3.2: no dispatch when `require_feature_enabled` raises."""
    endpoint = SimpleNamespace(
        endpoint_uuid="endpoint-uuid",
        lifecycle_status="validation_only",
        selected_profile="chat",
    )
    monkeypatch.setattr(
        "api.services.langgraph_integration.endpoint_registration.db_client.get_langgraph_endpoint",
        AsyncMock(return_value=endpoint),
    )
    monkeypatch.setattr(
        "api.services.langgraph_integration.endpoint_registration.get_langgraph_feature_configuration",
        AsyncMock(
            return_value=LangGraphFeatureConfiguration(
                enabled=False,
                experimental_acknowledged_at=None,
                experimental_acknowledged_by=None,
            )
        ),
    )
    dispatch = AsyncMock()
    monkeypatch.setattr(
        "api.services.langgraph_integration.endpoint_registration._dispatch_validation",
        dispatch,
    )

    with pytest.raises(FeatureDisabledError):
        await request_validation(
            organization_id=11,
            endpoint_uuid="endpoint-uuid",
            role=LangGraphRole.ORGANIZATION_ADMIN,
        )

    dispatch.assert_not_awaited()


@pytest.mark.asyncio
async def test_request_validation_no_dispatch_when_transition_raises(monkeypatch):
    """Fix (bugfix.md 3.3/3.4): a transition failure propagates and does NOT dispatch."""
    endpoint = SimpleNamespace(
        endpoint_uuid="endpoint-uuid",
        lifecycle_status="validation_only",
        selected_profile="chat",
    )
    monkeypatch.setattr(
        "api.services.langgraph_integration.endpoint_registration.db_client.get_langgraph_endpoint",
        AsyncMock(return_value=endpoint),
    )
    # Lost compare-and-set race => transition_endpoint raises InvalidLifecycleTransition.
    monkeypatch.setattr(
        "api.services.langgraph_integration.endpoint_registration.db_client.compare_and_set_langgraph_lifecycle",
        AsyncMock(return_value=False),
    )
    monkeypatch.setattr(
        "api.services.langgraph_integration.endpoint_registration.get_langgraph_feature_configuration",
        AsyncMock(
            return_value=LangGraphFeatureConfiguration(
                enabled=True,
                experimental_acknowledged_at=NOW,
                experimental_acknowledged_by=7,
            )
        ),
    )
    dispatch = AsyncMock()
    monkeypatch.setattr(
        "api.services.langgraph_integration.endpoint_registration._dispatch_validation",
        dispatch,
    )

    with pytest.raises(InvalidLifecycleTransition):
        await request_validation(
            organization_id=11,
            endpoint_uuid="endpoint-uuid",
            role=LangGraphRole.ORGANIZATION_ADMIN,
        )

    dispatch.assert_not_awaited()


# ---------------------------------------------------------------------------
# Task 7 integration-style fix check (Property 1; bugfix.md 2.3): running the
# job that `request_validation` enqueues (simulating ARQ execution) against
# mocked db_client/gateway/discovery/conformance.runner leaves a
# `Validation_Report` behind for the endpoint.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_enqueued_validate_job_persists_a_validation_report(monkeypatch):
    """Fix check (bugfix.md 2.3): the enqueued job creates a Validation_Report.

    Runs `validate_langgraph_endpoint` directly (as ARQ would) against mocked
    `db_client`, `gateway.discover_manifest`, `discovery`, and
    `conformance.runner`, and asserts `db_client.insert_langgraph_validation_report`
    is awaited — i.e. a `Validation_Report` now exists for the endpoint that
    `get_current_langgraph_activation_evidence` can retrieve.
    """
    from copy import deepcopy

    import api.tasks.langgraph_validation as job_module
    from api.schemas.langgraph_integration import v1_0
    from api.schemas.langgraph_integration.examples import EXECUTABLE_EXAMPLES
    from api.services.langgraph_integration.configuration import (
        LangGraphFeatureConfiguration as JobFeatureConfiguration,
    )
    from api.services.langgraph_integration.conformance import ConformanceSuiteResult
    from api.services.langgraph_integration.conformance.live import LiveEndpointEvidence
    from api.services.langgraph_integration.conformance.platform import PlatformEvidence
    from api.services.langgraph_integration.contract import (
        MatrixVersion,
        ProfileRequirements,
    )

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
    matrix_row = SimpleNamespace(
        id=9, matrix_uuid="matrix-uuid", matrix=matrix.model_dump(mode="json")
    )
    endpoint = SimpleNamespace(
        id=3,
        endpoint_uuid="endpoint-uuid",
        organization_id=11,
        endpoint_url="https://example.com",
        credential_id=4,
        selected_profile="chat",
        selected_capabilities=["streaming"],
        lifecycle_status="pending_validation",
    )
    credential = SimpleNamespace(
        id=4,
        organization_id=11,
        credential_type="bearer_token",
        credential_data={"token": "secret"},
    )

    monkeypatch.setattr(
        job_module.db_client,
        "get_langgraph_endpoint",
        AsyncMock(return_value=endpoint),
    )
    monkeypatch.setattr(
        job_module.db_client,
        "list_langgraph_compatibility_matrices",
        AsyncMock(return_value=[matrix_row]),
    )
    monkeypatch.setattr(
        job_module.db_client,
        "get_langgraph_endpoint_credential",
        AsyncMock(return_value=credential),
    )
    monkeypatch.setattr(
        job_module,
        "get_langgraph_feature_configuration",
        AsyncMock(return_value=JobFeatureConfiguration()),
    )
    insert_report = AsyncMock()
    monkeypatch.setattr(
        job_module.db_client, "insert_langgraph_validation_report", insert_report
    )
    monkeypatch.setattr(job_module, "build_auth_header", lambda credential: {})
    manifest = v1_0.CapabilityManifest.model_validate(
        deepcopy(EXECUTABLE_EXAMPLES["1.0"]["manifest"])
    )
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
    monkeypatch.setattr(
        job_module,
        "record_capability_snapshot",
        AsyncMock(
            return_value=SimpleNamespace(
                snapshot=SimpleNamespace(id=77),
                changed=True,
                digest="d" * 64,
                normalized_manifest={},
            )
        ),
    )
    monkeypatch.setattr(
        job_module,
        "negotiate_capabilities",
        lambda **_: SimpleNamespace(
            contract_version="1.1",
            invocation_modes=frozenset({"streaming"}),
            features=frozenset(),
        ),
    )
    monkeypatch.setattr(
        job_module,
        "run_suite",
        lambda: ConformanceSuiteResult(
            suite_version="chat-1.0.0",
            fixture_digest="f" * 64,
            result_digest="r" * 64,
            passed=True,
            results=(),
        ),
    )
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
    assert kwargs["registration_id"] == 3
    assert kwargs["capability_snapshot_id"] == 77
    assert kwargs["status"] == "passed"
    assert kwargs["completed_at"] is not None


# ---------------------------------------------------------------------------
# Task 9 idempotent duplicate-dispatch test (bugfix.md 2.2; design.md
# Non-Goals "Idempotency is best-effort duplicate-suppression"): two rapid
# `request_validation` calls for the same endpoint each enqueue the validation
# job with the IDENTICAL deterministic job id `f"langgraph_validate:{uuid}"`.
# ARQ's own duplicate-job-id collapsing is NOT exercised here (ARQ is not run
# in these unit tests) — we only assert the fixed code always passes the same
# job id, which is what makes rapid duplicate "Validate" clicks idempotent.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rapid_duplicate_validate_calls_use_identical_deterministic_job_id(
    monkeypatch,
):
    """Two rapid validate calls enqueue with the same deterministic job id."""
    endpoint = SimpleNamespace(
        endpoint_uuid="endpoint-uuid",
        lifecycle_status="pending_validation",
        selected_profile="chat",
    )
    get_endpoint = AsyncMock(return_value=endpoint)
    cas = AsyncMock(return_value=True)
    insert_report = AsyncMock()
    enqueue_job = AsyncMock()
    monkeypatch.setattr(
        "api.services.langgraph_integration.endpoint_registration.db_client.get_langgraph_endpoint",
        get_endpoint,
    )
    monkeypatch.setattr(
        "api.services.langgraph_integration.endpoint_registration.db_client.compare_and_set_langgraph_lifecycle",
        cas,
    )
    monkeypatch.setattr(
        "api.services.langgraph_integration.endpoint_registration.db_client.insert_langgraph_validation_report",
        insert_report,
    )
    monkeypatch.setattr(
        "api.services.langgraph_integration.endpoint_registration.get_langgraph_feature_configuration",
        AsyncMock(
            return_value=LangGraphFeatureConfiguration(
                enabled=True,
                experimental_acknowledged_at=NOW,
                experimental_acknowledged_by=7,
            )
        ),
    )
    monkeypatch.setattr("api.tasks.arq.enqueue_job", enqueue_job)

    # Two rapid "Validate" clicks for the same endpoint.
    for _ in range(2):
        await request_validation(
            organization_id=11,
            endpoint_uuid="endpoint-uuid",
            role=endpoint_routes.LangGraphRole.ORGANIZATION_ADMIN,
        )

    expected_job_id = "langgraph_validate:endpoint-uuid"
    assert enqueue_job.await_count == 2
    observed_job_ids = [call.kwargs["_job_id"] for call in enqueue_job.await_args_list]
    # Both calls pass the identical endpoint-scoped deterministic job id; ARQ
    # collapses the duplicate at the queue level (not exercised in this unit test).
    assert observed_job_ids == [expected_job_id, expected_job_id]

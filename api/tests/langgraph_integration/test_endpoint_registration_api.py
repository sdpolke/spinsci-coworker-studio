from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

import api.routes.langgraph_endpoints as endpoint_routes
from api.routes.langgraph_endpoints import router
from api.schemas.langgraph_integration.endpoints import EndpointCreateRequest
from api.services.auth.depends import get_user
from api.services.langgraph_integration.configuration import (
    LangGraphFeatureConfiguration,
)
from api.services.langgraph_integration.endpoint_registration import (
    CredentialOwnershipError,
    FeatureDisabledError,
    create_endpoint,
)

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _user(organization_id=11, role="organization_admin"):
    return SimpleNamespace(
        id=7,
        selected_organization_id=organization_id,
        langgraph_role=role,
    )


def _endpoint(**overrides):
    values = {
        "id": 1,
        "endpoint_uuid": "endpoint-uuid",
        "organization_id": 11,
        "name": "Support",
        "endpoint_url": "https://example.com",
        "credential_id": 4,
        "selected_profile": "chat",
        "selected_capabilities": ["streaming"],
        "lifecycle_status": "pending_validation",
        "current_validation_report_id": None,
        "current_capability_snapshot_id": None,
        "private_network_enabled": False,
        "created_at": NOW,
        "updated_at": NOW,
        "retired_at": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _credential(organization_id=11):
    return SimpleNamespace(
        id=4,
        organization_id=organization_id,
        credential_uuid="credential-uuid",
        credential_type="bearer_token",
        credential_data={"token": "never-return-this-secret"},
        updated_at=NOW,
    )


def _view(endpoint=None, credential=None, snapshot=None, report=None):
    return endpoint or _endpoint(), credential or _credential(), snapshot, report


def _client(user=None):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_user] = lambda: user or _user()
    return TestClient(app)


def _create_payload(endpoint_url="https://example.com"):
    return {
        "name": "Support",
        "endpoint_url": endpoint_url,
        "credential_uuid": "credential-uuid",
        "selected_profile": "chat",
        "selected_capabilities": ["streaming"],
    }


def test_endpoint_url_accepts_exactly_2048_characters_and_rejects_2049():
    prefix = "https://example.com/"
    exact = prefix + "a" * (2048 - len(prefix))
    request = EndpointCreateRequest.model_validate(_create_payload(exact))
    assert len(str(request.endpoint_url)) == 2048

    with pytest.raises(ValidationError, match="2048"):
        EndpointCreateRequest.model_validate(_create_payload(exact + "a"))


def test_create_list_detail_update_delete_and_masked_projection(monkeypatch):
    client = _client()
    created = _endpoint()
    updated = _endpoint(name="Updated")
    create_mock = AsyncMock(return_value=created)
    update_mock = AsyncMock(return_value=updated)
    delete_mock = AsyncMock(return_value="deleted")
    views = [_view(created), _view(created), _view(updated)]

    monkeypatch.setattr(endpoint_routes, "create_endpoint", create_mock)
    monkeypatch.setattr(endpoint_routes, "update_endpoint", update_mock)
    monkeypatch.setattr(endpoint_routes, "delete_or_retire_endpoint", delete_mock)
    monkeypatch.setattr(
        endpoint_routes.db_client,
        "get_langgraph_endpoint_management_view",
        AsyncMock(side_effect=views),
    )
    monkeypatch.setattr(
        endpoint_routes.db_client,
        "list_langgraph_endpoint_management_views",
        AsyncMock(return_value=[_view(created)]),
    )

    create_response = client.post("/langgraph-endpoints", json=_create_payload())
    assert create_response.status_code == 201
    body = create_response.json()
    assert body["credential"] == {
        "credential_type": "bearer_token",
        "reference_id": "credential-uuid",
        "last_updated_at": "2026-01-01T00:00:00Z",
    }
    assert "credential_data" not in body
    assert "never-return-this-secret" not in create_response.text

    list_response = client.get("/langgraph-endpoints")
    assert list_response.status_code == 200
    assert [item["endpoint_uuid"] for item in list_response.json()] == ["endpoint-uuid"]
    endpoint_routes.db_client.list_langgraph_endpoint_management_views.assert_awaited_once_with(
        organization_id=11
    )

    detail_response = client.get("/langgraph-endpoints/endpoint-uuid")
    assert detail_response.status_code == 200
    assert detail_response.json()["endpoint_uuid"] == "endpoint-uuid"

    update_response = client.patch(
        "/langgraph-endpoints/endpoint-uuid", json={"name": "Updated"}
    )
    assert update_response.status_code == 200
    assert update_response.json()["name"] == "Updated"
    assert update_mock.await_args.kwargs["organization_id"] == 11

    delete_response = client.delete("/langgraph-endpoints/endpoint-uuid")
    assert delete_response.status_code == 200
    assert delete_response.json() == {
        "endpoint_uuid": "endpoint-uuid",
        "outcome": "deleted",
    }
    assert delete_mock.await_args.kwargs["organization_id"] == 11


@pytest.mark.asyncio
async def test_create_rejects_foreign_credential_before_registration(monkeypatch):
    create_db = AsyncMock()
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
        "api.services.langgraph_integration.endpoint_registration.db_client.get_credential_by_uuid",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        "api.services.langgraph_integration.endpoint_registration.db_client.create_langgraph_endpoint",
        create_db,
    )

    with pytest.raises(CredentialOwnershipError):
        await create_endpoint(
            organization_id=11,
            actor_user_id=7,
            role=endpoint_routes.LangGraphRole.ORGANIZATION_ADMIN,
            name="Support",
            endpoint_url="https://example.com",
            credential_uuid="foreign",
            selected_profile="chat",
            selected_capabilities=["streaming"],
        )
    create_db.assert_not_awaited()


def test_disabled_feature_create_is_mutation_free(monkeypatch):
    client = _client()
    create_mock = AsyncMock(side_effect=FeatureDisabledError("disabled"))
    load_mock = AsyncMock()
    monkeypatch.setattr(endpoint_routes, "create_endpoint", create_mock)
    monkeypatch.setattr(
        endpoint_routes.db_client, "get_langgraph_endpoint_management_view", load_mock
    )

    response = client.post("/langgraph-endpoints", json=_create_payload())

    assert response.status_code == 403
    assert response.json()["detail"] == "disabled"
    load_mock.assert_not_awaited()


def test_list_and_detail_are_tenant_scoped_and_member_mutation_is_denied(monkeypatch):
    client = _client(_user(organization_id=22, role="member"))
    list_mock = AsyncMock(return_value=[])
    detail_mock = AsyncMock(return_value=None)
    update_db = AsyncMock()
    monkeypatch.setattr(
        endpoint_routes.db_client, "list_langgraph_endpoint_management_views", list_mock
    )
    monkeypatch.setattr(
        endpoint_routes.db_client, "get_langgraph_endpoint_management_view", detail_mock
    )
    monkeypatch.setattr(
        "api.services.langgraph_integration.endpoint_registration.db_client.update_langgraph_endpoint",
        update_db,
    )

    assert client.get("/langgraph-endpoints").status_code == 200
    assert client.get("/langgraph-endpoints/foreign").status_code == 404
    assert (
        client.patch("/langgraph-endpoints/foreign", json={"name": "Nope"}).status_code
        == 403
    )
    list_mock.assert_awaited_once_with(organization_id=22)
    detail_mock.assert_awaited_once_with(organization_id=22, endpoint_uuid="foreign")
    update_db.assert_not_awaited()


# ---------------------------------------------------------------------------
# Task 11: end-to-end integration tests for validate -> job -> activate.
#
# These exercise the real /validate and /activate routes against a shared
# in-memory db_client harness, running the enqueued ARQ job inline between the
# two route calls (as the design.md "Integration Tests" section prescribes).
# gateway.discover_manifest and conformance.runner.run_suite are mocked so no
# network, database, or Redis is touched, consistent with the rest of
# api/tests/langgraph_integration/. Covers bugfix.md 2.1, 2.2, 2.3, 2.4.
# ---------------------------------------------------------------------------

import asyncio
from copy import deepcopy

import api.tasks.arq as arq_module
import api.tasks.langgraph_validation as job_module
from api.schemas.langgraph_integration import v1_0
from api.schemas.langgraph_integration.examples import EXECUTABLE_EXAMPLES
from api.services.langgraph_integration.conformance import ConformanceSuiteResult
from api.services.langgraph_integration.conformance.live import LiveEndpointEvidence
from api.services.langgraph_integration.conformance.platform import PlatformEvidence
from api.services.langgraph_integration.contract import (
    MatrixVersion,
    ProfileRequirements,
)
from api.services.langgraph_integration.gateway import DiscoveryTimeoutError


def _snapshot(snapshot_id=55):
    return SimpleNamespace(
        id=snapshot_id,
        snapshot_uuid="snapshot-uuid",
        manifest_digest="d" * 64,
        schema_version="1.0",
        manifest={},
        discovered_at=NOW,
    )


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
        matrix_version="2026-01",
        matrix=matrix.model_dump(mode="json"),
    )


def _manifest():
    return v1_0.CapabilityManifest.model_validate(
        deepcopy(EXECUTABLE_EXAMPLES["1.0"]["manifest"])
    )


def _suite_result(passed=True):
    return ConformanceSuiteResult(
        suite_version="chat-1.0.0",
        fixture_digest="f" * 64,
        result_digest="r" * 64,
        passed=passed,
        results=(),
    )


class _Harness:
    """Stateful in-memory stand-in for the shared db_client singleton.

    A single endpoint row plus its credential/snapshot/report is mutated in
    place so the /validate route, the inline job, and the /activate route all
    observe the same evolving state, exactly as they would against Postgres.
    """

    def __init__(self, *, endpoint, credential, matrix_row):
        self.endpoint = endpoint
        self.credential = credential
        self.matrix_row = matrix_row
        self.snapshot = None
        self.report = None
        self.reports = []

    async def get_langgraph_endpoint(self, *, organization_id, endpoint_uuid):
        if (
            self.endpoint.organization_id == organization_id
            and self.endpoint.endpoint_uuid == endpoint_uuid
        ):
            return self.endpoint
        return None

    async def compare_and_set_langgraph_lifecycle(
        self, *, organization_id, endpoint_uuid, expected_status, new_status
    ):
        if self.endpoint.lifecycle_status != expected_status:
            return False
        self.endpoint.lifecycle_status = new_status
        return True

    async def list_langgraph_compatibility_matrices(self):
        return [self.matrix_row]

    async def get_langgraph_endpoint_credential(
        self, *, organization_id, credential_id
    ):
        if (
            self.credential.organization_id == organization_id
            and self.credential.id == credential_id
        ):
            return self.credential
        return None

    async def insert_langgraph_validation_report(
        self,
        *,
        organization_id,
        registration_id,
        capability_snapshot_id,
        compatibility_matrix_id,
        suite_version,
        contract_version,
        selected_profile,
        status,
        started_at,
        completed_at,
        evidence,
        report_digest,
        results,
    ):
        report = SimpleNamespace(
            report_uuid=f"report-{len(self.reports)}",
            capability_snapshot_id=capability_snapshot_id,
            selected_profile=selected_profile,
            status=status,
            started_at=started_at,
            completed_at=completed_at,
            evidence=evidence,
            report_digest=report_digest,
        )
        self.report = report
        self.reports.append(report)
        # Mirror the production side effect: a passing/validation report drops
        # the endpoint out of pending_validation into validation_only so the
        # activate path's transition check behaves as it does today.
        if status in {
            "passed",
            "validation_only",
        } and self.endpoint.lifecycle_status not in {
            "active",
        }:
            self.endpoint.lifecycle_status = "validation_only"
        elif status == "failed":
            self.endpoint.lifecycle_status = "incompatible"
        self.endpoint.current_validation_report_id = registration_id
        self.endpoint.current_capability_snapshot_id = capability_snapshot_id
        return report

    async def get_current_langgraph_activation_evidence(
        self, *, organization_id, endpoint_uuid
    ):
        endpoint = await self.get_langgraph_endpoint(
            organization_id=organization_id, endpoint_uuid=endpoint_uuid
        )
        if endpoint is None:
            return None
        return endpoint, self.report, self.snapshot


def _install_harness(monkeypatch, harness):
    """Point the shared db_client (used by routes, service, and job) at the harness."""
    for method in (
        "get_langgraph_endpoint",
        "compare_and_set_langgraph_lifecycle",
        "list_langgraph_compatibility_matrices",
        "get_langgraph_endpoint_credential",
        "insert_langgraph_validation_report",
        "get_current_langgraph_activation_evidence",
    ):
        monkeypatch.setattr(endpoint_routes.db_client, method, getattr(harness, method))
    monkeypatch.setattr(
        job_module,
        "get_langgraph_feature_configuration",
        AsyncMock(return_value=LangGraphFeatureConfiguration()),
    )
    monkeypatch.setattr(job_module, "build_auth_header", lambda credential: {})
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


async def _run_enqueued_job(enqueue_mock, harness):
    """Invoke validate_langgraph_endpoint inline with the captured enqueue args."""
    assert enqueue_mock.await_count >= 1
    call = enqueue_mock.await_args
    _function_name, organization_id, endpoint_uuid = call.args
    assert call.kwargs["_job_id"] == f"langgraph_validate:{endpoint_uuid}"
    await job_module.validate_langgraph_endpoint(
        {}, organization_id=organization_id, endpoint_uuid=endpoint_uuid
    )


def _feature_enabled(monkeypatch):
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


def test_validate_job_then_activate_succeeds_for_passing_manifest(monkeypatch):
    """Passing scenario: validate -> inline job (passing) -> activate succeeds (bugfix.md 2.4)."""
    client = _client()
    _feature_enabled(monkeypatch)
    endpoint = _endpoint(
        lifecycle_status="validation_only", selected_capabilities=["streaming"]
    )
    harness = _Harness(
        endpoint=endpoint, credential=_credential(), matrix_row=_matrix_row()
    )
    _install_harness(monkeypatch, harness)

    enqueue_mock = AsyncMock()
    monkeypatch.setattr(arq_module, "enqueue_job", enqueue_mock)

    # Job internals: discovery returns a manifest, the recorded snapshot becomes
    # the endpoint's current snapshot, negotiation succeeds, conformance passes.
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
    snapshot = _snapshot(snapshot_id=55)

    async def _record(**_):
        harness.snapshot = snapshot
        return SimpleNamespace(
            snapshot=snapshot, changed=True, digest="d" * 64, normalized_manifest={}
        )

    monkeypatch.setattr(job_module, "record_capability_snapshot", _record)
    monkeypatch.setattr(
        job_module,
        "negotiate_capabilities",
        lambda **_: SimpleNamespace(
            contract_version="1.1",
            invocation_modes=frozenset({"streaming"}),
            features=frozenset(),
        ),
    )
    monkeypatch.setattr(job_module, "run_suite", lambda: _suite_result(passed=True))

    # 1. /validate enqueues the job and flips lifecycle to pending_validation.
    validate_response = client.post("/langgraph-endpoints/endpoint-uuid/validate")
    assert validate_response.status_code == 200
    assert validate_response.json()["lifecycle_status"] == "pending_validation"

    # 2. Run the enqueued job inline (persists a passing Validation_Report).
    asyncio.run(_run_enqueued_job(enqueue_mock, harness))
    assert harness.report is not None
    assert harness.report.status == "passed"

    # 3. /activate now finds passing evidence and succeeds.
    activate_response = client.post("/langgraph-endpoints/endpoint-uuid/activate")
    assert activate_response.status_code == 200
    assert activate_response.json()["lifecycle_status"] == "active"


def test_validate_job_then_activate_fails_with_real_reason_on_discovery_failure(
    monkeypatch,
):
    """Failing-discovery scenario: activate fails on a real reason, not 'evidence is required' (bugfix.md 2.3, 2.4)."""
    client = _client()
    _feature_enabled(monkeypatch)
    endpoint = _endpoint(lifecycle_status="validation_only")
    harness = _Harness(
        endpoint=endpoint, credential=_credential(), matrix_row=_matrix_row()
    )
    _install_harness(monkeypatch, harness)

    enqueue_mock = AsyncMock()
    monkeypatch.setattr(arq_module, "enqueue_job", enqueue_mock)

    monkeypatch.setattr(
        job_module,
        "discover_manifest",
        AsyncMock(side_effect=DiscoveryTimeoutError("timed out")),
    )

    validate_response = client.post("/langgraph-endpoints/endpoint-uuid/validate")
    assert validate_response.status_code == 200

    asyncio.run(_run_enqueued_job(enqueue_mock, harness))
    # A failing report exists (completed_at set, no snapshot), so evidence is
    # present. The key regression assertion: /activate no longer fails on the
    # misleading "current validation evidence is required" (the pre-fix symptom
    # of a missing report) — the failure is now grounded in the real failed
    # report, not the absence of one (bugfix.md 2.3, 2.4).
    assert harness.report is not None
    assert harness.report.status == "failed"
    assert harness.report.completed_at is not None
    assert harness.snapshot is None

    activate_response = client.post("/langgraph-endpoints/endpoint-uuid/activate")
    assert activate_response.status_code == 409
    detail = activate_response.json()["detail"]
    # Regression guard: activation is NOT rejected on the pre-fix "current
    # validation evidence is required" symptom (which meant no report existed
    # at all). A real failed report now exists and drives the endpoint to
    # `incompatible` (see db_client.insert_langgraph_validation_report on a
    # `failed`/`completed_at` report), so activation is rejected on the genuine
    # lifecycle guard instead.
    #
    # NOTE: design.md's "Integration Tests" narrative described this as failing
    # with "not passing". In the shipped code a discovery failure records no
    # capability snapshot, so `activate_endpoint`'s "report is None or snapshot
    # is None" check and the `incompatible` lifecycle guard are reached before
    # the "report status is not passing" check — the literal "not passing"
    # string is unreachable on the discovery-failure path. The behavior that
    # actually matters (and that the fix restores) is that the misleading
    # "evidence is required" no longer fires because a report now exists.
    assert "evidence is required" not in detail
    assert "incompatible" in detail


def test_revalidate_pending_endpoint_creates_new_report_for_corrected_manifest(
    monkeypatch,
):
    """Re-validate scenario: a pending_validation endpoint validated again yields a new report (bugfix.md 2.2)."""
    client = _client()
    _feature_enabled(monkeypatch)
    # Endpoint already in pending_validation (e.g. a prior failed/stuck attempt).
    endpoint = _endpoint(
        lifecycle_status="pending_validation", selected_capabilities=["streaming"]
    )
    harness = _Harness(
        endpoint=endpoint, credential=_credential(), matrix_row=_matrix_row()
    )
    # Seed a stale failing report from the previous attempt.
    harness.report = SimpleNamespace(
        report_uuid="report-stale",
        capability_snapshot_id=None,
        selected_profile="chat",
        status="failed",
        started_at=NOW,
        completed_at=NOW,
        evidence={"discovery_failed": True},
        report_digest="stale",
    )
    harness.reports.append(harness.report)
    _install_harness(monkeypatch, harness)

    enqueue_mock = AsyncMock()
    monkeypatch.setattr(arq_module, "enqueue_job", enqueue_mock)

    # The corrected manifest now discovers, negotiates, and passes conformance.
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
    snapshot = _snapshot(snapshot_id=88)

    async def _record(**_):
        harness.snapshot = snapshot
        return SimpleNamespace(
            snapshot=snapshot, changed=True, digest="e" * 64, normalized_manifest={}
        )

    monkeypatch.setattr(job_module, "record_capability_snapshot", _record)
    monkeypatch.setattr(
        job_module,
        "negotiate_capabilities",
        lambda **_: SimpleNamespace(
            contract_version="1.1",
            invocation_modes=frozenset({"streaming"}),
            features=frozenset(),
        ),
    )
    monkeypatch.setattr(job_module, "run_suite", lambda: _suite_result(passed=True))

    reports_before = len(harness.reports)

    # Re-validate the already-pending endpoint: must re-dispatch, not no-op.
    validate_response = client.post("/langgraph-endpoints/endpoint-uuid/validate")
    assert validate_response.status_code == 200
    assert validate_response.json()["lifecycle_status"] == "pending_validation"
    enqueue_mock.assert_awaited_once()

    asyncio.run(_run_enqueued_job(enqueue_mock, harness))

    # A brand-new report reflecting the corrected manifest now exists.
    assert len(harness.reports) == reports_before + 1
    assert harness.report is not harness.reports[0]
    assert harness.report.status == "passed"
    assert harness.report.capability_snapshot_id == 88

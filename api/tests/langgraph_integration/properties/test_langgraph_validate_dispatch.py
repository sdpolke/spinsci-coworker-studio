"""Property-based tests for the LangGraph validate-endpoint no-op bugfix (task 10).

Covers three properties from design.md's "Property-Based Tests" section:
  1. Authorization: `request_validation` dispatches validation work iff the role is
     authorized for `VALIDATE` and the feature is enabled (design.md bullet 1).
  2. Transition table: `can_transition` for `target_status="pending_validation"` matches
     `EXPECTED_TRANSITIONS` exactly, unaffected by the added dispatch call (bullet 2).
  3. Discovery-failure reporting: any discovery failure type persists a report with
     `status != "passed"` and `completed_at is not None` (bullet 3).

No live network/DB/ARQ calls: `db_client`, `_dispatch_validation`, `discover_manifest`,
and the compatibility-matrix/credential lookups are mocked throughout, consistent with
the rest of `api/tests/langgraph_integration/`.
"""

from contextlib import ExitStack
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from hypothesis import given
from hypothesis import strategies as st

import api.tasks.langgraph_validation as job_module
from api.services.langgraph_integration.access_control import (
    LangGraphAuthorizationError,
    LangGraphPermission,
    LangGraphRole,
    is_langgraph_authorized,
)
from api.services.langgraph_integration.configuration import (
    LangGraphFeatureConfiguration,
)
from api.services.langgraph_integration.contract.models import (
    MatrixVersion,
    ProfileRequirements,
)
from api.services.langgraph_integration.endpoint_registration import (
    FeatureDisabledError,
    request_validation,
)
from api.services.langgraph_integration.gateway import (
    DiscoveryTimeoutError,
    InvalidManifestError,
    UnsafeDestinationError,
)
from api.services.langgraph_integration.lifecycle import (
    EndpointLifecycle,
    can_transition,
)

NOW = datetime(2026, 1, 1, tzinfo=UTC)

# Replicated from `test_endpoint_lifecycle.py`; the properties package does not import
# across sibling test modules, so the transition table is duplicated here (matching the
# local convention of keeping property tests self-contained).
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


def _feature_config(*, enabled: bool) -> LangGraphFeatureConfiguration:
    return LangGraphFeatureConfiguration(
        enabled=enabled,
        experimental_acknowledged_at=NOW if enabled else None,
        experimental_acknowledged_by=7 if enabled else None,
    )


# Feature: langgraph-validate-endpoint-noop, Property 3: Validate dispatch follows
# authorization and the feature flag (design.md Property-Based Tests, bullet 1).
@given(
    role=st.sampled_from(list(LangGraphRole)),
    feature_enabled=st.booleans(),
    lifecycle_status=st.sampled_from(["validation_only", "pending_validation"]),
)
@pytest.mark.asyncio
async def test_request_validation_dispatches_iff_authorized_and_enabled(
    role, feature_enabled, lifecycle_status
):
    # `@given` reuses the test callable across examples, so a function-scoped
    # `monkeypatch` fixture would not reset between inputs; use `patch` context
    # managers that are entered/exited per generated example instead.
    endpoint = SimpleNamespace(
        endpoint_uuid="endpoint-uuid",
        lifecycle_status=lifecycle_status,
        selected_profile="chat",
    )
    module = "api.services.langgraph_integration.endpoint_registration"
    dispatch = AsyncMock()
    with ExitStack() as stack:
        stack.enter_context(
            patch(
                f"{module}.db_client.get_langgraph_endpoint",
                AsyncMock(return_value=endpoint),
            )
        )
        stack.enter_context(
            patch(
                f"{module}.db_client.compare_and_set_langgraph_lifecycle",
                AsyncMock(return_value=True),
            )
        )
        stack.enter_context(
            patch(
                f"{module}.get_langgraph_feature_configuration",
                AsyncMock(return_value=_feature_config(enabled=feature_enabled)),
            )
        )
        stack.enter_context(patch(f"{module}._dispatch_validation", dispatch))

        authorized = is_langgraph_authorized(
            role=role, permission=LangGraphPermission.VALIDATE
        )
        should_dispatch = authorized and feature_enabled

        if should_dispatch:
            await request_validation(
                organization_id=11, endpoint_uuid="endpoint-uuid", role=role
            )
            dispatch.assert_awaited_once_with(11, "endpoint-uuid")
        else:
            expected_error = (
                LangGraphAuthorizationError if not authorized else FeatureDisabledError
            )
            with pytest.raises(expected_error):
                await request_validation(
                    organization_id=11, endpoint_uuid="endpoint-uuid", role=role
                )
            dispatch.assert_not_awaited()


# Feature: langgraph-validate-endpoint-noop, Property 4: Transition table used by
# request_validation is unaffected by the dispatch fix (design.md Property-Based Tests,
# bullet 2).
@given(current_status=st.sampled_from(sorted(EndpointLifecycle)))
def test_can_transition_to_pending_validation_matches_expected_transitions(
    current_status,
):
    current = current_status.value
    target = "pending_validation"
    # `request_validation` short-circuits the same-status case itself before ever
    # consulting `can_transition`, so the transition table is what governs every
    # non-same-status branch. `can_transition` matches `EXPECTED_TRANSITIONS`
    # exactly (same-status is not itself a listed transition).
    expected_allowed = target in EXPECTED_TRANSITIONS[current]
    assert can_transition(current, target) is expected_allowed


# Feature: langgraph-validate-endpoint-noop, Property 5: Discovery failures always
# persist a non-passing, completed report (design.md Property-Based Tests, bullet 3).
@given(
    error=st.one_of(
        st.builds(DiscoveryTimeoutError, st.text(max_size=40)),
        st.builds(InvalidManifestError, st.tuples(st.text(max_size=20))),
        st.builds(UnsafeDestinationError, st.text(max_size=40)),
    )
)
@pytest.mark.asyncio
async def test_discovery_failure_persists_non_passing_completed_report(error):
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

    insert_report = AsyncMock()
    with ExitStack() as stack:
        stack.enter_context(
            patch.object(
                job_module.db_client,
                "get_langgraph_endpoint",
                AsyncMock(return_value=endpoint),
            )
        )
        stack.enter_context(
            patch.object(
                job_module.db_client,
                "list_langgraph_compatibility_matrices",
                AsyncMock(return_value=[matrix_row]),
            )
        )
        stack.enter_context(
            patch.object(
                job_module.db_client,
                "get_langgraph_endpoint_credential",
                AsyncMock(return_value=credential),
            )
        )
        stack.enter_context(
            patch.object(
                job_module,
                "get_langgraph_feature_configuration",
                AsyncMock(return_value=LangGraphFeatureConfiguration()),
            )
        )
        stack.enter_context(
            patch.object(job_module, "build_auth_header", lambda credential: {})
        )
        stack.enter_context(
            patch.object(job_module, "discover_manifest", AsyncMock(side_effect=error))
        )
        # Discovery failure must short-circuit before negotiation/conformance;
        # guard that by making the next step raise if the failure path reaches it.
        stack.enter_context(
            patch.object(
                job_module,
                "record_capability_snapshot",
                AsyncMock(
                    side_effect=AssertionError(
                        "negotiation reached on discovery failure"
                    )
                ),
            )
        )
        stack.enter_context(
            patch.object(
                job_module.db_client,
                "insert_langgraph_validation_report",
                insert_report,
            )
        )

        await job_module.validate_langgraph_endpoint(
            {}, organization_id=11, endpoint_uuid="endpoint-uuid"
        )

    insert_report.assert_awaited_once()
    kwargs = insert_report.await_args.kwargs
    assert kwargs["status"] != "passed"
    assert kwargs["completed_at"] is not None
    assert kwargs["capability_snapshot_id"] is None

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from api.db.models import LangGraphRolloutStateModel, OrganizationModel
from api.services.langgraph_integration.configuration import (
    update_langgraph_feature_configuration,
)
from api.services.langgraph_integration.rollout import (
    InvalidRolloutTransition,
    RolloutEvaluationPoint,
    RolloutStage,
    active_pinned_run_may_finish,
    evaluate_expansion_window,
    is_valid_stage_transition,
    kill_switch_deadline,
    new_langgraph_run_allowed,
    tenant_selected_for_stage,
)
from api.services.langgraph_integration.rollout_service import (
    evaluate_and_record_rollout,
)

NOW = datetime(2026, 1, 15, 12, 0, tzinfo=UTC)


def _window_points(
    *,
    turns: int = 100,
    failure_rate: float = 0.051,
    first_event_p95_ms: float = 2_000,
) -> list[RolloutEvaluationPoint]:
    return [
        RolloutEvaluationPoint(
            observed_at=NOW + timedelta(minutes=minute),
            endpoint_turns=turns,
            failure_rate=failure_rate,
            first_event_p95_ms=first_event_p95_ms,
        )
        for minute in range(16)
    ]


def test_rollout_stages_only_advance_to_the_immediate_next_stage():
    stages = tuple(RolloutStage)
    for index, current in enumerate(stages):
        for target_index, target in enumerate(stages):
            expected = target_index <= index or target_index == index + 1
            assert is_valid_stage_transition(current, target) is expected

    assert not is_valid_stage_transition(
        RolloutStage.INTERNAL_TEST_TENANT,
        RolloutStage.PERCENTAGE_COHORT,
    )


def test_tenant_selection_is_cumulative_and_percentage_is_deterministic():
    internal = frozenset({1})
    allowlist = frozenset({2})

    assert tenant_selected_for_stage(
        stage=RolloutStage.INTERNAL_TEST_TENANT,
        organization_id=1,
        internal_tenant_ids=internal,
    )
    assert not tenant_selected_for_stage(
        stage=RolloutStage.INTERNAL_TEST_TENANT,
        organization_id=2,
        internal_tenant_ids=internal,
        allowlisted_tenant_ids=allowlist,
    )
    assert tenant_selected_for_stage(
        stage=RolloutStage.SELECTED_TENANT_ALLOWLIST,
        organization_id=2,
        internal_tenant_ids=internal,
        allowlisted_tenant_ids=allowlist,
    )
    assert not tenant_selected_for_stage(
        stage=RolloutStage.PERCENTAGE_COHORT,
        organization_id=3,
        percentage=0,
    )
    assert tenant_selected_for_stage(
        stage=RolloutStage.PERCENTAGE_COHORT,
        organization_id=3,
        percentage=100,
    )
    first = tenant_selected_for_stage(
        stage=RolloutStage.PERCENTAGE_COHORT,
        organization_id=42,
        percentage=37,
        cohort_salt="stable-release",
    )
    second = tenant_selected_for_stage(
        stage=RolloutStage.PERCENTAGE_COHORT,
        organization_id=42,
        percentage=37,
        cohort_salt="stable-release",
    )
    assert first is second
    assert tenant_selected_for_stage(
        stage=RolloutStage.GENERAL_EXPERIMENTAL_AVAILABILITY,
        organization_id=999,
    )


def test_complete_continuous_failure_window_halts_and_builds_alert():
    evaluation = evaluate_expansion_window(
        stage=RolloutStage.PERCENTAGE_COHORT,
        points=_window_points(),
    )

    assert evaluation.halt_expansion
    assert evaluation.alert is not None
    assert evaluation.alert.evaluation_started_at == NOW
    assert evaluation.alert.evaluation_ended_at == NOW + timedelta(minutes=15)
    assert evaluation.alert.reason == "rollout_threshold_exceeded:failure_rate"


@pytest.mark.parametrize("mutation", ["low_volume", "healthy_point", "gap", "boundary"])
def test_window_does_not_halt_unless_every_due_point_qualifies(mutation: str):
    points = _window_points()
    if mutation == "low_volume":
        points[8] = RolloutEvaluationPoint(points[8].observed_at, 99, 0.9, 9_000)
    elif mutation == "healthy_point":
        points[8] = RolloutEvaluationPoint(points[8].observed_at, 100, 0.05, 2_000)
    elif mutation == "gap":
        points.pop(8)
    else:
        points = _window_points(failure_rate=0.05, first_event_p95_ms=2_000)

    evaluation = evaluate_expansion_window(
        stage=RolloutStage.PERCENTAGE_COHORT,
        points=points,
    )
    assert not evaluation.halt_expansion
    assert evaluation.alert is None


def test_latest_window_ignores_older_nonqualifying_points_and_reports_both_reasons():
    points = [
        RolloutEvaluationPoint(NOW - timedelta(minutes=1), 1, 0, 0),
        *_window_points(failure_rate=0.051, first_event_p95_ms=2_001),
    ]
    evaluation = evaluate_expansion_window(
        stage=RolloutStage.PERCENTAGE_COHORT,
        points=points,
    )
    assert evaluation.halt_expansion
    assert evaluation.alert is not None
    assert evaluation.alert.reason == (
        "rollout_threshold_exceeded:failure_rate,first_event_p95_ms"
    )


def test_kill_switch_blocks_new_runs_within_60_seconds_but_preserves_active_bindings():
    disabled_at = NOW

    assert not new_langgraph_run_allowed(
        feature_enabled=False,
        disabled_at=disabled_at,
        now=NOW,
    )
    assert kill_switch_deadline(disabled_at) == NOW + timedelta(seconds=60)
    assert active_pinned_run_may_finish(binding_created_while_enabled=True)
    assert not active_pinned_run_may_finish(binding_created_while_enabled=False)


@pytest.mark.asyncio
async def test_halted_evaluation_emits_a_bounded_operator_alert():
    state = SimpleNamespace(rollout_stage=RolloutStage.PERCENTAGE_COHORT.value)
    with (
        patch(
            "api.services.langgraph_integration.rollout_service.db_client.get_langgraph_rollout_state",
            AsyncMock(return_value=state),
        ),
        patch(
            "api.services.langgraph_integration.rollout_service.db_client.record_langgraph_rollout_evaluation",
            AsyncMock(return_value=(state, True)),
        ) as record,
    ):
        evaluation, emitted = await evaluate_and_record_rollout(
            organization_id=17,
            points=_window_points(),
        )

    assert evaluation.halt_expansion
    assert emitted
    payload = record.await_args.kwargs["alert_payload"]
    assert payload == {
        "organization_id": 17,
        "stage": "percentage_cohort",
        "evaluation_started_at": NOW,
        "evaluation_ended_at": NOW + timedelta(minutes=15),
        "reason": "rollout_threshold_exceeded:failure_rate",
        "minimum_turns": 100,
        "failure_rate_threshold": 0.05,
        "first_event_p95_threshold_ms": 2_000,
    }


@pytest.mark.asyncio
async def test_operator_alert_is_persisted_once_per_tenant_window(
    db_session, async_session
):
    organization = OrganizationModel(provider_id="rollout-alert-org")
    async_session.add(organization)
    await async_session.flush()
    async_session.add(
        LangGraphRolloutStateModel(
            organization_id=organization.id,
            feature_enabled=True,
            experimental_acknowledged_at=NOW,
            rollout_stage=RolloutStage.PERCENTAGE_COHORT.value,
            internal_tenant_ids=[organization.id],
            percentage_cohort=25,
        )
    )
    await async_session.commit()

    payload = {
        "organization_id": organization.id,
        "stage": RolloutStage.PERCENTAGE_COHORT.value,
        "evaluation_started_at": NOW,
        "evaluation_ended_at": NOW + timedelta(minutes=15),
        "reason": "rollout_threshold_exceeded:failure_rate",
    }
    first_state, first_inserted = await db_session.record_langgraph_rollout_evaluation(
        organization_id=organization.id,
        evaluated_at=NOW + timedelta(minutes=15),
        halt_expansion=True,
        alert_payload=payload,
    )
    second_state, second_inserted = await db_session.record_langgraph_rollout_evaluation(
        organization_id=organization.id,
        evaluated_at=NOW + timedelta(minutes=15),
        halt_expansion=True,
        alert_payload=payload,
    )

    assert first_state.expansion_halted
    assert second_state.expansion_halted
    assert first_inserted
    assert not second_inserted


@pytest.mark.asyncio
async def test_configuration_rejects_forward_expansion_while_halted():
    state = SimpleNamespace(
        rollout_stage=RolloutStage.SELECTED_TENANT_ALLOWLIST.value,
        expansion_halted=True,
        expansion_halted_at=NOW,
        disabled_at=None,
        feature_enabled=True,
    )
    with (
        patch(
            "api.services.langgraph_integration.configuration.db_client.get_langgraph_rollout_state",
            AsyncMock(return_value=state),
        ),
        pytest.raises(InvalidRolloutTransition, match="halted"),
    ):
        await update_langgraph_feature_configuration(
            organization_id=1,
            actor_user_id=2,
            enabled=True,
            acknowledged=True,
            rollout_stage=RolloutStage.PERCENTAGE_COHORT.value,
        )

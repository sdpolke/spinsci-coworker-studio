"""Persistence orchestration for LangGraph rollout evaluation windows."""

from __future__ import annotations

import logging
from collections.abc import Iterable
from datetime import timedelta

from api.db import db_client
from api.services.langgraph_integration.rollout import (
    RolloutEvaluation,
    RolloutEvaluationPoint,
    RolloutStage,
    evaluate_expansion_window,
)

logger = logging.getLogger(__name__)


async def evaluate_and_record_rollout(
    *,
    organization_id: int,
    points: Iterable[RolloutEvaluationPoint],
    evaluation_interval: timedelta = timedelta(minutes=1),
) -> tuple[RolloutEvaluation, bool]:
    """Evaluate one tenant's latest window and emit each operator alert once."""
    state = await db_client.get_langgraph_rollout_state(
        organization_id=organization_id
    )
    if state is None:
        raise ValueError("LangGraph rollout state is not configured")

    point_list = tuple(points)
    if not point_list:
        raise ValueError("at least one rollout evaluation point is required")
    evaluation = evaluate_expansion_window(
        stage=RolloutStage(state.rollout_stage),
        points=point_list,
        evaluation_interval=evaluation_interval,
    )
    evaluated_at = max(point.observed_at for point in point_list)
    alert_payload = None
    if evaluation.alert is not None:
        alert_payload = {
            "organization_id": organization_id,
            "stage": evaluation.alert.stage.value,
            "evaluation_started_at": evaluation.alert.evaluation_started_at,
            "evaluation_ended_at": evaluation.alert.evaluation_ended_at,
            "reason": evaluation.alert.reason,
            "minimum_turns": evaluation.alert.minimum_turns,
            "failure_rate_threshold": evaluation.alert.failure_rate_threshold,
            "first_event_p95_threshold_ms": (
                evaluation.alert.first_event_p95_threshold_ms
            ),
        }

    _, alert_emitted = await db_client.record_langgraph_rollout_evaluation(
        organization_id=organization_id,
        evaluated_at=evaluated_at,
        halt_expansion=evaluation.halt_expansion,
        alert_payload=alert_payload,
    )
    if alert_emitted:
        logger.warning(
            "LangGraph rollout expansion halted",
            extra={
                "organization_id": organization_id,
                "rollout_stage": state.rollout_stage,
                "reason": evaluation.alert.reason if evaluation.alert else None,
            },
        )
    return evaluation, alert_emitted

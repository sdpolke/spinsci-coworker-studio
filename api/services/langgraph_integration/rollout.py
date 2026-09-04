"""Deterministic rollout policy for the experimental LangGraph integration."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from itertools import pairwise


class RolloutStage(StrEnum):
    INTERNAL_TEST_TENANT = "internal_test_tenant"
    SELECTED_TENANT_ALLOWLIST = "selected_tenant_allowlist"
    PERCENTAGE_COHORT = "percentage_cohort"
    GENERAL_EXPERIMENTAL_AVAILABILITY = "general_experimental_availability"


ROLLOUT_STAGES = tuple(RolloutStage)
QUALIFICATION_WINDOW = timedelta(minutes=15)
MINIMUM_TURNS = 100
FAILURE_RATE_THRESHOLD = 0.05
FIRST_EVENT_P95_THRESHOLD_MS = 2_000
KILL_SWITCH_PROPAGATION = timedelta(seconds=60)


class InvalidRolloutTransition(ValueError):
    pass


@dataclass(frozen=True)
class RolloutEvaluationPoint:
    observed_at: datetime
    endpoint_turns: int
    failure_rate: float
    first_event_p95_ms: float

    @property
    def has_required_volume(self) -> bool:
        return self.endpoint_turns >= MINIMUM_TURNS

    @property
    def breaches_threshold(self) -> bool:
        return (
            self.failure_rate > FAILURE_RATE_THRESHOLD
            or self.first_event_p95_ms > FIRST_EVENT_P95_THRESHOLD_MS
        )


@dataclass(frozen=True)
class RolloutAlert:
    stage: RolloutStage
    evaluation_started_at: datetime
    evaluation_ended_at: datetime
    reason: str
    minimum_turns: int = MINIMUM_TURNS
    failure_rate_threshold: float = FAILURE_RATE_THRESHOLD
    first_event_p95_threshold_ms: int = FIRST_EVENT_P95_THRESHOLD_MS


@dataclass(frozen=True)
class RolloutEvaluation:
    halt_expansion: bool
    alert: RolloutAlert | None


def is_valid_stage_transition(current: RolloutStage, target: RolloutStage) -> bool:
    """Allow no-op/backward transitions and only the immediate forward stage."""
    current_index = ROLLOUT_STAGES.index(current)
    target_index = ROLLOUT_STAGES.index(target)
    return target_index <= current_index or target_index == current_index + 1


def require_valid_stage_transition(
    current: RolloutStage, target: RolloutStage
) -> None:
    if not is_valid_stage_transition(current, target):
        raise InvalidRolloutTransition(
            f"rollout cannot advance from {current.value} to {target.value}"
        )


def tenant_selected_for_stage(
    *,
    stage: RolloutStage,
    organization_id: int,
    internal_tenant_ids: frozenset[int] = frozenset(),
    allowlisted_tenant_ids: frozenset[int] = frozenset(),
    percentage: int = 0,
    cohort_salt: str = "langgraph-rollout-v1",
) -> bool:
    """Select tenants deterministically without exposing tenant data externally."""
    if stage is RolloutStage.GENERAL_EXPERIMENTAL_AVAILABILITY:
        return True
    if organization_id in internal_tenant_ids:
        return True
    if stage is RolloutStage.INTERNAL_TEST_TENANT:
        return False
    if organization_id in allowlisted_tenant_ids:
        return True
    if stage is RolloutStage.SELECTED_TENANT_ALLOWLIST:
        return False
    bounded_percentage = max(0, min(100, percentage))
    digest = hashlib.sha256(
        f"{cohort_salt}:{organization_id}".encode()
    ).digest()
    bucket = int.from_bytes(digest[:8], "big") % 100
    return bucket < bounded_percentage


def evaluate_expansion_window(
    *,
    stage: RolloutStage,
    points: Iterable[RolloutEvaluationPoint],
    evaluation_interval: timedelta = timedelta(minutes=1),
) -> RolloutEvaluation:
    """Evaluate the latest complete, continuous 15-minute qualification window.

    Every configured evaluation point due in the window must be present, have at
    least 100 endpoint-attributable turns, and breach at least one rollout
    threshold. Older points are deliberately ignored so a prior healthy or
    incomplete interval cannot mask the current continuous window.
    """
    if evaluation_interval <= timedelta(0) or evaluation_interval > QUALIFICATION_WINDOW:
        raise ValueError("evaluation interval must be within the qualification window")

    ordered = sorted(points, key=lambda point: point.observed_at)
    if not ordered:
        return RolloutEvaluation(False, None)

    window_end = ordered[-1].observed_at
    window_start = window_end - QUALIFICATION_WINDOW
    window = [point for point in ordered if window_start <= point.observed_at <= window_end]
    expected_points = int(QUALIFICATION_WINDOW / evaluation_interval) + 1
    continuous = (
        len(window) == expected_points
        and window[0].observed_at == window_start
        and all(
            right.observed_at - left.observed_at == evaluation_interval
            for left, right in pairwise(window)
        )
    )
    halt = continuous and all(
        point.has_required_volume and point.breaches_threshold for point in window
    )
    if not halt:
        return RolloutEvaluation(False, None)

    reasons: set[str] = set()
    if any(point.failure_rate > FAILURE_RATE_THRESHOLD for point in window):
        reasons.add("failure_rate")
    if any(point.first_event_p95_ms > FIRST_EVENT_P95_THRESHOLD_MS for point in window):
        reasons.add("first_event_p95_ms")
    return RolloutEvaluation(
        True,
        RolloutAlert(
            stage=stage,
            evaluation_started_at=window_start,
            evaluation_ended_at=window_end,
            reason="rollout_threshold_exceeded:" + ",".join(sorted(reasons)),
        ),
    )


def new_langgraph_run_allowed(
    *, feature_enabled: bool, disabled_at: datetime | None, now: datetime
) -> bool:
    """Reject new backed runs immediately (and therefore within 60 seconds)."""
    if not feature_enabled:
        return False
    return disabled_at is None or now < disabled_at


def active_pinned_run_may_finish(*, binding_created_while_enabled: bool) -> bool:
    """Kill-switch changes never invalidate a run's immutable binding."""
    return binding_created_while_enabled


def kill_switch_deadline(disabled_at: datetime) -> datetime:
    return disabled_at + KILL_SWITCH_PROPAGATION

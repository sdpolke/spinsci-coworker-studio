from datetime import UTC, datetime, timedelta

from hypothesis import given, strategies as st

from api.services.langgraph_integration.rollout import (
    RolloutEvaluationPoint,
    RolloutStage,
    evaluate_expansion_window,
)

_WINDOW_END = datetime(2026, 1, 15, 12, 15, tzinfo=UTC)
_WINDOW_DURATION = timedelta(minutes=15)


@st.composite
def rollout_windows(draw):
    interval_minutes = draw(st.sampled_from((1, 3, 5)))
    interval = timedelta(minutes=interval_minutes)
    point_count = 15 // interval_minutes + 1
    window_start = _WINDOW_END - _WINDOW_DURATION
    timestamps = [window_start + index * interval for index in range(point_count)]
    case = draw(
        st.sampled_from(
            (
                "qualifying_failure_rate",
                "qualifying_latency",
                "qualifying_mixed",
                "low_volume_point",
                "threshold_equality_point",
                "continuity_gap",
            )
        )
    )

    points: list[RolloutEvaluationPoint] = []
    for observed_at in timestamps:
        breach = case.removeprefix("qualifying_")
        if breach not in {"failure_rate", "latency", "mixed"}:
            breach = draw(st.sampled_from(("failure_rate", "latency", "mixed")))

        failure_rate = draw(st.sampled_from((0.050001, 0.051, 0.25)))
        first_event_p95_ms = draw(st.sampled_from((2_000.001, 2_001.0, 4_000.0)))
        if breach == "failure_rate":
            first_event_p95_ms = draw(st.sampled_from((1_999.0, 2_000.0)))
        elif breach == "latency":
            failure_rate = draw(st.sampled_from((0.049, 0.05)))

        points.append(
            RolloutEvaluationPoint(
                observed_at=observed_at,
                endpoint_turns=draw(st.sampled_from((100, 101, 1_000))),
                failure_rate=failure_rate,
                first_event_p95_ms=first_event_p95_ms,
            )
        )

    if case in {"low_volume_point", "threshold_equality_point"}:
        index = draw(st.integers(min_value=0, max_value=point_count - 1))
        original = points[index]
        points[index] = RolloutEvaluationPoint(
            observed_at=original.observed_at,
            endpoint_turns=99 if case == "low_volume_point" else original.endpoint_turns,
            failure_rate=original.failure_rate if case == "low_volume_point" else 0.05,
            first_event_p95_ms=(
                original.first_event_p95_ms
                if case == "low_volume_point"
                else 2_000.0
            ),
        )
    elif case == "continuity_gap":
        del points[draw(st.integers(min_value=1, max_value=point_count - 2))]

    if draw(st.booleans()):
        points.insert(
            0,
            RolloutEvaluationPoint(
                observed_at=window_start - interval,
                endpoint_turns=0,
                failure_rate=0.0,
                first_event_p95_ms=0.0,
            ),
        )

    return interval, points


def _reference_should_halt(
    interval: timedelta,
    points: list[RolloutEvaluationPoint],
) -> bool:
    latest = max(point.observed_at for point in points)
    window_start = latest - _WINDOW_DURATION
    window = [point for point in points if window_start <= point.observed_at <= latest]
    required_timestamps = {
        window_start + step * interval
        for step in range(int(_WINDOW_DURATION / interval) + 1)
    }
    observed_timestamps = [point.observed_at for point in window]
    is_complete_continuous_window = (
        len(observed_timestamps) == len(required_timestamps)
        and set(observed_timestamps) == required_timestamps
    )
    every_point_qualifies = all(
        point.endpoint_turns >= 100
        and (point.failure_rate > 0.05 or point.first_event_p95_ms > 2_000)
        for point in window
    )
    return is_complete_continuous_window and every_point_qualifies


# Feature: langgraph-voice-integration, Property 37: Rollout gates use every qualifying evaluation point
# **Validates: Requirements 18.7, 18.8**
@given(
    stage=st.sampled_from(tuple(RolloutStage)),
    generated_window=rollout_windows(),
)
def test_property_37_rollout_halts_iff_every_window_point_qualifies(
    stage: RolloutStage,
    generated_window: tuple[timedelta, list[RolloutEvaluationPoint]],
) -> None:
    interval, points = generated_window

    evaluation = evaluate_expansion_window(
        stage=stage,
        points=points,
        evaluation_interval=interval,
    )

    expected_halt = _reference_should_halt(interval, points)
    assert evaluation.halt_expansion is expected_halt
    assert (evaluation.alert is not None) is expected_halt

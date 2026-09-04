import pytest

from api.services.langgraph_integration.health import (
    HealthSample,
    due_health_sample_offsets,
    evaluate_health_degradation_window,
)
from api.services.langgraph_integration.lifecycle import EndpointLifecycle


def _samples(interval: int, results: tuple[bool, ...]) -> tuple[HealthSample, ...]:
    offsets = due_health_sample_offsets(interval)
    assert len(offsets) == len(results)
    return tuple(
        HealthSample(offset_seconds=offset, successful=successful)
        for offset, successful in zip(offsets, results, strict=True)
    )


def test_all_due_failures_degrade_only_at_window_end_and_alert_once():
    samples = _samples(15, (False, False, False, False, False))

    before_end = evaluate_health_degradation_window(
        samples=samples,
        sampling_interval_seconds=15,
        elapsed_seconds=59,
        lifecycle_status=EndpointLifecycle.ACTIVE,
    )
    assert before_end.lifecycle_status is EndpointLifecycle.ACTIVE
    assert not before_end.window_complete
    assert not before_end.emit_status_change_alert

    at_end = evaluate_health_degradation_window(
        samples=samples,
        sampling_interval_seconds=15,
        elapsed_seconds=60,
        lifecycle_status=EndpointLifecycle.ACTIVE,
    )
    assert at_end.lifecycle_status is EndpointLifecycle.DEGRADED
    assert at_end.window_complete
    assert at_end.status_changed
    assert at_end.emit_status_change_alert

    replay = evaluate_health_degradation_window(
        samples=samples,
        sampling_interval_seconds=15,
        elapsed_seconds=60,
        lifecycle_status=at_end.lifecycle_status,
        alert_already_emitted=at_end.emit_status_change_alert,
    )
    assert replay.lifecycle_status is EndpointLifecycle.DEGRADED
    assert not replay.status_changed
    assert not replay.emit_status_change_alert


def test_any_due_success_prevents_degradation_and_alert():
    decision = evaluate_health_degradation_window(
        samples=_samples(20, (False, False, True, False)),
        sampling_interval_seconds=20,
        elapsed_seconds=60,
        lifecycle_status=EndpointLifecycle.ACTIVE,
    )

    assert decision.window_complete
    assert decision.lifecycle_status is EndpointLifecycle.ACTIVE
    assert not decision.status_changed
    assert not decision.emit_status_change_alert


def test_missing_due_sample_fails_closed_without_degradation():
    decision = evaluate_health_degradation_window(
        samples=(HealthSample(offset_seconds=0, successful=False),),
        sampling_interval_seconds=30,
        elapsed_seconds=60,
        lifecycle_status=EndpointLifecycle.ACTIVE,
    )

    assert not decision.window_complete
    assert decision.lifecycle_status is EndpointLifecycle.ACTIVE
    assert not decision.emit_status_change_alert


def test_invalid_sampling_interval_is_rejected():
    with pytest.raises(ValueError, match="between 1 and 60"):
        due_health_sample_offsets(0)

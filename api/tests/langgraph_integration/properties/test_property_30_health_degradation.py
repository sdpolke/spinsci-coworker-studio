from hypothesis import given

from api.services.langgraph_integration.health import (
    HealthSample,
    evaluate_health_degradation_window,
)
from api.services.langgraph_integration.lifecycle import EndpointLifecycle
from api.tests.langgraph_integration.properties.strategies import health_windows


# Feature: langgraph-voice-integration, Property 30: Health degradation follows the complete sample window
# **Validates: Requirements 15.7**
@given(window=health_windows())
def test_property_30_health_degradation_follows_complete_sample_window(window):
    samples = tuple(
        HealthSample(offset_seconds=offset, successful=successful)
        for offset, successful in window["samples"]
    )
    interval = window["sampling_interval_seconds"]
    every_due_sample_failed = all(not sample.successful for sample in samples)

    before_window_end = evaluate_health_degradation_window(
        samples=samples,
        sampling_interval_seconds=interval,
        elapsed_seconds=59,
        lifecycle_status=EndpointLifecycle.ACTIVE,
    )
    assert not before_window_end.window_complete
    assert before_window_end.lifecycle_status is EndpointLifecycle.ACTIVE
    assert not before_window_end.status_changed
    assert not before_window_end.emit_status_change_alert

    at_window_end = evaluate_health_degradation_window(
        samples=samples,
        sampling_interval_seconds=interval,
        elapsed_seconds=60,
        lifecycle_status=EndpointLifecycle.ACTIVE,
    )
    assert at_window_end.window_complete
    assert (
        at_window_end.lifecycle_status is EndpointLifecycle.DEGRADED
    ) is every_due_sample_failed
    assert at_window_end.status_changed is every_due_sample_failed
    assert at_window_end.emit_status_change_alert is every_due_sample_failed

    replay = evaluate_health_degradation_window(
        samples=samples,
        sampling_interval_seconds=interval,
        elapsed_seconds=60,
        lifecycle_status=at_window_end.lifecycle_status,
        alert_already_emitted=at_window_end.emit_status_change_alert,
    )
    assert replay.lifecycle_status is at_window_end.lifecycle_status
    assert not replay.status_changed
    assert not replay.emit_status_change_alert

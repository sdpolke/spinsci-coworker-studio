"""Pure health-sampling window policy for LangGraph endpoint lifecycle changes."""

from __future__ import annotations

from dataclasses import dataclass

from api.services.langgraph_integration.lifecycle import EndpointLifecycle

HEALTH_DEGRADATION_WINDOW_SECONDS = 60


@dataclass(frozen=True)
class HealthSample:
    """One configured health observation measured relative to the first failure."""

    offset_seconds: int
    successful: bool


@dataclass(frozen=True)
class HealthWindowDecision:
    """Lifecycle and alert effects permitted by one health-window evaluation."""

    lifecycle_status: EndpointLifecycle
    window_complete: bool
    status_changed: bool
    emit_status_change_alert: bool


def due_health_sample_offsets(sampling_interval_seconds: int) -> tuple[int, ...]:
    """Return every configured sample offset due in the 60-second window.

    Offset zero is the failure that starts the window. Subsequent observations
    occur at the configured interval through the end of the window.
    """
    if not 1 <= sampling_interval_seconds <= HEALTH_DEGRADATION_WINDOW_SECONDS:
        raise ValueError("health sampling interval must be between 1 and 60 seconds")
    return tuple(
        range(
            0,
            HEALTH_DEGRADATION_WINDOW_SECONDS + 1,
            sampling_interval_seconds,
        )
    )


def evaluate_health_degradation_window(
    *,
    samples: tuple[HealthSample, ...],
    sampling_interval_seconds: int,
    elapsed_seconds: int,
    lifecycle_status: EndpointLifecycle,
    alert_already_emitted: bool = False,
) -> HealthWindowDecision:
    """Evaluate the complete post-failure window without early degradation.

    The caller persists the returned lifecycle transition and alert marker
    atomically. Re-evaluating a degraded window therefore cannot emit another
    status-change alert.
    """
    if elapsed_seconds < 0:
        raise ValueError("elapsed seconds cannot be negative")

    due_offsets = due_health_sample_offsets(sampling_interval_seconds)
    samples_by_offset: dict[int, HealthSample] = {}
    for sample in samples:
        if sample.offset_seconds in samples_by_offset:
            raise ValueError("health sample offsets must be unique")
        samples_by_offset[sample.offset_seconds] = sample

    window_complete = (
        elapsed_seconds >= HEALTH_DEGRADATION_WINDOW_SECONDS
        and all(offset in samples_by_offset for offset in due_offsets)
    )
    every_due_sample_failed = window_complete and all(
        not samples_by_offset[offset].successful for offset in due_offsets
    )
    status_changed = (
        lifecycle_status is EndpointLifecycle.ACTIVE and every_due_sample_failed
    )
    resulting_status = (
        EndpointLifecycle.DEGRADED if status_changed else lifecycle_status
    )

    return HealthWindowDecision(
        lifecycle_status=resulting_status,
        window_complete=window_complete,
        status_changed=status_changed,
        emit_status_change_alert=status_changed and not alert_already_emitted,
    )

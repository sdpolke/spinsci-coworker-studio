from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

from api.services.langgraph_integration.performance import (
    CapacitySnapshot,
    FixedEnvironment,
    LoadSample,
    evaluate_performance,
    run_fixed_load,
)

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def environment(concurrency: int = 10) -> FixedEnvironment:
    return FixedEnvironment(
        name="ci-local-simulator",
        concurrency=concurrency,
        warmed_requests=5,
        payload_bytes=4096,
        tool_count=2,
        endpoint_region="local",
    )


def sample(**changes: float) -> LoadSample:
    values = {
        "first_event_ms": 100.0,
        "completion_ms": 500.0,
        "cancellation_suppression_ms": 20.0,
        "cancellation_dispatch_ms": 25.0,
    }
    values.update(changes)
    return LoadSample(**values)


def capacity(**changes: float | int) -> CapacitySnapshot:
    values = {
        "peak_active_streams": 10,
        "event_loop_lag_p95_ms": 5.0,
        "configured_stream_capacity": 20,
        "required_headroom_ratio": 0.2,
    }
    values.update(changes)
    return CapacitySnapshot(**values)


def test_fixed_environment_gate_persists_metadata_and_required_percentiles():
    report = evaluate_performance(
        environment=environment(),
        samples=[sample() for _ in range(100)],
        capacity=capacity(),
        measured_at=NOW,
    )

    evidence = report.report_evidence()
    assert report.passed
    assert evidence["request_count"] == 100
    assert evidence["environment"]["concurrency"] == 10
    assert evidence["capacity"]["headroom_ratio"] == 0.5
    assert len(report.evidence_digest) == 64


@pytest.mark.parametrize(
    ("samples", "capacity_value", "failure"),
    [
        ([sample() for _ in range(99)], capacity(), "request_count_below_100"),
        ([sample(first_event_ms=1501) for _ in range(100)], capacity(), "first_event_p95_exceeded"),
        ([sample(completion_ms=10001) for _ in range(100)], capacity(), "completion_p95_exceeded"),
        ([sample(cancellation_dispatch_ms=251) for _ in range(100)], capacity(), "cancellation_dispatch_p95_exceeded"),
        ([sample() for _ in range(100)], capacity(event_loop_lag_p95_ms=51), "event_loop_lag_p95_exceeded"),
        ([sample() for _ in range(100)], capacity(configured_stream_capacity=12), "stream_capacity_headroom_insufficient"),
    ],
)
def test_live_eligibility_fails_closed_for_latency_capacity_or_sample_gaps(
    samples, capacity_value, failure
):
    report = evaluate_performance(
        environment=environment(), samples=samples, capacity=capacity_value, measured_at=NOW
    )
    assert not report.passed
    assert failure in report.failures


@pytest.mark.asyncio
async def test_non_watch_load_runner_warms_then_bounds_100_measured_requests():
    active = 0
    peak = 0
    calls: list[int] = []
    lock = asyncio.Lock()

    async def invoke(ordinal: int) -> LoadSample:
        nonlocal active, peak
        async with lock:
            active += 1
            peak = max(peak, active)
            calls.append(ordinal)
        await asyncio.sleep(0)
        async with lock:
            active -= 1
        return sample()

    report = await run_fixed_load(
        environment=environment(concurrency=8),
        request_count=100,
        invoke=invoke,
        capacity=capacity(peak_active_streams=8),
        measured_at=NOW,
    )

    assert report.passed
    assert calls[:5] == [-1, -2, -3, -4, -5]
    assert sorted(calls[5:]) == list(range(100))
    assert peak <= 8

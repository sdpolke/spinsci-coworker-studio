"""Fixed-environment Chat Compatibility load and live-eligibility gates."""

from __future__ import annotations

import asyncio
import math
import platform
import sys
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

from api.services.langgraph_integration.conformance import deterministic_digest

MIN_REQUIRED_REQUESTS = 100
FIRST_EVENT_P95_LIMIT_MS = 1_500.0
COMPLETION_P95_LIMIT_MS = 10_000.0
CANCELLATION_LIMIT_MS = 250.0
DEFAULT_EVENT_LOOP_LAG_LIMIT_MS = 50.0


@dataclass(frozen=True)
class FixedEnvironment:
    name: str
    concurrency: int
    warmed_requests: int
    payload_bytes: int
    tool_count: int
    endpoint_region: str
    runner_version: str = "chat-load-1.0.0"
    python_version: str = platform.python_version()
    platform: str = sys.platform

    def __post_init__(self) -> None:
        if self.concurrency < 1:
            raise ValueError("concurrency must be positive")
        if self.warmed_requests < 1:
            raise ValueError("at least one warmed request is required")
        if self.payload_bytes < 1 or self.tool_count < 0:
            raise ValueError("payload_bytes must be positive and tool_count non-negative")
        if not self.name or not self.endpoint_region:
            raise ValueError("environment name and endpoint region are required")


@dataclass(frozen=True)
class LoadSample:
    first_event_ms: float
    completion_ms: float
    cancellation_suppression_ms: float
    cancellation_dispatch_ms: float

    def __post_init__(self) -> None:
        if any(value < 0 or not math.isfinite(value) for value in asdict(self).values()):
            raise ValueError("sample timings must be finite and non-negative")


@dataclass(frozen=True)
class CapacitySnapshot:
    peak_active_streams: int
    event_loop_lag_p95_ms: float
    configured_stream_capacity: int
    required_headroom_ratio: float = 0.20

    @property
    def headroom_ratio(self) -> float:
        if self.configured_stream_capacity <= 0:
            return 0.0
        return max(
            0.0,
            (self.configured_stream_capacity - self.peak_active_streams)
            / self.configured_stream_capacity,
        )


@dataclass(frozen=True)
class PerformanceReport:
    environment: FixedEnvironment
    request_count: int
    first_event_p95_ms: float
    completion_p95_ms: float
    cancellation_suppression_p95_ms: float
    cancellation_dispatch_p95_ms: float
    capacity: CapacitySnapshot
    passed: bool
    failures: tuple[str, ...]
    measured_at: str
    evidence_digest: str

    def report_evidence(self) -> dict[str, Any]:
        return {
            "environment": asdict(self.environment),
            "request_count": self.request_count,
            "first_event_p95_ms": self.first_event_p95_ms,
            "completion_p95_ms": self.completion_p95_ms,
            "cancellation_suppression_p95_ms": self.cancellation_suppression_p95_ms,
            "cancellation_dispatch_p95_ms": self.cancellation_dispatch_p95_ms,
            "capacity": asdict(self.capacity) | {"headroom_ratio": self.capacity.headroom_ratio},
            "passed": self.passed,
            "failures": list(self.failures),
            "measured_at": self.measured_at,
            "evidence_digest": self.evidence_digest,
        }


def nearest_rank_p95(values: list[float]) -> float:
    if not values:
        raise ValueError("at least one sample is required")
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, math.ceil(0.95 * len(ordered)) - 1)]


def evaluate_performance(
    *,
    environment: FixedEnvironment,
    samples: list[LoadSample],
    capacity: CapacitySnapshot,
    measured_at: datetime | None = None,
    event_loop_lag_limit_ms: float = DEFAULT_EVENT_LOOP_LAG_LIMIT_MS,
) -> PerformanceReport:
    """Evaluate immutable live-eligibility evidence from a fixed load run."""

    failures: list[str] = []
    if len(samples) < MIN_REQUIRED_REQUESTS:
        failures.append(f"request_count_below_{MIN_REQUIRED_REQUESTS}")

    first_p95 = nearest_rank_p95([sample.first_event_ms for sample in samples])
    completion_p95 = nearest_rank_p95([sample.completion_ms for sample in samples])
    suppression_p95 = nearest_rank_p95(
        [sample.cancellation_suppression_ms for sample in samples]
    )
    dispatch_p95 = nearest_rank_p95(
        [sample.cancellation_dispatch_ms for sample in samples]
    )
    if first_p95 > FIRST_EVENT_P95_LIMIT_MS:
        failures.append("first_event_p95_exceeded")
    if completion_p95 > COMPLETION_P95_LIMIT_MS:
        failures.append("completion_p95_exceeded")
    if suppression_p95 > CANCELLATION_LIMIT_MS:
        failures.append("cancellation_suppression_p95_exceeded")
    if dispatch_p95 > CANCELLATION_LIMIT_MS:
        failures.append("cancellation_dispatch_p95_exceeded")
    if capacity.event_loop_lag_p95_ms > event_loop_lag_limit_ms:
        failures.append("event_loop_lag_p95_exceeded")
    if capacity.peak_active_streams > environment.concurrency:
        failures.append("active_stream_count_exceeded")
    if capacity.headroom_ratio < capacity.required_headroom_ratio:
        failures.append("stream_capacity_headroom_insufficient")

    timestamp = (measured_at or datetime.now(UTC)).isoformat()
    body: dict[str, Any] = {
        "environment": asdict(environment),
        "request_count": len(samples),
        "first_event_p95_ms": first_p95,
        "completion_p95_ms": completion_p95,
        "cancellation_suppression_p95_ms": suppression_p95,
        "cancellation_dispatch_p95_ms": dispatch_p95,
        "capacity": asdict(capacity) | {"headroom_ratio": capacity.headroom_ratio},
        "failures": failures,
        "measured_at": timestamp,
    }
    return PerformanceReport(
        environment=environment,
        request_count=len(samples),
        first_event_p95_ms=first_p95,
        completion_p95_ms=completion_p95,
        cancellation_suppression_p95_ms=suppression_p95,
        cancellation_dispatch_p95_ms=dispatch_p95,
        capacity=capacity,
        passed=not failures,
        failures=tuple(failures),
        measured_at=timestamp,
        evidence_digest=deterministic_digest(body),
    )


async def run_fixed_load(
    *,
    environment: FixedEnvironment,
    request_count: int,
    invoke: Callable[[int], Awaitable[LoadSample]],
    capacity: CapacitySnapshot,
    measured_at: datetime | None = None,
) -> PerformanceReport:
    """Run a bounded, non-watch load batch after explicit connection warming."""

    if request_count < MIN_REQUIRED_REQUESTS:
        raise ValueError(f"request_count must be at least {MIN_REQUIRED_REQUESTS}")

    for ordinal in range(environment.warmed_requests):
        await invoke(-(ordinal + 1))

    semaphore = asyncio.Semaphore(environment.concurrency)

    async def measured(ordinal: int) -> LoadSample:
        async with semaphore:
            return await invoke(ordinal)

    samples = list(await asyncio.gather(*(measured(i) for i in range(request_count))))
    return evaluate_performance(
        environment=environment,
        samples=samples,
        capacity=capacity,
        measured_at=measured_at,
    )


def environment_from_mapping(value: Mapping[str, Any]) -> FixedEnvironment:
    """Validate documented environment metadata loaded by a release runner."""

    return FixedEnvironment(
        name=str(value["name"]),
        concurrency=int(value["concurrency"]),
        warmed_requests=int(value["warmed_requests"]),
        payload_bytes=int(value["payload_bytes"]),
        tool_count=int(value["tool_count"]),
        endpoint_region=str(value["endpoint_region"]),
        runner_version=str(value.get("runner_version", "chat-load-1.0.0")),
    )

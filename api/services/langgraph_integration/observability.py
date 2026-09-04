"""Causal runtime observations, metric reduction, and tenant-safe alert evaluation."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from itertools import pairwise
from typing import Any

from api.services.langgraph_integration.privacy import redact_sensitive_data


class ObservationKind(StrEnum):
    USER_TURN = "user_turn"
    DISPATCH = "dispatch"
    RUNTIME_EVENT = "runtime_event"
    SYNTHESIZED_AUDIO = "synthesized_audio"
    TERMINAL = "terminal"
    CANCELLATION_ACCEPTED = "cancellation_accepted"
    CANCELLATION_SUPPRESSED = "cancellation_suppressed"
    CANCELLATION_DISPATCHED = "cancellation_dispatched"


@dataclass(frozen=True)
class RuntimeObservation:
    kind: ObservationKind
    timestamp_ms: int
    order: int
    voice_run_id: str
    invocation_id: str | None = None
    sequence: int | None = None
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.timestamp_ms < 0 or self.order < 0:
            raise ValueError("observation timestamp and order must be non-negative")
        if not self.voice_run_id:
            raise ValueError("voice_run_id is required")
        if self.kind is not ObservationKind.USER_TURN and not self.invocation_id:
            raise ValueError("invocation_id is required for invocation observations")
        if self.kind is ObservationKind.RUNTIME_EVENT and self.sequence is None:
            raise ValueError("Runtime Event observations require a sequence")


@dataclass(frozen=True)
class MetricProjection:
    counts: Mapping[str, int]
    first_event_ms: int | None
    completion_ms: int | None
    stream_duration_ms: int | None
    cancellation_suppression_ms: int | None
    cancellation_dispatch_ms: int | None


def _first(observations: Iterable[RuntimeObservation], kind: ObservationKind) -> RuntimeObservation | None:
    return next((item for item in observations if item.kind is kind), None)


def validate_causal_order(observations: Iterable[RuntimeObservation]) -> tuple[RuntimeObservation, ...]:
    """Return a canonical trace or reject causally impossible observations."""
    items = tuple(sorted(observations, key=lambda item: item.order))
    if len({item.order for item in items}) != len(items):
        raise ValueError("observation order values must be unique")
    if any(right.timestamp_ms < left.timestamp_ms for left, right in pairwise(items)):
        raise ValueError("observation timestamps must be monotonic")

    by_invocation: dict[str, list[RuntimeObservation]] = {}
    for item in items:
        if item.invocation_id:
            by_invocation.setdefault(item.invocation_id, []).append(item)
    for invocation_items in by_invocation.values():
        dispatch = _first(invocation_items, ObservationKind.DISPATCH)
        runtime_events = [item for item in invocation_items if item.kind is ObservationKind.RUNTIME_EVENT]
        terminal = _first(invocation_items, ObservationKind.TERMINAL)
        audio = [item for item in invocation_items if item.kind is ObservationKind.SYNTHESIZED_AUDIO]
        if (runtime_events or terminal) and dispatch is None:
            raise ValueError("Runtime Events and terminal observations require dispatch")
        if dispatch and any(item.order <= dispatch.order for item in runtime_events):
            raise ValueError("Runtime Events must follow dispatch")
        if terminal and (
            dispatch is None
            or terminal.order <= dispatch.order
            or any(item.order >= terminal.order for item in runtime_events)
        ):
            raise ValueError("terminal must follow dispatch and earlier Runtime Events")
        for synthesized in audio:
            producing_sequence = synthesized.attributes.get("producing_sequence")
            producing = next(
                (item for item in runtime_events if item.sequence == producing_sequence), None
            )
            if producing is None or synthesized.order <= producing.order:
                raise ValueError("synthesized audio must follow its producing text event")
    return items


def reduce_metrics(observations: Iterable[RuntimeObservation]) -> MetricProjection:
    items = validate_causal_order(observations)
    counts = Counter(item.kind.value for item in items)
    dispatch = _first(items, ObservationKind.DISPATCH)
    first_event = _first(items, ObservationKind.RUNTIME_EVENT)
    terminal = _first(items, ObservationKind.TERMINAL)
    cancellation = _first(items, ObservationKind.CANCELLATION_ACCEPTED)
    suppressed = _first(items, ObservationKind.CANCELLATION_SUPPRESSED)
    cancellation_dispatched = _first(items, ObservationKind.CANCELLATION_DISPATCHED)

    def difference(end: RuntimeObservation | None, start: RuntimeObservation | None) -> int | None:
        return None if end is None or start is None else end.timestamp_ms - start.timestamp_ms

    return MetricProjection(
        counts=dict(counts),
        first_event_ms=difference(first_event, dispatch),
        completion_ms=difference(terminal, dispatch),
        stream_duration_ms=difference(terminal, first_event),
        cancellation_suppression_ms=difference(suppressed, cancellation),
        cancellation_dispatch_ms=difference(cancellation_dispatched, cancellation),
    )


ALERT_METRICS = frozenset(
    {"first_event_latency", "completion_latency", "error_rate", "health_failures", "security_rejections"}
)
ALERT_UNITS = {
    "first_event_latency": "ms",
    "completion_latency": "ms",
    "error_rate": "percent",
    "health_failures": "count",
    "security_rejections": "count",
}


@dataclass(frozen=True)
class AlertBounds:
    minimum_threshold: float
    maximum_threshold: float
    minimum_interval_seconds: int
    maximum_interval_seconds: int


@dataclass(frozen=True)
class AlertPolicy:
    metric_name: str
    threshold: float
    evaluation_interval_seconds: int


def compile_alert_policy(policy: AlertPolicy, bounds: AlertBounds) -> AlertPolicy:
    if policy.metric_name not in ALERT_METRICS:
        raise ValueError("unsupported alert metric")
    if not bounds.minimum_threshold <= policy.threshold <= bounds.maximum_threshold:
        raise ValueError("alert threshold is outside deployment bounds")
    if not bounds.minimum_interval_seconds <= policy.evaluation_interval_seconds <= bounds.maximum_interval_seconds:
        raise ValueError("alert evaluation interval is outside deployment bounds")
    return policy


def evaluate_alert(
    *,
    policy: AlertPolicy,
    bounds: AlertBounds,
    measured_value: float,
    elapsed_seconds: int,
    organization_id: int,
    endpoint_identifier: str,
    contract_version: str,
    trace_url: str | None,
    attributes: Mapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Emit exactly at interval end when the bounded threshold is violated."""
    compile_alert_policy(policy, bounds)
    if elapsed_seconds != policy.evaluation_interval_seconds or measured_value <= policy.threshold:
        return None
    payload = {
        "organization_id": organization_id,
        "endpoint_identifier": endpoint_identifier[:128],
        "contract_version": contract_version[:16],
        "metric_name": policy.metric_name,
        "measured_value": measured_value,
        "unit": ALERT_UNITS[policy.metric_name],
        "threshold": policy.threshold,
        "evaluation_interval_seconds": policy.evaluation_interval_seconds,
        "trace_url": trace_url[:512] if trace_url else None,
        "attributes": dict(attributes or {}),
    }
    return redact_sensitive_data(payload)

from datetime import UTC
from unittest.mock import AsyncMock

import pytest

from api.services.langgraph_integration.observability import (
    AlertBounds,
    AlertPolicy,
    ObservationKind,
    RuntimeObservation,
    compile_alert_policy,
    evaluate_alert,
    reduce_metrics,
    validate_causal_order,
)
from api.services.langgraph_integration.privacy import (
    compile_privacy_policy,
    governed_capture,
    project_outbound_fields,
    redact_sensitive_data,
)
from api.tasks import langgraph_retention


def _observation(kind, timestamp, order, *, sequence=None, attributes=None):
    return RuntimeObservation(
        kind=kind,
        timestamp_ms=timestamp,
        order=order,
        voice_run_id="run-1",
        invocation_id="inv-1",
        sequence=sequence,
        attributes=attributes or {},
    )


def test_causal_reducer_counts_and_calculates_exact_latencies():
    observations = (
        _observation(ObservationKind.DISPATCH, 1000, 0),
        _observation(ObservationKind.RUNTIME_EVENT, 1250, 1, sequence=0),
        _observation(
            ObservationKind.SYNTHESIZED_AUDIO,
            1400,
            2,
            attributes={"producing_sequence": 0},
        ),
        _observation(ObservationKind.TERMINAL, 1800, 3),
    )

    metrics = reduce_metrics(observations)

    assert metrics.counts == {
        "dispatch": 1,
        "runtime_event": 1,
        "synthesized_audio": 1,
        "terminal": 1,
    }
    assert metrics.first_event_ms == 250
    assert metrics.completion_ms == 800
    assert metrics.stream_duration_ms == 550


def test_causal_validation_rejects_audio_before_text_and_terminal_before_event():
    with pytest.raises(ValueError, match="synthesized audio"):
        validate_causal_order(
            (
                _observation(ObservationKind.DISPATCH, 1000, 0),
                _observation(
                    ObservationKind.SYNTHESIZED_AUDIO,
                    1100,
                    1,
                    attributes={"producing_sequence": 0},
                ),
                _observation(ObservationKind.RUNTIME_EVENT, 1200, 2, sequence=0),
            )
        )


def test_alert_bounds_interval_end_and_sensitive_fields():
    bounds = AlertBounds(100, 5000, 30, 900)
    policy = compile_alert_policy(AlertPolicy("first_event_latency", 1500, 60), bounds)
    assert evaluate_alert(
        policy=policy,
        bounds=bounds,
        measured_value=2000,
        elapsed_seconds=59,
        organization_id=7,
        endpoint_identifier="endpoint-1",
        contract_version="1.1",
        trace_url="/traces/abc",
    ) is None

    alert = evaluate_alert(
        policy=policy,
        bounds=bounds,
        measured_value=2000,
        elapsed_seconds=60,
        organization_id=7,
        endpoint_identifier="endpoint-1",
        contract_version="1.1",
        trace_url="/traces/abc",
        attributes={"prompt": "private", "status": "slow"},
    )
    assert alert == {
        "organization_id": 7,
        "endpoint_identifier": "endpoint-1",
        "contract_version": "1.1",
        "metric_name": "first_event_latency",
        "measured_value": 2000,
        "unit": "ms",
        "threshold": 1500,
        "evaluation_interval_seconds": 60,
        "trace_url": "/traces/abc",
        "attributes": {"prompt": "[REDACTED]", "status": "slow"},
    }
    with pytest.raises(ValueError, match="deployment bounds"):
        compile_alert_policy(AlertPolicy("first_event_latency", 99, 60), bounds)


def test_compiled_privacy_allowlist_redaction_and_capture_off():
    policy = compile_privacy_policy(
        workflow_version_id="definition-2",
        data_sharing_policy={"allow": ["history", "locale", "context"]},
        redaction_policy={"fields": ["history"]},
        supported_fields=["history", "locale", "context", "audio"],
    )
    outbound = project_outbound_fields(
        {"history": "private", "locale": "en-US", "context": {"token": "x"}, "audio": b"raw"},
        policy,
    )
    assert outbound == {
        "history": "[REDACTED]",
        "locale": "en-US",
        "context": {"token": "x"},
    }
    captured = governed_capture(
        payload={"request_count": 1, "prompt": "private", "nested": {"status": "ok", "tool_result": "private"}},
        policy=policy,
        capture_payloads=False,
    )
    assert captured == {"request_count": 1, "nested": {"status": "ok"}}
    assert redact_sensitive_data({"error": {"authorization": "Bearer secret", "code": "bad"}}) == {
        "error": {"authorization": "[REDACTED]", "code": "bad"}
    }


@pytest.mark.asyncio
async def test_retention_job_is_tenant_scoped_and_replay_safe(monkeypatch):
    list_organizations = AsyncMock(return_value=[11, 22])
    sweep = AsyncMock(
        side_effect=[
            {"bindings_anonymized": 1, "payloads_anonymized": 2, "invocations_deleted": 3},
            {"bindings_anonymized": 0, "payloads_anonymized": 0, "invocations_deleted": 0},
        ]
    )
    monkeypatch.setattr(langgraph_retention.db_client, "list_langgraph_retention_organizations", list_organizations)
    monkeypatch.setattr(langgraph_retention.db_client, "sweep_langgraph_retention", sweep)

    result = await langgraph_retention.sweep_langgraph_retention({})

    assert result[11]["invocations_deleted"] == 3
    assert result[22]["invocations_deleted"] == 0
    assert [call.kwargs["organization_id"] for call in sweep.await_args_list] == [11, 22]
    assert all(call.kwargs["now"].tzinfo is UTC for call in sweep.await_args_list)

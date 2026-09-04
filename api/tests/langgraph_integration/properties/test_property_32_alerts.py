from hypothesis import given
from hypothesis import strategies as st

from api.services.langgraph_integration.observability import (
    ALERT_METRICS,
    AlertBounds,
    AlertPolicy,
    evaluate_alert,
)


# Feature: langgraph-voice-integration, Property 32: Alerts are bounded, complete, and redacted
@given(
    metric=st.sampled_from(sorted(ALERT_METRICS)),
    threshold=st.floats(min_value=1, max_value=10000, allow_nan=False, allow_infinity=False),
    measured=st.floats(min_value=0, max_value=20000, allow_nan=False, allow_infinity=False),
    interval=st.integers(min_value=30, max_value=900),
    elapsed=st.integers(min_value=0, max_value=1000),
    secret=st.text(min_size=1).map(lambda value: f"hypothesis-secret::{value}"),
)
def test_property_32_alerts_are_bounded_complete_and_redacted(
    metric, threshold, measured, interval, elapsed, secret
):
    bounds = AlertBounds(1, 10000, 30, 900)
    alert = evaluate_alert(
        policy=AlertPolicy(metric, threshold, interval),
        bounds=bounds,
        measured_value=measured,
        elapsed_seconds=elapsed,
        organization_id=4,
        endpoint_identifier="endpoint",
        contract_version="1.1",
        trace_url="/traces/abc",
        attributes={"secret": secret},
    )
    should_emit = elapsed == interval and measured > threshold
    assert (alert is not None) is should_emit
    if alert is not None:
        assert {
            "organization_id",
            "endpoint_identifier",
            "contract_version",
            "metric_name",
            "measured_value",
            "unit",
            "threshold",
            "evaluation_interval_seconds",
            "trace_url",
        } <= alert.keys()
        assert alert["attributes"]["secret"] == "[REDACTED]"
        assert secret not in repr(alert) or secret == "[REDACTED]"

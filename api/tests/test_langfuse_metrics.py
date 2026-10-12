"""Tests for the telemetry read layer.

Weighted towards the things that were silently wrong rather than towards
coverage. The dashboard reads Langfuse over HTTP and reduces the rows in
Python, which means a mistake here does not raise -- it renders a plausible
number. Two such mistakes shipped: every call was reported as channel
``unknown`` because the channel was read from a span attribute nothing writes,
and the average call duration included a health check and a seeding script.
Both are pinned below.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from api.services.observability import langfuse_metrics as metrics
from api.services.observability.conventions import (
    TOOL_DURATION_MS,
    TOOL_NAME,
    TOOL_OUTCOME,
    TOOL_SERVER,
    CallChannel,
    SpanName,
    ToolOutcome,
    channel_for_transport,
)

WINDOW = metrics.TimeWindow(
    start=datetime(2026, 10, 12, tzinfo=timezone.utc),
    end=datetime(2026, 10, 13, tzinfo=timezone.utc),
)


def trace_row(
    trace_id: str,
    *,
    transport: str | None = "smallwebrtc",
    name: str = "GI Patient Scheduling Agent",
    latency: float | None = 120.0,
    session_id: str | None = "41",
) -> dict:
    """A trace as the Langfuse public API returns one."""
    tags = ["cascade", "model:openai/gpt-oss-120b"]
    if transport:
        tags.append(f"channel:{transport}")
    return {
        "id": trace_id,
        "name": name,
        "timestamp": "2026-10-12T10:00:00Z",
        "latency": latency,
        "sessionId": session_id,
        "userId": "2",
        "tags": tags,
    }


def span(
    trace_id: str,
    name: str,
    *,
    latency: float | None = 1.0,
    ttfb: float | None = None,
    start: str = "2026-10-12T10:00:00Z",
    level: str = "DEFAULT",
    attributes: dict | None = None,
    span_type: str = "SPAN",
    model: str | None = None,
    tokens: int | None = None,
) -> dict:
    payload = dict(attributes or {})
    if ttfb is not None:
        payload[metrics.TTFB_ATTRIBUTE] = ttfb
    observation = {
        "id": f"{trace_id}-{name}-{start}",
        "traceId": trace_id,
        "name": name,
        "latency": latency,
        "startTime": start,
        "level": level,
        "type": span_type,
        "metadata": {"attributes": payload},
    }
    if model:
        observation["model"] = model
    if tokens is not None:
        observation["usage"] = {"total": tokens}
    return observation


def tool_span(trace_id: str, tool: str, *, outcome: str = "ok", ms: float = 500.0) -> dict:
    return span(
        trace_id,
        str(SpanName.MCP_TOOL_CALL),
        attributes={
            TOOL_SERVER: "Epic Direct Scheduling",
            TOOL_NAME: tool,
            TOOL_OUTCOME: outcome,
            TOOL_DURATION_MS: ms,
        },
    )


@pytest.fixture
def stub_langfuse(monkeypatch):
    """Serve fixed traces and observations in place of the HTTP calls."""

    def install(traces: list[dict], observations: list[dict], truncated: bool = False):
        def fake_paged(path: str, params: dict, limit: int):
            rows = traces if "traces" in path else observations
            return list(rows), truncated

        monkeypatch.setattr(metrics, "_paged", fake_paged)

    return install


# --- channel ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("transport", "expected"),
    [
        ("smallwebrtc", CallChannel.BROWSER),
        ("webrtc", CallChannel.BROWSER),
        ("twilio", CallChannel.TELEPHONY),
        ("telnyx", CallChannel.TELEPHONY),
        ("exotel", CallChannel.TELEPHONY),
        ("textchat", CallChannel.TEXT_CHAT),
        ("CHAT", CallChannel.TEXT_CHAT),
        # Historical and genuinely ambiguous: it says a voice call but not over
        # what. Guessing telephony would put a wrong row in the channel split.
        ("VOICE", CallChannel.UNKNOWN),
        (None, CallChannel.UNKNOWN),
        ("carrier-we-have-never-heard-of", CallChannel.UNKNOWN),
    ],
)
def test_transport_classifies_to_a_channel(transport, expected):
    assert channel_for_transport(transport) is expected


def test_channel_comes_from_the_trace_tag():
    """The regression that made every call "unknown".

    The channel is a trace tag the pipeline stamps, not a span attribute. The
    dashboard read an attribute that nothing writes, so every row fell through
    to a default.
    """
    assert metrics.channel_of(trace_row("a", transport="twilio")) is CallChannel.TELEPHONY
    assert metrics.transport_of(trace_row("a", transport="twilio")) == "twilio"
    assert metrics.channel_label(trace_row("a", transport="smallwebrtc")) == "Browser"


def test_a_tagless_trace_is_not_guessed_into_a_channel():
    assert metrics.channel_of(trace_row("a", transport=None)) is CallChannel.UNKNOWN


# --- what counts as a call -------------------------------------------------


def test_health_checks_and_seed_scripts_are_not_calls():
    """They land in the same project and would drag every average with them."""
    assert metrics._is_call(trace_row("a")) is True
    assert (
        metrics._is_call(
            {"id": "x", "name": "spinsci-e2e-15b126a", "latency": 0.05, "tags": []}
        )
        is False
    )
    assert (
        metrics._is_call({"id": "y", "name": "telemetry seed", "latency": 24.5, "tags": []})
        is False
    )


def test_a_synthetic_trace_is_excluded_from_call_figures(stub_langfuse):
    stub_langfuse(
        [
            trace_row("real", latency=120.0),
            {"id": "fake", "name": "telemetry seed", "latency": 0.1, "tags": []},
        ],
        [span("real", "turn-1", latency=4.0), span("fake", "noise", latency=0.1)],
    )
    data = metrics.load(WINDOW)

    assert [t["id"] for t in data.calls] == ["real"]
    # The synthetic trace's spans are dropped too, so the layer and tool panels
    # are not polluted either.
    assert all(o["traceId"] == "real" for o in data.observations)
    assert metrics.turn_stats(data)["avg_conversation_latency"] == 120.0


def test_a_span_whose_trace_began_before_the_window_is_kept(stub_langfuse):
    """Dropping it would lose real work rather than filter out noise."""
    stub_langfuse([trace_row("real")], [span("earlier-call", "turn-1", latency=3.0)])
    data = metrics.load(WINDOW)
    assert [o["traceId"] for o in data.observations] == ["earlier-call"]


# --- the channel filter ----------------------------------------------------


def test_the_channel_filter_narrows_every_panel(stub_langfuse):
    """It is applied to traces and propagated to their spans.

    Filtering on a span attribute matched nothing, so choosing "telephony"
    previously left the tool and model panels showing browser calls.
    """
    stub_langfuse(
        [
            trace_row("web", transport="smallwebrtc"),
            trace_row("phone", transport="twilio"),
        ],
        [tool_span("web", "epic_patient_lookup"), tool_span("phone", "epic_get_open_slots")],
    )

    telephony = metrics.load(WINDOW, channel="telephony")
    assert [t["id"] for t in telephony.calls] == ["phone"]
    assert [row[TOOL_NAME] for row in metrics.tool_performance(telephony)] == [
        "epic_get_open_slots"
    ]

    everything = metrics.load(WINDOW)
    assert len(everything.calls) == 2
    assert len(metrics.tool_performance(everything)) == 2


# --- per-call --------------------------------------------------------------


def test_per_call_reports_one_row_with_the_shape_of_the_call(stub_langfuse):
    stub_langfuse(
        [trace_row("call", transport="twilio", latency=90.0)],
        [
            span("call", "turn-1", latency=4.0),
            span("call", "turn-2", latency=6.0),
            span("call", "llm-collect", latency=1.2, ttfb=0.2),
            span("call", "llm-confirm", latency=0.8, ttfb=0.4),
            span("call", "stt", latency=1.5, ttfb=0.3),
            span("call", "tts", latency=0.5, ttfb=0.1),
            tool_span("call", "epic_patient_lookup", ms=400.0),
            tool_span("call", "epic_get_open_slots", outcome="unavailable", ms=100.0),
        ],
    )
    (row,) = metrics.per_call(metrics.load(WINDOW))

    assert row["channel"] == "Telephony"
    assert row["transport"] == "twilio"
    assert row["duration"] == 90.0
    assert row["turns"] == 2
    assert row["avg_turn_latency"] == 5.0
    assert row["max_turn_latency"] == 6.0
    # First token is the model's; first audio is what the caller hears. They
    # are different waits and the table shows both.
    assert row["avg_first_token"] == pytest.approx(0.3)
    assert row["avg_first_audio"] == pytest.approx(0.1)
    assert row["avg_llm_latency"] == pytest.approx(1.0)
    assert row["tool_calls"] == 2
    assert row["tool_seconds"] == pytest.approx(0.5)
    # The unavailable tool returned without raising, so only this catches it.
    assert row["failures"] == 1


def test_per_call_still_reports_a_call_with_no_trace_latency(stub_langfuse):
    """A call in progress has no trace latency yet."""
    stub_langfuse(
        [trace_row("live", latency=None)],
        [span("live", "conversation", latency=42.0), span("live", "turn-1", latency=3.0)],
    )
    (row,) = metrics.per_call(metrics.load(WINDOW))
    assert row["duration"] == 42.0


# --- panels ----------------------------------------------------------------


def test_call_volume_groups_by_workflow_not_channel(stub_langfuse):
    """It was labelled as the channel split, which is what produced "unknown"."""
    stub_langfuse(
        [
            trace_row("a", name="GI Patient Scheduling Agent"),
            trace_row("b", name="GI Patient Scheduling Agent"),
            trace_row("c", name="Demo Receptionist"),
        ],
        [],
    )
    rows = metrics.call_volume(metrics.load(WINDOW))

    assert [(row["workflow"], row["count_count"]) for row in rows] == [
        ("GI Patient Scheduling Agent", 2),
        ("Demo Receptionist", 1),
    ]
    assert "channel" not in rows[0]


def test_channel_breakdown_compares_browser_against_telephony(stub_langfuse):
    stub_langfuse(
        [
            trace_row("web1", transport="smallwebrtc", latency=100.0),
            trace_row("web2", transport="webrtc", latency=200.0),
            trace_row("phone", transport="twilio", latency=60.0),
        ],
        [
            span("web1", "turn-1", latency=5.0),
            span("web1", "llm", latency=1.0, ttfb=0.2),
            span("phone", "turn-1", latency=9.0),
            span("phone", "llm", latency=1.0, ttfb=0.6),
        ],
    )
    rows = {row["channel"]: row for row in metrics.channel_breakdown(metrics.load(WINDOW))}

    assert rows["Browser"]["count_count"] == 2
    assert rows["Browser"]["avg_latency"] == 150.0
    assert rows["Browser"]["transports"] == "smallwebrtc, webrtc"
    assert rows["Telephony"]["count_count"] == 1
    # The comparison the panel exists for: the same pipeline, slower over a
    # carrier.
    assert rows["Telephony"]["avg_first_token"] > rows["Browser"]["avg_first_token"]
    assert rows["Telephony"]["avg_turn_latency"] == 9.0


def test_tool_latency_prefers_the_recorded_duration_over_langfuse(stub_langfuse):
    """Tool spans time themselves on a monotonic clock; clock skew distorts the
    timestamps Langfuse subtracts."""
    observation = tool_span("call", "epic_patient_lookup", ms=250.0)
    observation["latency"] = 99.0
    stub_langfuse([trace_row("call")], [observation])

    (row,) = metrics.tool_performance(metrics.load(WINDOW))
    assert row["avg_latency"] == pytest.approx(0.25)


def test_models_carry_time_to_first_token(stub_langfuse):
    stub_langfuse(
        [trace_row("call")],
        [
            span(
                "call",
                "llm-greet",
                latency=1.0,
                ttfb=0.2,
                span_type="GENERATION",
                model="openai/gpt-oss-120b",
                tokens=500,
            ),
            span(
                "call",
                "llm-confirm",
                latency=2.0,
                ttfb=0.4,
                span_type="GENERATION",
                model="openai/gpt-oss-120b",
                tokens=700,
            ),
        ],
    )
    (row,) = metrics.model_performance(metrics.load(WINDOW))

    assert row["providedModelName"] == "openai/gpt-oss-120b"
    assert row["avg_latency"] == 1.5
    assert row["avg_first_token"] == pytest.approx(0.3)
    assert row["sum_totalTokens"] == 1200


def test_failures_cover_both_raising_and_degrading(stub_langfuse):
    """A tool that returns "unavailable" never raises, so a level-only check
    reports a healthy system while calls quietly degrade."""
    stub_langfuse(
        [trace_row("a"), trace_row("b")],
        [
            span("a", "llm", level="ERROR", latency=1.0),
            tool_span("a", "epic_get_open_slots", outcome="unavailable"),
            tool_span("b", "epic_get_open_slots", outcome="unavailable"),
            tool_span("b", "epic_patient_lookup", outcome="ok"),
        ],
    )
    rows = metrics.failures(metrics.load(WINDOW))

    degraded = next(row for row in rows if "epic_get_open_slots" in row["source"])
    assert degraded["count_count"] == 2
    # Two calls hit it once each, which needs a different response from one
    # call retrying twice.
    assert degraded["calls"] == 2
    assert degraded["detail"] == str(ToolOutcome.UNAVAILABLE)
    assert any(row["detail"] == "Error" for row in rows)
    assert all("epic_patient_lookup" not in row["source"] for row in rows)


def test_layer_breakdown_excludes_the_container_spans(stub_langfuse):
    """A turn span wraps the stt, llm and tts spans inside it. Counting it as a
    layer would double every figure on the panel."""
    stub_langfuse(
        [trace_row("call")],
        [
            span("call", "conversation", latency=100.0),
            span("call", "turn-1", latency=8.0),
            span("call", "stt", latency=1.0),
            span("call", "llm-greet", latency=2.0),
            span("call", "tts", latency=0.5),
            tool_span("call", "epic_patient_lookup", ms=500.0),
        ],
    )
    layers = {row["layer"] for row in metrics.layer_breakdown(metrics.load(WINDOW))}
    assert layers == {"LLM", "Speech to text", "Text to speech", "Tools"}


def test_a_truncated_window_says_so(stub_langfuse):
    """Partial figures presented as complete are worse than no figures."""
    stub_langfuse([trace_row("call")], [span("call", "turn-1")], truncated=True)
    assert metrics.load(WINDOW).truncated is True


# --- percentiles -----------------------------------------------------------


def test_percentile_is_nearest_rank():
    """Interpolation invents a figure no call actually took, which matters most
    on the handful of samples a quiet tool produces."""
    samples = [0.1, 0.2, 0.3, 0.4, 10.0]
    assert metrics._percentile(samples, 0.95) == 10.0
    assert metrics._percentile([], 0.95) is None
    assert metrics._percentile([0.5], 0.95) == 0.5


def test_time_to_first_token_falls_back_to_the_otel_field():
    """Kept so this survives the pipeline stopping stamping metrics.ttfb."""
    start = datetime(2026, 10, 12, 10, 0, 0, tzinfo=timezone.utc)
    observation = span("call", "llm", latency=2.0)
    assert metrics.time_to_first_token(observation) is None

    observation["startTime"] = start.isoformat()
    observation["completionStartTime"] = (start + timedelta(milliseconds=250)).isoformat()
    assert metrics.time_to_first_token(observation) == pytest.approx(0.25)

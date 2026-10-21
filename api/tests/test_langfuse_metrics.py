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

import pathlib
from datetime import datetime, timedelta, timezone

import pytest

from api.services.observability import langfuse_metrics as metrics
from api.services.observability.conventions import (
    ORG_ID,
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


ORG = "2"
OTHER_ORG = "1"


def span(
    trace_id: str,
    name: str,
    *,
    org: str | None = ORG,
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
    if org is not None:
        payload[ORG_ID] = org
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


def tool_span(
    trace_id: str,
    tool: str,
    *,
    outcome: str = "ok",
    ms: float = 500.0,
    org: str | None = ORG,
) -> dict:
    return span(
        trace_id,
        str(SpanName.MCP_TOOL_CALL),
        org=org,
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
    data = metrics.load(WINDOW, ORG)

    assert [t["id"] for t in data.calls] == ["real"]
    # The synthetic trace's spans are dropped too, so the layer and tool panels
    # are not polluted either.
    assert all(o["traceId"] == "real" for o in data.observations)
    assert metrics.turn_stats(data)["avg_conversation_latency"] == 120.0


def test_a_span_whose_trace_began_before_the_window_is_kept(stub_langfuse):
    """Dropping it would lose real work rather than filter out noise."""
    stub_langfuse([trace_row("real")], [span("earlier-call", "turn-1", latency=3.0)])
    data = metrics.load(WINDOW, ORG)
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

    telephony = metrics.load(WINDOW, ORG, channel="telephony")
    assert [t["id"] for t in telephony.calls] == ["phone"]
    assert [row[TOOL_NAME] for row in metrics.tool_performance(telephony)] == [
        "epic_get_open_slots"
    ]

    everything = metrics.load(WINDOW, ORG)
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
    (row,) = metrics.per_call(metrics.load(WINDOW, ORG))

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
    (row,) = metrics.per_call(metrics.load(WINDOW, ORG))
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
        # One span each: ownership is read from spans, so a trace with none is
        # excluded by design and these rows would not appear at all.
        [span("a", "turn-1"), span("b", "turn-1"), span("c", "turn-1")],
    )
    rows = metrics.call_volume(metrics.load(WINDOW, ORG))

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
            # web2 needs a span of its own or it cannot be shown to anyone.
            span("web2", "turn-1", latency=4.0),
            span("phone", "turn-1", latency=9.0),
            span("phone", "llm", latency=1.0, ttfb=0.6),
        ],
    )
    rows = {row["channel"]: row for row in metrics.channel_breakdown(metrics.load(WINDOW, ORG))}

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

    (row,) = metrics.tool_performance(metrics.load(WINDOW, ORG))
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
    (row,) = metrics.model_performance(metrics.load(WINDOW, ORG))

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
    rows = metrics.failures(metrics.load(WINDOW, ORG))

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
    layers = {row["layer"] for row in metrics.layer_breakdown(metrics.load(WINDOW, ORG))}
    assert layers == {"LLM", "Speech to text", "Text to speech", "Tools"}


def test_a_truncated_window_says_so(stub_langfuse):
    """Partial figures presented as complete are worse than no figures."""
    stub_langfuse([trace_row("call")], [span("call", "turn-1")], truncated=True)
    assert metrics.load(WINDOW, ORG).truncated is True


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


# --- per-turn breakdown ----------------------------------------------------


def turn(trace_id: str, index: int, *, start: str, latency: float = 10.0) -> dict:
    return span(trace_id, f"turn-{index}", latency=latency, start=start)


def test_turn_breakdown_sums_stages_and_never_subtracts(stub_langfuse):
    """A tool span is nested under its generation but is not contained by it in
    time: a real booking generation reported 2.086s around a 3.644s Epic call.
    Subtracting the nesting produces negative model time."""
    stub_langfuse(
        [trace_row("call")],
        [
            turn("call", 1, start="2026-10-12T10:00:00Z", latency=20.0),
            span("call", "stt", latency=6.0, ttfb=0.30, start="2026-10-12T10:00:01Z"),
            span("call", "llm-book-appointment", latency=2.086, ttfb=0.12,
                 start="2026-10-12T10:00:08Z"),
            tool_span("call", "epic_schedule_appointment", ms=3644.39),
            span("call", "tts", latency=4.0, ttfb=0.11, start="2026-10-12T10:00:12Z"),
        ],
    )
    (row,) = metrics.turn_breakdown(metrics.load(WINDOW, ORG).by_call["call"])

    assert row["llm_seconds"] == pytest.approx(2.086)
    assert row["tool_seconds"] == pytest.approx(3.64439)
    # Summed, so the Epic call is visible rather than cancelling the model out.
    assert row["segments"]["llm"] > 0
    assert row["segments"]["tool"] == pytest.approx(3.64439)
    assert row["route"] == "epic_schedule_appointment"
    assert row["tool_calls"] == 1


def test_first_word_uses_the_transcription_lag_not_the_whole_stt_span(stub_langfuse):
    """An stt span runs while the caller is still talking, so its latency is
    mostly their speech. Counting it would report a six second wait that nobody
    experienced."""
    stub_langfuse(
        [trace_row("call")],
        [
            turn("call", 1, start="2026-10-12T10:00:00Z", latency=20.0),
            span("call", "stt", latency=6.0, ttfb=0.30, start="2026-10-12T10:00:01Z"),
            span("call", "llm-greet", latency=1.0, ttfb=0.20, start="2026-10-12T10:00:07Z"),
            span("call", "tts", latency=4.0, ttfb=0.10, start="2026-10-12T10:00:08Z"),
        ],
    )
    (row,) = metrics.turn_breakdown(metrics.load(WINDOW, ORG).by_call["call"])

    assert row["first_word"] == pytest.approx(0.60)  # 0.30 + 0.20 + 0.10
    assert row["ttft"] == pytest.approx(0.20)
    assert row["segments"]["stt"] == pytest.approx(0.30)
    assert row["segments"]["tts"] == pytest.approx(0.10)


def test_a_tool_outliving_its_turn_is_still_counted(stub_langfuse):
    """Attribution is by time, and a tool call can finish after the turn window
    closes. Dropping it would quietly lose Epic time from the totals."""
    stub_langfuse(
        [trace_row("call")],
        [
            turn("call", 1, start="2026-10-12T10:00:00Z", latency=2.0),
            span("call", "llm-find", latency=1.0, ttfb=0.2, start="2026-10-12T10:00:01Z"),
            # Starts after the turn window has closed.
            {**tool_span("call", "epic_get_open_slots", ms=800.0),
             "startTime": "2026-10-12T10:00:30Z"},
        ],
    )
    (row,) = metrics.turn_breakdown(metrics.load(WINDOW, ORG).by_call["call"])
    assert row["tool_calls"] == 1
    assert row["tool_seconds"] == pytest.approx(0.8)


def test_transcripts_are_withheld_unless_switched_on(stub_langfuse, monkeypatch):
    """Turn text is a patient saying their name and date of birth. The timings
    and the route are unaffected; only the two text fields are."""
    spans = [
        turn("call", 1, start="2026-10-12T10:00:00Z"),
        span("call", "stt", latency=2.0, ttfb=0.3, start="2026-10-12T10:00:01Z",
             attributes={"transcript": "Theodore Mychart, seventh of July 1948"}),
        span("call", "tts", latency=2.0, ttfb=0.1, start="2026-10-12T10:00:03Z",
             attributes={"text": "Thank you, let me pull that up."}),
    ]
    stub_langfuse([trace_row("call")], spans)

    monkeypatch.delenv("SPINSCI_TELEMETRY_TRANSCRIPTS", raising=False)
    (hidden,) = metrics.turn_breakdown(metrics.load(WINDOW, ORG).by_call["call"])
    assert hidden["caller"] is None and hidden["agent"] is None
    assert hidden["first_word"] == pytest.approx(0.40)
    # Lengths survive the flag, so the column reports "6 words" rather than
    # going blank. They are also what the column is mostly read for.
    assert hidden["caller_words"] == 6
    assert hidden["agent_words"] == 7

    monkeypatch.setenv("SPINSCI_TELEMETRY_TRANSCRIPTS", "true")
    (shown,) = metrics.turn_breakdown(metrics.load(WINDOW, ORG).by_call["call"])
    assert "Theodore Mychart" in shown["caller"]
    assert shown["caller_words"] == 6


def test_route_falls_back_to_the_node_when_no_tool_ran(stub_langfuse):
    stub_langfuse(
        [trace_row("call")],
        [
            turn("call", 1, start="2026-10-12T10:00:00Z"),
            span("call", "llm-collect-patient", latency=1.0, ttfb=0.2,
                 start="2026-10-12T10:00:01Z"),
        ],
    )
    (row,) = metrics.turn_breakdown(metrics.load(WINDOW, ORG).by_call["call"])
    assert row["route"] == "collect patient"
    assert row["tool_calls"] == 0


def test_percentiles_travel_with_their_sample_count(stub_langfuse):
    """A p99 over nine turns is the slowest turn wearing a statistic's name, so
    the reader is given n to judge it by."""
    stub_langfuse(
        [trace_row("call")],
        [
            turn("call", 1, start="2026-10-12T10:00:00Z"),
            span("call", "llm-a", latency=1.0, ttfb=0.2, start="2026-10-12T10:00:01Z"),
            span("call", "tts", latency=1.0, ttfb=0.1, start="2026-10-12T10:00:02Z"),
        ],
    )
    stats = metrics.turn_stats(metrics.load(WINDOW, ORG))
    assert stats["first_word_samples"] == 1
    assert stats["first_token_samples"] == 1
    assert stats["p99_first_word"] is not None
    assert stats["p50_first_token"] == pytest.approx(0.2)


def test_the_transcript_flag_is_read_not_inferred(stub_langfuse, monkeypatch):
    """Inferring it from "did any row have text" made a silent call look like a
    configured one, so the columns appeared on that call and nowhere else."""
    monkeypatch.delenv("SPINSCI_TELEMETRY_TRANSCRIPTS", raising=False)
    silent = trace_row("silent")
    stub_langfuse([silent], [turn("silent", 1, start="2026-10-12T10:00:00Z")])

    def fake_get(path, params):
        return silent if path.endswith("silent") else None

    monkeypatch.setattr(metrics, "_get", fake_get)
    detail = metrics.call_detail("silent", ORG)
    assert detail is not None
    # No speech on this call at all, and the answer still reflects the setting.
    assert detail["transcripts_enabled"] is False


# --- tenant isolation ------------------------------------------------------
#
# These exist because the dashboard shipped without them and two real tenants
# read each other's calls on a live deployment. Every assertion below is a way
# that was found to be possible, or a way the fix could be undone.


def test_another_organisation_is_not_in_the_call_list(stub_langfuse):
    """The leak as it actually happened: one Langfuse project, two tenants."""
    stub_langfuse(
        [trace_row("mine", name="GI Scheduling"), trace_row("theirs", name="SIEC Water Outbound")],
        [
            span("mine", "turn-1"),
            span("theirs", "turn-1", org=OTHER_ORG),
            span("theirs", "llm-outbound", org=OTHER_ORG, latency=2.0, ttfb=0.2),
        ],
    )
    data = metrics.load(WINDOW, ORG)

    assert [t["id"] for t in data.calls] == ["mine"]
    assert [row["workflow"] for row in metrics.call_volume(data)] == ["GI Scheduling"]
    # Their workflow name alone identifies their business. It must not survive
    # into any row, in any panel.
    assert "SIEC" not in str(metrics.per_call(data))


def test_another_organisation_cannot_reach_any_panel(stub_langfuse):
    """Scoping the call list is not enough: a figure is a leak too.

    Their tool names say which systems they integrate, their failures say what
    is broken, and their token counts say how much they spend.
    """
    stub_langfuse(
        [trace_row("mine"), trace_row("theirs")],
        [
            span("mine", "turn-1"),
            tool_span("mine", "epic_patient_lookup", ms=300.0),
            span("theirs", "turn-1", org=OTHER_ORG),
            tool_span("theirs", "schedule_callback", outcome="error", org=OTHER_ORG),
            span("theirs", "llm-outbound", org=OTHER_ORG, level="ERROR", latency=1.0),
            span(
                "theirs",
                "llm-outbound",
                org=OTHER_ORG,
                span_type="GENERATION",
                model="their-private-model",
                tokens=99999,
                latency=1.0,
            ),
        ],
    )
    data = metrics.load(WINDOW, ORG)

    assert [r[TOOL_NAME] for r in metrics.tool_performance(data)] == ["epic_patient_lookup"]
    assert all("schedule_callback" not in str(r) for r in metrics.failures(data))
    assert all("their-private-model" not in str(r) for r in metrics.model_performance(data))
    assert all("schedule_callback" not in str(r) for r in metrics.tool_outcomes(data))
    assert "their-private-model" not in str(metrics.pipeline_stage_latency(data))
    assert metrics.turn_stats(data)["conversations"] == 1
    assert [r["channel"] for r in metrics.channel_breakdown(data)] == ["Browser"]


def test_a_trace_with_no_organisation_on_any_span_is_shown_to_nobody(stub_langfuse):
    """Fails closed. There is nothing to say whose it is, so it is no one's."""
    stub_langfuse([trace_row("orphan")], [span("orphan", "turn-1", org=None)])
    assert metrics.load(WINDOW, ORG).calls == []
    assert metrics.load(WINDOW, OTHER_ORG).calls == []


def test_a_trace_with_two_organisations_is_shown_to_neither(stub_langfuse):
    """Should not happen, and is not resolved by picking a winner: whichever
    was picked, the other tenant would be reading someone else's call."""
    stub_langfuse(
        [trace_row("mixed")],
        [span("mixed", "turn-1"), span("mixed", "llm-a", org=OTHER_ORG, latency=1.0)],
    )
    assert metrics.load(WINDOW, ORG).calls == []
    assert metrics.load(WINDOW, OTHER_ORG).calls == []


@pytest.mark.parametrize("given", [2, "2", " 2 "])
def test_the_organisation_matches_whatever_shape_it_arrives_in(stub_langfuse, given):
    """The pipeline stamps str(org_id); the caller's arrives from the database
    as an int. 1 != "1", and a filter that matches nothing is the failure mode
    most likely to be "fixed" by removing it."""
    stub_langfuse([trace_row("mine")], [span("mine", "turn-1")])
    assert len(metrics.load(WINDOW, given).calls) == 1


@pytest.mark.parametrize("empty", ["", "   ", None])
def test_an_empty_organisation_is_refused_not_treated_as_no_filter(stub_langfuse, empty):
    """The dangerous default. An absent tenant must never widen the query."""
    stub_langfuse([trace_row("mine")], [span("mine", "turn-1")])
    with pytest.raises(ValueError):
        metrics.load(WINDOW, empty)
    with pytest.raises(ValueError):
        metrics.call_detail("mine", empty)


@pytest.mark.parametrize("blank", ["", "   "])
def test_a_blank_organisation_on_a_span_counts_as_no_evidence(stub_langfuse, blank):
    """An attribute present but empty proves nothing and must not match."""
    stub_langfuse([trace_row("mine")], [span("mine", "turn-1", org=blank)])
    assert metrics.load(WINDOW, ORG).calls == []


def test_a_span_whose_trace_began_before_the_window_needs_proof_too(stub_langfuse):
    """These are deliberately kept so long-running calls are not lost. Kept on
    trust, they would carry another tenant's spans into every aggregate."""
    stub_langfuse(
        [trace_row("mine")],
        [
            span("mine", "turn-1"),
            span("earlier-mine", "llm-a", latency=2.0, ttfb=0.2),
            span("earlier-theirs", "llm-b", org=OTHER_ORG, latency=9.0, ttfb=0.9),
        ],
    )
    data = metrics.load(WINDOW, ORG)
    kept = {str(o.get("traceId")) for o in data.observations}

    assert "earlier-mine" in kept
    assert "earlier-theirs" not in kept


def test_the_channel_filter_does_not_widen_the_tenant_filter(stub_langfuse):
    """Two filters that compose wrongly is how a scoped query comes unscoped."""
    stub_langfuse(
        [
            trace_row("mine", transport="twilio"),
            trace_row("theirs", transport="twilio"),
        ],
        [span("mine", "turn-1"), span("theirs", "turn-1", org=OTHER_ORG)],
    )
    data = metrics.load(WINDOW, ORG, channel="telephony")
    assert [t["id"] for t in data.calls] == ["mine"]
    assert all(metrics.organisation_of(o) == ORG for o in data.observations)


# --- call_detail ownership -------------------------------------------------


@pytest.fixture
def stub_trace(monkeypatch):
    """Serve one trace by id, the way the detail endpoint fetches it."""

    def install(trace: dict, spans: list[dict]):
        def fake_get(path, params):
            return {**trace, "observations": spans} if trace["id"] in path else None

        monkeypatch.setattr(metrics, "_get", fake_get)

    return install


def test_a_call_detail_is_refused_to_another_organisation(stub_trace):
    """A trace id is guessable and was the only thing this check had."""
    stub_trace(trace_row("theirs"), [span("theirs", "turn-1", org=OTHER_ORG)])
    assert metrics.call_detail("theirs", ORG) is None
    # And is served to the organisation it belongs to.
    assert metrics.call_detail("theirs", OTHER_ORG) is not None


def test_a_call_detail_with_no_spans_proves_nothing_and_is_refused(stub_trace):
    stub_trace(trace_row("empty"), [])
    assert metrics.call_detail("empty", ORG) is None


def test_a_call_detail_with_mixed_organisations_is_refused(stub_trace):
    stub_trace(
        trace_row("mixed"),
        [span("mixed", "turn-1"), span("mixed", "llm-a", org=OTHER_ORG, latency=1.0)],
    )
    assert metrics.call_detail("mixed", ORG) is None
    assert metrics.call_detail("mixed", OTHER_ORG) is None


def test_a_call_detail_is_served_to_its_owner(stub_trace):
    stub_trace(
        trace_row("mine"),
        [
            span("mine", "turn-1", latency=10.0),
            span("mine", "llm-greet", latency=1.0, ttfb=0.2),
            span("mine", "tts", latency=1.0, ttfb=0.1),
        ],
    )
    detail = metrics.call_detail("mine", ORG)
    assert detail is not None
    assert detail["turns"] == 1


# --- the constant the whole filter rests on --------------------------------


def test_the_org_attribute_matches_what_the_pipeline_stamps():
    """ORG_ID read "spinsci.organization_id", which nothing emits, so anything
    filtering by it matched no spans at all. The pipeline's own value is the
    source of truth; this fails if either side moves."""
    source = (
        pathlib.Path(__file__).resolve().parents[1]
        / "services"
        / "pipecat"
        / "tracing_config.py"
    ).read_text()
    assert f'set_attribute("{ORG_ID}"' in source, (
        f"ORG_ID is {ORG_ID!r} but tracing_config.py stamps something else"
    )


def test_an_empty_window_scopes_cleanly(stub_langfuse):
    stub_langfuse([], [])
    data = metrics.load(WINDOW, ORG)
    assert data.calls == [] and data.observations == []
    assert metrics.turn_stats(data)["conversations"] == 0
    assert metrics.per_call(data) == []

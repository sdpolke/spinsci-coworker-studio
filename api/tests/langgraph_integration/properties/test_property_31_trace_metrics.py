from hypothesis import given
from hypothesis import strategies as st

from api.services.langgraph_integration.gateway import GatewayTraceContext
from api.services.langgraph_integration.observability import (
    ObservationKind,
    RuntimeObservation,
    reduce_metrics,
)


# Feature: langgraph-voice-integration, Property 31: Trace and metric projections are causally correct
@given(
    dispatch=st.integers(min_value=0, max_value=10**9),
    first_delta=st.integers(min_value=0, max_value=10000),
    audio_delta=st.integers(min_value=0, max_value=10000),
    terminal_delta=st.integers(min_value=0, max_value=10000),
)
def test_property_31_trace_and_metric_projections_are_causally_correct(
    dispatch, first_delta, audio_delta, terminal_delta
):
    first = dispatch + first_delta
    audio = first + audio_delta
    terminal = audio + terminal_delta
    observations = (
        RuntimeObservation(ObservationKind.DISPATCH, dispatch, 0, "run", "inv"),
        RuntimeObservation(ObservationKind.RUNTIME_EVENT, first, 1, "run", "inv", sequence=0),
        RuntimeObservation(
            ObservationKind.SYNTHESIZED_AUDIO,
            audio,
            2,
            "run",
            "inv",
            attributes={"producing_sequence": 0},
        ),
        RuntimeObservation(ObservationKind.TERMINAL, terminal, 3, "run", "inv"),
    )
    projection = reduce_metrics(observations)
    assert projection.counts == {
        "dispatch": 1,
        "runtime_event": 1,
        "synthesized_audio": 1,
        "terminal": 1,
    }
    assert projection.first_event_ms == first_delta
    assert projection.completion_ms == terminal - dispatch
    assert projection.stream_duration_ms == terminal - first

    voice_trace = GatewayTraceContext(
        organization_id=7,
        registration_id="endpoint",
        contract_version="1.1",
        trace_id="a" * 32,
        voice_run_id="run",
        invocation_id="inv",
        attempt_id="attempt",
        workflow_version_id="definition",
    ).span_attributes("invoke")
    assert {
        "langgraph.voice_run_id",
        "langgraph.invocation_id",
        "langgraph.attempt_id",
        "langgraph.workflow_version_id",
        "langgraph.registration_id",
        "langgraph.contract_version",
        "langgraph.organization_id",
    } <= voice_trace.keys()

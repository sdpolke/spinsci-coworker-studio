from hypothesis import given, strategies as st

from api.services.workflow.langgraph_binding import live_eligibility_evidence_complete


# Feature: langgraph-voice-integration, Property 38: Live eligibility evidence is complete
@given(
    text_session_conformance=st.booleans(),
    accepted_transition=st.booleans(),
    cancellation_verified=st.booleans(),
    recording_verified=st.booleans(),
)
def test_property_38_live_eligibility_requires_every_evidence_item(
    text_session_conformance,
    accepted_transition,
    cancellation_verified,
    recording_verified,
):
    evidence = {
        "text_session_conformance": text_session_conformance,
        "accepted_transition": accepted_transition,
        "cancellation_verified": cancellation_verified,
        "recording_verified": recording_verified,
    }
    assert live_eligibility_evidence_complete(evidence) is all(evidence.values())

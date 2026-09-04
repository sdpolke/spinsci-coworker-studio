from hypothesis import given
from hypothesis import strategies as st

from api.services.langgraph_integration.threat_model import AgentRequirements, UnsupportedReason, classify_agent_requirements


# Feature: langgraph-voice-integration, Property 2: Unsupported integration requirements are rejected deterministically
@given(st.booleans(), st.booleans(), st.booleans(), st.booleans())
def test_property_2_unsupported_classification(direct_audio, in_process, package, undocumented):
    requirements = AgentRequirements(direct_audio, in_process, package, undocumented)
    first = classify_agent_requirements(requirements)
    second = classify_agent_requirements(requirements)
    expected = tuple(reason for enabled, reason in zip((direct_audio, in_process, package, undocumented), UnsupportedReason) if enabled)
    assert first == second
    assert first.reasons == expected
    assert first.supported is (not expected)

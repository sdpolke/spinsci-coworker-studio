from hypothesis import given
from hypothesis import strategies as st

from api.services.langgraph_integration.protocol import (
    validated_endpoint_trace_headers,
)

_MALFORMED_TRACEPARENT = st.text(max_size=256).filter(
    lambda value: not (
        len(value) == 55
        and value[:3].lower() == "00-"
        and value[35] == "-"
        and value[52] == "-"
        and all(character in "0123456789abcdefABCDEF" for character in value[3:35] + value[36:52])
        and value[53:].lower() in {"00", "01"}
    )
)


# Feature: langgraph-voice-integration, Property 33: Malformed trace headers cannot replace Mural trace identity
@given(candidate=_MALFORMED_TRACEPARENT, tenant_claim=st.text(max_size=64))
def test_property_33_malformed_trace_headers_cannot_replace_mural_identity(candidate, tenant_claim):
    mural_traceparent = f"00-{'a' * 32}-{'b' * 16}-01"
    headers, warnings = validated_endpoint_trace_headers(
        {"traceparent": candidate, "x-organization-id": tenant_claim},
        mural_traceparent=mural_traceparent,
    )
    assert headers["traceparent"] == mural_traceparent
    assert "endpoint tenant claim ignored" in warnings
    if candidate:
        assert "malformed endpoint traceparent ignored" in warnings

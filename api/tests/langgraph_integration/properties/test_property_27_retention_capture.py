from hypothesis import given
from hypothesis import strategies as st

from api.services.langgraph_integration.privacy import (
    RetentionPolicy,
    apply_retention_request,
    persistence_projection,
)


@st.composite
def retention_policies(draw, *, valid: bool):
    days = (
        st.integers(min_value=1, max_value=365)
        if valid
        else st.one_of(st.integers(max_value=0), st.integers(min_value=366, max_value=10000))
    )
    values = [draw(days) for _ in range(4)]
    return RetentionPolicy(*values, capture_payloads=draw(st.booleans()))


# Feature: langgraph-voice-integration, Property 27: Retention and capture policies cannot broaden storage
@given(
    active=retention_policies(valid=True),
    requested=retention_policies(valid=False),
    prompt=st.text(),
    transcript=st.text(),
    arguments=st.dictionaries(st.text(min_size=1, max_size=8), st.text(), max_size=4),
    result=st.text(),
    checkpoint=st.text(),
    request_count=st.integers(min_value=0),
)
def test_property_27_invalid_retention_and_capture_off_cannot_broaden_storage(
    active, requested, prompt, transcript, arguments, result, checkpoint, request_count
):
    assert apply_retention_request(
        active, requested, minimum_days=1, maximum_days=365
    ) == active

    projected = persistence_projection(
        {
            "request_count": request_count,
            "prompt": prompt,
            "nested": {
                "transcript_text": transcript,
                "tool_arguments": arguments,
                "tool_result": result,
                "checkpoint_contents": checkpoint,
                "status": "completed",
            },
        },
        capture_payloads=False,
    )
    assert projected == {
        "request_count": request_count,
        "nested": {"status": "completed"},
    }

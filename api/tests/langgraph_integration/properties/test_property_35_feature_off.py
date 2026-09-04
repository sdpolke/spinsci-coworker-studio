import copy

import pytest
from hypothesis import given, strategies as st

from api.services.workflow.langgraph_binding import (
    LangGraphFeatureDisabledError,
    require_langgraph_feature_for_operation,
)


# Feature: langgraph-voice-integration, Property 35: Feature-off requests are mutation-free
@given(
    operation=st.sampled_from(["create", "attach", "publish", "invoke"]),
    integration_state=st.dictionaries(
        st.text(min_size=1, max_size=12), st.integers(), max_size=8
    ),
)
def test_property_35_feature_off_requests_are_mutation_free(
    operation, integration_state
):
    before = copy.deepcopy(integration_state)
    with pytest.raises(LangGraphFeatureDisabledError):
        require_langgraph_feature_for_operation(enabled=False, operation=operation)
    assert integration_state == before

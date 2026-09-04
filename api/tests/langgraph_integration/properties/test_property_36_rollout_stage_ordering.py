from hypothesis import given, strategies as st

from api.services.langgraph_integration.rollout import (
    ROLLOUT_STAGES,
    RolloutStage,
    is_valid_stage_transition,
)


# Feature: langgraph-voice-integration, Property 36: Rollout stages advance only in order
# **Validates: Requirements 18.5**
@given(
    current=st.sampled_from(ROLLOUT_STAGES),
    target=st.sampled_from(ROLLOUT_STAGES),
)
def test_property_36_only_immediate_forward_stage_transition_is_valid(
    current: RolloutStage,
    target: RolloutStage,
) -> None:
    current_index = ROLLOUT_STAGES.index(current)
    target_index = ROLLOUT_STAGES.index(target)

    if target_index > current_index:
        assert is_valid_stage_transition(current, target) is (
            target_index == current_index + 1
        )
    else:
        assert is_valid_stage_transition(current, target)

import asyncio

from hypothesis import given, strategies as st

from api.services.langgraph_integration.failure_policies import (
    FIRST_EVENT_ACTIONS,
    FailurePolicy,
    FailurePolicyCoordinator,
    InMemoryPolicyEffectStore,
)


# Feature: langgraph-voice-integration, Property 23: First-event deadlines are bounded and idempotent
@given(
    deadline=st.integers(min_value=0, max_value=4000),
    action=st.sampled_from(sorted(FIRST_EVENT_ACTIONS)),
    first_event_accepted=st.booleans(),
)
def test_property_23_first_event_deadlines_are_bounded_and_idempotent(
    deadline, action, first_event_accepted
):
    if deadline < 500 or deadline > 3000:
        try:
            FailurePolicy(deadline, action, "end_call")
        except ValueError:
            return
        raise AssertionError("out-of-bound deadline was accepted")

    effects = []
    metrics = []

    async def execute(selected):
        effects.append(selected)

    async def cancel():
        effects.append("cancel")

    coordinator = FailurePolicyCoordinator(
        store=InMemoryPolicyEffectStore(),
        execute_action=execute,
        cancel_late_stream=cancel,
        record_metric=metrics.append,
    )
    policy = FailurePolicy(deadline, action, "end_call")
    first = asyncio.run(
        coordinator.on_first_event_deadline(
            organization_id=1,
            invocation_id="invocation",
            policy=policy,
            first_event_accepted=first_event_accepted,
        )
    )
    replay = asyncio.run(
        coordinator.on_first_event_deadline(
            organization_id=1,
            invocation_id="invocation",
            policy=policy,
            first_event_accepted=first_event_accepted,
        )
    )
    assert first is (not first_event_accepted)
    assert replay is False
    assert metrics == ([] if first_event_accepted else ["first_event_timeout"])
    assert effects == ([] if first_event_accepted else ["cancel", action])

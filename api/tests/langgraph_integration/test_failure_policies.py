import asyncio

import pytest

from api.services.langgraph_integration.failure_policies import (
    FailurePolicy,
    FailurePolicyCoordinator,
    InMemoryPolicyEffectStore,
)


@pytest.mark.parametrize("deadline", [500, 3000])
def test_first_event_policy_accepts_inclusive_boundaries(deadline):
    assert FailurePolicy(deadline, "fallback_message", "retry_prompt").first_event_deadline_ms == deadline


@pytest.mark.parametrize("action", ["retry_prompt", "fallback_message", "transfer", "end_call"])
def test_terminal_actions_execute_once_on_replay(action):
    calls = []

    async def execute(selected):
        calls.append(selected)

    async def cancel():
        calls.append("cancel")

    coordinator = FailurePolicyCoordinator(
        store=InMemoryPolicyEffectStore(),
        execute_action=execute,
        cancel_late_stream=cancel,
    )
    policy = FailurePolicy(1000, "fallback_message", action)
    assert asyncio.run(coordinator.on_terminal_failure(
        organization_id=1, invocation_id="inv", policy=policy, error_category="timeout"
    ))
    assert not asyncio.run(coordinator.on_terminal_failure(
        organization_id=1, invocation_id="inv", policy=policy, error_category="timeout"
    ))
    assert calls == [action]


def test_late_stream_is_cancelled_before_one_timeout_metric_and_action():
    order = []

    async def execute(action):
        order.append(action)

    async def cancel():
        order.append("cancel")

    coordinator = FailurePolicyCoordinator(
        store=InMemoryPolicyEffectStore(),
        execute_action=execute,
        cancel_late_stream=cancel,
        record_metric=lambda metric: order.append(metric),
    )
    policy = FailurePolicy(1500, "transfer", "end_call")
    assert asyncio.run(coordinator.on_first_event_deadline(
        organization_id=1, invocation_id="inv", policy=policy, first_event_accepted=False
    ))
    assert not asyncio.run(coordinator.on_first_event_deadline(
        organization_id=1, invocation_id="inv", policy=policy, first_event_accepted=False
    ))
    assert order == ["cancel", "first_event_timeout", "transfer"]


def test_accepted_first_event_has_no_timeout_effect():
    called = []

    async def callback(value="cancel"):
        called.append(value)

    coordinator = FailurePolicyCoordinator(
        store=InMemoryPolicyEffectStore(),
        execute_action=callback,
        cancel_late_stream=callback,
    )
    assert not asyncio.run(coordinator.on_first_event_deadline(
        organization_id=1,
        invocation_id="inv",
        policy=FailurePolicy(500, "end_call", "end_call"),
        first_event_accepted=True,
    ))
    assert called == []

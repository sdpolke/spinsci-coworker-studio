import asyncio
import uuid

from hypothesis import given
from hypothesis import strategies as st

from api.services.langgraph_integration.protocol import (
    InMemoryAcceptedEventLedger,
    InvocationIdentity,
    ProtocolViolation,
    ReductionDisposition,
    RetryState,
    RuntimeEventReducer,
    TerminalOutcomeGuard,
    asynchronous_deadline_outcome,
    should_retry,
    validate_asynchronous_acceptance,
    validate_synchronous_result,
)
from api.tests.langgraph_integration.properties.strategies import (
    identifier,
    json_fragments,
)


def _assistant_response(invocation_id="inv"):
    return {
        "contract_version": "1.0",
        "invocation_id": invocation_id,
        "result": {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [{"type": "text", "text": "accepted"}],
            },
            "status": "completed",
        },
    }


SAFE_TEXT = st.text(
    alphabet=st.characters(whitelist_categories=("Ll", "Lu", "Nd")),
    min_size=1,
    max_size=50,
)


# Feature: langgraph-voice-integration, Property 4: Only negotiated output semantics can progress state
@given(st.sampled_from(["valid", "missing", "multiple", "unknown"]), identifier)
def test_property_4_only_valid_negotiated_output_progresses(kind, initial_node):
    state = {"history": [], "node": initial_node}
    before = {"history": list(state["history"]), "node": state["node"]}
    payload = _assistant_response()
    if kind == "missing":
        payload.pop("result")
    elif kind == "multiple":
        payload["result"] = [payload["result"], payload["result"]]
    elif kind == "unknown":
        payload["result"] = {"type": "endpoint_control", "node": "foreign"}
    try:
        result = validate_synchronous_result(
            payload,
            contract_version="1.0",
            invocation_id="inv",
            response_bytes_limit=1_000_000,
        )
    except ProtocolViolation:
        result = None
    if result is not None:
        state["history"].append(result.result.type)
    assert (state != before) is (kind == "valid")
    if kind != "valid":
        assert state == before


# Feature: langgraph-voice-integration, Property 13: Streaming accepts one ordered terminal history
@given(st.lists(SAFE_TEXT, max_size=20), st.lists(SAFE_TEXT, max_size=10))
def test_property_13_first_terminal_is_authoritative_and_post_terminal_is_inert(texts, late_texts):
    async def scenario():
        reducer = RuntimeEventReducer(
            contract_version="1.0",
            invocation_id="inv",
            ledger=InMemoryAcceptedEventLedger(),
            event_bytes_limit=65_536,
            tool_argument_bytes_limit=262_144,
        )
        forwarded = []
        for sequence, text in enumerate(texts):
            result = await reducer.reduce(
                {
                    "contract_version": "1.0",
                    "invocation_id": "inv",
                    "sequence": sequence,
                    "event_id": f"event-{sequence}",
                    "type": "text_delta",
                    "data": {"text": text},
                }
            )
            forwarded.append(result.speakable_text)
        terminal_sequence = len(texts)
        terminal = await reducer.reduce(
            {
                "contract_version": "1.0",
                "invocation_id": "inv",
                "sequence": terminal_sequence,
                "event_id": f"event-{terminal_sequence}",
                "type": "completed",
                "data": {"status": "completed"},
            }
        )
        for offset, text in enumerate(late_texts, 1):
            late = await reducer.reduce(
                {
                    "contract_version": "1.0",
                    "invocation_id": "inv",
                    "sequence": terminal_sequence + offset,
                    "event_id": f"late-{offset}",
                    "type": "text_delta",
                    "data": {"text": text},
                }
            )
            assert late.disposition is ReductionDisposition.POST_TERMINAL
            assert late.speakable_text is None
        return forwarded, terminal

    forwarded, terminal = asyncio.run(scenario())
    assert forwarded == texts
    assert terminal.terminal
    assert terminal.event.sequence == len(texts)


# Feature: langgraph-voice-integration, Property 14: Synchronous and asynchronous cardinality is exact
@given(st.integers(min_value=0, max_value=3), st.one_of(identifier, st.just(""), st.just("   ")))
def test_property_14_mode_cardinality_is_exact(sync_count, external_run_id):
    sync_payload = _assistant_response()
    if sync_count == 0:
        sync_payload.pop("result")
    elif sync_count != 1:
        sync_payload["result"] = [sync_payload["result"]] * sync_count
    sync_accepted = True
    try:
        validate_synchronous_result(
            sync_payload,
            contract_version="1.0",
            invocation_id="inv",
            response_bytes_limit=1_000_000,
        )
    except ProtocolViolation:
        sync_accepted = False
    assert sync_accepted is (sync_count == 1)

    async_accepted = True
    try:
        validate_asynchronous_acceptance(
            {
                "contract_version": "1.0",
                "invocation_id": "inv",
                "status": "accepted",
                "external_run_id": external_run_id,
            },
            contract_version="1.0",
            invocation_id="inv",
            response_bytes_limit=1_000_000,
        )
    except ProtocolViolation:
        async_accepted = False
    assert async_accepted is bool(external_run_id.strip())


# Feature: langgraph-voice-integration, Property 15: Asynchronous deadlines produce one pinned outcome
@given(st.booleans())
def test_property_15_async_deadline_orders_cancel_before_single_timeout(cancellation_declared):
    outcome = asynchronous_deadline_outcome(cancellation_declared=cancellation_declared)
    assert outcome.operations.count("timeout_effect") == 1
    if cancellation_declared:
        assert outcome.operations == ("cancel", "timeout_effect")
    else:
        assert outcome.operations == ("timeout_effect",)


# Feature: langgraph-voice-integration, Property 17: Retry decisions preserve logical identity and obey the event boundary
@given(
    failure=st.one_of(
        st.sampled_from(["connection_failure", "timeout", "invalid_response"]),
        st.sampled_from([408, 425, 429, 500, 502, 503, 504]),
    ),
    accepted_event=st.booleans(),
    attempts_used=st.integers(min_value=1, max_value=3),
    remaining_ms=st.integers(min_value=0, max_value=10_000),
    minimum_attempt_ms=st.integers(min_value=1, max_value=5_000),
    cancelled=st.booleans(),
)
def test_property_17_retry_identity_and_event_boundary(
    failure, accepted_event, attempts_used, remaining_ms, minimum_attempt_ms, cancelled
):
    state = RetryState(
        accepted_event=accepted_event,
        attempts_used=attempts_used,
        remaining_ms=remaining_ms,
        minimum_attempt_ms=minimum_attempt_ms,
        cancelled=cancelled,
    )
    expected = (
        failure in {"connection_failure", "timeout", 408, 425, 429, 502, 503, 504}
        and not accepted_event
        and not cancelled
        and attempts_used == 1
        and remaining_ms >= minimum_attempt_ms
    )
    assert should_retry(failure=failure, state=state) is expected

    identity = InvocationIdentity("logical-invocation")
    attempt_ids = [uuid.uuid4().hex for _ in range(2 if expected else 1)]
    for attempt_id in attempt_ids:
        identity.new_attempt(attempt_id)
    assert identity.invocation_id == "logical-invocation"
    assert len(identity.attempt_ids) == len(set(attempt_ids))
    assert len(identity.attempt_ids) == (2 if expected else 1)


# Feature: langgraph-voice-integration, Property 18: Terminal outcomes and failure actions are idempotent
@given(st.dictionaries(identifier, st.integers(), max_size=5), st.sampled_from(["retry_prompt", "fallback_message", "transfer", "end_call"]))
def test_property_18_terminal_replay_and_failure_action_are_idempotent(outcome, action):
    guard = TerminalOutcomeGuard()
    first, inserted = guard.record(outcome)
    replay, replay_inserted = guard.record({"different": True})
    assert inserted
    assert not replay_inserted
    assert replay == first == outcome
    assert guard.execute_failure_action(action)
    assert not guard.execute_failure_action(action)
    assert guard.failure_action == action


# Feature: langgraph-voice-integration, Property 19: Tool Call fragmentation round-trips
@given(json_fragments(), identifier)
def test_property_19_tool_call_fragmentation_round_trips(fragment_case, tool_name):
    value, fragments = fragment_case

    async def scenario():
        reducer = RuntimeEventReducer(
            contract_version="1.0",
            invocation_id="inv",
            ledger=InMemoryAcceptedEventLedger(),
            event_bytes_limit=65_536,
            tool_argument_bytes_limit=262_144,
        )
        sequence = 0
        await reducer.reduce(
            {
                "contract_version": "1.0",
                "invocation_id": "inv",
                "sequence": sequence,
                "event_id": "start",
                "type": "tool_call_start",
                "data": {"tool_call_id": "call", "name": tool_name},
            }
        )
        for index, fragment in enumerate(fragments):
            sequence += 1
            await reducer.reduce(
                {
                    "contract_version": "1.0",
                    "invocation_id": "inv",
                    "sequence": sequence,
                    "event_id": f"delta-{index}",
                    "type": "tool_call_delta",
                    "data": {"tool_call_id": "call", "fragment": fragment},
                }
            )
        sequence += 1
        return await reducer.reduce(
            {
                "contract_version": "1.0",
                "invocation_id": "inv",
                "sequence": sequence,
                "event_id": "end",
                "type": "tool_call_end",
                "data": {"tool_call_id": "call"},
            }
        )

    result = asyncio.run(scenario())
    assert result.tool_call.arguments == value
    assert result.tool_call.name == tool_name


# Feature: langgraph-voice-integration, Property 22: Speakable text is forwarded exactly once
@given(st.lists(SAFE_TEXT, min_size=1, max_size=20, unique=True))
def test_property_22_unique_non_empty_text_is_forwarded_once(texts):
    async def scenario():
        reducer = RuntimeEventReducer(
            contract_version="1.0",
            invocation_id="inv",
            ledger=InMemoryAcceptedEventLedger(),
            event_bytes_limit=65_536,
            tool_argument_bytes_limit=262_144,
        )
        forwarded = []
        first_payload = None
        for sequence, text in enumerate(texts):
            payload = {
                "contract_version": "1.0",
                "invocation_id": "inv",
                "sequence": sequence,
                "event_id": f"event-{sequence}",
                "type": "text_delta",
                "data": {"text": text},
            }
            first_payload = first_payload or payload
            result = await reducer.reduce(payload)
            if result.disposition is ReductionDisposition.ACCEPTED:
                forwarded.append(result.speakable_text)
        duplicate = await reducer.reduce(first_payload)
        if duplicate.disposition is ReductionDisposition.ACCEPTED:
            forwarded.append(duplicate.speakable_text)
        return forwarded, duplicate

    forwarded, duplicate = asyncio.run(scenario())
    assert forwarded == texts
    assert duplicate.disposition is ReductionDisposition.DUPLICATE
    assert all(text for text in forwarded)

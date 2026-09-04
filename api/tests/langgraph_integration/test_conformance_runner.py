from __future__ import annotations

from dataclasses import replace

import pytest

from api.services.langgraph_integration.conformance import (
    CHAT_BASELINE_FIXTURES,
    FIXTURES_BY_ID,
    SUITE_VERSION,
    ConformanceObservation,
    ScriptedEndpointSimulator,
    run_fixture,
    run_suite,
    suite_digest,
)

_REQUIRED_BASELINE_IDS = {
    "chat.valid.plain_text",
    "chat.valid.fragmented_text",
    "chat.valid.single_tool_call",
    "chat.valid.multiple_tool_calls",
    "chat.valid.fragmented_json",
    "chat.valid.tool_result",
    "chat.valid.usage",
    "chat.valid.structured_error",
    "chat.valid.retry_before_event",
    "chat.valid.cancellation",
    "chat.valid.terminal",
    "chat.valid.idempotent_replay",
    "chat.malformed.invalid_schema",
    "chat.malformed.unknown_event",
    "chat.malformed.duplicate_event",
    "chat.malformed.reordered_fragments",
    "chat.malformed.oversized_payload",
    "chat.malformed.authentication",
    "chat.malformed.timeout",
    "chat.malformed.disconnect",
    "chat.malformed.post_terminal",
}


def test_baseline_catalog_covers_every_required_chat_conformance_case() -> None:
    assert set(FIXTURES_BY_ID) == _REQUIRED_BASELINE_IDS
    assert all(fixture.required for fixture in CHAT_BASELINE_FIXTURES)
    assert all(fixture.contract_version == "1.0" for fixture in CHAT_BASELINE_FIXTURES)
    assert all(fixture.test_version == "1.0" for fixture in CHAT_BASELINE_FIXTURES)


@pytest.mark.parametrize("fixture", CHAT_BASELINE_FIXTURES, ids=lambda fixture: fixture.identifier)
def test_fixture_runner_matches_declared_oracle(fixture) -> None:
    result = run_fixture(fixture)

    assert result.passed, result.mismatches
    assert result.mismatches == ()
    assert len(result.fixture_digest) == 64
    assert len(result.observation_digest) == 64
    assert len(result.result_digest) == 64


def test_valid_fixtures_declare_terminal_outcomes_and_malformed_fixtures_declare_errors() -> None:
    for fixture in CHAT_BASELINE_FIXTURES:
        if fixture.kind == "valid":
            assert fixture.oracle.terminal_outcome is not None
        else:
            assert fixture.oracle.structured_error is not None
            assert fixture.oracle.unauthorized_effects == ()


def test_simulator_replays_isolated_steps_and_produces_reference_observation() -> None:
    fixture = FIXTURES_BY_ID["chat.valid.plain_text"]
    simulator = ScriptedEndpointSimulator(fixture)
    steps = list(simulator.steps())
    steps[0]["data"]["text"] = "mutated"

    assert fixture.script[0]["data"]["text"] == "Hello"
    assert simulator.observe().to_dict() == fixture.oracle.to_dict()
    assert simulator.suite_contract_version == fixture.contract_version


def test_oracle_comparison_detects_each_observable_dimension() -> None:
    fixture = FIXTURES_BY_ID["chat.valid.plain_text"]
    baseline = ScriptedEndpointSimulator(fixture).observe()
    changed_observation = replace(
        baseline,
        effects=(*baseline.effects, {"type": "unauthorized_tool"}),
        unauthorized_effects=({"type": "unauthorized_tool"},),
    )

    result = run_fixture(fixture, changed_observation)

    assert not result.passed
    assert result.mismatches == ("effects", "unauthorized_effects")
    persistence = result.to_validation_result()
    assert persistence["outcome"] == "failed"
    assert persistence["redacted_error"] == {"mismatches": ["effects", "unauthorized_effects"]}


def test_malformed_post_terminal_data_preserves_terminal_but_has_no_late_effect() -> None:
    fixture = FIXTURES_BY_ID["chat.malformed.post_terminal"]
    observation = ScriptedEndpointSimulator(fixture).observe()

    assert observation.terminal_outcome == {"status": "completed"}
    assert observation.structured_error == {
        "category": "invalid_response",
        "code": "post_terminal_data",
        "retryable": False,
    }
    assert observation.effects == ()
    assert observation.state_mutations == ()
    assert observation.unauthorized_effects == ()


def test_idempotent_fixture_executes_one_tool_effect_and_one_logical_result() -> None:
    observation = ScriptedEndpointSimulator(FIXTURES_BY_ID["chat.valid.idempotent_replay"]).observe()

    assert [effect["type"] for effect in observation.effects] == ["tool_call"]
    assert observation.terminal_outcome == {"status": "completed", "logical_results": 1}
    assert observation.state_mutations == ({"type": "append_tool_call", "tool_call_id": "tool-1"},)


def test_suite_metadata_is_deterministic_and_persistence_ready() -> None:
    first = run_suite()
    second = run_suite()

    assert first == second
    assert first.passed
    assert first.suite_version == SUITE_VERSION
    assert first.fixture_digest == suite_digest()
    assert len(first.result_digest) == 64
    assert first.report_evidence() == {
        "suite_version": SUITE_VERSION,
        "fixture_digest": first.fixture_digest,
        "result_digest": first.result_digest,
        "required_fixture_count": len(CHAT_BASELINE_FIXTURES),
        "passed_fixture_count": len(CHAT_BASELINE_FIXTURES),
    }

    persistence_results = first.persistence_results()
    assert len(persistence_results) == len(CHAT_BASELINE_FIXTURES)
    assert {result["test_identifier"] for result in persistence_results} == _REQUIRED_BASELINE_IDS
    assert all(result["outcome"] == "passed" for result in persistence_results)
    assert all(result["measurements"]["suite_version"] == SUITE_VERSION for result in persistence_results)


def test_suite_digest_changes_when_fixture_oracle_changes() -> None:
    fixture = CHAT_BASELINE_FIXTURES[0]
    changed = replace(
        fixture,
        oracle=replace(fixture.oracle, terminal_outcome={"status": "failed"}),
    )

    assert suite_digest((fixture,)) != suite_digest((changed,))


def test_external_observation_can_be_compared_without_running_simulator() -> None:
    fixture = FIXTURES_BY_ID["chat.malformed.authentication"]
    observation = ConformanceObservation(
        structured_error={
            "category": "authentication",
            "code": "endpoint_authentication_failed",
            "retryable": False,
        }
    )

    assert run_fixture(fixture, observation).passed

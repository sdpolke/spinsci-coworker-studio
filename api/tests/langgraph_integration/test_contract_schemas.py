from datetime import date

import pytest
from pydantic import ValidationError

from api.schemas.langgraph_integration import SUPPORTED_SCHEMA_VERSIONS, schema_for, v1_0, v1_1
from api.schemas.langgraph_integration.examples import EXECUTABLE_EXAMPLES
from api.services.langgraph_integration.contract import MatrixVersion, ProfileRequirements, negotiate_contract_version


def test_all_executable_examples_validate_for_claimed_version():
    for version, examples in EXECUTABLE_EXAMPLES.items():
        for operation, payload in examples.items():
            assert schema_for(version, operation).model_validate(payload)


def test_supported_minor_versions_are_explicit():
    assert SUPPORTED_SCHEMA_VERSIONS == ("1.0", "1.1")


def test_v10_rejects_v11_optional_invocation_field():
    payload = EXECUTABLE_EXAMPLES["1.0"]["invocation"] | {"locale": "en-US"}
    with pytest.raises(ValidationError):
        v1_0.InvocationRequest.model_validate(payload)


def test_v11_accepts_payload_valid_under_v10_when_version_is_pinned_to_v11():
    payload = EXECUTABLE_EXAMPLES["1.0"]["invocation"] | {"contract_version": "1.1"}
    assert v1_1.InvocationRequest.model_validate(payload).locale is None


def test_identifier_and_deadline_bounds_are_enforced():
    payload = EXECUTABLE_EXAMPLES["1.0"]["invocation"] | {"invocation_id": "x" * 256}
    with pytest.raises(ValidationError):
        v1_0.InvocationRequest.model_validate(payload)
    payload = EXECUTABLE_EXAMPLES["1.0"]["invocation"] | {"deadlines": {"first_event_ms": 499, "turn_ms": 1000}}
    with pytest.raises(ValidationError):
        v1_0.InvocationRequest.model_validate(payload)


def test_sync_and_async_cardinality_models_are_exact():
    with pytest.raises(ValidationError):
        v1_0.SynchronousResponse.model_validate({"contract_version": "1.0", "invocation_id": "inv", "result": []})
    with pytest.raises(ValidationError):
        v1_0.AsynchronousAcceptance.model_validate({"contract_version": "1.0", "invocation_id": "inv", "external_run_id": ""})


def test_matrix_is_immutable_and_selects_highest_common_minor():
    matrix = MatrixVersion(
        matrix_version="2026-01", effective_date=date(2026, 1, 1), mural_release_version="1.44.0",
        supported_contract_versions=("1.0", "1.1"),
        profiles=(ProfileRequirements(profile="chat", required_invocation_modes=frozenset({"streaming"}), allowed_state_modes=frozenset({"mural_authoritative"})),),
    )
    assert negotiate_contract_version(["1.0", "1.1", "2.0"], matrix) == "1.1"
    with pytest.raises(ValidationError):
        matrix.matrix_version = "changed"

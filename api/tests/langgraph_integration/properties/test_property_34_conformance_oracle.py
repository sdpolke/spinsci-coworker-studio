from __future__ import annotations

from dataclasses import fields, replace
from typing import Any

from hypothesis import given
from hypothesis import strategies as st

from api.services.langgraph_integration.conformance import (
    CHAT_BASELINE_FIXTURES,
    ConformanceObservation,
    ScriptedEndpointSimulator,
    run_fixture,
)

_ORACLE_FIELDS = tuple(field.name for field in fields(ConformanceObservation))
_VALID_FIXTURES = tuple(fixture for fixture in CHAT_BASELINE_FIXTURES if fixture.kind == "valid")
_MALFORMED_FIXTURES = tuple(fixture for fixture in CHAT_BASELINE_FIXTURES if fixture.kind == "malformed")


def _different_value(field_name: str, original: Any) -> Any:
    marker = {"property_34_mismatch": field_name}
    if field_name in {"accepted_events", "effects", "state_mutations", "unauthorized_effects"}:
        return (*original, marker)
    return marker if original != marker else {"property_34_mismatch": f"different_{field_name}"}


@st.composite
def conformance_oracle_cases(draw):
    kind = draw(st.sampled_from(("valid", "malformed")))
    fixtures = _VALID_FIXTURES if kind == "valid" else _MALFORMED_FIXTURES
    fixture = draw(st.sampled_from(fixtures))
    mismatched_fields = draw(st.sets(st.sampled_from(_ORACLE_FIELDS), max_size=len(_ORACLE_FIELDS)))

    reference = ScriptedEndpointSimulator(fixture).observe()
    changes = {
        field_name: _different_value(field_name, getattr(reference, field_name))
        for field_name in mismatched_fields
    }
    return fixture, replace(reference, **changes), mismatched_fields


# Feature: langgraph-voice-integration, Property 34: Conformance results equal their declared oracle
@given(conformance_oracle_cases())
def test_property_34_conformance_result_equals_declared_oracle(case) -> None:
    fixture, observation, mismatched_fields = case

    result = run_fixture(fixture, observation)
    expected_mismatches = tuple(
        field_name for field_name in _ORACLE_FIELDS if field_name in mismatched_fields
    )

    assert result.passed is (not expected_mismatches)
    assert result.mismatches == expected_mismatches
    assert result.to_validation_result()["outcome"] == (
        "passed" if not expected_mismatches else "failed"
    )

    if fixture.kind == "valid":
        assert fixture.oracle.terminal_outcome is not None
    else:
        assert fixture.oracle.structured_error is not None
        assert fixture.oracle.unauthorized_effects == ()

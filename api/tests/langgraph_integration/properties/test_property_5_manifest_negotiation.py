from datetime import date

import pytest
from hypothesis import given
from hypothesis import strategies as st

from api.services.langgraph_integration.contract import MatrixVersion, VersionIncompatibilityError, negotiate_contract_version, validate_manifest, validate_selected_capabilities

from .strategies import manifests, version_sets


def matrix(versions):
    return MatrixVersion(matrix_version="test", effective_date=date(2026, 1, 1), mural_release_version="test", supported_contract_versions=tuple(sorted(versions)), profiles=())


# Feature: langgraph-voice-integration, Property 5: Discovery validation and version negotiation are exact
@given(manifests, st.sets(st.sampled_from(["streaming", "synchronous", "asynchronous", "interrupts"]), max_size=4), version_sets)
def test_property_5_manifest_validation_and_negotiation(payload, selected, supported):
    result = validate_manifest(payload, "1.0")
    assert not result.violations
    declared = set(payload["invocation_modes"])
    assert set(validate_selected_capabilities(declared=declared, selected=selected)) == selected - declared

    offered = set(payload["contract_versions"])
    common = offered & supported
    if common:
        expected = max(common, key=lambda value: tuple(map(int, value.split("."))))
        assert negotiate_contract_version(offered, matrix(supported)) == expected
    else:
        with pytest.raises(VersionIncompatibilityError):
            negotiate_contract_version(offered, matrix(supported))


@given(st.dictionaries(st.text(min_size=1, max_size=8), st.integers(), max_size=8))
def test_property_5_reports_every_manifest_schema_violation(payload):
    result = validate_manifest(payload, "1.0")
    if result.manifest is None:
        assert result.violations
        assert len(result.violations) == len(set(result.violations))

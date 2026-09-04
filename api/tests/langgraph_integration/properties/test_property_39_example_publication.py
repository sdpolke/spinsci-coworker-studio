from __future__ import annotations

from copy import deepcopy
from typing import Any

from hypothesis import given
from hypothesis import strategies as st

from api.schemas.langgraph_integration import SUPPORTED_SCHEMA_VERSIONS
from api.schemas.langgraph_integration.examples import PUBLICATION_EXAMPLES
from api.services.langgraph_integration.contract.reference import (
    ExamplePublicationError,
    validate_publication_examples,
)


def _association_for(category: str, version: str) -> dict[str, Any]:
    source = next(
        example for example in PUBLICATION_EXAMPLES if example["category"] == category
    )
    return {
        "id": f"property-39-{category}-{version}",
        "category": category,
        "claimed_contract_versions": (version,),
        "steps_by_version": {version: deepcopy(source["steps_by_version"][version])},
        "expected_observable_result": source["expected_observable_result"],
    }


@st.composite
def example_version_associations(draw):
    category = draw(
        st.sampled_from(tuple(example["category"] for example in PUBLICATION_EXAMPLES))
    )
    version = draw(st.sampled_from(SUPPORTED_SCHEMA_VERSIONS))
    execution_passes = draw(st.booleans())
    association = _association_for(category, version)

    if not execution_passes:
        association["steps_by_version"][version][0]["payload"][
            "contract_version"
        ] = "unsupported-property-version"

    return association, version, execution_passes


# Feature: langgraph-voice-integration, Property 39: Documentation examples publish only for passing versions
# **Validates: Requirements 19.6**
@given(example_version_associations())
def test_property_39_example_version_publication_matches_execution(
    generated_association,
) -> None:
    association, version, execution_passes = generated_association

    try:
        validated = validate_publication_examples([association])
    except ExamplePublicationError:
        publishable = False
        validated = []
    else:
        publishable = True

    assert publishable is execution_passes
    if publishable:
        assert [(item["example_id"], item["contract_version"]) for item in validated] == [
            (association["id"], version)
        ]

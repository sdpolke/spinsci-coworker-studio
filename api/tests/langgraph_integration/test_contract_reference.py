import json
from pathlib import Path

import pytest

from api.schemas.langgraph_integration import (
    SUPPORTED_SCHEMA_VERSIONS,
    schema_operations,
)
from api.schemas.langgraph_integration.common import ErrorCategory
from api.schemas.langgraph_integration.examples import copy_publication_examples
from api.services.langgraph_integration.contract.catalog import (
    COMPATIBILITY_MATRICES,
    OPERATOR_CHECKLIST,
)
from api.services.langgraph_integration.contract.reference import (
    EXAMPLE_CATEGORIES,
    ExamplePublicationError,
    build_contract_reference,
    render_contract_reference_json,
    render_contract_reference_mdx,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
JSON_ARTIFACT = REPO_ROOT / "docs/developer/generated/langgraph-contract-reference.json"
MDX_ARTIFACT = REPO_ROOT / "docs/developer/langgraph-contract-reference.mdx"


def test_inventory_is_complete_and_retains_all_supported_versions():
    reference = build_contract_reference()
    contracts = {
        contract["contract_version"]: contract for contract in reference["contracts"]
    }

    assert tuple(contracts) == SUPPORTED_SCHEMA_VERSIONS
    assert {
        version
        for matrix in COMPATIBILITY_MATRICES
        for version in matrix.supported_contract_versions
    } == set(contracts)
    for version, contract in contracts.items():
        expected_operations = set(schema_operations(version))
        assert set(contract["schemas"]) == expected_operations
        assert {
            operation["schema"] for operation in contract["operations"]
        } == expected_operations
        assert (
            contract["documentation_version"] == reference["documentation"]["version"]
        )
        assert contract["mural_release_versions"]

    assert {profile["profile"] for profile in reference["profiles"]} == {
        "chat",
        "stateful_run",
    }
    operations_by_schema = {
        operation["schema"]: operation for operation in contracts["1.2"]["operations"]
    }
    assert operations_by_schema["topology_request"] == {"schema": "topology_request"}
    assert operations_by_schema["topology"] == {"schema": "topology"}
    assert operations_by_schema["topology_unsupported"] == {
        "schema": "topology_unsupported"
    }
    assert {method["id"] for method in reference["authentication"]} == {
        "credential_reference"
    }
    assert {policy["id"] for policy in reference["timeouts"]} == {
        "discovery",
        "first_event",
        "turn",
        "cancellation_dispatch",
    }
    assert reference["retries"] and reference["cancellation"]
    assert set(reference["errors"]) == {category.value for category in ErrorCategory}
    assert {item["field"] for item in reference["ownership"]} == {
        "prompts",
        "conversation_history",
        "frontend_workflow_state",
        "langgraph_internal_state",
        "checkpoints",
        "thread_id",
        "external_run_id",
        "tool_definitions",
        "tool_calls",
        "tool_results",
        "telephony_controls",
        "recordings",
    }
    assert tuple(reference["operator_checklist"]) == OPERATOR_CHECKLIST


def test_all_example_categories_execute_for_every_claimed_version_with_observable_metadata():
    reference = build_contract_reference()
    examples = reference["examples"]

    assert {example["category"] for example in examples} == EXAMPLE_CATEGORIES
    associations = {
        (example["category"], example["contract_version"]) for example in examples
    }
    assert associations == {
        (category, version)
        for category in EXAMPLE_CATEGORIES
        for version in SUPPORTED_SCHEMA_VERSIONS
    }
    for example in examples:
        assert example["steps"]
        assert example["validated_at"].endswith("Z")
        assert example["expected_observable_result"]


def test_publication_is_blocked_if_any_claimed_version_fails():
    examples = copy_publication_examples()
    examples[0]["steps_by_version"]["1.0"][0]["payload"]["invocation_id"] = ""

    with pytest.raises(ExamplePublicationError) as exc_info:
        build_contract_reference(examples)

    assert any(
        failure["example_id"] == "sync-example" and failure["version"] == "1.0"
        for failure in exc_info.value.failures
    )


def test_generated_contract_reference_artifacts_are_current():
    reference = build_contract_reference()

    assert json.loads(JSON_ARTIFACT.read_text()) == reference
    assert JSON_ARTIFACT.read_text() == render_contract_reference_json(reference)
    assert MDX_ARTIFACT.read_text() == render_contract_reference_mdx(reference)

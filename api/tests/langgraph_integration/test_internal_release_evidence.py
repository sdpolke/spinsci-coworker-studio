from datetime import UTC, datetime

from api.services.langgraph_integration.conformance import run_suite
from api.services.langgraph_integration.performance import (
    CapacitySnapshot,
    FixedEnvironment,
    LoadSample,
    evaluate_performance,
)
from api.services.langgraph_integration.release_evidence import (
    RuntimeEligibilityEvidence,
    assemble_internal_release_evidence,
    release_validation_results,
)
from api.services.langgraph_integration.configuration import LangGraphFeatureConfiguration

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def passing_performance():
    return evaluate_performance(
        environment=FixedEnvironment(
            name="ci-local-simulator",
            concurrency=10,
            warmed_requests=5,
            payload_bytes=4096,
            tool_count=2,
            endpoint_region="local",
        ),
        samples=[LoadSample(100, 500, 20, 25) for _ in range(100)],
        capacity=CapacitySnapshot(10, 5, 20),
        measured_at=NOW,
    )


def runtime(**changes):
    values = {
        "text_session_conformance": True,
        "accepted_transition": True,
        "cancellation_verified": True,
        "recording_verified": True,
        "live_smoke_passed": True,
    }
    values.update(changes)
    return RuntimeEligibilityEvidence(**values)


def test_release_evidence_is_complete_immutable_and_report_ready():
    evidence = assemble_internal_release_evidence(
        contract_version="1.1",
        matrix_version="2026.1",
        conformance=run_suite(),
        performance=passing_performance(),
        runtime=runtime(),
        feature_enabled_by_default=LangGraphFeatureConfiguration().enabled,
        assembled_at=NOW,
    )

    payload = evidence.validation_report_evidence()
    assert evidence.passed
    assert payload["fixture_digest"]
    assert payload["performance"]["request_count"] == 100
    assert payload["live_smoke_passed"] if "live_smoke_passed" in payload else payload["runtime"]["live_smoke_passed"]
    assert payload["feature_enabled_by_default"] is False
    assert len(evidence.evidence_digest) == 64
    assert all(result["outcome"] == "passed" for result in release_validation_results(evidence))


def test_release_cannot_advance_with_incomplete_evidence_or_enabled_default():
    evidence = assemble_internal_release_evidence(
        contract_version="1.1",
        matrix_version="2026.1",
        conformance=run_suite(),
        performance=passing_performance(),
        runtime=runtime(recording_verified=False),
        feature_enabled_by_default=True,
        assembled_at=NOW,
    )

    assert not evidence.passed
    assert evidence.failures == (
        "runtime_eligibility_evidence_incomplete",
        "experimental_feature_must_default_disabled",
    )
    failed = [item["test_identifier"] for item in release_validation_results(evidence) if item["outcome"] == "failed"]
    assert failed == [
        "internal_release.runtime_evidence",
        "internal_release.feature_default",
    ]

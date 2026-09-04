"""Immutable evidence assembly and gates for the internal Chat release."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

from api.services.langgraph_integration.conformance import ConformanceSuiteResult
from api.services.langgraph_integration.performance import PerformanceReport

from .conformance import deterministic_digest

RELEASE_EVIDENCE_VERSION = "internal-chat-1.0.0"


@dataclass(frozen=True)
class RuntimeEligibilityEvidence:
    text_session_conformance: bool
    accepted_transition: bool
    cancellation_verified: bool
    recording_verified: bool
    live_smoke_passed: bool

    @property
    def complete(self) -> bool:
        return all(asdict(self).values())


@dataclass(frozen=True)
class InternalReleaseEvidence:
    evidence_version: str
    contract_version: str
    matrix_version: str
    suite_version: str
    fixture_digest: str
    conformance_result_digest: str
    performance_evidence: dict[str, Any]
    runtime_evidence: RuntimeEligibilityEvidence
    feature_enabled_by_default: bool
    passed: bool
    failures: tuple[str, ...]
    assembled_at: str
    evidence_digest: str

    def validation_report_evidence(self) -> dict[str, Any]:
        """Return a detached payload suitable for immutable report persistence."""

        return {
            "evidence_version": self.evidence_version,
            "contract_version": self.contract_version,
            "matrix_version": self.matrix_version,
            "suite_version": self.suite_version,
            "fixture_digest": self.fixture_digest,
            "conformance_result_digest": self.conformance_result_digest,
            "performance": self.performance_evidence,
            "runtime": asdict(self.runtime_evidence),
            "feature_enabled_by_default": self.feature_enabled_by_default,
            "internal_release_passed": self.passed,
            "failures": list(self.failures),
            "assembled_at": self.assembled_at,
            "evidence_digest": self.evidence_digest,
            # Existing workflow publication gates consume these exact keys.
            "text_session_conformance": self.runtime_evidence.text_session_conformance,
            "accepted_transition": self.runtime_evidence.accepted_transition,
            "cancellation_verified": self.runtime_evidence.cancellation_verified,
            "recording_verified": self.runtime_evidence.recording_verified,
        }


def assemble_internal_release_evidence(
    *,
    contract_version: str,
    matrix_version: str,
    conformance: ConformanceSuiteResult,
    performance: PerformanceReport,
    runtime: RuntimeEligibilityEvidence,
    feature_enabled_by_default: bool = False,
    assembled_at: datetime | None = None,
) -> InternalReleaseEvidence:
    """Fail closed unless every immutable internal-release input passes."""

    failures: list[str] = []
    if not conformance.passed:
        failures.append("required_conformance_failed")
    if not performance.passed:
        failures.append("performance_or_capacity_gate_failed")
    if not runtime.complete:
        failures.append("runtime_eligibility_evidence_incomplete")
    if feature_enabled_by_default:
        failures.append("experimental_feature_must_default_disabled")
    if not contract_version or not matrix_version:
        failures.append("version_metadata_missing")

    timestamp = (assembled_at or datetime.now(UTC)).isoformat()
    body = {
        "evidence_version": RELEASE_EVIDENCE_VERSION,
        "contract_version": contract_version,
        "matrix_version": matrix_version,
        "suite_version": conformance.suite_version,
        "fixture_digest": conformance.fixture_digest,
        "conformance_result_digest": conformance.result_digest,
        "performance_evidence_digest": performance.evidence_digest,
        "runtime_evidence": asdict(runtime),
        "feature_enabled_by_default": feature_enabled_by_default,
        "failures": failures,
        "assembled_at": timestamp,
    }
    return InternalReleaseEvidence(
        evidence_version=RELEASE_EVIDENCE_VERSION,
        contract_version=contract_version,
        matrix_version=matrix_version,
        suite_version=conformance.suite_version,
        fixture_digest=conformance.fixture_digest,
        conformance_result_digest=conformance.result_digest,
        performance_evidence=performance.report_evidence(),
        runtime_evidence=runtime,
        feature_enabled_by_default=feature_enabled_by_default,
        passed=not failures,
        failures=tuple(failures),
        assembled_at=timestamp,
        evidence_digest=deterministic_digest(body),
    )


def release_validation_results(
    evidence: InternalReleaseEvidence,
) -> list[dict[str, Any]]:
    """Build deterministic report children for conformance/runtime/release gates."""

    checks = {
        "internal_release.conformance": "required_conformance_failed" not in evidence.failures,
        "internal_release.performance": "performance_or_capacity_gate_failed" not in evidence.failures,
        "internal_release.runtime_evidence": "runtime_eligibility_evidence_incomplete" not in evidence.failures,
        "internal_release.feature_default": not evidence.feature_enabled_by_default,
        "internal_release.version_metadata": "version_metadata_missing" not in evidence.failures,
    }
    return [
        {
            "test_identifier": identifier,
            "test_version": evidence.evidence_version,
            "required": True,
            "outcome": "passed" if passed else "failed",
            "duration_ms": 0,
            "measurements": {
                "evidence_digest": evidence.evidence_digest,
                "suite_version": evidence.suite_version,
                "fixture_digest": evidence.fixture_digest,
            },
            "redacted_error": None if passed else {"code": identifier.rsplit(".", 1)[-1]},
        }
        for identifier, passed in checks.items()
    ]

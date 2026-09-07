"""Persistence-safe results for executable endpoint and platform evidence checks."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .runner import deterministic_digest

ELIGIBILITY_SUITE_VERSION = "eligibility-1.0.0"


@dataclass(frozen=True)
class EligibilityCheckResult:
    """One executable check with payload-free, persistence-ready evidence."""

    identifier: str
    passed: bool
    duration_ms: int
    measurements: dict[str, Any] = field(default_factory=dict)
    error_code: str | None = None

    def to_validation_result(self) -> dict[str, Any]:
        observation_digest = deterministic_digest(self.measurements)
        return {
            "test_identifier": self.identifier,
            "test_version": ELIGIBILITY_SUITE_VERSION,
            "required": True,
            "outcome": "passed" if self.passed else "failed",
            "duration_ms": self.duration_ms,
            "measurements": {
                **self.measurements,
                "observation_digest": observation_digest,
            },
            "redacted_error": (
                None if self.passed else {"code": self.error_code or "check_failed"}
            ),
        }

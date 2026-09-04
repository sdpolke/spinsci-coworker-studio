"""Deterministic Chat Compatibility conformance fixtures and runner."""

from .fixtures import (
    CHAT_BASELINE_FIXTURES,
    FIXTURE_VERSION,
    FIXTURES_BY_ID,
    SUITE_VERSION,
    ConformanceFixture,
    FixtureOracle,
)
from .runner import (
    ConformanceObservation,
    ConformanceResult,
    ConformanceSuiteResult,
    deterministic_digest,
    observe_script,
    run_fixture,
    run_suite,
    suite_digest,
)
from .simulator import ScriptedEndpointSimulator

__all__ = [
    "CHAT_BASELINE_FIXTURES",
    "FIXTURES_BY_ID",
    "FIXTURE_VERSION",
    "SUITE_VERSION",
    "ConformanceFixture",
    "ConformanceObservation",
    "ConformanceResult",
    "ConformanceSuiteResult",
    "FixtureOracle",
    "ScriptedEndpointSimulator",
    "deterministic_digest",
    "observe_script",
    "run_fixture",
    "run_suite",
    "suite_digest",
]

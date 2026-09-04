"""Deterministic endpoint simulator used by conformance and integration tests."""

from __future__ import annotations

from collections.abc import Iterator
from copy import deepcopy
from dataclasses import dataclass

from .fixtures import ConformanceFixture, JsonObject
from .runner import ConformanceObservation, observe_script


@dataclass(frozen=True)
class ScriptedEndpointSimulator:
    """Replay a versioned fixture without network access or wall-clock behavior."""

    fixture: ConformanceFixture

    @property
    def suite_contract_version(self) -> str:
        return self.fixture.contract_version

    def steps(self) -> Iterator[JsonObject]:
        """Yield isolated script values so a consumer cannot mutate the fixture."""

        for step in self.fixture.script:
            yield deepcopy(step)

    def observe(self) -> ConformanceObservation:
        """Run the script through the deterministic reference reducer."""

        return observe_script(self.fixture, self.steps())

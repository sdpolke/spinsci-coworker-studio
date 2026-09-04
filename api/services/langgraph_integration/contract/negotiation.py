from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from pydantic import ValidationError

from api.schemas.langgraph_integration import schema_for

from .models import MatrixVersion, SemanticVersion


class VersionIncompatibilityError(ValueError):
    """No exact contract version is shared by the endpoint and matrix."""

    def __init__(
        self,
        *,
        offered_versions: Iterable[str],
        supported_versions: Iterable[str],
    ) -> None:
        self.offered_versions = tuple(sorted(set(offered_versions), key=_version_key))
        self.supported_versions = tuple(
            sorted(set(supported_versions), key=_version_key)
        )
        self.offered_majors = tuple(
            sorted({SemanticVersion.parse(version).major for version in self.offered_versions})
        )
        self.supported_majors = tuple(
            sorted(
                {
                    SemanticVersion.parse(version).major
                    for version in self.supported_versions
                }
            )
        )
        super().__init__(
            "no mutually supported contract version; "
            f"offered versions={list(self.offered_versions)}, "
            f"supported versions={list(self.supported_versions)}, "
            f"offered majors={list(self.offered_majors)}, "
            f"supported majors={list(self.supported_majors)}"
        )

    @property
    def details(self) -> dict[str, list[str] | list[int]]:
        return {
            "offered_versions": list(self.offered_versions),
            "supported_versions": list(self.supported_versions),
            "offered_majors": list(self.offered_majors),
            "supported_majors": list(self.supported_majors),
        }


def _version_key(value: str) -> tuple[int, int]:
    version = SemanticVersion.parse(value)
    return version.major, version.minor


@dataclass(frozen=True)
class ManifestValidation:
    manifest: object | None
    violations: tuple[str, ...]


def validate_manifest(payload: object, schema_version: str) -> ManifestValidation:
    model = schema_for(schema_version, "manifest")
    try:
        return ManifestValidation(model.model_validate(payload), ())
    except ValidationError as exc:
        violations = tuple(
            f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
            for error in exc.errors()
        )
        return ManifestValidation(None, violations)


def validate_selected_capabilities(*, declared: Iterable[str], selected: Iterable[str]) -> tuple[str, ...]:
    declared_set = set(declared)
    return tuple(sorted(set(selected) - declared_set))


def negotiate_contract_version(endpoint_versions: Iterable[str], matrix: MatrixVersion) -> str:
    offered_versions = tuple(endpoint_versions)
    endpoint = {SemanticVersion.parse(version) for version in offered_versions}
    supported = {SemanticVersion.parse(version) for version in matrix.supported_contract_versions}
    common = endpoint & supported
    if not common:
        raise VersionIncompatibilityError(
            offered_versions=offered_versions,
            supported_versions=matrix.supported_contract_versions,
        )
    selected = max(common, key=lambda version: (version.major, version.minor))
    return str(selected)

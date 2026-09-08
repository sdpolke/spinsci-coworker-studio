"""Pure endpoint lifecycle, eligibility, and capability-change rules."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class EndpointLifecycle(StrEnum):
    PENDING_VALIDATION = "pending_validation"
    VALIDATION_ONLY = "validation_only"
    ACTIVE = "active"
    DEGRADED = "degraded"
    DISABLED = "disabled"
    INCOMPATIBLE = "incompatible"
    RETIRED = "retired"


_ALLOWED_TRANSITIONS: dict[EndpointLifecycle, frozenset[EndpointLifecycle]] = {
    EndpointLifecycle.PENDING_VALIDATION: frozenset(
        {
            EndpointLifecycle.VALIDATION_ONLY,
            EndpointLifecycle.ACTIVE,
            EndpointLifecycle.INCOMPATIBLE,
            EndpointLifecycle.RETIRED,
        }
    ),
    EndpointLifecycle.VALIDATION_ONLY: frozenset(
        {
            EndpointLifecycle.PENDING_VALIDATION,
            EndpointLifecycle.ACTIVE,
            EndpointLifecycle.DISABLED,
            EndpointLifecycle.INCOMPATIBLE,
            EndpointLifecycle.RETIRED,
        }
    ),
    EndpointLifecycle.ACTIVE: frozenset(
        {
            EndpointLifecycle.PENDING_VALIDATION,
            EndpointLifecycle.DEGRADED,
            EndpointLifecycle.DISABLED,
            EndpointLifecycle.INCOMPATIBLE,
            EndpointLifecycle.RETIRED,
        }
    ),
    EndpointLifecycle.DEGRADED: frozenset(
        {
            EndpointLifecycle.PENDING_VALIDATION,
            EndpointLifecycle.ACTIVE,
            EndpointLifecycle.DISABLED,
            EndpointLifecycle.INCOMPATIBLE,
            EndpointLifecycle.RETIRED,
        }
    ),
    EndpointLifecycle.DISABLED: frozenset(
        {EndpointLifecycle.PENDING_VALIDATION, EndpointLifecycle.RETIRED}
    ),
    EndpointLifecycle.INCOMPATIBLE: frozenset(
        {EndpointLifecycle.PENDING_VALIDATION, EndpointLifecycle.RETIRED}
    ),
    EndpointLifecycle.RETIRED: frozenset(),
}

NEW_RUN_ALLOWED_STATUSES = frozenset({EndpointLifecycle.ACTIVE})
PASSING_REPORT_STATUSES = frozenset({"passed", "live_voice_eligible"})


class InvalidLifecycleTransition(ValueError):
    pass


def can_transition(current: str, target: str) -> bool:
    try:
        current_status = EndpointLifecycle(current)
        target_status = EndpointLifecycle(target)
    except ValueError:
        return False
    return target_status in _ALLOWED_TRANSITIONS[current_status]


def require_transition(current: str, target: str) -> None:
    if not can_transition(current, target):
        raise InvalidLifecycleTransition(f"cannot transition endpoint from {current} to {target}")


def permits_new_runs(status: str) -> bool:
    try:
        return EndpointLifecycle(status) in NEW_RUN_ALLOWED_STATUSES
    except ValueError:
        return False


@dataclass(frozen=True)
class EligibilityDecision:
    classification: str
    live_voice_selectable: bool
    reasons: tuple[str, ...]


def evaluate_live_voice_eligibility(
    *,
    matrix_versions: Iterable[str],
    matrix_profiles: Iterable[str],
    manifest_versions: Iterable[str],
    manifest_profiles: Iterable[str],
    declared_modes: Iterable[str],
    selected_modes: Iterable[str],
    selected_profile: str,
    required_non_latency_results: Iterable[bool],
    latency_passed: bool,
    lifecycle_status: str,
) -> EligibilityDecision:
    """Classify support and live selection from all required evidence."""
    reasons: list[str] = []
    if not set(matrix_versions) & set(manifest_versions):
        reasons.append("unsupported_contract_version")
    if selected_profile not in set(matrix_profiles):
        reasons.append("unsupported_profile")
    if selected_profile not in set(manifest_profiles):
        reasons.append("undeclared_profile")
    if not all(required_non_latency_results):
        reasons.append("required_test_failed")

    if reasons:
        return EligibilityDecision("incompatible", False, tuple(reasons))

    selected = set(selected_modes)
    if not selected <= set(declared_modes):
        reasons.append("undeclared_invocation_mode")
    if "streaming" not in selected:
        reasons.append("streaming_required")
    if not latency_passed:
        reasons.append("latency_gate_failed")
    if reasons:
        return EligibilityDecision("validation_only", False, tuple(reasons))

    selectable = permits_new_runs(lifecycle_status)
    if not selectable:
        reasons.append("lifecycle_blocks_new_runs")
    return EligibilityDecision("supported", selectable, tuple(reasons))


def normalized_capability_payload(manifest: Mapping[str, Any]) -> dict[str, Any]:
    """Return only semantic capabilities with unordered declarations normalized.

    ``operations`` and ``data_regions`` are part of the semantic surface: the
    presence of an operation (for example ``topology``) is what makes the
    corresponding behavior available, and the advertised regions constrain where
    a binding may run. Omitting either from the digest would make a re-discovered
    manifest compare equal to a stale snapshot, so the stale snapshot would be
    reused and the new operation could never be adopted.
    """
    return {
        "contract_versions": sorted(set(manifest.get("contract_versions", ()))),
        "compatibility_profiles": sorted(
            set(manifest.get("compatibility_profiles", ()))
        ),
        "invocation_modes": sorted(set(manifest.get("invocation_modes", ()))),
        "state_modes": sorted(set(manifest.get("state_modes", ()))),
        "data_regions": sorted(set(manifest.get("data_regions", ()))),
        "features": manifest.get("features", {}),
        "limits": manifest.get("limits", {}),
        "operations": manifest.get("operations", {}),
    }


def capability_digest(manifest: Mapping[str, Any]) -> str:
    canonical = json.dumps(
        normalized_capability_payload(manifest),
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(canonical).hexdigest()


def capabilities_changed(
    previous: Mapping[str, Any], discovered: Mapping[str, Any]
) -> bool:
    return capability_digest(previous) != capability_digest(discovered)

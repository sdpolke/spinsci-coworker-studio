"""Tenant-safe validation for authenticated asynchronous endpoint callbacks."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class CallbackScope:
    organization_id: int
    registration_id: str
    voice_run_id: str
    external_run_id: str


def validate_callback_scope(
    *,
    authenticated_scope: CallbackScope,
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    """Authorize callback correlation from server-owned registration scope.

    Tenant identity is never accepted from endpoint-controlled payload data.
    The returned copy intentionally omits any organization assertion.
    """

    expected = {
        "registration_id": authenticated_scope.registration_id,
        "voice_run_id": authenticated_scope.voice_run_id,
        "external_run_id": authenticated_scope.external_run_id,
    }
    if "organization_id" in payload:
        try:
            supplied_organization_id = int(payload["organization_id"])
        except (TypeError, ValueError) as exc:
            raise PermissionError("callback organization scope mismatch") from exc
        if supplied_organization_id != authenticated_scope.organization_id:
            raise PermissionError("callback organization scope mismatch")
    for field, value in expected.items():
        if str(payload.get(field, "")) != value:
            raise PermissionError(f"callback {field} scope mismatch")
    return {key: value for key, value in payload.items() if key != "organization_id"}

from __future__ import annotations

from typing import Any

from api.schemas.langgraph_integration import schema_for


def serialize_pinned_request(*, pinned_version: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Validate and serialize with the immutable workflow-pinned wire version."""
    wire_payload = {**payload, "contract_version": pinned_version}
    model = schema_for(pinned_version, "invocation").model_validate(wire_payload)
    return model.model_dump(mode="json", exclude_none=True)

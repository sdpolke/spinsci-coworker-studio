from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Iterable, Mapping

from api.schemas.langgraph_integration.common import ToolOwner


class UnsupportedReason(StrEnum):
    DIRECT_AUDIO = "direct_audio_required"
    IN_PROCESS_OBJECT = "in_process_object_required"
    EXECUTABLE_PACKAGE = "executable_package_required"
    UNDOCUMENTED_PAYLOAD = "undocumented_payload_required"


@dataclass(frozen=True)
class AgentRequirements:
    direct_audio: bool = False
    in_process_object: bool = False
    executable_package: bool = False
    undocumented_payload: bool = False


@dataclass(frozen=True)
class Classification:
    supported: bool
    reasons: tuple[UnsupportedReason, ...]


def classify_agent_requirements(requirements: AgentRequirements) -> Classification:
    checks = (
        (requirements.direct_audio, UnsupportedReason.DIRECT_AUDIO),
        (requirements.in_process_object, UnsupportedReason.IN_PROCESS_OBJECT),
        (requirements.executable_package, UnsupportedReason.EXECUTABLE_PACKAGE),
        (requirements.undocumented_payload, UnsupportedReason.UNDOCUMENTED_PAYLOAD),
    )
    reasons = tuple(reason for applies, reason in checks if applies)
    return Classification(supported=not reasons, reasons=reasons)


class UntrustedOutputKind(StrEnum):
    TEXT = "text"
    TOOL_CALL = "tool_call"
    TOOL_ARGUMENTS = "tool_arguments"
    CHECKPOINT_REFERENCE = "checkpoint_reference"
    CALLBACK = "callback"
    ERROR_DETAIL = "error_detail"


def is_untrusted_endpoint_output(kind: UntrustedOutputKind | str) -> bool:
    try:
        UntrustedOutputKind(kind)
    except ValueError:
        return True
    return True


@dataclass(frozen=True)
class PayloadBounds:
    request_bytes: int
    response_bytes: int
    event_bytes: int
    tool_argument_bytes: int
    callback_bytes: int

    def limit_for(self, payload_type: str) -> int:
        try:
            limit = getattr(self, f"{payload_type}_bytes")
        except AttributeError as exc:
            raise ValueError(f"unknown payload type: {payload_type}") from exc
        if limit <= 0:
            raise ValueError("payload limits must be positive")
        return limit


def encoded_payload_size(payload: bytes | str | Mapping[str, Any] | list[Any]) -> int:
    if isinstance(payload, bytes):
        return len(payload)
    if isinstance(payload, str):
        return len(payload.encode("utf-8"))
    return len(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8"))


def payload_within_bound(payload: Any, *, payload_type: str, bounds: PayloadBounds) -> bool:
    return encoded_payload_size(payload) <= bounds.limit_for(payload_type)


_SECRET_PATTERNS = (
    re.compile(r"(?i)\b(?:api[_-]?key|secret|password|authorization)\b\s*[:=]\s*[^\s,;]+"),
    re.compile(r"\b(?:sk|pk)_[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/-]{12,}=*", re.IGNORECASE),
)


def contains_continuation_secret(value: Any) -> bool:
    serialized = value if isinstance(value, str) else json.dumps(value, sort_keys=True, default=str)
    return any(pattern.search(serialized) is not None for pattern in _SECRET_PATTERNS)


@dataclass(frozen=True)
class OwnershipDeclaration:
    field: str
    owner: str


_MURAL_OWNED = frozenset({
    "voice_run_id", "workflow_version", "active_node", "node_prompt", "conversation_history",
    "tool_definitions", "tool_results", "telephony", "recording", "credentials", "organization_scope", "contract_controls",
})
_ENDPOINT_OWNED = frozenset({"internal_graph_state", "endpoint_internal_tools", "checkpoint_contents"})


def classify_ownership(fields: Iterable[str]) -> tuple[OwnershipDeclaration, ...]:
    declarations: list[OwnershipDeclaration] = []
    for field in fields:
        if field in _MURAL_OWNED:
            owner = "mural"
        elif field in _ENDPOINT_OWNED:
            owner = "endpoint"
        else:
            owner = "undeclared"
        declarations.append(OwnershipDeclaration(field=field, owner=owner))
    return tuple(declarations)


def endpoint_text_has_control_authority(_text: str) -> bool:
    """Endpoint text is model output and never changes Mural-pinned controls."""
    return False


def tool_owner_is_mural_authorized(owner: ToolOwner) -> bool:
    return owner in {ToolOwner.MURAL_PLATFORM, ToolOwner.MURAL_TRANSITION}

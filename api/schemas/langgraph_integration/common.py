from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field

MAX_IDENTIFIER_LENGTH = 255
MAX_URL_LENGTH = 2048
MAX_REQUEST_BYTES = 1_048_576
MAX_RESPONSE_BYTES = 2_097_152
MAX_EVENT_BYTES = 65_536
MAX_TOOL_ARGUMENT_BYTES = 262_144

Identifier = Annotated[str, Field(min_length=1, max_length=MAX_IDENTIFIER_LENGTH)]
ContractVersion = Annotated[str, Field(pattern=r"^\d+\.\d+$", max_length=32)]
JsonObject = dict[str, Any]


class StrictContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class ExtensibleContractModel(BaseModel):
    model_config = ConfigDict(extra="allow", frozen=True, str_strip_whitespace=True)


class CompatibilityProfile(StrEnum):
    CHAT = "chat"
    STATEFUL_RUN = "stateful_run"


class InvocationMode(StrEnum):
    SYNCHRONOUS = "synchronous"
    STREAMING = "streaming"
    ASYNCHRONOUS = "asynchronous"


class StateMode(StrEnum):
    MURAL_AUTHORITATIVE = "mural_authoritative"
    ENDPOINT_CHECKPOINTED = "endpoint_checkpointed"


class ToolOwner(StrEnum):
    MURAL_TRANSITION = "mural_transition"
    MURAL_PLATFORM = "mural_platform"
    ENDPOINT_INTERNAL = "endpoint_internal"


class ErrorCategory(StrEnum):
    AUTHENTICATION = "authentication"
    AUTHORIZATION = "authorization"
    INVALID_REQUEST = "invalid_request"
    INVALID_RESPONSE = "invalid_response"
    UNSUPPORTED_VERSION = "unsupported_version"
    RATE_LIMITED = "rate_limited"
    OVERLOADED = "overloaded"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"
    STATE_CONFLICT = "state_conflict"
    SECURITY_VIOLATION = "security_violation"
    INTERNAL = "internal"

from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import ConfigDict, Field, RootModel

from . import v1_0
from .common import Identifier, JsonObject

V1_1 = "1.1"


class CapabilityManifest(v1_0.CapabilityManifest):
    schema_version: Literal["1.1"] = "1.1"
    metadata: JsonObject | None = None


class InvocationRequest(v1_0.InvocationRequest):
    contract_version: Literal["1.1"] = "1.1"
    locale: str | None = Field(default=None, min_length=2, max_length=35)


class SynchronousResponse(v1_0.SynchronousResponse):
    contract_version: Literal["1.1"] = "1.1"
    response_id: Identifier | None = None


class AsynchronousAcceptance(v1_0.AsynchronousAcceptance):
    contract_version: Literal["1.1"] = "1.1"
    poll_after_ms: int | None = Field(default=None, ge=50, le=60_000)


class StatusResponse(v1_0.StatusResponse):
    contract_version: Literal["1.1"] = "1.1"


class RuntimeEventBase(v1_0.RuntimeEventBase):
    contract_version: Literal["1.1"] = "1.1"
    timestamp_ms: int | None = Field(default=None, ge=0)


class TextDeltaEvent(RuntimeEventBase):
    type: Literal["text_delta"] = "text_delta"
    data: v1_0.TextDeltaData


class ToolCallStartEvent(RuntimeEventBase):
    type: Literal["tool_call_start"] = "tool_call_start"
    data: v1_0.ToolCallStartData


class ToolCallDeltaEvent(RuntimeEventBase):
    type: Literal["tool_call_delta"] = "tool_call_delta"
    data: v1_0.ToolCallDeltaData


class ToolCallEndEvent(RuntimeEventBase):
    type: Literal["tool_call_end"] = "tool_call_end"
    data: v1_0.ToolCallEndData


class UsageEvent(RuntimeEventBase):
    type: Literal["usage"] = "usage"
    data: v1_0.UsageData


class StatusEvent(RuntimeEventBase):
    type: Literal["status"] = "status"
    data: v1_0.StatusData


class CheckpointEvent(RuntimeEventBase):
    type: Literal["checkpoint"] = "checkpoint"
    data: v1_0.CheckpointData


class InterruptEvent(RuntimeEventBase):
    type: Literal["interrupt"] = "interrupt"
    data: v1_0.InterruptData


class CompletedEvent(RuntimeEventBase):
    type: Literal["completed"] = "completed"
    data: v1_0.CompletedData = Field(default_factory=v1_0.CompletedData)


class ErrorEvent(RuntimeEventBase):
    type: Literal["error"] = "error"
    data: v1_0.ContractError


RuntimeEvent = Annotated[
    Union[TextDeltaEvent, ToolCallStartEvent, ToolCallDeltaEvent, ToolCallEndEvent, UsageEvent, StatusEvent, CheckpointEvent, InterruptEvent, CompletedEvent, ErrorEvent],
    Field(discriminator="type"),
]


class RuntimeEventEnvelope(RootModel[RuntimeEvent]):
    model_config = ConfigDict(frozen=True)


class CancellationRequest(v1_0.CancellationRequest):
    contract_version: Literal["1.1"] = "1.1"
    detail: str | None = Field(default=None, max_length=512)


class CancellationResponse(v1_0.CancellationResponse):
    contract_version: Literal["1.1"] = "1.1"


class ResumeRequest(v1_0.ResumeRequest):
    contract_version: Literal["1.1"] = "1.1"
    metadata: JsonObject | None = None


class HealthResponse(v1_0.HealthResponse):
    contract_version: Literal["1.1"] = "1.1"
    checks: dict[str, Literal["healthy", "degraded", "unhealthy"]] | None = None

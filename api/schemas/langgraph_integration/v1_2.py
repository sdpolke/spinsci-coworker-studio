from __future__ import annotations

from typing import Annotated, Literal

from pydantic import ConfigDict, Field, RootModel

from . import v1_0, v1_1
from .common import Identifier, StrictContractModel

V1_2 = "1.2"


class CapabilityManifest(v1_1.CapabilityManifest):
    schema_version: Literal["1.2"] = "1.2"


class InvocationContinuation(StrictContractModel):
    """Opaque endpoint-issued state required to continue a Stateful Run."""

    thread_id: Identifier
    checkpoint_reference: Identifier
    external_run_id: Identifier | None = None


class InvocationRequest(v1_1.InvocationRequest):
    contract_version: Literal["1.2"] = "1.2"
    state: InvocationContinuation | None = None


class SynchronousResponse(v1_1.SynchronousResponse):
    contract_version: Literal["1.2"] = "1.2"


class AsynchronousAcceptance(v1_1.AsynchronousAcceptance):
    contract_version: Literal["1.2"] = "1.2"


class StatusResponse(v1_1.StatusResponse):
    contract_version: Literal["1.2"] = "1.2"


class RuntimeEventBase(v1_1.RuntimeEventBase):
    contract_version: Literal["1.2"] = "1.2"


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
    TextDeltaEvent
    | ToolCallStartEvent
    | ToolCallDeltaEvent
    | ToolCallEndEvent
    | UsageEvent
    | StatusEvent
    | CheckpointEvent
    | InterruptEvent
    | CompletedEvent
    | ErrorEvent,
    Field(discriminator="type"),
]


class RuntimeEventEnvelope(RootModel[RuntimeEvent]):
    model_config = ConfigDict(frozen=True)


class CancellationRequest(v1_1.CancellationRequest):
    contract_version: Literal["1.2"] = "1.2"


class CancellationResponse(v1_1.CancellationResponse):
    contract_version: Literal["1.2"] = "1.2"


class ResumeRequest(v1_1.ResumeRequest):
    contract_version: Literal["1.2"] = "1.2"


class HealthResponse(v1_1.HealthResponse):
    contract_version: Literal["1.2"] = "1.2"

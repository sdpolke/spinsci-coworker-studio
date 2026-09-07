from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal, Union

from pydantic import ConfigDict, Field, RootModel, model_validator

from .common import (
    ContractVersion,
    ErrorCategory,
    ExtensibleContractModel,
    Identifier,
    InvocationMode,
    JsonObject,
    MAX_EVENT_BYTES,
    MAX_REQUEST_BYTES,
    MAX_RESPONSE_BYTES,
    MAX_TOOL_ARGUMENT_BYTES,
    StateMode,
    StrictContractModel,
    ToolOwner,
)

V1_0 = "1.0"


class OperationalLimits(StrictContractModel):
    request_bytes: int = Field(default=MAX_REQUEST_BYTES, gt=0, le=MAX_REQUEST_BYTES)
    response_bytes: int = Field(default=MAX_RESPONSE_BYTES, gt=0, le=MAX_RESPONSE_BYTES)
    event_bytes: int = Field(default=MAX_EVENT_BYTES, gt=0, le=MAX_EVENT_BYTES)
    tool_argument_bytes: int = Field(default=MAX_TOOL_ARGUMENT_BYTES, gt=0, le=MAX_TOOL_ARGUMENT_BYTES)


class DiscoveryOperations(StrictContractModel):
    invoke: str = Field(min_length=1, max_length=512, pattern=r"^/")
    status: str | None = Field(default=None, max_length=512, pattern=r"^/")
    cancel: str | None = Field(default=None, max_length=512, pattern=r"^/")
    resume: str | None = Field(default=None, max_length=512, pattern=r"^/")
    health: str = Field(min_length=1, max_length=512, pattern=r"^/")


class EndpointFeatures(StrictContractModel):
    interrupts: bool = False
    idempotent_invocations: bool = False
    distributed_tracing: bool = False


class CapabilityManifest(ExtensibleContractModel):
    schema_version: Literal["1.0"] = "1.0"
    endpoint_id: Identifier
    display_name: str = Field(min_length=1, max_length=255)
    data_regions: list[Identifier] = Field(min_length=1, max_length=32)
    contract_versions: list[ContractVersion] = Field(min_length=1, max_length=16)
    compatibility_profiles: list[Literal["chat", "stateful_run"]] = Field(min_length=1)
    invocation_modes: list[InvocationMode] = Field(min_length=1)
    state_modes: list[StateMode] = Field(min_length=1)
    operations: DiscoveryOperations
    features: EndpointFeatures = Field(default_factory=EndpointFeatures)
    limits: OperationalLimits = Field(default_factory=OperationalLimits)

    @model_validator(mode="after")
    def declared_operations_support_capabilities(self) -> "CapabilityManifest":
        if InvocationMode.ASYNCHRONOUS in self.invocation_modes and not self.operations.status:
            raise ValueError("asynchronous mode requires a status operation")
        if self.features.interrupts and not self.operations.resume:
            raise ValueError("interrupts require a resume operation")
        return self


class TextContent(StrictContractModel):
    type: Literal["text"] = "text"
    text: str = Field(min_length=1, max_length=MAX_REQUEST_BYTES)


class Message(StrictContractModel):
    role: Literal["system", "user", "assistant", "tool_call", "tool_result"]
    content: list[TextContent] = Field(min_length=1)
    tool_call_id: Identifier | None = None


class ToolDefinition(StrictContractModel):
    name: Identifier
    description: str = Field(max_length=4096)
    input_schema: JsonObject
    owner: ToolOwner
    authorization: Identifier


class Deadlines(StrictContractModel):
    first_event_ms: int = Field(ge=500, le=3000)
    turn_ms: int = Field(gt=0, le=300_000)


class InvocationRequest(StrictContractModel):
    contract_version: Literal["1.0"] = "1.0"
    operation: Literal["invoke"] = "invoke"
    invocation_id: Identifier
    attempt_id: Identifier
    voice_run_id: Identifier
    workflow_version_id: Identifier
    mode: InvocationMode
    state_mode: StateMode
    messages: list[Message] = Field(min_length=1, max_length=10_000)
    tools: list[ToolDefinition] = Field(default_factory=list, max_length=256)
    context: JsonObject = Field(default_factory=dict)
    deadlines: Deadlines
    trace: dict[str, str] = Field(default_factory=dict)


class ContractError(StrictContractModel):
    category: ErrorCategory
    code: Identifier
    retryable: bool = False
    message: str | None = Field(default=None, max_length=4096)


class AssistantResult(StrictContractModel):
    type: Literal["assistant"] = "assistant"
    message: Message
    status: Literal["completed"] = "completed"


class ErrorResult(StrictContractModel):
    type: Literal["error"] = "error"
    error: ContractError
    status: Literal["failed", "cancelled"]


SyncResult = Annotated[Union[AssistantResult, ErrorResult], Field(discriminator="type")]


class SynchronousResponse(StrictContractModel):
    contract_version: Literal["1.0"] = "1.0"
    invocation_id: Identifier
    result: SyncResult


class AsynchronousAcceptance(StrictContractModel):
    contract_version: Literal["1.0"] = "1.0"
    invocation_id: Identifier
    status: Literal["accepted"] = "accepted"
    external_run_id: Identifier


class StatusResponse(StrictContractModel):
    contract_version: Literal["1.0"] = "1.0"
    operation: Literal["status"] = "status"
    invocation_id: Identifier
    external_run_id: Identifier
    status: Literal["running", "completed", "failed", "cancelled"]
    result: SyncResult | None = None

    @model_validator(mode="after")
    def terminal_status_has_result(self) -> "StatusResponse":
        terminal = self.status in {"completed", "failed", "cancelled"}
        if terminal != (self.result is not None):
            raise ValueError("terminal status must contain exactly one result")
        return self


class RuntimeEventBase(StrictContractModel):
    contract_version: Literal["1.0"] = "1.0"
    invocation_id: Identifier
    sequence: int = Field(ge=0)
    event_id: Identifier


class TextDeltaData(StrictContractModel):
    # Stream deltas carry authoritative boundary whitespace. Trimming each
    # independently validated chunk corrupts words when consumers concatenate.
    model_config = ConfigDict(str_strip_whitespace=False)

    text: str = Field(min_length=1, max_length=MAX_EVENT_BYTES)


class TextDeltaEvent(RuntimeEventBase):
    type: Literal["text_delta"] = "text_delta"
    data: TextDeltaData


class ToolCallStartData(StrictContractModel):
    tool_call_id: Identifier
    name: Identifier


class ToolCallStartEvent(RuntimeEventBase):
    type: Literal["tool_call_start"] = "tool_call_start"
    data: ToolCallStartData


class ToolCallDeltaData(StrictContractModel):
    # Tool argument fragments are opaque stream content and must remain byte-for-byte
    # equivalent after validation so JSON string whitespace is not changed.
    model_config = ConfigDict(str_strip_whitespace=False)

    tool_call_id: Identifier
    fragment: str = Field(min_length=1, max_length=MAX_TOOL_ARGUMENT_BYTES)


class ToolCallDeltaEvent(RuntimeEventBase):
    type: Literal["tool_call_delta"] = "tool_call_delta"
    data: ToolCallDeltaData


class ToolCallEndData(StrictContractModel):
    tool_call_id: Identifier


class ToolCallEndEvent(RuntimeEventBase):
    type: Literal["tool_call_end"] = "tool_call_end"
    data: ToolCallEndData


class UsageData(StrictContractModel):
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)


class UsageEvent(RuntimeEventBase):
    type: Literal["usage"] = "usage"
    data: UsageData


class StatusData(StrictContractModel):
    status: Literal["queued", "running", "waiting_for_tool"]


class StatusEvent(RuntimeEventBase):
    type: Literal["status"] = "status"
    data: StatusData


class CheckpointData(StrictContractModel):
    thread_id: Identifier
    external_run_id: Identifier | None = None
    checkpoint_reference: Identifier


class CheckpointEvent(RuntimeEventBase):
    type: Literal["checkpoint"] = "checkpoint"
    data: CheckpointData


class InterruptData(StrictContractModel):
    interrupt_type: Identifier
    reason: str = Field(min_length=1, max_length=4096)
    allowed_decisions: list[Identifier] = Field(min_length=1, max_length=32)
    expires_at: datetime
    checkpoint_reference: Identifier


class InterruptEvent(RuntimeEventBase):
    type: Literal["interrupt"] = "interrupt"
    data: InterruptData


class CompletedData(StrictContractModel):
    status: Literal["completed"] = "completed"


class CompletedEvent(RuntimeEventBase):
    type: Literal["completed"] = "completed"
    data: CompletedData = Field(default_factory=CompletedData)


class ErrorEvent(RuntimeEventBase):
    type: Literal["error"] = "error"
    data: ContractError


RuntimeEvent = Annotated[
    Union[TextDeltaEvent, ToolCallStartEvent, ToolCallDeltaEvent, ToolCallEndEvent, UsageEvent, StatusEvent, CheckpointEvent, InterruptEvent, CompletedEvent, ErrorEvent],
    Field(discriminator="type"),
]


class RuntimeEventEnvelope(RootModel[RuntimeEvent]):
    model_config = ConfigDict(frozen=True)


class CancellationRequest(StrictContractModel):
    contract_version: Literal["1.0"] = "1.0"
    operation: Literal["cancel"] = "cancel"
    invocation_id: Identifier
    reason: Literal["caller_barge_in", "hangup", "node_change", "operator_action", "platform_shutdown", "deadline"]


class CancellationResponse(StrictContractModel):
    contract_version: Literal["1.0"] = "1.0"
    invocation_id: Identifier
    status: Literal["cancelled", "already_terminal"]


class ResumeState(StrictContractModel):
    thread_id: Identifier
    checkpoint_reference: Identifier


class ResumeDecision(StrictContractModel):
    type: Identifier
    value: JsonObject | str | int | float | bool | None = None


class ResumeRequest(StrictContractModel):
    contract_version: Literal["1.0"] = "1.0"
    operation: Literal["resume"] = "resume"
    invocation_id: Identifier
    prior_invocation_id: Identifier
    voice_run_id: Identifier
    state: ResumeState
    decision: ResumeDecision


class HealthResponse(StrictContractModel):
    contract_version: Literal["1.0"] = "1.0"
    operation: Literal["health"] = "health"
    status: Literal["healthy", "degraded", "unhealthy"]
    endpoint_id: Identifier
    observed_at: datetime

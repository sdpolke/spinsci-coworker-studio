"""Provider-neutral reasoning contracts shared by local and remote workflow paths."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

JsonObject = dict[str, Any]
ToolHandler = Callable[[JsonObject], Awaitable[JsonObject]]


@dataclass(frozen=True)
class ReasoningMessage:
    """One accepted wire-visible message in canonical acceptance order."""

    role: str
    content: Any
    tool_call_id: str | None = None
    name: str | None = None

    def to_wire(self) -> JsonObject:
        value: JsonObject = {"role": self.role, "content": self.content}
        if self.tool_call_id is not None:
            value["tool_call_id"] = self.tool_call_id
        if self.name is not None:
            value["name"] = self.name
        return value


@dataclass(frozen=True)
class ReasoningToolDefinition:
    name: str
    description: str
    input_schema: JsonObject
    owner: str
    authorization: str = "current_node"
    node_id: str = ""
    workflow_version_id: str = ""
    organization_id: int = 0
    voice_run_id: str = ""
    registration_id: str = ""
    enabled: bool = True
    high_impact: bool = False
    argument_size_limit: int = 262_144
    resource_organization_id: int | None = None
    transition_target: str | None = None
    handler: ToolHandler | None = field(default=None, compare=False, repr=False)

    def to_wire(self) -> JsonObject:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
            "owner": self.owner,
            "authorization": self.authorization,
        }


@dataclass(frozen=True)
class ReasoningRequest:
    contract_version: str
    invocation_id: str
    voice_run_id: str
    workflow_version_id: str
    mode: str
    state_mode: str
    messages: tuple[ReasoningMessage, ...]
    tools: tuple[ReasoningToolDefinition, ...]
    context: Mapping[str, Any] = field(default_factory=dict)
    state: Mapping[str, str] = field(default_factory=dict)

    def to_wire(self) -> JsonObject:
        payload: JsonObject = {
            "contract_version": self.contract_version,
            "operation": "invoke",
            "invocation_id": self.invocation_id,
            "voice_run_id": self.voice_run_id,
            "workflow_version_id": self.workflow_version_id,
            "mode": self.mode,
            "state_mode": self.state_mode,
            "messages": [message.to_wire() for message in self.messages],
            "tools": [tool.to_wire() for tool in self.tools],
        }
        if self.context:
            payload["context"] = dict(self.context)
        if self.state:
            payload["state"] = dict(self.state)
        return payload


class ReasoningProvider(Protocol):
    async def invoke(self, request: ReasoningRequest) -> Any: ...

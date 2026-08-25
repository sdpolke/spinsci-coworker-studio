"""Data models for workflow generation sessions."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field


class GenerationSessionStatus(str, Enum):
    CLARIFYING = "clarifying"
    READY = "ready"
    GENERATING = "generating"
    COMPLETED = "completed"
    FAILED = "failed"


class GenerationMessageRole(str, Enum):
    ASSISTANT = "assistant"
    USER = "user"


class GenerationMessage(BaseModel):
    role: GenerationMessageRole
    content: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class GenerationBrief(BaseModel):
    call_type: Literal["inbound", "outbound"]
    use_case: str
    activity_description: str


class GenerationSession(BaseModel):
    session_id: str = Field(default_factory=lambda: str(uuid4()))
    user_id: int
    organization_id: int | None
    provider_id: str
    status: GenerationSessionStatus = GenerationSessionStatus.CLARIFYING
    brief: GenerationBrief
    messages: list[GenerationMessage] = Field(default_factory=list)
    summary: str | None = None
    plan: str | None = None
    workflow_id: int | None = None
    error: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    def touch(self) -> None:
        self.updated_at = datetime.now(UTC)


class PlannerResponse(BaseModel):
    status: Literal["clarifying", "ready"]
    question: str | None = None
    summary: str | None = None
    plan: str | None = None


class CompilerResponse(BaseModel):
    typescript: str


class CatalogSnapshot(BaseModel):
    node_types: list[dict[str, Any]]
    tools: list[dict[str, Any]]
    documents: list[dict[str, Any]]
    credentials: list[dict[str, Any]]

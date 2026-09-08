from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from api.constants import (
    MAX_TEXT_CHAT_INACTIVITY_TIMEOUT_SECONDS,
    MIN_TEXT_CHAT_INACTIVITY_TIMEOUT_SECONDS,
    TEXT_CHAT_INACTIVITY_TIMEOUT_SECONDS,
)

DEFAULT_MAX_CALL_DURATION_SECONDS = 300
# Hard ceiling on configurable call duration. Must stay <= the concurrency
# rate limiter's stale_call_timeout (20 min): a call running past that has
# its slot purged as stale and the org concurrency limit under-counts.
MAX_CALL_DURATION_SECONDS = 1200
DEFAULT_MAX_USER_IDLE_TIMEOUT_SECONDS = 10.0
DEFAULT_SMART_TURN_STOP_SECS = 2.0
DEFAULT_TURN_START_STRATEGY = "default"
DEFAULT_TURN_START_MIN_WORDS = 3
DEFAULT_PROVISIONAL_VAD_PAUSE_SECS = 1.5
DEFAULT_TURN_STOP_STRATEGY = "transcription"
DEFAULT_CONTEXT_COMPACTION_ENABLED = False


class ExternalPBXFieldMapping(BaseModel):
    """Map one gathered-context value to a provider-native field."""

    context_path: str = Field(min_length=1, max_length=255)
    destination_field: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_]{0,63}$")

    @field_validator("context_path", mode="before")
    @classmethod
    def strip_context_path(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("destination_field", mode="before")
    @classmethod
    def strip_destination_field(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class AmbientNoiseConfigurationDefaults(BaseModel):
    model_config = ConfigDict(extra="allow")

    enabled: bool = False
    volume: float = 0.3


class LangGraphEligibilityEvidence(BaseModel):
    """Immutable evidence required before a workflow can serve live voice."""

    model_config = ConfigDict(extra="forbid")

    text_session_conformance: bool = False
    accepted_transition: bool = False
    endpoint_state_continuity: bool = False
    cancellation_verified: bool = False
    recording_verified: bool = False

    @property
    def complete(self) -> bool:
        """Return Chat-profile completeness for backward compatibility."""
        return self.complete_for("chat")

    def complete_for(self, profile: Literal["chat", "stateful_run"]) -> bool:
        orchestration_verified = (
            self.accepted_transition
            if profile == "chat"
            else self.endpoint_state_continuity
        )
        return all(
            (
                self.text_session_conformance,
                orchestration_verified,
                self.cancellation_verified,
                self.recording_verified,
            )
        )


class LangGraphTopologySnapshot(BaseModel):
    """Immutable external topology retained with one workflow-version binding."""

    model_config = ConfigDict(extra="forbid")

    endpoint_binding_revision: str = Field(min_length=1, max_length=64)
    digest: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")
    topology: dict[str, Any]


class LangGraphEndpointBinding(BaseModel):
    """Complete workflow-version-pinned endpoint behavior snapshot."""

    model_config = ConfigDict(extra="forbid")

    registration_uuid: str = Field(min_length=1, max_length=64)
    validation_report_uuid: str = Field(min_length=1, max_length=64)
    validation_report_digest: str = Field(min_length=1, max_length=128)
    contract_version: str = Field(min_length=1, max_length=16)
    compatibility_profile: Literal["chat", "stateful_run"]
    state_mode: Literal["mural_authoritative", "endpoint_checkpointed"]
    live_invocation_mode: Literal["streaming"]
    non_conversational_modes: dict[str, Literal["synchronous", "asynchronous"]] = (
        Field(default_factory=dict)
    )
    selected_capabilities: list[str] = Field(default_factory=list)
    capability_snapshot_uuid: str = Field(min_length=1, max_length=64)
    capability_snapshot_digest: str = Field(min_length=1, max_length=128)
    capability_snapshot: dict[str, Any]
    data_sharing_policy: dict[str, Any] = Field(default_factory=dict)
    redaction_policy_id: str | None = Field(default=None, max_length=255)
    compiled_policy_versions: dict[str, str] = Field(default_factory=dict)
    data_region: str = Field(min_length=1, max_length=128)
    first_event_deadline_ms: int = Field(ge=500, le=3000)
    first_event_action: Literal["fallback_message", "transfer", "end_call"]
    terminal_failure_action: Literal[
        "retry_prompt", "fallback_message", "transfer", "end_call"
    ]
    evidence: LangGraphEligibilityEvidence
    endpoint_url: str = Field(min_length=1, max_length=2048)
    credential_reference: str = Field(min_length=1, max_length=64)
    operations: dict[str, str]
    limits: dict[str, int]
    ownership: dict[str, str] = Field(default_factory=dict)
    topology_snapshot: LangGraphTopologySnapshot | None = None


class WorkflowConfigurationDefaults(BaseModel):
    model_config = ConfigDict(extra="allow")

    @model_validator(mode="before")
    @classmethod
    def _treat_null_as_unset(cls, data):
        # Stored configs (and older clients) carry explicit JSON nulls for
        # keys the user never configured; dropping them lets the field
        # defaults apply instead of failing validation.
        if isinstance(data, dict):
            return {k: v for k, v in data.items() if v is not None}
        return data

    ambient_noise_configuration: AmbientNoiseConfigurationDefaults = Field(
        default_factory=AmbientNoiseConfigurationDefaults
    )
    max_call_duration: int = Field(
        default=DEFAULT_MAX_CALL_DURATION_SECONDS,
        gt=0,
        le=MAX_CALL_DURATION_SECONDS,
    )
    max_user_idle_timeout: float = DEFAULT_MAX_USER_IDLE_TIMEOUT_SECONDS
    smart_turn_stop_secs: float = DEFAULT_SMART_TURN_STOP_SECS
    turn_start_strategy: Literal["default", "min_words", "provisional_vad"] = (
        DEFAULT_TURN_START_STRATEGY
    )
    turn_start_min_words: int = DEFAULT_TURN_START_MIN_WORDS
    provisional_vad_pause_secs: float = DEFAULT_PROVISIONAL_VAD_PAUSE_SECS
    turn_stop_strategy: Literal["transcription", "turn_analyzer"] = (
        DEFAULT_TURN_STOP_STRATEGY
    )
    dictionary: str = ""
    context_compaction_enabled: bool = DEFAULT_CONTEXT_COMPACTION_ENABLED
    text_chat_inactivity_timeout_seconds: int = Field(
        default=TEXT_CHAT_INACTIVITY_TIMEOUT_SECONDS,
        ge=MIN_TEXT_CHAT_INACTIVITY_TIMEOUT_SECONDS,
        le=MAX_TEXT_CHAT_INACTIVITY_TIMEOUT_SECONDS,
    )
    external_pbx_field_mappings: list[ExternalPBXFieldMapping] = Field(
        default_factory=list,
        max_length=100,
    )
    langgraph_endpoint: LangGraphEndpointBinding | None = None


class TextChatInactivityTimeoutConstraints(BaseModel):
    """Backend-owned timeout metadata consumed by generated API clients."""

    default_seconds: int = TEXT_CHAT_INACTIVITY_TIMEOUT_SECONDS
    minimum_seconds: int = MIN_TEXT_CHAT_INACTIVITY_TIMEOUT_SECONDS
    maximum_seconds: int = MAX_TEXT_CHAT_INACTIVITY_TIMEOUT_SECONDS


def get_default_workflow_configurations() -> WorkflowConfigurationDefaults:
    return WorkflowConfigurationDefaults()

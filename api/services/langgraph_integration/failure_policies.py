from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

FIRST_EVENT_ACTIONS = frozenset({"fallback_message", "transfer", "end_call"})
TERMINAL_FAILURE_ACTIONS = frozenset(
    {"retry_prompt", "fallback_message", "transfer", "end_call"}
)
MIN_FIRST_EVENT_DEADLINE_MS = 500
MAX_FIRST_EVENT_DEADLINE_MS = 3000


@dataclass(frozen=True)
class FailurePolicy:
    first_event_deadline_ms: int
    first_event_action: str
    terminal_failure_action: str

    def __post_init__(self) -> None:
        if not MIN_FIRST_EVENT_DEADLINE_MS <= self.first_event_deadline_ms <= MAX_FIRST_EVENT_DEADLINE_MS:
            raise ValueError("first-event deadline must be between 500 and 3000 milliseconds")
        if self.first_event_action not in FIRST_EVENT_ACTIONS:
            raise ValueError("invalid first-event latency action")
        if self.terminal_failure_action not in TERMINAL_FAILURE_ACTIONS:
            raise ValueError("invalid terminal-failure action")


class PolicyEffectStore(Protocol):
    async def claim(
        self,
        *,
        organization_id: int,
        invocation_id: int | str,
        effect_type: str,
        action: str,
        details: dict[str, Any],
    ) -> bool: ...


@dataclass
class InMemoryPolicyEffectStore:
    effects: dict[tuple[int, int | str, str], dict[str, Any]] = field(
        default_factory=dict
    )

    async def claim(
        self,
        *,
        organization_id: int,
        invocation_id: int | str,
        effect_type: str,
        action: str,
        details: dict[str, Any],
    ) -> bool:
        key = (organization_id, invocation_id, effect_type)
        if key in self.effects:
            return False
        self.effects[key] = {"action": action, **details}
        return True


@dataclass(frozen=True)
class DatabasePolicyEffectStore:
    db_client: Any

    async def claim(
        self,
        *,
        organization_id: int,
        invocation_id: int | str,
        effect_type: str,
        action: str,
        details: dict[str, Any],
    ) -> bool:
        if not isinstance(invocation_id, int):
            raise TypeError("database policy effects require the invocation primary key")
        sequence = {"first_event_timeout": -1, "terminal_failure": -2}[effect_type]
        payload = {"action": action, **details}
        digest = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        _, inserted = await self.db_client.record_langgraph_event(
            organization_id=organization_id,
            invocation_id=invocation_id,
            sequence=sequence,
            endpoint_event_id=f"mural-policy:{effect_type}",
            event_type=effect_type,
            payload_digest=digest,
            metadata=payload,
            mutation_outcome="action_executed",
        )
        return inserted


ActionExecutor = Callable[[str], Awaitable[None]]
CancelLateStream = Callable[[], Awaitable[None]]
MetricRecorder = Callable[[str], None]


class FailurePolicyCoordinator:
    """Closes the stream before one durable caller-facing policy effect."""

    def __init__(
        self,
        *,
        store: PolicyEffectStore,
        execute_action: ActionExecutor,
        cancel_late_stream: CancelLateStream,
        record_metric: MetricRecorder | None = None,
    ) -> None:
        self.store = store
        self.execute_action = execute_action
        self.cancel_late_stream = cancel_late_stream
        self.record_metric = record_metric or (lambda _metric: None)

    async def on_first_event_deadline(
        self,
        *,
        organization_id: int,
        invocation_id: int | str,
        policy: FailurePolicy,
        first_event_accepted: bool,
    ) -> bool:
        if first_event_accepted:
            return False
        inserted = await self.store.claim(
            organization_id=organization_id,
            invocation_id=invocation_id,
            effect_type="first_event_timeout",
            action=policy.first_event_action,
            details={"timeout_ms": policy.first_event_deadline_ms},
        )
        if not inserted:
            return False
        # The durable guard is reserved before effects, while stream
        # cancellation/suppression still occurs before the caller action.
        await self.cancel_late_stream()
        self.record_metric("first_event_timeout")
        await self.execute_action(policy.first_event_action)
        return True

    async def on_terminal_failure(
        self,
        *,
        organization_id: int,
        invocation_id: int | str,
        policy: FailurePolicy,
        error_category: str,
    ) -> bool:
        inserted = await self.store.claim(
            organization_id=organization_id,
            invocation_id=invocation_id,
            effect_type="terminal_failure",
            action=policy.terminal_failure_action,
            details={"error_category": error_category},
        )
        if not inserted:
            return False
        await self.execute_action(policy.terminal_failure_action)
        return True

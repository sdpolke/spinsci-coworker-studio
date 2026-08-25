"""Redis-backed workflow generation session store."""

from __future__ import annotations

import json

from redis.asyncio import Redis

from api.constants import (
    REDIS_URL,
    WORKFLOW_GENERATION_SESSION_TTL_SECONDS,
)
from api.services.workflow.generation.models import GenerationSession

_SESSION_KEY_PREFIX = "workflow_generation:session:"


class WorkflowGenerationSessionStore:
    def __init__(
        self,
        *,
        redis_url: str | None = None,
        ttl_seconds: int | None = None,
    ) -> None:
        self._redis_url = redis_url or REDIS_URL
        self._ttl_seconds = ttl_seconds or WORKFLOW_GENERATION_SESSION_TTL_SECONDS
        self._redis: Redis | None = None

    async def _client(self) -> Redis:
        if self._redis is None:
            self._redis = Redis.from_url(self._redis_url, decode_responses=True)
        return self._redis

    def _key(self, session_id: str) -> str:
        return f"{_SESSION_KEY_PREFIX}{session_id}"

    async def save(self, session: GenerationSession) -> None:
        redis = await self._client()
        await redis.set(
            self._key(session.session_id),
            session.model_dump_json(),
            ex=self._ttl_seconds,
        )

    async def get(self, session_id: str) -> GenerationSession | None:
        redis = await self._client()
        raw = await redis.get(self._key(session_id))
        if not raw:
            return None
        return GenerationSession.model_validate_json(raw)

    async def delete(self, session_id: str) -> None:
        redis = await self._client()
        await redis.delete(self._key(session_id))


session_store = WorkflowGenerationSessionStore()

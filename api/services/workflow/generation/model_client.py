"""OpenAI-compatible chat client for workflow generation."""

from __future__ import annotations

import json
from typing import Any, TypeVar

import httpx
from loguru import logger
from pydantic import BaseModel, ValidationError

from api.constants import (
    WORKFLOW_GENERATOR_API_KEY,
    WORKFLOW_GENERATOR_BASE_URL,
    WORKFLOW_GENERATOR_MODEL,
    WORKFLOW_GENERATOR_TEMPERATURE,
    WORKFLOW_GENERATOR_TIMEOUT_SECONDS,
)

T = TypeVar("T", bound=BaseModel)


class WorkflowGeneratorModelError(Exception):
    """Raised when the configured workflow generator model is unavailable."""


class WorkflowGeneratorModelClient:
    def __init__(
        self,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        timeout_seconds: float | None = None,
    ) -> None:
        self._base_url = (base_url or WORKFLOW_GENERATOR_BASE_URL or "").rstrip("/")
        self._api_key = api_key or WORKFLOW_GENERATOR_API_KEY
        self._model = model or WORKFLOW_GENERATOR_MODEL
        self._timeout_seconds = timeout_seconds or WORKFLOW_GENERATOR_TIMEOUT_SECONDS

    @property
    def is_configured(self) -> bool:
        return bool(self._base_url and self._api_key and self._model)

    async def complete_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_model: type[T],
        temperature: float | None = None,
    ) -> T:
        if not self.is_configured:
            raise WorkflowGeneratorModelError(
                "Workflow generator model is not configured. Set "
                "WORKFLOW_GENERATOR_BASE_URL, WORKFLOW_GENERATOR_API_KEY, and "
                "WORKFLOW_GENERATOR_MODEL."
            )

        payload: dict[str, Any] = {
            "model": self._model,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        resolved_temperature = (
            temperature if temperature is not None else WORKFLOW_GENERATOR_TEMPERATURE
        )
        if resolved_temperature is not None:
            payload["temperature"] = resolved_temperature

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        url = f"{self._base_url}/chat/completions"
        try:
            async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
                response = await client.post(url, headers=headers, json=payload)
                response.raise_for_status()
                body = response.json()
        except httpx.HTTPStatusError as exc:
            detail = _extract_http_error_detail(exc.response)
            logger.error(
                "Workflow generator model request failed "
                f"(status={exc.response.status_code}, model={self._model}): {detail}"
            )
            raise WorkflowGeneratorModelError(
                f"Workflow generator model request failed: {detail}"
            ) from exc
        except httpx.HTTPError as exc:
            logger.error(f"Workflow generator model request failed: {exc}")
            raise WorkflowGeneratorModelError(
                "Workflow generator model request failed."
            ) from exc

        content = _extract_message_content(body)
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as exc:
            logger.error(f"Workflow generator returned non-JSON content: {content[:200]}")
            raise WorkflowGeneratorModelError(
                "Workflow generator returned invalid JSON."
            ) from exc

        try:
            return response_model.model_validate(parsed)
        except ValidationError as exc:
            logger.error(f"Workflow generator JSON failed validation: {exc}")
            raise WorkflowGeneratorModelError(
                "Workflow generator returned an unexpected response shape."
            ) from exc


def _extract_http_error_detail(response: httpx.Response) -> str:
    try:
        body = response.json()
    except json.JSONDecodeError:
        text = response.text.strip()
        return text[:200] if text else f"HTTP {response.status_code}"

    if isinstance(body, dict):
        error = body.get("error")
        if isinstance(error, dict):
            message = error.get("message")
            if isinstance(message, str) and message.strip():
                return message.strip()
        message = body.get("message")
        if isinstance(message, str) and message.strip():
            return message.strip()

    text = response.text.strip()
    return text[:200] if text else f"HTTP {response.status_code}"


def _extract_message_content(body: dict[str, Any]) -> str:
    choices = body.get("choices") or []
    if not choices:
        raise WorkflowGeneratorModelError("Workflow generator returned no choices.")
    message = choices[0].get("message") or {}
    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise WorkflowGeneratorModelError("Workflow generator returned empty content.")
    return content.strip()

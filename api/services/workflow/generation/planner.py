"""Clarification planner for workflow generation."""

from __future__ import annotations

from api.mcp_server.instructions import DOGRAH_MCP_INSTRUCTIONS
from api.services.voice_prompting_guide import Stage, build_briefing
from api.services.workflow.generation.catalog import format_catalog_for_prompt
from api.services.workflow.generation.model_client import WorkflowGeneratorModelClient
from api.services.workflow.generation.models import (
    CatalogSnapshot,
    GenerationBrief,
    GenerationMessage,
    PlannerResponse,
)

MAX_CLARIFICATION_TURNS = 5


PLANNER_SYSTEM_PROMPT = """You are a Dograh voice-workflow planning assistant.

Your job is to gather enough context to build a voice agent workflow. Ask at most
one focused clarification question per turn. Prefer concrete business questions
over generic ones. Stop asking once you can produce a clear plan.

Rules:
- Never invent tool UUIDs, document UUIDs, or credential UUIDs.
- If the user needs an integration that is not in the catalog, ask them to
  configure it in Dograh first or proceed without that integration.
- When ready, set status to "ready" and provide a concise summary and plan.
- When still clarifying, set status to "clarifying" and ask exactly one question.
- Respond with JSON only matching this schema:
  {"status":"clarifying|ready","question":string|null,"summary":string|null,"plan":string|null}
"""


def _format_conversation(messages: list[GenerationMessage]) -> str:
    if not messages:
        return "(no messages yet)"
    lines: list[str] = []
    for message in messages:
        lines.append(f"{message.role.value}: {message.content}")
    return "\n".join(lines)


async def plan_next_step(
    *,
    brief: GenerationBrief,
    messages: list[GenerationMessage],
    catalog: CatalogSnapshot,
    model_client: WorkflowGeneratorModelClient | None = None,
) -> PlannerResponse:
    client = model_client or WorkflowGeneratorModelClient()
    voice_guide = build_briefing(stage=Stage.plan)
    user_turns = sum(1 for message in messages if message.role.value == "user")

    user_prompt = f"""## Builder brief
Call type: {brief.call_type}
Use case: {brief.use_case}
Activity description: {brief.activity_description}

## Voice prompting guide (plan stage)
{voice_guide}

## MCP authoring constraints (summary)
{DOGRAH_MCP_INSTRUCTIONS[:2500]}

## Organization catalog
{format_catalog_for_prompt(catalog)}

## Conversation so far
{_format_conversation(messages)}

## Turn budget
You have asked {user_turns} clarification question(s). Ask at most
{MAX_CLARIFICATION_TURNS} total. If enough context exists, mark ready now.
"""

    return await client.complete_json(
        system_prompt=PLANNER_SYSTEM_PROMPT,
        user_prompt=user_prompt,
        response_model=PlannerResponse,
    )

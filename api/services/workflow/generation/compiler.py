"""TypeScript compiler with validation repair loop."""

from __future__ import annotations

from api.mcp_server.instructions import SPINSCI_MCP_INSTRUCTIONS
from api.services.voice_prompting_guide import Stage, build_briefing
from api.services.workflow.authoring import (
    AuthoringFailure,
    PreparedWorkflow,
    prepare_workflow_from_code,
)
from api.services.workflow.generation.catalog import format_catalog_for_prompt
from api.services.workflow.generation.model_client import WorkflowGeneratorModelClient
from api.services.workflow.generation.models import (
    CatalogSnapshot,
    CompilerResponse,
    GenerationBrief,
    GenerationMessage,
)

MAX_REPAIR_ATTEMPTS = 3

COMPILER_SYSTEM_PROMPT = """You are a SpinSci voice-workflow code generator.

Emit ONLY valid TypeScript using @spinsci/sdk that follows the allowed grammar.
Do not include markdown fences or commentary.

Rules:
- Use `new Workflow({ name: "..." })` with a descriptive snake_case or plain name.
- Prefer wf.addTyped(startCall/endCall/agentNode/...) over wf.add.
- Include explicit wf.edge(...) calls with label and condition for every branch.
- Design a spoken conversation, not a written script or business-process
  description. Each conversational node must handle one focused exchange.
- Write prompts that make the agent respond with one or two short sentences at a
  time, use plain language and contractions, acknowledge the user's answer
  naturally, and ask only one question at a time. Avoid lists, long explanations,
  repeated context, and essay-like responses.
- Make each turn move the conversation forward with a brief question, confirmation,
  or clear next step. Do not have the agent recite the workflow or its instructions.
- Re-check every tool in the final organization catalog against each node's task.
  Attach exact `tool_uuids` when a listed tool is useful; do not attach irrelevant
  tools. The final catalog is authoritative even if the approved plan differs.
- For every attached tool, state in that node's prompt exactly when to invoke it,
  what information must be collected first, and how to recover conversationally if
  the call fails. Keep any spoken pre-call notice brief and never speak a tool call.
- Only reference tool_uuids, document_uuids, and credential UUIDs from the catalog.
- Never invent UUIDs.
- Set `allow_interrupt: true` explicitly on every startCall and agentNode so callers
  can speak naturally. Use false only when the approved requirements identify a
  specific mandatory disclosure that must not be interrupted.
- Keep the first version simple: startCall, a few agent nodes, endCall.
- Respond with JSON only: {"typescript":"..."}"""


async def compile_workflow_typescript(
    *,
    brief: GenerationBrief,
    summary: str,
    plan: str,
    messages: list[GenerationMessage],
    catalog: CatalogSnapshot,
    organization_id: int | None,
    model_client: WorkflowGeneratorModelClient | None = None,
) -> tuple[PreparedWorkflow, str]:
    client = model_client or WorkflowGeneratorModelClient()
    voice_guide = build_briefing(stage=Stage.create)

    conversation = "\n".join(
        f"{message.role.value}: {message.content}" for message in messages
    )
    base_user_prompt = f"""## Builder brief
Call type: {brief.call_type}
Use case: {brief.use_case}
Activity description: {brief.activity_description}

## Approved summary
{summary}

## Approved plan
{plan}

## Clarification conversation
{conversation or "(none)"}

## Voice prompting guide (create stage)
{voice_guide}

## MCP authoring constraints
{SPINSCI_MCP_INSTRUCTIONS}

## Organization catalog
{format_catalog_for_prompt(catalog)}
"""

    typescript = ""
    last_failure: AuthoringFailure | None = None

    for attempt in range(MAX_REPAIR_ATTEMPTS):
        repair_hint = ""
        if last_failure is not None:
            repair_hint = (
                "\n\n## Previous validation errors\n"
                f"{last_failure.error_code}: {last_failure.message}\n"
                "Fix the TypeScript and resubmit the full corrected source."
            )

        response = await client.complete_json(
            system_prompt=COMPILER_SYSTEM_PROMPT,
            user_prompt=base_user_prompt + repair_hint,
            response_model=CompilerResponse,
        )
        typescript = response.typescript.strip()
        prepared = await prepare_workflow_from_code(
            typescript,
            organization_id=organization_id,
        )
        if isinstance(prepared, PreparedWorkflow):
            return prepared, typescript

        last_failure = prepared

    assert last_failure is not None
    raise WorkflowCompilationError(last_failure.message, typescript=typescript)


class WorkflowCompilationError(Exception):
    def __init__(self, message: str, *, typescript: str = "") -> None:
        super().__init__(message)
        self.typescript = typescript

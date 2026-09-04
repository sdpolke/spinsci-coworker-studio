"""An OpenAI-compatible ``/v1/chat/completions`` endpoint over the graph.

This is the seam for **Pattern B** ("agent as model endpoint") from
voiceagent_v2's ``VOICE_API_INTEGRATION.md`` §4: point an agent's LLM
provider config at this server's base URL (e.g.
``http://localhost:8000/v1``) and the platform's own pipeline — STT, TTS,
turn-taking, recording, transcript upload — calls out here for the text of
each turn, exactly like it would call OpenAI.

What this **does** implement, matching what that doc requires of an
OpenAI-compatible provider:

* ``POST /v1/chat/completions`` with the standard request shape
  (``messages``, ``model``, ``stream``).
* **Server-sent event streaming** when ``stream: true`` — tokens are pushed
  as they arrive from the graph, in the OpenAI streaming chunk shape, so the
  calling platform can start speech synthesis before the graph finishes.
* A non-streaming fallback (single JSON response) for clients that don't
  stream.

What this **does not** implement, and why that's fine for this repo's scope:

* The platform's per-turn **tool-calling contract** — on every node
  transition it rebuilds the system prompt and injects one function per
  outgoing graph edge, expecting the model to call one to advance *its own*
  node graph. This server ignores any ``tools`` sent in the request: our
  LangGraph already owns the whole conversation (triage → scheduling /
  booking / billing, verification, tool use) end-to-end and only needs to
  produce the next thing to say — it isn't a per-node brain for someone
  else's graph. Practically, this means the platform-side agent you point at
  this endpoint should be a **single node** (no outgoing edges to advance),
  since this server will never call an edge-function.
* The platform's rebuilt **system prompt** — our graph supplies its own
  prompts per active agent (see ``prompts.py``), so incoming system messages
  are dropped, same as ``langgraph_llm_service.py`` does for the Pipecat
  path.

Recordings, transcripts, and turn-taking are entirely the calling platform's
job in Pattern B — nothing here needs to know about them.

────────────────────────────────────────────────────────────────────────────
WHY THIS ENDPOINT USES A CHECKPOINTER (unlike the voice path)

The voice path (``langgraph_llm_service.py``) runs the graph with no
checkpointer: Pipecat's own ``LLMContext`` is a real Python object retained
across turns, and ``_tool_exchange`` persists each turn's handoff tool calls
back into it — so ``active_agent`` (tracked in ``graph.py`` by scanning
history for ``transfer_to_*`` tool calls) survives.

Over this HTTP endpoint there is no equivalent object: the caller
(voiceagent_v2) resends plain OpenAI-format ``role``/``content`` messages
every turn and has no reason to preserve or replay tool-call messages this
graph produced — those never round-trip back to us. Without a checkpointer,
``active_agent`` would reset to ``triage`` on every single call, because the
history this endpoint actually receives never contains the handoff tool
calls it's looking for.

The fix mirrors ``server.py``'s ``/chat`` endpoint: a LangGraph
``InMemorySaver`` checkpointer tracks ``active_agent`` server-side, keyed by
a conversation id derived from the request (see ``_conversation_key``) since
voiceagent_v2's generic OpenAI-compatible provider path sends no stable
per-call identifier (checked in ``api/services/pipecat/service_factory.py``
on the voiceagent_v2 side — only its first-party provider threads a
``correlation_id``). The key is a hash of the first message in the
conversation, which is stable for the duration of one call because
voiceagent_v2 always resends the same prefix on every turn.
────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from typing import Any, AsyncIterator

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse
from langchain_core.messages import convert_to_messages
from langgraph.checkpoint.memory import InMemorySaver

from .graph import build_graph

router = APIRouter()

# Checkpointed — see the module docstring for why this differs from the
# voice path. One shared saver; each conversation gets its own thread_id.
_graph = build_graph(checkpointer=InMemorySaver())

# How many of the caller's raw messages we've already sent into the graph,
# per thread_id. Can't be derived from the checkpointed state's message
# count: the graph appends handoff tool-call/tool-result messages the caller
# never sends back, so the two counts drift apart after the first handoff.
_raw_messages_seen: dict[str, int] = {}


def _conversation_key(raw_messages: list[dict]) -> str:
    """A conversation id stable across turns of one call, absent a real one.

    voiceagent_v2 resends the full message history every turn but supplies
    no call/session identifier on the generic OpenAI-compatible provider
    path (see module docstring). The first message in the history is the
    same on every turn of a given call, so hashing it is a cheap stand-in —
    it will collide if two different calls open with an identical first
    utterance, which is an acceptable tradeoff for local/experimental use
    but not a substitute for voiceagent_v2 sending a real conversation id.
    """
    first = raw_messages[0] if raw_messages else {}
    seed = json.dumps(first, sort_keys=True)
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:32]


_SPOKEN_NODES = {"model"}


def _spoken_text(event: dict) -> str | None:
    """Same extraction logic as ``langgraph_llm_service._spoken_text``."""
    if event.get("event") != "on_chat_model_stream":
        return None
    node = (event.get("metadata") or {}).get("langgraph_node")
    if node not in _SPOKEN_NODES:
        return None
    chunk = event.get("data", {}).get("chunk")
    text = getattr(chunk, "text", None)
    return text if isinstance(text, str) and text else None


def _sse_chunk(request_id: str, created: int, model: str, delta: dict, finish_reason: str | None = None) -> str:
    payload = {
        "id": request_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": model,
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
    }
    return f"data: {json.dumps(payload)}\n\n"


async def _stream_response(messages: list, thread_id: str, model: str) -> AsyncIterator[str]:
    request_id = f"chatcmpl-{uuid.uuid4().hex}"
    created = int(time.time())
    config = {"configurable": {"thread_id": thread_id}}

    yield _sse_chunk(request_id, created, model, {"role": "assistant", "content": ""})

    async for event in _graph.astream_events({"messages": messages}, config, version="v2"):
        text = _spoken_text(event)
        if text:
            yield _sse_chunk(request_id, created, model, {"content": text})

    yield _sse_chunk(request_id, created, model, {}, finish_reason="stop")
    yield "data: [DONE]\n\n"


async def _collect_response(messages: list, thread_id: str) -> str:
    config = {"configurable": {"thread_id": thread_id}}
    parts: list[str] = []
    async for event in _graph.astream_events({"messages": messages}, config, version="v2"):
        text = _spoken_text(event)
        if text:
            parts.append(text)
    return "".join(parts)


@router.post("/v1/chat/completions")
async def chat_completions(request: Request) -> Any:
    body = await request.json()
    raw_messages = [m for m in body.get("messages", []) if m.get("role") != "system"]
    thread_id = _conversation_key(raw_messages)

    # The checkpointer already holds every prior turn under this thread_id —
    # send only the new tail of the conversation, same pattern as server.py's
    # /chat endpoint. On the first call for this thread, that tail is the
    # whole history; on later calls it's just the newest message(s).
    already_seen = _raw_messages_seen.get(thread_id, 0)
    new_raw_messages = raw_messages[already_seen:] or raw_messages[-1:]
    _raw_messages_seen[thread_id] = len(raw_messages)
    messages = convert_to_messages(new_raw_messages)

    model = body.get("model") or "gym-support-graph"
    stream = bool(body.get("stream", False))

    if stream:
        return StreamingResponse(
            _stream_response(messages, thread_id, model),
            media_type="text/event-stream",
        )

    content = await _collect_response(messages, thread_id)
    return JSONResponse(
        {
            "id": f"chatcmpl-{uuid.uuid4().hex}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": content},
                    "finish_reason": "stop",
                }
            ],
        }
    )


@router.get("/v1/models")
async def list_models() -> Any:
    return {
        "object": "list",
        "data": [{"id": "gym-support-graph", "object": "model", "owned_by": "local"}],
    }

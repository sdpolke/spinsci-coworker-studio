# Integrating this LangGraph agent with voiceagent_v2

This documents what a LangGraph workflow in this repo's shape needs to change
to work as a **Pattern B** ("agent as model endpoint") backend for
voiceagent_v2 — i.e. to sit behind an agent's LLM provider configuration and
receive real calls, rather than being tested standalone through
`gym_support.voice` or `POST /chat`.

It reflects one bug found and fixed while integration-testing this graph
against a running voiceagent_v2 instance (see "The stateless-endpoint bug"
below), plus the config/deployment changes required on the voiceagent_v2 side.
Treat this as a checklist for adapting *any* LangGraph agent to this seam, not
just this repo's eye-clinic demo.

## Background: why this integration exists

voiceagent_v2 owns the whole call — telephony/WebRTC, STT, TTS, turn-taking,
interruption handling, recording, and transcript upload. It has no callback
that asks an external service "what should I say next" mid-turn. The
supported way to make an external agent (LangGraph, LangChain, or otherwise)
own conversation *content* is to expose it as a
**model endpoint**: an OpenAI-compatible `POST /v1/chat/completions` server
that voiceagent_v2's own LLM provider configuration points at via `base_url`.
voiceagent_v2 still runs STT → **your endpoint** → TTS, still records the
call, still uploads the transcript — none of that changes. Your endpoint's
only job is to receive the conversation history on every turn and return the
next thing to say.

This repo's `src/gym_support/openai_compat.py` is that endpoint, wrapping
`graph.py`'s compiled LangGraph.

## Required changes to the LangGraph workflow

### 1. Expose an OpenAI-compatible `/v1/chat/completions` endpoint

voiceagent_v2 calls this endpoint exactly like it would call OpenAI:
`POST {base_url}/chat/completions` with `messages`, `model`, `stream`.

- **Streaming (SSE) is not optional in production.** voiceagent_v2 starts
  speech synthesis as tokens arrive; a non-streaming response means the
  caller hears nothing until the whole turn is generated. Implement both, but
  expect `stream: true` on real calls.
- Drop incoming `system` messages — voiceagent_v2 sends one, rebuilt from its
  own node/prompt config, but this agent supplies its own prompts per active
  specialist (see `prompts.py`). Don't merge or fight over which system
  prompt wins; just ignore theirs.
- Ignore any `tools` in the request. voiceagent_v2's platform-native agents
  use per-turn tool-calling to advance *their own* node graph (one function
  per outgoing edge); a LangGraph-backed endpoint is a different mechanism
  for the same "decide what to say/do next" job and should own that decision
  entirely. Practically, the voiceagent_v2-side workflow node you point at
  this endpoint should be a single terminal node with no outgoing edges the
  model would need to call.

### 2. The stateless-endpoint bug: don't rely on tool calls surviving a round trip

This is the one substantive bug this integration surfaced, and it will
recur in any LangGraph agent that uses `Command(graph=Command.PARENT)`
handoffs (the "agents as graph nodes" pattern) behind this seam.

**Symptom:** mid-conversation, replies came back as several unrelated
sentences concatenated with no separators — different phrasings of the same
question, then a question that belonged to a completely different
specialist. Verification appeared to restart from scratch on every turn.

**Root cause:** this graph tracks "which specialist is active"
(`active_agent` in `graph.py`) by scanning the message history for
`transfer_to_*` tool calls (`_derive_active_agent`). The graph itself is
stateless by design — voiceagent_v2 resends the *entire* history on every
turn, so no LangGraph checkpointer is needed, matching the same statelessness
`langgraph_llm_service.py` uses for the Pipecat voice path.

The gap: the OpenAI chat-completions response shape only returns `content`
(the text) or `tool_calls` in a specific request/response cycle — and
voiceagent_v2 has no reason to preserve or replay tool-call messages it
didn't itself generate. Each HTTP call this endpoint receives contains only
plain user/assistant text turns. `_derive_active_agent` finds no
`transfer_to_*` tool call in that history — there never was one, from
voiceagent_v2's point of view — and resets to `triage` on every single call.
Triage then re-routes (usually back to the same specialist, since the intent
is still visible in the conversation) and the specialist re-asks its opening
questions, producing exactly the garbled, repetitive output observed.

**The fix, and why it works:** the voice path
(`langgraph_llm_service.py::_tool_exchange`) never has this problem because
it persists the handoff tool-call exchange directly into Pipecat's own
`LLMContext` object, which is retained in-process across turns — continuity
lives in a real Python object, not in what gets sent back over the wire.
`openai_compat.py` had no equivalent mechanism. The fix follows the pattern
already used correctly by `server.py`'s `/chat` endpoint: use a LangGraph
**checkpointer** (`InMemorySaver`, keyed by a stable per-conversation id) so
`active_agent` is tracked server-side, and stop trying to reconstruct it from
replayed history at all.

**Why this matters for any LangGraph agent, not just this one:** if your
graph tracks routing/handoff state via tool calls in message history (a
common LangGraph pattern), and you're exposing it through a generic
OpenAI-compatible endpoint to a caller that only round-trips plain
`role`/`content` messages, you will hit this same bug. The fix is the same:
track that state server-side, keyed by something stable across the calls for
one conversation — not by parsing history the caller sends back.

**The missing piece — no stable per-conversation key.** voiceagent_v2's
generic `openai` provider path does not send any correlation id, session id,
or `user` field with the request (checked in
`api/services/pipecat/service_factory.py` and pipecat's
`BaseOpenAILLMService.build_chat_completion_params` — the only place a
`correlation_id` is threaded through today is the first-party `SpinSciLLMService`
provider, not the generic OpenAI-compatible path this integration uses).
Concretely, this means:

- You cannot key a checkpointer on a call id, run id, or thread id supplied
  by voiceagent_v2 — there isn't one in the request.
- The only thing consistently available across a single call's turns is
  **the message history itself**. A reasonable, cheap key is a hash of the
  first user message (or the full initial message list) — stable for the
  duration of one call, since voiceagent_v2 always resends the same prefix on
  every turn of the same conversation. This won't dedupe two different calls
  that happen to open with an identical first utterance, but for a
  single-organization test deployment that's an acceptable tradeoff; a
  production integration should push voiceagent_v2 to add a stable
  conversation identifier to the request (see "Open items" below) rather than
  work around its absence indefinitely.

### 3. Recordings, transcripts, and turn-taking need no changes here

Confirmed by tracing voiceagent_v2's own pipeline: `AudioBufferProcessor` and
the STT/TTS stages that produce `recording_url`, `user_recording_url`,
`bot_recording_url`, and `transcript_url` operate entirely at the
transport/audio layer, independent of which `LLMService` class is servicing
`/chat/completions`. Swapping the LLM provider to point at this endpoint does
not require, and should not attempt, any recording/transcript logic on this
side — that stays voiceagent_v2's job for every pattern, including this one.

## Required configuration on the voiceagent_v2 side

None of this is a code change in voiceagent_v2 — it's a per-workflow
configuration value, and it should be scoped as narrowly as possible while
this integration is experimental.

1. **Scope the override to one workflow's draft definition**, not the
   org-level default and not the published definition. The override lives in
   `workflow_definitions.workflow_configurations` (JSON column) for the
   specific draft row, under the legacy `model_overrides` key (merges onto
   the org default rather than replacing it):

   ```json
   {
     "model_overrides": {
       "llm": {
         "provider": "openai",
         "base_url": "http://127.0.0.1:8010/v1",
         "model": "gym-support-graph",
         "api_key": "local-dev-key"
       }
     }
   }
   ```

   Editing the **draft** definition (not `workflows.workflow_configurations`,
   which mirrors the *published* definition) means real/production calls —
   which always resolve to the published definition — are unaffected. Only
   test-runs invoked with `use_draft=True` (the workflow editor's Test button,
   test text-chat sessions, `/test/` public trigger endpoints) pick up the
   override.

2. **Run this endpoint on a port voiceagent_v2 isn't already using.**
   voiceagent_v2's own API defaults to `:8000`; run this repo's server with
   `PORT=8010 uv run pipecat-langgraph-example` (or any free port) and point
   `base_url` at that port.

3. **Confirm `DEPLOYMENT_MODE` allows a local `base_url`.** voiceagent_v2's
   `api/utils/url_security.py` rejects `localhost`/private-IP/CGNAT
   `base_url` values unless `DEPLOYMENT_MODE=oss` (the default for a
   self-hosted dev instance — check `GET /api/v1/health` reports
   `"deployment_mode":"oss"`). A hosted/SaaS deployment will reject this
   `base_url` outright; that check exists for a reason and should not be
   bypassed for a real deployment target — only local dev.

4. **`api_key` is not validated against this endpoint.** voiceagent_v2 just
   forwards whatever string you configure as a bearer credential; this
   endpoint doesn't check it. Anything non-empty works for local testing.
   A real deployment should still require and check a shared secret here —
   this endpoint currently accepts any value, which is fine for local
   experimentation but not for anything internet-reachable.

## Open items / not yet done

- **No shared-secret enforcement on `openai_compat.py`.** Anyone who can
  reach this endpoint's port can drive the graph. Fine for `127.0.0.1`-only
  local testing; add bearer-token validation before exposing this endpoint
  beyond localhost.
- **No stable conversation id from voiceagent_v2.** As noted above, the
  generic `openai` provider path sends no correlation/session identifier.
  The message-history-hash keying approach is a workaround, not a fix; the
  clean fix is on voiceagent_v2's side (thread a stable id, e.g. the
  `workflow_run_id`, through to the LLM request — perhaps as an OpenAI
  `user` field or a custom header) if this integration moves past
  experimentation.
- **Checkpointer is in-memory (`InMemorySaver`).** State is lost on restart
  and doesn't survive multiple worker processes. Fine for a single local dev
  server; a real deployment behind this pattern needs a persistent
  checkpointer (e.g. LangGraph's Postgres/Redis-backed savers) sized to
  however many concurrent calls voiceagent_v2 can route to it.

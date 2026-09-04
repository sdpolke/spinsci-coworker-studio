# pipecat-langgraph-example — Lakeview Eye Care front desk (multi-agent handoffs)

A tiny front-desk agent for a fictional eye clinic, built with
**LangChain / LangGraph** multi-agent **handoffs**, traced to **LangSmith** — and
served as a **text chat**, a real-time **Pipecat voice bot**, and an
**OpenAI-compatible `/v1/chat/completions` endpoint** from the same graph.

It demonstrates the **"agents as graph nodes"** pattern (what we've been calling
*Option A*): a **triage** front desk (persona: "Ava") plus three specialists —
**scheduling** (modify an existing appointment), **booking** (make a new one),
and **billing** — each a distinct node in the graph. The customer stays
"inside" a specialist across turns because the active agent is stored in
state, not because execution pauses there. This is a small-scale version of
the switchboard → scheduling → booking squad pattern used by production
voice-agent deployments (verify caller identity, look up an EHR-style record,
then either self-serve modify or hand off to book a new visit) — collapsed
into a single LangGraph handoff graph, with mock data standing in for the real
EHR integration.

> The graph re-enters at `START` every turn and routes straight to the
> `active_agent`. State remembers where the conversation is — the engine does
> not freeze you inside a node.

```
START ──(route_initial: active_agent or "triage")──► triage ──┐
                                                              ├─► scheduling ─┐
                                                              ├─► booking ────┼─► (route_after_agent) ─► END
                                                              └─► billing ────┘            ▲
                                                  specialists ── transfer_to_triage ───────┘
```

Each agent's handoff tools (`transfer_to_scheduling`, …) return a
`Command(goto=..., graph=Command.PARENT)` that jumps to a sibling node and
updates `active_agent`. This is the LangChain
["Multiple agent subgraphs"](https://docs.langchain.com/oss/python/langchain/multi-agent/handoffs)
handoff pattern.

## What it does

- **Verify identity** — every specialist (scheduling, booking, billing) verifies
  phone number + full name + date of birth against a mock patient record
  before touching a chart, mirroring how a real deployment never trusts an
  unverified caller.
- **Manage an existing appointment** — list, confirm, cancel, or reschedule.
- **Book a new appointment** — pick a doctor (optionally by specialty), check
  mock availability, and book a slot.
- **Check account balance** — a mock billing lookup.

All data is **mocked in-process** (`mock_data.py`). There is no database or
external API: a small set of phone numbers "exist," and tool side effects
mutate an in-memory dict that resets when the server restarts.

## Layout

```
src/gym_support/
├── graph.py                 # the 4 agents wired as nodes + routing (the core)
├── tools.py                 # verification + business tools + transfer_to_* handoffs
├── prompts.py               # one system prompt per agent
├── mock_data.py             # in-memory patient/appointment/doctor store
├── server.py                # FastAPI: GET / (chat page) + POST /chat + /v1/chat/completions
├── openai_compat.py         # OpenAI-compatible endpoint (Pattern B seam — see below)
├── voice.py                 # Pipecat voice bot (same graph, spoken)
├── langgraph_llm_service.py # adapter: runs the graph as Pipecat's LLM stage
├── processor.py             # OTel → LangSmith bridge (+ conversation audio)
└── static/
    └── index.html           # the chat box
```

## Setup

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```bash
cd pipecat-langgraph-example
uv sync
cp .env.example .env      # then fill in keys
```

Set in `.env`:

- `ANTHROPIC_API_KEY` — the default model is `anthropic:claude-sonnet-4-6`.
  To use OpenAI instead, set `GYM_SUPPORT_MODEL=openai:gpt-5.5` and
  `OPENAI_API_KEY` (and `uv add langchain-openai`).
- `OPENAI_API_KEY` — required for the **voice bot** (speech-to-text and
  text-to-speech run on OpenAI).
- `LANGSMITH_TRACING=true` + `LANGSMITH_API_KEY` — to see the handoffs in the
  trace tree. `LANGSMITH_PROJECT` defaults to `pipecat-langgraph-example`.
- For voice tracing, the `OTEL_EXPORTER_OTLP_*` vars + `LANGSMITH_TRACING_MODE=otel`
  route Pipecat's spans (and the conversation audio) into the same LangSmith
  project — see `.env.example`.

## Run

```bash
uv run pipecat-langgraph-example
```

Open http://127.0.0.1:8000 and chat. Try:

- "I need to reschedule my appointment" → watch the badge switch to
  **scheduling**, then verify with phone `555-123-0001`, name `Alex Rivera`,
  DOB `1985-03-14`.
- "I'd like to book a new appointment" → **booking**, verify with phone
  `555-123-0002`, name `Jamie Chen`, DOB `1990-11-02`, then ask about doctors
  or availability.
- "What's my account balance?" → **billing**.
- Mid-conversation, switch intent ("actually, I want to book a new
  appointment instead") — the specialist hands you back to triage, which
  re-routes you.

## Use it as a model endpoint (Pattern B)

The same graph is also exposed as an OpenAI-compatible `POST /v1/chat/completions`
endpoint (SSE streaming and a non-streaming fallback — see `openai_compat.py`).
This is the seam described in a hosted voice-agent platform's "agent as model
endpoint" pattern: point an agent's LLM provider configuration at this
server's `base_url` (e.g. `http://localhost:8000/v1`), and that platform's own
pipeline — STT, TTS, turn-taking, call recording, transcript upload — runs the
call while this graph supplies the text for each turn. No code in this repo
needs to know about recordings or transcripts; the calling platform owns all
of that in this pattern.

This endpoint does **not** implement the calling platform's per-node
tool-calling contract (it ignores any `tools` in the request) — this graph
already owns the whole conversation end-to-end, so the platform-side agent
you point at it should be a single node with no outgoing edges.

```bash
uv run pipecat-langgraph-example   # same server as the text chat
curl -N http://127.0.0.1:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model": "gym-support-graph", "stream": true,
       "messages": [{"role": "user", "content": "I need to reschedule my appointment"}]}'
```

## Talk to it (voice)

The same graph also runs as a real-time **Pipecat** voice bot — the agent
doesn't change, it just gets ears and a mouth:

```bash
uv run python -m gym_support.voice
```

Open the URL it prints (default http://localhost:7860), click **Connect**, allow
the mic, and talk. The flow is STT → the LangGraph brain → TTS, with barge-in
(interrupt the bot mid-sentence). Here the graph runs **statelessly**: Pipecat's
context is the source of truth, and the active specialist is recovered from the
transcript each turn, so interruptions never corrupt routing state.

`voice.py` is the whole story — the only real change from the text app is that
the LLM stage is `LangGraphLLMService` (our graph) instead of a stock model.

## What you see in LangSmith

**Text** — one trace per `/chat` turn. A handoff shows the triage agent calling a
`transfer_to_*` tool, then the specialist node running and replying, so the
routing decision and the specialist's work sit side by side in the tree.

**Voice** — a `conversation` root span (grouped as a thread) with
`turn → stt / llm / tts` underneath, the graph's `model`/`tool` nodes nested
inside the `llm` span, and the full conversation **audio** attached to the root.

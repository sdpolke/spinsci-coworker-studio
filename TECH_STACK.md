# SpinSci — Technology Stack

Shareable list of languages, frameworks, packages, and infrastructure used in this repository. (Component inventory only — not an architecture overview.)

**Product:** Open-source voice AI platform for building and deploying conversational agents (telephony, WebRTC, text chat, workflow builder).

**Repository layout:** `api/` (backend), `ui/` (frontend), `pipecat/` (voice framework submodule), `sdk/` (Python + TypeScript SDKs), `deploy/` (Helm, templates), `scripts/` (setup & ops).

---

## Languages

| Area | Languages |
|------|-----------|
| Backend | Python 3.13 |
| Frontend | TypeScript, JavaScript |
| Voice pipeline | Python (Pipecat) |
| SDKs | Python 3.10+, TypeScript (Node 20+) |
| Shell / ops | Bash, PowerShell |
| Config / data | YAML, JSON, TOML, SQL |
| Docs site | MDX (Mintlify) |

---

## Backend (`api/`)

| Category | Technology |
|----------|------------|
| Framework | FastAPI |
| ASGI server | Uvicorn |
| ORM | SQLAlchemy 2 (async) |
| DB driver | asyncpg |
| Migrations | Alembic, alembic-postgresql-enum |
| Validation | Pydantic v2 |
| Background jobs | ARQ (Redis-backed) |
| Caching / queues | Redis |
| Object storage | MinIO client; optional AWS S3 via aioboto3 |
| Vector search | pgvector |
| HTTP / multipart | python-multipart |
| Password hashing | bcrypt |
| Email validation | email-validator |
| Serialization | msgpack |
| MCP server | FastMCP |
| TypeScript bridge | Node.js (`api/mcp_server/ts_validator`) |
| Logging | Loguru |
| Dev / quality | pytest, mypy, watchfiles, datamodel-code-generator |

**Key Python packages** (`api/requirements.txt`): `fastapi`, `uvicorn`, `sqlalchemy[asyncio]`, `asyncpg`, `alembic`, `arq`, `redis`, `minio`, `aioboto3`, `pgvector`, `twilio`, `sentry-sdk[fastapi]`, `posthog`, `langfuse`, `fastmcp`, `tuner-pipecat-sdk`, `PyNaCl`.

**Install tooling:** `uv` (Docker builds), standard `venv` + pip for local dev.

---

## Frontend (`ui/`)

| Category | Technology |
|----------|------------|
| Framework | Next.js 15 (App Router) |
| UI library | React 19 |
| Language | TypeScript 5 |
| Styling | Tailwind CSS 4, PostCSS |
| Components | Radix UI, shadcn/ui patterns, Lucide icons |
| Workflow graph | @xyflow/react, @dagrejs/dagre |
| Forms | react-hook-form |
| State | Zustand, zundo |
| Themes | next-themes |
| Charts | Recharts |
| Auth (hosted) | Stack Auth (`@stackframe/stack`) |
| API client | OpenAPI-generated client (`@hey-api/openapi-ts`) |
| Analytics | PostHog (`posthog-js`, `posthog-node`) |
| Error tracking | Sentry (`@sentry/nextjs`) |
| Logging | Pino |
| Support widget | Chatwoot embed |
| Scheduling embed | Cal.com |
| Fonts | Sora, Noto Serif, Geist Mono (next/font) |
| Testing | Vitest, Testing Library, jsdom |
| Linting | ESLint 9, eslint-config-next |

---

## Voice & realtime (`pipecat/`)

| Category | Technology |
|----------|------------|
| Framework | Pipecat (git submodule, `pipecat-ai`) |
| Role | Real-time voice pipelines: STT, LLM, TTS, WebRTC transport |
| Core deps | aiohttp, websockets, OpenAI SDK, numpy, onnxruntime, pydantic, loguru |
| Optional extras (Docker image) | cartesia, deepgram, openai, elevenlabs, groq, google, azure, sarvam, speechmatics, openrouter, camb, mcp, inworld, smallest, webrtc, soundfile, silero |
| Media | ffmpeg (static binary in API image), opencv-python-headless, NLTK |

SpinSci-specific Pipecat services live under `pipecat/src/pipecat/services/spinsci/`.

---

## Data & infrastructure

| Component | Technology | Purpose |
|-----------|------------|---------|
| Primary database | PostgreSQL 17 + pgvector | App data, embeddings |
| Cache / queue broker | Redis 7 | ARQ workers, sessions, caching |
| Object storage | MinIO (default) or AWS S3 | Call audio, recordings, assets |
| Reverse proxy | nginx (Alpine) | TLS termination, upstream to API workers |
| WebRTC TURN | coturn 4.8 | Media relay for browser calls |
| Tunnel (optional) | Cloudflare cloudflared | Private-host deployments |
| Init / config render | bash + templates | nginx/coturn config generation |

**Local dev:** `docker-compose-local.yaml` (Postgres, Redis, MinIO).  
**Production / OSS:** `docker-compose.yaml` (full stack).

---

## Telephony integrations

Built-in provider modules under `api/services/telephony/providers/`:

- Twilio
- Telnyx
- Plivo
- Vonage
- Exotel
- Vobiz
- Cloudonix
- Asterisk ARI (with external PBX hooks, e.g. Vicidial)

Transport patterns: REST webhooks, WebSocket media streams, SIP/ARI where applicable.

---

## AI model providers (configurable per org/workflow)

**LLM / realtime (BYOK or managed):** OpenAI, Azure OpenAI, Google, Google Vertex, Groq, OpenRouter, Atlas Cloud, AWS Bedrock, xAI, Sarvam, SpinSci managed, OpenAI Realtime, Azure Realtime, Google Realtime, Google Vertex Realtime, Grok Realtime, Ultravox Realtime.

**Speech-to-text:** Deepgram, Azure Speech, Google, AssemblyAI, Gladia, Speechmatics, Cartesia, ElevenLabs, Speaches, Hugging Face, Sarvam, Camb, SpinSci managed.

**Text-to-speech:** ElevenLabs, Cartesia, Azure Speech, Google, Inworld, Rime, Minimax, Smallest, LMNT, Sarvam, Camb, SpinSci managed.

**Embeddings:** OpenAI, Azure, SpinSci managed.

---

## SDKs (`sdk/`)

| Package | Runtime | Build / publish |
|---------|---------|-----------------|
| `spinsci-sdk` | Python ≥3.10 | hatchling, httpx, pydantic |
| `@spinsci/sdk` | Node ≥20, ESM | TypeScript, openapi-typescript |

Codegen from backend OpenAPI + node-spec catalog (`scripts/generate_sdk.sh`).

---

## Authentication & security

| Mode | Technology |
|------|------------|
| OSS / local | JWT (`OSS_JWT_SECRET`), cookie-based session |
| Hosted option | Stack Auth |
| API keys | Organization service keys (`X-API-Key`) |
| Telephony WS | HMAC-signed media WebSocket URLs |
| Secrets | Env-based config; Helm/kubernetes secrets in cluster deploys |

---

## Observability & analytics

| Tool | Use |
|------|-----|
| Sentry | API + UI error tracking |
| PostHog | Product analytics |
| Langfuse | LLM / agent tracing (optional) |
| Structured logs | Loguru (API), Pino (UI) |

---

## Documentation

| Tool | Location |
|------|----------|
| Mintlify | `docs/` (guides, API reference, deployment docs) |
| OpenAPI | Backend exposes OpenAPI; drives UI client + SDK codegen |

---

## Deployment & operations

| Target | Technology |
|--------|------------|
| Containers | Docker multi-stage images (`api/Dockerfile`, `ui/Dockerfile`) |
| Compose | Docker Compose (local, remote, tunnel profiles) |
| Kubernetes | Helm chart (`deploy/helm/spinsci/`) — web, UI, ARQ worker, ARI manager, campaign orchestrator, coturn, migrate job |
| Registry | GHCR (`ghcr.io/spinsci-hq`) |
| TLS | Let's Encrypt (Certbot), self-signed, sslip.io / nip.io patterns |
| CI | GitHub Actions (API tests, Docker images, release, drift checks) |

**Runtime processes (typical production):**

- FastAPI / Uvicorn web workers
- ARQ background worker
- ARI manager (telephony singleton)
- Campaign orchestrator (singleton)
- Next.js UI server

---

## Testing

| Layer | Tools |
|-------|--------|
| API | pytest, pytest-asyncio, aiohttp test utilities |
| UI | Vitest, @testing-library/react |
| SDK | pytest (Python), Node test runner (TypeScript) |
| CI DB | pgvector/pgvector:pg17 service container |

---

## Version snapshot (app)

| Component | Version (from repo) |
|-----------|---------------------|
| API | 1.44.0 |
| UI | 1.44.0 |
| Python SDK | 0.1.8 |
| TypeScript SDK | 0.1.8 |
| Helm chart | 0.1.0 |

---

*Generated from the SpinSci / voiceagent_v2 repository. For setup steps, see `docs/contribution/setup.mdx` and `AGENTS.md`.*

# SpinSci — Technology Stack

Shareable list of languages, frameworks, packages, and infrastructure used in this repository. (Component inventory only — not an architecture overview.)

**Product:** Open-source voice AI platform for building and deploying conversational agents (telephony, WebRTC, text chat, workflow builder).

**Repository layout:** `api/` (backend), `ui/` (frontend), `pipecat/` (voice framework submodule), `sdk/` (Python + TypeScript SDKs), `infrastructure/` (AWS CDK — EC2 provisioning), `deploy/` (Helm/templates — not currently used), `scripts/` (setup & ops).

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
| Langfuse | LLM / agent tracing — conversation & turn-level traces (optional) |
| Structured logs | Loguru (API), Pino (UI) |

### Langfuse tracing

LLM-side observability for conversations and agent turns. Tracing is **per-org** and
**opt-in** (gated on configured credentials), so an instance runs without it until an org
supplies keys.

| Aspect | Detail |
|--------|--------|
| SDK | `langfuse` (Python, in `api/requirements.txt`) |
| Transport | OTLP spans posted to `${LANGFUSE_HOST}/api/public/otel/v1/traces` with HTTP Basic (`base64(public:secret)`) |
| Configuration | `LANGFUSE_HOST`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_PROJECT_ID` — all four set together or none (`api/constants.py`); per-org exporters preloaded at startup |
| Backend | Managed Langfuse Cloud **or** self-hosted Langfuse v3 (web + worker, with ClickHouse, Postgres, Redis/Valkey, and S3/MinIO blob storage) |
| What's traced | Per-run conversation traces, turn-level LLM activity, variable extraction, node transitions |

---

## Documentation

| Tool | Location |
|------|----------|
| Mintlify | `docs/` (guides, API reference, deployment docs) |
| OpenAPI | Backend exposes OpenAPI; drives UI client + SDK codegen |

---

## Deployment & operations

Deployment targets a **single EC2 host** running the Docker Compose stack, provisioned by an AWS CDK app. The Kubernetes/Helm assets under `deploy/` are **not currently used**.

### Infrastructure as code (`infrastructure/`)

| Category | Technology |
|----------|------------|
| IaC framework | AWS CDK v2 (`aws-cdk-lib` 2.272.0, `constructs` 10), TypeScript 5.6 |
| CDK CLI | `aws-cdk` 2.1143.0 |
| App entrypoint | `bin/spinsci-ec2.ts` → `SpinSciEc2Stack` (`lib/`: network, compute, storage, IAM, user-data constructs) |
| Provisions | VPC (public subnet, IGW, no NAT), security group (80/443/TURN only — no SSH), one EC2 instance (default `t3.large`, Ubuntu), Elastic IP, encrypted gp3 data volume (`RETAIN`) with daily DLM snapshots |
| Admin access | SSM Session Manager (no inbound SSH, no static keys) |
| Secrets | AWS Secrets Manager (one secret, fetched at container start via instance role by `scripts/fetch_secrets.sh`); box-internal secrets stay in `.env` on the data volume |
| Testing | Vitest 3 + fast-check (unit + property tests) |

### Runtime & delivery

| Target | Technology |
|--------|------------|
| Containers | Docker multi-stage images (`api/Dockerfile`, `ui/Dockerfile`) |
| Compose | Docker Compose (local, remote, tunnel profiles) |
| Deploy pipeline | GitHub Actions `deploy-ec2.yml` — ships releases to the host over AWS SSM Run Command (`update_remote.sh` + `remote_up.sh`), gated on image availability + health check |
| Registry | GHCR (`ghcr.io/spinsci-hq`) |
| TLS | Let's Encrypt (Certbot), self-signed, sslip.io / nip.io patterns |
| CI | GitHub Actions (API tests, Docker images, release, drift checks) |
| Kubernetes (unused) | Helm chart (`deploy/helm/spinsci/`) — scaffolded but not currently deployed |

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

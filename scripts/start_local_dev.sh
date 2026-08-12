#!/usr/bin/env bash
# Start host-managed local development: Docker infra + local API/UI with hot reload.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

COMPOSE=(docker compose -f docker-compose-local.yaml -f docker-compose.dev-host.yaml)

echo "→ Starting Docker infra (postgres, redis, minio)..."
"${COMPOSE[@]}" up -d postgres redis minio

echo "→ Pointing api/.env at Docker Postgres..."
bash scripts/update_dev_db_host.sh

echo "→ Starting backend (uvicorn + workers, hot reload)..."
source venv/bin/activate
bash scripts/start_services_dev.sh

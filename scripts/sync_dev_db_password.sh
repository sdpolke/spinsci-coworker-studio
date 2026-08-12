#!/usr/bin/env bash
# Sync Postgres password inside the Docker container to match repo root .env.
# Needed when the postgres volume was initialized with a different password
# than docker-compose-local.yaml's defaults.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ROOT_DIR}/.env"
COMPOSE_FILES=(-f "${ROOT_DIR}/docker-compose-local.yaml")
if [[ -f "${ROOT_DIR}/docker-compose.dev-host.yaml" ]]; then
  COMPOSE_FILES+=(-f "${ROOT_DIR}/docker-compose.dev-host.yaml")
fi

TARGET_PASSWORD="${1:-}"
if [[ -z "$TARGET_PASSWORD" && -f "$ENV_FILE" ]]; then
  # shellcheck disable=SC1090
  set -a && source "$ENV_FILE" && set +a
  TARGET_PASSWORD="${POSTGRES_PASSWORD:-postgres}"
elif [[ -z "$TARGET_PASSWORD" ]]; then
  TARGET_PASSWORD="postgres"
fi

echo "Syncing Postgres password in container..."
printf "ALTER USER postgres WITH PASSWORD '%s';\n" "$TARGET_PASSWORD" \
  | docker compose "${COMPOSE_FILES[@]}" exec -T postgres \
      psql -U postgres -d postgres -v ON_ERROR_STOP=1

echo "Postgres password synced."

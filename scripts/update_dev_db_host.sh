#!/usr/bin/env bash
# Point api/.env at the Docker Postgres container IP (host-managed dev).
# Needed on macOS when localhost:5432 is taken by a native Postgres install and
# Docker port forwards do not authenticate reliably from the host.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
API_ENV="${ROOT_DIR}/api/.env"
COMPOSE_FILES=(-f "${ROOT_DIR}/docker-compose-local.yaml")
if [[ -f "${ROOT_DIR}/docker-compose.dev-host.yaml" ]]; then
  COMPOSE_FILES+=(-f "${ROOT_DIR}/docker-compose.dev-host.yaml")
fi

CONTAINER_ID="$(docker compose "${COMPOSE_FILES[@]}" ps -q postgres)"
if [[ -z "$CONTAINER_ID" ]]; then
  echo "Postgres container is not running. Start infra first:" >&2
  echo "  docker compose -f docker-compose-local.yaml -f docker-compose.dev-host.yaml up -d" >&2
  exit 1
fi

POSTGRES_IP="$(docker inspect -f '{{range.NetworkSettings.Networks}}{{.IPAddress}}{{end}}' "$CONTAINER_ID")"
if [[ -z "$POSTGRES_IP" ]]; then
  echo "Could not resolve Postgres container IP." >&2
  exit 1
fi

if [[ ! -f "$API_ENV" ]]; then
  cp "${ROOT_DIR}/api/.env.example" "$API_ENV"
fi

python3 - "$API_ENV" "$POSTGRES_IP" <<'PY'
import pathlib, re, sys

path, ip = sys.argv[1], sys.argv[2]
text = pathlib.Path(path).read_text()
url = f'postgresql+asyncpg://postgres:postgres@{ip}:5432/postgres'
if re.search(r'^DATABASE_URL=.*$', text, flags=re.M):
    text = re.sub(r'^DATABASE_URL=.*$', f'DATABASE_URL="{url}"', text, flags=re.M)
else:
    text += f'\nDATABASE_URL="{url}"\n'
pathlib.Path(path).write_text(text)
print(f"Updated DATABASE_URL to use Docker Postgres at {ip}:5432")
PY

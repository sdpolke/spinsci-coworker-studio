#!/usr/bin/env bash
# Relax Postgres host auth for host-managed local dev (Docker port forwards).
# pg_hba.conf matches the first rule — the default scram rule must be overridden.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILES=(-f "${ROOT_DIR}/docker-compose-local.yaml")
if [[ -f "${ROOT_DIR}/docker-compose.dev-host.yaml" ]]; then
  COMPOSE_FILES+=(-f "${ROOT_DIR}/docker-compose.dev-host.yaml")
fi

docker compose "${COMPOSE_FILES[@]}" exec -T postgres sh -c '
  HBA=/var/lib/postgresql/data/pg_hba.conf
  if ! grep -q "# spinsci-dev-host-trust" "$HBA"; then
    sed -i.bak "s/^host all all all scram-sha-256$/# disabled for local dev: &/" "$HBA"
    sed -i.bak "1i# spinsci-dev-host-trust\nhost all all all trust\n" "$HBA"
  fi
'

docker compose "${COMPOSE_FILES[@]}" exec -T postgres \
  psql -U postgres -d postgres -c "SELECT pg_reload_conf();" >/dev/null

echo "Postgres dev host auth relaxed."

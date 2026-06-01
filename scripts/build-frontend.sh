#!/usr/bin/env bash
# Build quantdinger-frontend:local from startlink-web (slow — run separately from backend deploy).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

export FRONTEND_SRC_PATH="${FRONTEND_SRC_PATH:-/var/www/startlink-web}"
[[ -f .env ]] && set -a && source .env && set +a

if [[ ! -f "${FRONTEND_SRC_PATH}/Dockerfile" ]]; then
  echo "ERROR: no Dockerfile at FRONTEND_SRC_PATH=${FRONTEND_SRC_PATH}" >&2
  exit 1
fi

echo "==> building frontend from ${FRONTEND_SRC_PATH}"
docker compose -f docker-compose.yml -f docker-compose.frontend-build.yml build frontend

echo "==> restart frontend container (no backend rebuild)"
docker compose up -d --no-build frontend

echo "==> done: $(docker images --format '{{.Repository}}:{{.Tag}}' | grep quantdinger-frontend | head -1)"

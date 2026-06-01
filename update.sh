#!/usr/bin/env bash
# Update QuantDinger stack: pull git, rebuild backend from source, rebuild frontend
# from local startlink-web — does NOT pull ghcr.io/.../quantdinger-frontend.
#
# Usage (from repo root):
#   chmod +x update.sh && ./update.sh
#
# Frontend path (default: sibling ../startlink-web):
#   export FRONTEND_SRC_PATH=/path/to/startlink-web
# Or set in project-root .env: FRONTEND_SRC_PATH=../startlink-web

set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

export COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.yml:docker-compose.build.yml}"
export FRONTEND_SRC_PATH="${FRONTEND_SRC_PATH:-../startlink-web}"

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

if [[ ! -d "${FRONTEND_SRC_PATH}" ]]; then
  echo "ERROR: frontend source not found: ${FRONTEND_SRC_PATH}" >&2
  echo "Set FRONTEND_SRC_PATH to your startlink-web clone (e.g. ../startlink-web)." >&2
  exit 1
fi

echo "==> git pull"
git pull

echo "==> pull base images (postgres, redis only — not frontend)"
docker compose pull postgres redis

echo "==> build & up backend (local backend_api_python)"
docker compose build backend
docker compose up -d backend

echo "==> build & up frontend from ${FRONTEND_SRC_PATH} (no GHCR pull)"
docker compose build frontend
docker compose up -d frontend

echo "==> done"
docker compose ps

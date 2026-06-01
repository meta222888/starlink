#!/usr/bin/env bash
# Update stack: git pull + docker compose up -d --build (backend + local startlink-web).
set -euo pipefail
cd "$(dirname "$0")"
export FRONTEND_SRC_PATH="${FRONTEND_SRC_PATH:-../startlink-web}"
if [[ -f .env ]]; then set -a; source .env; set +a; fi
if [[ ! -d "${FRONTEND_SRC_PATH}" ]]; then
  echo "ERROR: FRONTEND_SRC_PATH not found: ${FRONTEND_SRC_PATH}" >&2
  exit 1
fi
git pull
docker compose up -d --build

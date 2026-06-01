#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
export FRONTEND_SRC_PATH="${FRONTEND_SRC_PATH:-/var/www/startlink-web}"
[[ -f .env ]] && set -a && source .env && set +a
[[ -d "${FRONTEND_SRC_PATH}" ]] || { echo "Missing ${FRONTEND_SRC_PATH}" >&2; exit 1; }
git pull origin main
docker compose up -d --build

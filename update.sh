#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
[ -f .env ] || { echo 'Run setup.sh first'; exit 1; }
[ -f compose.override.yaml ] || { echo 'Missing compose.override.yaml; restore the local deployment mode before updating.'; exit 1; }
bash backup.sh
services="$(docker compose config --services)"
docker compose pull sub-store
if printf '%s\n' "$services" | grep -qx caddy; then
  docker compose pull caddy
fi
docker compose up -d --build
printf 'Updated this Compose project only. Verify: docker compose ps\n'

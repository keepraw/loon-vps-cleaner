#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
[ -f .env ] || { echo 'Run setup.sh first'; exit 1; }
bash backup.sh
docker compose pull sub-store caddy
docker compose up -d --build
printf 'Updated containers. Verify: docker compose ps\n'

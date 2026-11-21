#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
umask 077
[ -f .env ] || { echo 'Missing .env'; exit 1; }
mkdir -p backups
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
archive="backups/loon-cleaner-$stamp.tar.gz"
echo 'Stopping Registry + Sub-Store briefly for consistent on-disk backup...'
docker compose stop registry sub-store
restore() { docker compose start sub-store registry >/dev/null 2>&1 || true; }
trap restore EXIT
tar --warning=no-file-changed -czf "$archive" .env data/registry data/sub-store
chmod 600 "$archive"
echo "Backup saved to: $archive (contains subscription credentials and keys)"

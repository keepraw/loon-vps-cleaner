#!/usr/bin/env bash
# Upgrade Registry application code in an existing archive installation.
# Do not touch .env, data/, Compose overrides, Caddy, or other projects.
set -euo pipefail
umask 077
REF=main
INSTALL_DIR=/opt/loon-vps-cleaner
while [ "$#" -gt 0 ]; do
  case "$1" in
    --ref) [ "$#" -ge 2 ] || { echo 'Missing --ref' >&2; exit 2; }; REF="$2"; shift 2 ;;
    --dir) [ "$#" -ge 2 ] || { echo 'Missing --dir' >&2; exit 2; }; INSTALL_DIR="$2"; shift 2 ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
done
[ "$(id -u)" -eq 0 ] || { echo 'Run as root' >&2; exit 1; }
if [ "$REF" != main ] && ! [[ "$REF" =~ ^[0-9a-f]{40}$ ]]; then
  echo 'Ref must be main or a full 40-character commit SHA' >&2
  exit 2
fi
[[ "$INSTALL_DIR" == /* && "$INSTALL_DIR" != / ]] || { echo 'Invalid --dir' >&2; exit 2; }
[ -f "$INSTALL_DIR/.env" ] || { echo 'Existing .env not found' >&2; exit 1; }
[ -f "$INSTALL_DIR/compose.override.yaml" ] || { echo 'Existing Compose override not found' >&2; exit 1; }
[ -f "$INSTALL_DIR/backup.sh" ] || { echo 'Existing backup.sh not found' >&2; exit 1; }
for bin in curl tar docker python3 mktemp; do
  command -v "$bin" >/dev/null 2>&1 || { echo "Missing: $bin" >&2; exit 1; }
done
docker compose version >/dev/null
cd "$INSTALL_DIR"
stage="$(mktemp -d)"
trap 'rm -rf -- "$stage"' EXIT
archive="$stage/source.tar.gz"
echo "Downloading reviewed code at $REF"
curl --proto '=https' --tlsv1.2 -fsSL --retry 3 --connect-timeout 15 --max-time 180 \
  "https://codeload.github.com/keepraw/loon-vps-cleaner/tar.gz/$REF" -o "$archive"
tar -tzf "$archive" >/dev/null
mkdir -p "$stage/source"
tar -xzf "$archive" -C "$stage/source" --strip-components=1
for file in registry/app.py registry/core.py registry/Dockerfile registry/requirements.txt registry/static/app.js registry/static/index.html upgrade.sh; do
  [ -f "$stage/source/$file" ] || { echo "Missing source: $file" >&2; exit 1; }
done
bash -n "$stage/source/upgrade.sh"
python3 -m py_compile "$stage/source/registry/app.py" "$stage/source/registry/core.py"
cp -a "$INSTALL_DIR/registry" "$stage/registry-before"
echo 'Backing up configuration, subscription data, database, and secrets...'
bash "$INSTALL_DIR/backup.sh"
echo 'Updating Registry only...'
cp -a "$stage/source/registry/." "$INSTALL_DIR/registry/"
cp "$stage/source/upgrade.sh" "$INSTALL_DIR/upgrade.sh"
chmod 700 "$INSTALL_DIR/upgrade.sh"
rollback() {
  echo 'Restoring previous Registry application code...' >&2
  cp -a "$stage/registry-before/." "$INSTALL_DIR/registry/"
  docker compose up -d --no-deps --build registry || true
}
if ! docker compose config --quiet || ! docker compose up -d --no-deps --build registry; then
  rollback
  exit 1
fi
ok=0
for i in $(seq 1 20); do
  if docker compose exec -T registry python -c 'import urllib.request; urllib.request.urlopen("http://127.0.0.1:8000/api/feeds", timeout=5).read()' >/dev/null 2>&1; then
    ok=1
    break
  fi
  sleep 1
done
if [ "$ok" -ne 1 ]; then
  echo 'Registry did not pass its API smoke test' >&2
  rollback
  exit 1
fi
echo "Registry upgraded to $REF; Caddy, Sub-Store, and other Compose projects unchanged."
docker compose ps

#!/usr/bin/env bash
# Bootstrap installation from the public source repository.
# Review this script and setup.sh before running as root.
set -euo pipefail
umask 077

REPO='keepraw/loon-vps-cleaner'
REF='main'
INSTALL_DIR='/opt/loon-vps-cleaner'

usage() {
  cat <<'HELP'
Usage: sudo bash install.sh [--ref main|40-character-commit-sha] [--dir /absolute/path]

Downloads the GitHub source archive, stages it locally, and runs setup.sh.
The destination must not exist; an existing deployment is never overwritten.
For an immutable audited install, use --ref <full commit SHA>.
HELP
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --ref)
      [ "$#" -ge 2 ] || { echo 'Missing --ref value' >&2; exit 2; }
      REF="$2"; shift 2 ;;
    --dir)
      [ "$#" -ge 2 ] || { echo 'Missing --dir value' >&2; exit 2; }
      INSTALL_DIR="$2"; shift 2 ;;
    --help|-h) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

if [ "$(id -u)" -ne 0 ]; then
  echo 'Run as root: sudo bash install.sh' >&2
  exit 1
fi
if [ "$REF" != 'main' ] && ! [[ "$REF" =~ ^[0-9a-f]{40}$ ]]; then
  echo 'Ref must be main or a full lowercase 40-character commit SHA.' >&2
  exit 2
fi
if [[ "$INSTALL_DIR" != /* || "$INSTALL_DIR" == '/' || "$INSTALL_DIR" == *$'\n'* ]]; then
  echo 'Installation directory must be an absolute, non-root path.' >&2
  exit 2
fi
if [ -e "$INSTALL_DIR" ] || [ -L "$INSTALL_DIR" ]; then
  echo "Refusing to overwrite existing directory: $INSTALL_DIR" >&2
  echo 'To update containers without replacing your configuration, use update.sh in the existing directory.' >&2
  exit 1
fi
for command in curl tar mktemp; do
  if ! command -v "$command" >/dev/null 2>&1; then
    echo "Missing required command: $command" >&2
    exit 1
  fi
done
if [ ! -r /etc/os-release ]; then
  echo 'Cannot determine Linux distribution' >&2
  exit 1
fi
# shellcheck disable=SC1091
. /etc/os-release
if [ "${ID:-}" != 'debian' ] || [ "${VERSION_ID:-}" != '12' ]; then
  echo 'This bootstrap installer is intended for Debian 12 only.' >&2
  exit 1
fi

stage="$(mktemp -d)"
trap 'rm -rf -- "$stage"' EXIT
archive="$stage/source.tar.gz"
url="https://codeload.github.com/$REPO/tar.gz/$REF"
printf 'Downloading %s at ref %s ...\n' "$REPO" "$REF"
curl --proto '=https' --tlsv1.2 -fsSL --retry 3 --connect-timeout 15 \
  --max-time 180 "$url" -o "$archive"
tar -tzf "$archive" >/dev/null
mkdir -m 0700 "$stage/source"
tar -xzf "$archive" -C "$stage/source" --strip-components=1
for file in setup.sh compose.yaml Caddyfile registry/app.py registry/Dockerfile; do
  if [ ! -f "$stage/source/$file" ]; then
    echo "Downloaded archive is missing $file" >&2
    exit 1
  fi
done
# Archives are extracted under umask 077. Normalize public source permissions
# before Docker COPY, otherwise files could be unreadable by the app's UID.
find "$stage/source" -type d -exec chmod 755 {} +
find "$stage/source" -type f -exec chmod 644 {} +
chmod 755 "$stage/source/install.sh" "$stage/source/setup.sh" \
  "$stage/source/update.sh" "$stage/source/backup.sh"
parent="$(dirname "$INSTALL_DIR")"
mkdir -p -- "$parent"
mv -- "$stage/source" "$INSTALL_DIR"
chmod 755 "$INSTALL_DIR"
printf '\nDownloaded source to: %s\n' "$INSTALL_DIR"
printf 'Source repository: https://github.com/%s\n' "$REPO"
printf 'Continuing with interactive Debian 12 setup...\n\n'
# Intentionally runs the downloaded, auditable local setup script.
exec bash "$INSTALL_DIR/setup.sh"

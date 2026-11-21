#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
umask 077

if [ "$(id -u)" -ne 0 ]; then
  printf 'Run as root: sudo bash setup.sh\n' >&2
  exit 1
fi
if [ -f .env ]; then
  printf 'Existing .env found. Refusing to replace secrets. Use: docker compose up -d --build\n'
  exit 1
fi

install_docker() {
  if dpkg-query -W -f='${Status}' docker.io 2>/dev/null | grep -q 'install ok installed'; then
    echo 'Existing Debian docker.io installation found. Review it manually; will not remove existing packages.' >&2
    exit 1
  fi
  if dpkg-query -W -f='${Status}' podman-docker 2>/dev/null | grep -q 'install ok installed'; then
    echo 'podman-docker installed. Review conflicting packages before continuing.' >&2
    exit 1
  fi
  . /etc/os-release
  if [ "${ID:-}" != "debian" ] || [ "${VERSION_ID:-}" != "12" ]; then
    echo 'Automated Docker installation is limited to Debian 12.' >&2
    exit 1
  fi
  apt-get update
  apt-get install -y ca-certificates curl python3
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
  docker_arch="$(dpkg --print-architecture)"
  cat > /etc/apt/sources.list.d/docker.sources <<DOCKER_SOURCES
Types: deb
URIs: https://download.docker.com/linux/debian
Suites: bookworm
Components: stable
Architectures: $docker_arch
Signed-By: /etc/apt/keyrings/docker.asc
DOCKER_SOURCES
  apt-get update
  apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
  systemctl enable --now docker
}

if ! command -v docker >/dev/null 2>&1; then
  read -r -p 'Docker missing. Install Docker Engine from official Debian repository? [y/N] ' consent
  if [ "${consent:-}" != "y" ] && [ "${consent:-}" != "Y" ]; then
    exit 1
  fi
  install_docker
fi
if ! docker compose version >/dev/null 2>&1; then
  echo 'Docker Compose plugin is missing. Install it from the official Docker repository, then re-run.' >&2
  exit 1
fi
if ! docker info >/dev/null 2>&1; then
  echo 'Docker service unavailable. Check: systemctl status docker' >&2
  exit 1
fi
if ! command -v python3 >/dev/null 2>&1; then
  apt-get update && apt-get install -y python3
fi

read -r -p 'Domain (e.g. sub.example.com): ' domain
if ! [[ "$domain" =~ ^[A-Za-z0-9][A-Za-z0-9.-]*\.[A-Za-z]{2,}$ ]]; then
  echo 'Invalid domain' >&2
  exit 1
fi
read -r -p 'Admin username [admin]: ' admin_name
admin_name="${admin_name:-admin}"
if ! [[ "$admin_name" =~ ^[a-zA-Z0-9_-]{3,40}$ ]]; then
  echo 'Admin username must use 3-40 letters, digits, underscores or hyphens.' >&2
  exit 1
fi
read -r -s -p 'Admin password (at least 16 characters): ' admin_password
printf '\n'
if [ "${#admin_password}" -lt 16 ]; then
  echo 'Password too short' >&2
  exit 1
fi
read -r -s -p 'Confirm admin password: ' admin_confirm
printf '\n'
if [ "$admin_password" != "$admin_confirm" ]; then
  echo 'Passwords differ' >&2
  exit 1
fi
hash="$(printf '%s\n' "$admin_password" | docker run --rm -i caddy:2 caddy hash-password --algorithm bcrypt)"
unset admin_password admin_confirm
if [ -z "$hash" ]; then
  echo 'Could not hash admin password' >&2
  exit 1
fi
secret_path="/$(python3 -c 'import secrets;print(secrets.token_urlsafe(32))')"
fernet="$(python3 -c 'import os,base64;print(base64.urlsafe_b64encode(os.urandom(32)).decode())')"
fingerprint="$(python3 -c 'import secrets;print(secrets.token_hex(32))')"
hk="$(python3 -c 'import secrets;print(secrets.token_urlsafe(36))')"
us="$(python3 -c 'import secrets;print(secrets.token_urlsafe(36))')"
jp="$(python3 -c 'import secrets;print(secrets.token_urlsafe(36))')"
over="$(python3 -c 'import secrets;print(secrets.token_urlsafe(36))')"
cat > .env <<ENV
DOMAIN=$domain
PUBLIC_BASE_URL=https://$domain
ADMIN_USER=$admin_name
ADMIN_HASH='$hash'
SUBSTORE_SECRET_PATH=$secret_path
SUBSTORE_IMAGE=xream/sub-store:latest
SNAPSHOT_KEY=$fernet
FINGERPRINT_KEY=$fingerprint
FEED_TOKEN_HK=$hk
FEED_TOKEN_US=$us
FEED_TOKEN_JP=$jp
FEED_TOKEN_OVERSEAS=$over
TZ=Asia/Shanghai
ENV
chmod 600 .env
mkdir -p data/registry data/sub-store backups
chmod 700 data/registry data/sub-store backups
chown 10001:10001 data/registry

# Caddy needs ports 80 and 443. Stop rather than interrupt existing services.
if command -v ss >/dev/null 2>&1; then
  if ss -ltnH '( sport = :80 or sport = :443 )' | grep -q .; then
    echo 'WARNING: HTTP/HTTPS ports appear occupied. Integrate with existing reverse proxy before starting.' >&2
    echo 'Secrets saved in .env. No containers started.' >&2
    exit 1
  fi
fi

docker compose config --quiet
docker compose up -d --build
printf '\nDeployed. Open https://%s/manager/ (DNS A record must point here).\n' "$domain"
printf 'Check status: docker compose ps\n'
printf 'View logs: docker compose logs --tail=80 registry sub-store caddy\n'

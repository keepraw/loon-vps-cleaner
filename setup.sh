#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
umask 077

INSTALL_DIR="$(pwd)"
ENV_FILE="$INSTALL_DIR/.env"
OVERRIDE_FILE="$INSTALL_DIR/compose.override.yaml"

say() { printf '\n==> %s\n' "$*"; }
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
package_installed() {
  command -v dpkg-query >/dev/null 2>&1 && \
    dpkg-query -W -f='${Status}' "$1" 2>/dev/null | grep -q 'install ok installed'
}

[ "$(id -u)" -eq 0 ] || die 'Run as root: sudo bash setup.sh'
[ ! -e "$ENV_FILE" ] || die 'Existing .env found. Refusing to replace secrets or data. Use update.sh for an existing installation.'
[ ! -e "$OVERRIDE_FILE" ] || die 'compose.override.yaml already exists. Review it and remove it only if this is a fresh, unconfigured installation.'
[ -r /etc/os-release ] || die 'Cannot identify Linux distribution: /etc/os-release is missing.'
# shellcheck disable=SC1091
. /etc/os-release
DISTRO_ID="${ID:-unknown}"
DISTRO_VERSION="${VERSION_ID:-unknown}"
DISTRO_CODENAME="${VERSION_CODENAME:-${UBUNTU_CODENAME:-}}"

install_docker_engine() {
  case "$DISTRO_ID" in
    debian|ubuntu) ;;
    *) die "Docker is missing. Automatic installation supports Debian/Ubuntu only; install Docker Engine + Compose V2 for $DISTRO_ID manually, then rerun setup.sh. Existing Docker installations are never replaced." ;;
  esac
  command -v apt-get >/dev/null 2>&1 || die 'apt-get is unavailable; install Docker Engine + Compose V2 manually.'
  [ -n "$DISTRO_CODENAME" ] || die "Cannot determine $DISTRO_ID release codename; refusing to guess a Docker APT suite."
  for pkg in docker.io docker-ce docker-ce-cli podman podman-docker moby-engine moby-cli containerd containerd.io runc docker-doc docker-compose; do
    if package_installed "$pkg"; then
      die "Package $pkg is already installed but the Docker CLI is missing. I will not replace or remove an existing container runtime. Repair that installation manually, then rerun."
    fi
  done
  say "Installing Docker Engine from Docker's official $DISTRO_ID repository ($DISTRO_CODENAME)"
  apt-get update
  apt-get install -y ca-certificates curl python3
  install -m 0755 -d /etc/apt/keyrings
  if [ ! -s /etc/apt/keyrings/docker-loon-vps-cleaner.asc ]; then
    curl -fsSL https://download.docker.com/linux/"$DISTRO_ID"/gpg \
      -o /etc/apt/keyrings/docker-loon-vps-cleaner.asc.tmp
    install -m 0644 /etc/apt/keyrings/docker-loon-vps-cleaner.asc.tmp \
      /etc/apt/keyrings/docker-loon-vps-cleaner.asc
    rm -f /etc/apt/keyrings/docker-loon-vps-cleaner.asc.tmp
  fi
  arch="$(dpkg --print-architecture)"
  source_file="/etc/apt/sources.list.d/docker-loon-vps-cleaner.sources"
  if [ ! -f "$source_file" ]; then
    cat > "$source_file" <<DOCKER_SOURCES
Types: deb
URIs: https://download.docker.com/linux/$DISTRO_ID
Suites: $DISTRO_CODENAME
Components: stable
Architectures: $arch
Signed-By: /etc/apt/keyrings/docker-loon-vps-cleaner.asc
DOCKER_SOURCES
  fi
  apt-get update
  apt-cache policy docker-ce | grep -q 'Candidate: (none)' && \
    die "Docker does not publish a package for $DISTRO_ID/$DISTRO_CODENAME/$arch through the configured repository. Install a supported Docker Engine manually."
  apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
  systemctl enable --now docker
}

if ! command -v docker >/dev/null 2>&1; then
  say "Docker CLI is not installed ($DISTRO_ID $DISTRO_VERSION)."
  printf 'The installer can add Docker official APT packages on Debian/Ubuntu. It will not remove existing container runtimes.\n'
  read -r -p 'Install Docker Engine + Compose V2 now? [y/N] ' consent
  [[ "${consent:-}" =~ ^[Yy]$ ]] || die 'Install Docker manually, then rerun setup.sh.'
  install_docker_engine
fi

if ! docker compose version >/dev/null 2>&1; then
  say 'Docker Compose V2 plugin is missing.'
  if command -v apt-get >/dev/null 2>&1; then
    compose_pkg=''
    if apt-cache show docker-compose-plugin >/dev/null 2>&1; then
      compose_pkg='docker-compose-plugin'
    elif apt-cache show docker-compose-v2 >/dev/null 2>&1; then
      compose_pkg='docker-compose-v2'
    fi
    if [ -n "$compose_pkg" ]; then
      read -r -p "Install only the $compose_pkg package (without replacing Docker Engine)? [y/N] " consent
      if [[ "${consent:-}" =~ ^[Yy]$ ]]; then
        apt-get install -y "$compose_pkg"
      fi
    fi
  fi
fi
docker compose version >/dev/null 2>&1 || die 'Docker Compose V2 is required. Install the Compose plugin matching your existing Docker Engine, then rerun setup.sh.'
if ! docker info >/dev/null 2>&1; then
  if command -v systemctl >/dev/null 2>&1 && systemctl list-unit-files docker.service >/dev/null 2>&1; then
    read -r -p 'Docker daemon is not responding. Try starting the existing docker.service? [y/N] ' consent
    if [[ "${consent:-}" =~ ^[Yy]$ ]]; then
      systemctl start docker
    fi
  fi
fi
docker info >/dev/null 2>&1 || die 'Docker daemon is unavailable. Check your existing Docker service/context; no containers or packages were changed.'
if ! command -v python3 >/dev/null 2>&1; then
  if command -v apt-get >/dev/null 2>&1; then
    apt-get update && apt-get install -y python3
  else
    die 'Python 3 is required for generating secrets. Install python3 and rerun.'
  fi
fi

port_listening() {
  local port="$1"
  if command -v ss >/dev/null 2>&1; then
    ss -H -ltn "( sport = :$port )" 2>/dev/null | grep -q .
  else
    python3 - "$port" <<'PY'
import errno, socket, sys
port = int(sys.argv[1])
for family, address in ((socket.AF_INET, ("0.0.0.0", port)), (socket.AF_INET6, ("::", port, 0, 0))):
    try:
        sock = socket.socket(family, socket.SOCK_STREAM)
        try:
            if family == socket.AF_INET6:
                sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
            sock.bind(address)
        finally:
            sock.close()
    except OSError as exc:
        if family == socket.AF_INET6 and exc.errno in (errno.EAFNOSUPPORT, errno.EADDRNOTAVAIL):
            continue
        sys.exit(0)
sys.exit(1)
PY
  fi
}

find_free_port() {
  local port
  for port in $(seq 18765 18865); do
    if ! port_listening "$port"; then
      printf '%s' "$port"
      return 0
    fi
  done
  return 1
}

ports_busy=0
if port_listening 80 || port_listening 443; then ports_busy=1; fi
if [ "$ports_busy" -eq 1 ]; then default_mode=2; else default_mode=1; fi
say "Host detected: $PRETTY_NAME (${DISTRO_ID} ${DISTRO_VERSION}), Docker $(docker --version | awk '{print $3}' | tr -d ',')"
if [ "$ports_busy" -eq 1 ]; then
  echo 'TCP 80 and/or 443 is already in use. The installer will not stop or replace that service.'
else
  echo 'TCP 80/443 appear free. Standalone Caddy is available, but you may use an existing reverse proxy instead.'
fi
cat <<'MODES'
Choose the ingress mode:
  1) standalone   - this project runs its own Caddy on public ports 80/443
  2) host-proxy   - existing host Nginx/Caddy proxies to a localhost-only port
  3) docker-proxy - existing Dockerized Nginx/Caddy shares an external Docker network
MODES
read -r -p "Deployment mode [${default_mode}]: " mode_choice
mode_choice="${mode_choice:-$default_mode}"
case "$mode_choice" in
  1) mode='standalone'; proxy_type='caddy';;
  2) mode='host-proxy';;
  3) mode='docker-proxy';;
  *) die 'Invalid deployment mode.';;
esac

if [ "$mode" = 'standalone' ] && [ "$ports_busy" -eq 1 ]; then
  die 'Cannot use standalone mode because 80/443 are occupied. Rerun and choose host-proxy or docker-proxy.'
fi

if [ "$mode" != 'standalone' ]; then
  echo 'Existing reverse proxy type:'
  echo '  1) Caddy'
  echo '  2) Nginx'
  read -r -p 'Proxy type [1]: ' proxy_choice
  case "${proxy_choice:-1}" in
    1) proxy_type='caddy';;
    2) proxy_type='nginx';;
    *) die 'Invalid reverse proxy type. Currently supported: Caddy and Nginx.';;
  esac
fi

proxy_network=''
registry_port=''
if [ "$mode" = 'host-proxy' ]; then
  registry_port="$(find_free_port)" || die 'No free localhost port found in 18765-18865.'
elif [ "$mode" = 'docker-proxy' ]; then
  read -r -p 'Existing external Docker network name (e.g. proxy): ' proxy_network
  [[ "$proxy_network" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]*$ ]] || die 'Invalid Docker network name.'
  docker network inspect "$proxy_network" >/dev/null 2>&1 || die "Docker network '$proxy_network' does not exist. Create it first and attach your reverse-proxy container; no files were changed."
fi

read -r -p 'Domain (e.g. cleaner.example.com): ' domain
[[ "$domain" =~ ^[A-Za-z0-9][A-Za-z0-9.-]*\.[A-Za-z]{2,}$ ]] || die 'Invalid domain.'
read -r -p 'Docker Compose project name [loon-vps-cleaner]: ' project_name
project_name="${project_name:-loon-vps-cleaner}"
[[ "$project_name" =~ ^[a-z0-9][a-z0-9_-]*$ ]] || die 'Project name must use lowercase letters, digits, underscores or hyphens.'
read -r -p 'Admin username [admin]: ' admin_name
admin_name="${admin_name:-admin}"
[[ "$admin_name" =~ ^[a-zA-Z0-9_-]{3,40}$ ]] || die 'Admin username must use 3-40 letters, digits, underscores or hyphens.'
read -r -s -p 'Admin password (at least 10 characters): ' admin_password
printf '\n'
[ "${#admin_password}" -ge 10 ] || die 'Password too short; use at least 10 characters.'
read -r -s -p 'Confirm admin password: ' admin_confirm
printf '\n'
[ "$admin_password" = "$admin_confirm" ] || die 'Passwords differ.'

admin_hash=''
nginx_hash=''
if [ "$proxy_type" = 'caddy' ]; then
  admin_hash="$(printf '%s\n' "$admin_password" | docker run --rm -i caddy:2 caddy hash-password --algorithm bcrypt)"
  [ -n "$admin_hash" ] || die 'Could not generate Caddy bcrypt password hash.'
else
  if ! command -v openssl >/dev/null 2>&1; then
    if command -v apt-get >/dev/null 2>&1; then apt-get update && apt-get install -y openssl; else die 'OpenSSL is required to generate the Nginx password file. Install openssl and rerun.'; fi
  fi
  nginx_hash="$(printf '%s\n' "$admin_password" | openssl passwd -6 -stdin)"
  [ -n "$nginx_hash" ] || die 'Could not generate Nginx password hash.'
fi
unset admin_password admin_confirm

secret_path="/$(python3 -c 'import secrets;print(secrets.token_urlsafe(32))')"
fernet="$(python3 -c 'import os,base64;print(base64.urlsafe_b64encode(os.urandom(32)).decode())')"
fingerprint="$(python3 -c 'import secrets;print(secrets.token_hex(32))')"
hk="$(python3 -c 'import secrets;print(secrets.token_urlsafe(36))')"
us="$(python3 -c 'import secrets;print(secrets.token_urlsafe(36))')"
jp="$(python3 -c 'import secrets;print(secrets.token_urlsafe(36))')"
over="$(python3 -c 'import secrets;print(secrets.token_urlsafe(36))')"

# All compatibility, ingress, and input checks have passed. Only now create secrets/config.
cat > "$ENV_FILE" <<ENV
DOMAIN=$domain
PUBLIC_BASE_URL=https://$domain
ADMIN_USER=$admin_name
ADMIN_HASH='$admin_hash'
SUBSTORE_SECRET_PATH=$secret_path
SUBSTORE_IMAGE=xream/sub-store:latest
SNAPSHOT_KEY=$fernet
FINGERPRINT_KEY=$fingerprint
FEED_TOKEN_HK=$hk
FEED_TOKEN_US=$us
FEED_TOKEN_JP=$jp
FEED_TOKEN_OVERSEAS=$over
TZ=Asia/Shanghai
COMPOSE_PROJECT_NAME=$project_name
DEPLOYMENT_MODE=$mode
PROXY_TYPE=$proxy_type
PROXY_DOCKER_NETWORK=$proxy_network
REGISTRY_HOST_PORT=$registry_port
ENV
chmod 600 "$ENV_FILE"
mkdir -p data/registry data/sub-store backups proxy-snippets caddy-sites
chmod 700 data/registry data/sub-store backups
chmod 755 caddy-sites
chown 10001:10001 data/registry

case "$mode" in
  standalone) cp deploy/compose.standalone.yaml "$OVERRIDE_FILE" ;;
  host-proxy) cp deploy/compose.host-proxy.yaml "$OVERRIDE_FILE" ;;
  docker-proxy) cp deploy/compose.docker-proxy.yaml "$OVERRIDE_FILE" ;;
esac
chmod 600 "$OVERRIDE_FILE"

if [ "$mode" != 'standalone' ]; then
  if [ "$proxy_type" = 'caddy' ]; then
    if [ "$mode" = 'host-proxy' ]; then template='proxy-snippets/caddy-host.caddy.example'; else template='proxy-snippets/caddy-docker.caddy.example'; fi
    python3 - "$template" proxy-snippets/loon-cleaner.caddy "$domain" "$registry_port" "$admin_name" "$admin_hash" <<'PY'
from pathlib import Path
import sys
src, dst, domain, port, user, hashed = sys.argv[1:]
text = Path(src).read_text(encoding="utf-8")
for old, new in {"__DOMAIN__": domain, "__PORT__": port, "__ADMIN_USER__": user, "__ADMIN_HASH__": hashed}.items():
    text = text.replace(old, new)
Path(dst).write_text(text, encoding="utf-8")
PY
    chmod 600 proxy-snippets/loon-cleaner.caddy
  else
    if [ "$mode" = 'host-proxy' ]; then
      template='proxy-snippets/nginx-host.locations.example'
      upstream_port="$registry_port"
      htpasswd_path="$INSTALL_DIR/proxy-snippets/nginx.htpasswd"
    else
      template='proxy-snippets/nginx-docker.locations.example'
      upstream_port=''
      htpasswd_path='/etc/nginx/auth/loon-vps-cleaner.htpasswd'
    fi
    printf '%s:%s\n' "$admin_name" "$nginx_hash" > proxy-snippets/nginx.htpasswd
    if [ "$mode" = 'host-proxy' ] && command -v getent >/dev/null 2>&1; then
      if getent group www-data >/dev/null 2>&1; then
        chgrp www-data proxy-snippets/nginx.htpasswd
        chmod 640 proxy-snippets/nginx.htpasswd
      elif getent group nginx >/dev/null 2>&1; then
        chgrp nginx proxy-snippets/nginx.htpasswd
        chmod 640 proxy-snippets/nginx.htpasswd
      else
        chmod 644 proxy-snippets/nginx.htpasswd
        echo 'WARNING: no common Nginx group found; htpasswd file is readable by local users. Restrict its group/permissions for your Nginx worker.' >&2
      fi
    else
      # Dockerized Nginx needs to read the bind-mounted file under its own UID.
      chmod 644 proxy-snippets/nginx.htpasswd
    fi
    python3 - "$template" proxy-snippets/loon-cleaner.nginx.conf "$domain" "$upstream_port" "$htpasswd_path" <<'PY'
from pathlib import Path
import sys
src, dst, domain, port, htpasswd = sys.argv[1:]
text = Path(src).read_text(encoding="utf-8")
upstream = f"127.0.0.1:{port}" if port else "loon-vps-cleaner-registry:8000"
for old, new in {"__DOMAIN__": domain, "__PORT__": port, "__HTPASSWD_PATH__": htpasswd}.items():
    text = text.replace(old, new)
text = text.replace(f"http://127.0.0.1:{port}", f"http://{upstream}")
Path(dst).write_text(text, encoding="utf-8")
PY
    chmod 644 proxy-snippets/loon-cleaner.nginx.conf
  fi
fi

docker compose config --quiet
docker compose up -d --build

say 'Loon VPS Cleaner containers started'
docker compose ps
printf '\nManagement URL: https://%s/manager/\n' "$domain"
printf 'Compose project: %s\n' "$project_name"
printf 'Deployment mode: %s (%s)\n' "$mode" "$proxy_type"
if [ "$mode" = 'standalone' ]; then
  printf 'Caddy in this project owns TCP 80/443. Ensure DNS points to this VPS and those ports are reachable.\n'
elif [ "$mode" = 'host-proxy' ]; then
  printf '\nRegistry is bound to 127.0.0.1:%s only. Integrate this generated file into your existing %s config:\n  %s/proxy-snippets/loon-cleaner.%s\n' "$registry_port" "$proxy_type" "$INSTALL_DIR" "$([ "$proxy_type" = 'caddy' ] && echo caddy || echo nginx.conf)"
  if [ "$proxy_type" = 'caddy' ]; then
    printf 'Add/import the site block, then validate and reload your existing Caddy service.\n'
  else
    printf 'Include the locations file inside the TLS server block for %s, then nginx -t && reload Nginx.\n' "$domain"
  fi
else
  printf '\nRegistry is reachable on external Docker network %s as loon-vps-cleaner-registry:8000.\n' "$proxy_network"
  printf 'Attach your existing %s container to that same network and integrate:\n  %s/proxy-snippets/loon-cleaner.%s\n' "$proxy_type" "$INSTALL_DIR" "$([ "$proxy_type" = 'caddy' ] && echo caddy || echo nginx.conf)"
  if [ "$proxy_type" = 'nginx' ]; then
    printf 'Mount %s/proxy-snippets/nginx.htpasswd read-only in the Nginx container at /etc/nginx/auth/loon-vps-cleaner.htpasswd.\n' "$INSTALL_DIR"
  fi
fi
printf '\nLogs: docker compose logs --tail=80 registry sub-store\n'

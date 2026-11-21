# Loon VPS Cleaner

**[中文完整使用指南](README.zh-CN.md)**

Self-hosted multi-provider subscription cleaner for Loon. Sub-Store handles provider fetching, parsing and native Loon serialization. FastAPI + SQLite keeps durable node identities, manual exclusions, region overrides and published feeds. The VPS does **not** forward everyday proxy traffic.

Features: multiple providers, daily refresh at 05:00 Asia/Shanghai, persistent exclusions across node renames, regex filters, batch keep/exclude/restore, manual display-name and region overrides, and four token-protected Loon feeds. No latency tests, sorting by speed or automatic node selection.

## Four feeds

| Feed | Meaning |
| --- | --- |
| `hk` | Accepted Hong Kong nodes |
| `us` | Accepted United States nodes |
| `jp` | Accepted Japan nodes |
| `overseas` | **All accepted nodes**, including HK/US/JP and every other region |

Overseas is an aggregate, not a mutually exclusive fourth region. A node appearing in a regional feed and Overseas is intentional.

## Supported deployment environments

- Recommended: Debian 12/13 and Ubuntu 22.04/24.04 or later releases supported by Docker's official repository.
- Any Linux distribution with a working rootful Docker Engine and Docker Compose V2 can use the project; an existing Docker installation is reused without replacement.
- If Docker is absent, automated Docker installation is offered only on Debian/Ubuntu. Other distributions should install Docker Engine + Compose V2 manually first.

## Multi-site ingress modes

At setup choose one mode:

1. **Standalone** — project-owned Caddy binds public TCP 80/443. Use only when those ports are free.

In Standalone mode, this Caddy can also become the VPS's **shared multi-site ingress**. The installer creates a local `caddy-sites/` directory, mounts it read-only at `/etc/caddy/sites`, and the main Caddyfile imports every `*.caddy` file there. Each website gets its own file; you do not need to edit the project's main Caddyfile.

The Caddy container maps `host.docker.internal` to the Docker host gateway. This allows a site file to reverse-proxy to an existing host-published port without changing that application's Compose project. For example, to route an existing BiliTool published on host port 3000:

```bash
cp caddy-sites/bilitool.example.caddy.example caddy-sites/bilitool.example.caddy
# Edit the domain in the new file and point its DNS to this VPS.
docker compose exec caddy caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
docker compose exec caddy caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile
```

Local `caddy-sites/*.caddy` files are git-ignored and included in backups. For an app without a host-published port, attach Caddy and that app to the same external Docker network and proxy to its service name instead.
2. **Host Proxy** — existing host Nginx/Caddy proxies to a localhost-only Registry port. No second proxy is started and no existing config is edited.
3. **Docker Proxy** — Registry joins an existing external Docker network with alias `loon-vps-cleaner-registry`; the existing proxy container must join that network too. No host port is published.

Use a dedicated subdomain such as `cleaner.example.com`. Each application has its own Compose project name, network and data directory. The installer never runs global Docker cleanup commands, modifies other projects, or automatically reloads an existing reverse proxy.

## Install

Point a dedicated DNS name at the VPS. Standalone needs public TCP 80/443; Host Proxy and Docker Proxy use the existing proxy's TLS ingress.

```bash
curl -fsSLo loon-cleaner-install.sh https://raw.githubusercontent.com/keepraw/loon-vps-cleaner/main/install.sh
less loon-cleaner-install.sh
sudo bash loon-cleaner-install.sh
```

For a reviewed immutable release:

```bash
sudo bash loon-cleaner-install.sh --ref <full-40-character-commit-sha>
```

The bootstrap downloads source into `/opt/loon-vps-cleaner` and runs interactive `setup.sh`. Existing destination directories are never overwritten. Use `--dir /absolute/path` to choose another new directory.

Setup detects the OS, Docker CLI, Compose V2 and daemon. It reuses an existing Docker Engine. If Docker is missing, it offers official Docker APT installation on Debian/Ubuntu only. It checks ingress ports before generating secrets; Standalone is blocked when 80/443 are occupied. It then writes a local `compose.override.yaml`, `.env` (mode 600), data directories and reverse-proxy snippets before starting only this Compose project.

## Use

Open `https://YOUR_DOMAIN/manager/`, add one or more HTTPS provider subscription URLs, refresh, and use the Nodes page to exclude unwanted nodes, add regex filters, restore nodes, rename them or override regions. The service refreshes providers daily at 05:00 Asia/Shanghai. A failed provider refresh keeps its last successful snapshot.

Copy the four private feed URLs from the manager into Loon. The admin UI uses HTTP Basic Auth; each feed has a separate long random token. Sub-Store's API is private to the Docker network.

## Maintenance

From the installation directory:

```bash
docker compose ps
docker compose logs --tail=100 registry sub-store
docker compose config --quiet
sudo bash backup.sh
sudo bash update.sh
```

`update.sh` updates the Sub-Store image and rebuilds the Registry from the **locally installed source**. It does not overwrite `.env` or automatically pull new GitHub source code. Audit source changes and back up before deploying application-code updates.

## Security and limitations

Never commit `.env`, `data/`, `backups/`, generated `compose.override.yaml`, generated `proxy-snippets/loon-cleaner.*`, or local `caddy-sites/*.caddy` files. They contain tokens, credentials or deployment details. Feed URLs are bearer tokens. Reverse-proxy snippets are generated for review and must be manually integrated/reloaded. Host Proxy Caddy snippets can be imported at the top level of the existing Caddyfile; Nginx snippets belong inside the dedicated TLS server block. Docker Proxy requires the existing proxy container to join the selected external network; Docker Nginx also needs the generated htpasswd file mounted read-only. Automated tests use a mocked Sub-Store API; verify your live provider protocols and iOS Loon import before replacing an existing Loon profile.

See [README.zh-CN.md](README.zh-CN.md) for detailed setup modes, reverse-proxy integration, maintenance and troubleshooting.

# Loon VPS Cleaner

**[中文完整使用指南](README.zh-CN.md)**

Self-hosted multi-provider subscription cleaner for Loon. Sub-Store handles provider fetching, parsing and native Loon serialization. FastAPI + SQLite keeps durable node identities, manual exclusions, region overrides and published feeds. The VPS does **not** forward everyday proxy traffic.

Features: multiple providers, daily refresh at 05:00 Asia/Shanghai, persistent exclusions across node renames, regex filters, batch keep/exclude/restore, manual display-name and region overrides, and one token-protected Loon feed with four manual groups. No latency tests, sorting by speed or automatic node selection.

## One subscription, four manual groups

The manager exposes **one unified Loon subscription URL**. Add it once under `[Remote Proxy]`; you do not need to copy four URLs.

| Loon group | Nodes |
| --- | --- |
| Hong Kong | VPS-prefixed `HK - ` nodes |
| United States | VPS-prefixed `US - ` nodes |
| Japan | VPS-prefixed `JP - ` nodes |
| Overseas | All accepted nodes, including every region |

Loon needs three tiny local `[Remote Filter]` (NameRegex) entries to split one subscription into regional groups. Region recognition remains server-side: the VPS adds stable prefixes before publishing. Loon only matches those prefixes; it does not need to understand the airport's original naming scheme. No speed tests, latency sorting or automatic switching are used.

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

## Usage tutorial

### 1. Sign in

Open https://YOUR_DOMAIN/manager/ and sign in with the admin username and password created during setup. The browser uses HTTP Basic Auth. Treat provider URLs and the generated Loon feed URL as secrets.

### 2. Add multiple providers

In **Airports**, add each provider separately:

1. Enter a recognizable name, e.g. Airport A.
2. Paste its public HTTPS subscription URL.
3. Optionally set a User-Agent if the provider requires one. Leave it blank to use clash.meta/v1.19.23.
4. Click **Add & refresh**.

Repeat for as many providers as needed. Edit a provider entry to change its name or URL. Only public HTTPS URLs are accepted.

### 3. Refresh providers

A newly added provider is refreshed immediately. Use **Refresh all airports** for all providers or **Refresh one** for a single provider. Scheduled refresh runs daily at 05:00 Asia/Shanghai. If a provider fetch fails, its last successful snapshot is retained.

### 4. Clean nodes

The Nodes section shows 40 entries per page. Use search, provider and decision filters.

- **Exclude**: excludes this node record for this provider.
- **Keep**: manually keeps the node and overrides regex rules.
- **Edit display name**: changes its published label, not its connection settings.
- **Region selector**: override automatic classification as HK, US, JP or Overseas.
- **Global Exclude**: excludes the same fingerprint across providers.
- **Global Restore**: removes that global exclusion.

Use **Restore Auto** to clear a manual decision. Select checkboxes and use the batch actions for multiple nodes.

### 5. Add persistent regex rules

Add a case-insensitive regular expression against upstream node names. Scope it to one provider or all providers. Example: (?i)(expire|traffic|0[.]1x). Manual Keep overrides regex rules; global exclusion, manual exclusion and review status still prevent publication.

Start with narrow patterns and inspect the result before broadening them.

### 6. Add one subscription to Loon

The manager exposes one **Unified subscription (all nodes)** URL. Click **Copy subscription** once.

Merge the following entries into the corresponding sections of your existing Loon profile; do not duplicate section headers if they already exist.

~~~ini
[Remote Proxy]
VPS = https://YOUR_DOMAIN/loon/all/YOUR_TOKEN,enabled=true,parser-enabled=false

[Remote Filter]
VPS-HK = NameRegex,VPS,FilterKey = "^HK - "
VPS-US = NameRegex,VPS,FilterKey = "^US - "
VPS-JP = NameRegex,VPS,FilterKey = "^JP - "

[Proxy Group]
Hong Kong = select,VPS-HK
United States = select,VPS-US
Japan = select,VPS-JP
Overseas = select,VPS
~~~

Replace the URL with the exact URL copied from the manager. Save the profile and update the VPS subscription in Loon.

The VPS prefixes node names with HK - , US - , JP - or OTHER - . The three Remote Filters split the single subscription into regional groups. Overseas intentionally contains every accepted node, including HK/US/JP. These are manual select groups; there is no latency test or automatic switching.

See loon-four-groups.example.conf for the Chinese group-name version.

### 7. Troubleshooting

- A node is missing from a regional group: correct its region in the manager, publish, then refresh the Loon subscription.
- A node appears in Overseas as well: this is intentional; Overseas is the aggregate group.
- A node is marked for review: its endpoint/credentials may have changed and need manual confirmation.
- The manager still shows four separate feed URLs: the server is running an older Registry version. Upgrade it using the instructions below, then hard-refresh the browser.

## Upgrade an existing deployment

The bootstrap downloads a source archive, not a Git checkout. The old `update.sh` does not fetch GitHub changes. Download and audit the new updater, then pin the reviewed commit SHA:

```bash
curl -fsSLo /tmp/loon-cleaner-upgrade.sh https://raw.githubusercontent.com/keepraw/loon-vps-cleaner/main/upgrade.sh
less /tmp/loon-cleaner-upgrade.sh
sudo bash /tmp/loon-cleaner-upgrade.sh --ref <40-character-commit-SHA>
```

The updater backs up settings/data first, then changes only Registry application code and rebuilds only its container. It preserves `.env`, SQLite, Caddy, Sub-Store and unrelated Compose projects, and attempts code rollback on failure.

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

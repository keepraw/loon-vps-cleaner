# Loon VPS Cleaner

**[中文使用指南](README.zh-CN.md) · [English details](#components)**

自托管多机场订阅清洗工具：Debian 12 上使用 Sub-Store 解析和转换订阅，SQLite 记录你手工排除的节点，每天北京时间 05:00 更新，生成香港、美国、日本和海外四个供 Loon 手动选择的订阅出口。VPS 不转发你的代理流量。

### Debian 12 安装（先审查，再运行）

```bash
curl -fsSLo loon-cleaner-install.sh https://raw.githubusercontent.com/keepraw/loon-vps-cleaner/main/install.sh
less loon-cleaner-install.sh
sudo bash loon-cleaner-install.sh
```

安装时需要有域名指向 VPS，且 TCP 80/443 可用。安装器将交互式检查/安装 Docker、配置域名和管理员账号，数据保存在 VPS，不会进入 GitHub。安装后访问 `https://你的域名/manager/`，添加多个机场的 HTTPS 订阅，按“刷新”获取节点，在页面批量排除或重命名节点，再复制四个私有订阅地址到 Loon。

具体操作、更新与故障排查见 **[中文完整指南](README.zh-CN.md)**。

---

## Technical reference (English)

A working self-hosted starter implementation of a multi-airport subscription cleaner. It uses the official Sub-Store engine for proxy parsing and native Loon output, a private FastAPI + SQLite Node Registry for persistent decisions, and Caddy for HTTPS and admin authentication.

**Scope:** Import multiple HTTPS airport subscriptions; update daily at 05:00 Asia/Shanghai; exclude individual nodes permanently; batch-exclude; add persistent regex filters; manually classify and rename nodes; publish four token-protected Loon feeds. No latency tests, auto-selected proxies, or sorting by speed. This project does **not** forward your traffic; it only provides subscription files.

## Feed semantics

| Feed | Meaning |
| --- | --- |
| `/loon/hk/<token>` | Accepted nodes whose name or manual override indicates Hong Kong |
| `/loon/us/<token>` | Accepted nodes whose name or override indicates USA |
| `/loon/jp/<token>` | Accepted nodes whose name or override indicates Japan |
| `/loon/overseas/<token>` | **All accepted nodes** (including HK, US, JP, Taiwan, Singapore, etc.) |

The Overseas feed is intentionally an aggregate, *not* a fourth mutually exclusive geographic bucket. You can manually choose any node in Overseas, or select a regional feed. An unknown country remains available in Overseas by default. Manual overrides to `overseas` prevent an incorrectly detected HK/US/JP node from appearing in a regional feed. Within a single feed, exact duplicates are removed. A single node appearing in both Overseas and a regional feed is expected.

## Components

- `xream/sub-store:latest` (upstream Sub-Store container image): provider subscription acquisition, parsing, format normalization and Loon serialization. On Docker's internal network only; its bare API is never publicly exposed.
- `registry` (Python FastAPI): source UI, snapshots, fingerprints, exclusion rules, four output feeds, scheduled refresh and manual replay. The UI is `https://YOUR_DOMAIN/manager/`.
- `SQLite`: node history, manual selections and audit-relevant timestamps. Stored at `data/registry/registry.sqlite3`.
- `Caddy`: automatic TLS, HTTP Basic authentication for `/manager/`, `/api/` and `/static/`, and four long, random feed URLs under `/loon/`.

Only TCP ports 80/443 are published. Sub-Store listens on port 3000 **inside Docker only** and its internal API is mounted at a generated private prefix. Caddy's `/loon/` routes require a random URL token but no Basic Auth, so Loon can download the four feeds unattended. All other public paths return 404.

## Install

**Before installing:** Point one DNS A record to this VPS. Ensure inbound TCP 80 and 443 are reachable. If an existing web service already owns these ports, do not run a second Caddy instance; integrate this project's proxy routes into your existing reverse proxy instead. If Cloudflare is enabled, use DNS-only during initial Caddy certificate issuance.

### Install from GitHub (recommended)

Once the repository is published, inspect the full source and in particular `install.sh`, `setup.sh`, and `compose.yaml` before executing privileged code.

```bash
curl -fsSLo loon-cleaner-install.sh https://raw.githubusercontent.com/keepraw/loon-vps-cleaner/main/install.sh
less loon-cleaner-install.sh
sudo bash loon-cleaner-install.sh
```

This is a one-time bootstrap; it downloads the source to `/opt/loon-vps-cleaner`, then runs interactive `setup.sh`. It does **not** overwrite an existing install. For code review tied to an immutable revision, pass `--ref <full-commit-SHA>` to the downloaded installer.

A shorter one-line form (still downloads the installer to disk rather than piping shell stdin, so interactive prompts work) is:

```bash
curl -fsSLo /tmp/loon-cleaner-install.sh https://raw.githubusercontent.com/keepraw/loon-vps-cleaner/main/install.sh && sudo bash /tmp/loon-cleaner-install.sh
```

The links above will work only after `keepraw/loon-vps-cleaner` has been created and its source pushed. Before publication, use the local ZIP deployment instructions below.

### Install from a downloaded source package

Upload/extract this project folder on the Debian 12 VPS, then run:

```bash
cd loon-vps-cleaner
sudo bash setup.sh
```

The installer checks whether Docker and `docker compose` are available. If Docker is entirely missing, it offers to install official Docker Engine from Docker's Debian 12 APT repository; it **does not** silently remove or replace existing Docker installations. If Docker is present but Compose is missing, it stops with a clear message rather than breaking an existing installation.

You will be prompted for a domain and admin credentials. Setup generates an encrypted-snapshot key, identity HMAC key, randomized Sub-Store path and four random feed tokens. It writes `.env` with mode 600, pulls Caddy to create a bcrypt password hash over stdin (your password is not passed as a process argument), prepares data directories and starts Compose.

When the domain is reachable, open:

```text
https://YOUR_DOMAIN/manager/
```

Log in with the credentials entered during installation. The manager contains the four precise Loon feed URLs under **Loon feeds**. Copy them rather than inventing paths.

### If Docker already exists, check it first

```bash
docker --version
docker compose version
docker info --format '{{.ServerVersion}}'
```

If all three succeed, no Docker installation is needed. If `docker --version` is unknown, `setup.sh` will offer installation. If the first succeeds but `docker compose version` fails, install the Docker Compose plugin using your existing Docker installation's package source before proceeding.

## Daily workflow

1. Add airport A in the manager using its **HTTPS** subscription URL, plus an optional subscription User-Agent. Repeat for airports B, C, etc. The browser never needs a local Sub-Store parser.
2. Adding a source immediately attempts its first refresh. You can also refresh that source or all sources with the buttons.
3. Use the Nodes page to search, batch-select and permanently exclude disliked nodes. Use **Keep** to make one node immune to regex exclusion rules. Use region dropdowns to correct classifications; optionally edit the stable display name.
4. Use a pattern such as `(?i)(expire|traffic|0[.]1x)` to exclude entire families of names on every daily update. Scope a pattern to one airport or all airports. Exclusion decisions stay in SQLite indefinitely.
5. At 05:00 Asia/Shanghai every day, Registry invokes Sub-Store with `noCache=true` to actually re-fetch each enabled airport and rebuild four native Loon feeds.
6. Configure four `select` groups in Loon using the URLs from the manager. See `loon-four-groups.example.conf` or the complete `loon-full-config.example.lcf`. Do **not** enable Loon's resource-parser for these feeds.

### Persistent identity and replacement review

A stable HMAC-SHA256 identity is computed from normalized *connection settings*, including protocol, server, port, credentials and transport fields. Names, proxy-test metadata and runtime flags are ignored. Fingerprints are scoped to each source in SQLite; an additional global fingerprint exclusion is supported across airports.

- The airport **renames a node** but keeps its connection settings: same identity; your old exclusion and display name persist.
- Credentials change while both endpoint and name stay identical: the service carries forward a prior exclusion automatically.
- Only the name or only the endpoint matches a previously excluded node: quarantine for manual review, rather than silently resurrecting it. The node is omitted until you choose Keep/Auto/Exclude.
- All identifying fields change: no reliable automatic matching is possible without a stable ID from the provider. A regex exclusion pattern is the best long-term defense against renamed or replaced node families.

Upstream names are preserved for matching; you can set a stable published alias. Proxy secrets are not displayed in the admin UI. Snapshots and published feeds are encrypted in the registry database with a Fernet key stored in `.env`. However **Sub-Store stores the original subscription links and local published-node records in its own data directory**, so that directory and backups still contain secrets. Protect all files and do not publish the original airport URL, database, `.env` or backups.

### Failure handling

- When airport B fails, it retains the most recent successful snapshot while airports A/C can still refresh.
- If Sub-Store cannot serialize one output, the four previously published feeds stay unchanged. Admin UI and logs report the failure.
- Empty region after valid exclusions publishes a comment-only feed; Loon may show an empty subscription. An unconfigured service returns HTTP 503 until first publication.
- Publication stages four feeds first, and commits all four encrypted cache entries to SQLite in a single database transaction.
- A node that Sub-Store cannot serialize to Loon is omitted, and the manager shows a warning count (the producer does not expose a full per-node compatibility error list through this workflow).

## Loon connection

Use the actual private URL values copied from `/manager/`. This is only a fragment for the existing Loon config:

```ini
[Remote Proxy]
VPS-HK = https://example.com/loon/hk/HK_TOKEN,enabled=true,parser-enabled=false
VPS-US = https://example.com/loon/us/US_TOKEN,enabled=true,parser-enabled=false
VPS-JP = https://example.com/loon/jp/JP_TOKEN,enabled=true,parser-enabled=false
VPS-OVERSEAS = https://example.com/loon/overseas/OVERSEAS_TOKEN,enabled=true,parser-enabled=false

[Proxy Group]
HongKong = select,VPS-HK
UnitedStates = select,VPS-US
Japan = select,VPS-JP
Overseas = select,VPS-OVERSEAS
```

Keep the China/WeChat direct rules already decided in your main Loon config. No per-app Hong Kong/Japan rule is required. You can refer to these groups in any existing `DOMAIN`/`FINAL` rules, using the exact group names that you choose.

## Maintenance

```bash
# Container status
docker compose ps

# Recent log entries (be careful: Sub-Store may log subscription detail)
docker compose logs --tail=100 registry sub-store caddy

# Validate configuration before starting
sudo docker compose config --quiet

# Create a private, consistent backup (brief service stop)
sudo bash backup.sh

# Backup, pull newer upstream images, rebuild Registry, restart
sudo bash update.sh

# Run the Python test suite on your development machine
python3 -m pytest -q registry/tests
```

`backup.sh` stops Registry and Sub-Store briefly before archiving `.env` and both data directories; this is deliberate to keep SQLite WAL and Sub-Store files consistent. Keep an offsite copy of the backup, never in a public repository. **Do not regenerate keys or `.env` on every update:** that would invalidate saved node IDs and encrypted snapshots.

### Source updates versus image updates

`update.sh` updates container images and rebuilds from the **already installed local source**. It does not pull newer Registry code from GitHub, and it never regenerates `.env`. To upgrade Registry code, first audit the new release/commit and use a controlled file deployment with a backup; do not rerun the bootstrap on top of existing data.

### Smoke tests on the VPS

```bash
sudo docker compose ps
curl -I "https://YOUR_DOMAIN/manager/"
# Expected: HTTP 401 before authentication.

curl -u admin "https://YOUR_DOMAIN/api/status"
# The command prompts for the admin password; expected JSON overview.

curl -I "https://YOUR_DOMAIN/loon/hk/not-a-real-token"
# Expected: HTTP 404.
```

After importing an airport, `/api/status` should report sources and feed counts. A previously unconfigured feed should return 503, then 200 after a successful publication.

## Known limitations and version discipline

- The code has local unit/integration-style tests with a **mock** Sub-Store API. It has not been exercised on your Debian 12 VPS, against a live Sub-Store Docker image, or inside the iOS Loon app. Validate those environments before replacing your currently working Loon profile.
- The `xream/sub-store:latest` image is a mutable upstream tag. After first successful acceptance testing, pin an exact image digest in `.env` for reproducible operations; upgrade through `update.sh` after reading upstream release notes.
- No speed tests, health probing, IP geolocation verification, mobile VPN configuration rewrite, automatic node selection or traffic forwarding are performed.
- Region classification initially depends on names. Manually override names that do not match HK/US/JP. The Overseas feed deliberately includes all approved nodes.
- The service rejects non-HTTPS airport URLs, localhost/private-IP literals and common local hostnames. It does not defend against provider DNS rebinding or all possible upstream redirects; use trusted airport links only, and keep this service admin-only.
- The aggregated feeds do not combine or display multiple airports' quota headers. Source quota details remain with the provider.
- Each output is serialized by Sub-Store from newline-delimited Clash-compatible JSON node objects. This approach is grounded in the upstream parser's single-node JSON handling, but should be tested against your specific node protocols and Loon version.

## Project tree

```text
loon-vps-cleaner/
  compose.yaml
  Caddyfile
  install.sh
  setup.sh
  backup.sh
  update.sh
  .env.example
  loon-four-groups.example.conf
  loon-full-config.example.lcf
  .github/workflows/ci.yml
  registry/
    Dockerfile
    requirements.txt
    app.py
    core.py
    static/index.html
    static/app.js
    static/style.css
    tests/test_core.py
    tests/test_app.py
```

## Security and public-repository review

Only commit application source, examples, CI and documentation. `.env`, `data/` and `backups/` must stay private. User-provided airport URLs are stored in private Sub-Store data, not in the GitHub repository. Loon feed links contain bearer tokens; sharing one grants access to your proxy credentials. The management interface uses HTTPS and Caddy Basic Auth, and public Loon endpoints require separate long random tokens.

**Never** execute installation scripts from an unreviewed branch. Review changes and prefer `--ref` set to an audited full commit SHA. A public GitHub repository makes code review possible, but does not itself provide a security audit.

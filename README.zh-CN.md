# Loon VPS Cleaner

自托管的多机场订阅清洗服务。Sub-Store 负责机场订阅获取、节点解析和原生 Loon 格式转换；FastAPI + SQLite 负责节点长期身份、人工排除、地区分类和发布缓存。

**它不转发你的日常代理流量，只负责生成订阅。** 支持多个机场、北京时间每日 05:00 更新、节点改名后仍记住排除决定、批量排除/恢复、正则排除、人工改名和地区修正，以及香港、美国、日本、海外四个 Loon 手动选择出口。

## 四个出口

| 订阅 | 内容 |
|---|---|
| 香港 `hk` | 已通过清洗、被识别或人工指定为香港的节点 |
| 美国 `us` | 已通过清洗、被识别或人工指定为美国的节点 |
| 日本 `jp` | 已通过清洗、被识别或人工指定为日本的节点 |
| 海外 `overseas` | **全部通过清洗的节点**，包含香港、美国、日本、台湾、新加坡及其他地区 |

海外是全量集合，不是“其他地区”集合。一个香港节点同时出现在香港和海外两个订阅中是预期行为。四组均不测速、不按延迟排序、不自动选择节点。

## 系统兼容性

- **推荐**：Debian 12/13、Ubuntu 22.04/24.04 及后续受 Docker 官方仓库支持的版本。
- 只要已有可用的 rootful Docker Engine、Docker Compose V2 和 Python 3，其他 Linux 发行版也可以使用本项目；安装器不会因为发行版名称不同就拒绝使用已有 Docker。当前不支持 rootless Docker。
- 如果系统没有 Docker，安装器只会在 Debian/Ubuntu 上提供自动安装选项，并使用 Docker 官方 APT 仓库。其他发行版请先自行安装 Docker Engine + Compose V2。
- 已有 Docker 不会被卸载、替换或重装。若只有 Compose V2 插件缺失，安装器最多询问是否只安装 Compose 插件。

## 多网站、多服务共存

项目默认不假设自己独占 VPS。安装时选择以下一种入口模式：

### 1. Standalone

适合 VPS 上没有其他服务占用公网 TCP 80/443 的情况。项目自己的 Caddy 容器负责 HTTPS 和反向代理。

- Caddy 映射宿主机 80/443。
- Sub-Store 的 3000 端口只在 Docker 内部可见。
- Registry 的 8000 端口只在 Docker 内部可见。

**Standalone 的 Caddy 同时可以作为这台 VPS 的共享网站入口**，不只服务 Loon Cleaner：

- 安装器创建本地目录 `caddy-sites/`，并将其只读挂载给 Caddy。
- 主 Caddyfile 自动导入 `caddy-sites/*.caddy`。每个网站一个独立文件，新增网站不需要修改项目主配置。
- Caddy 容器提供 `host.docker.internal` 到宿主机的网关映射，可以反代到现有服务已发布的宿主机端口。
- `caddy-sites/*.caddy` 不会提交到 GitHub，但会进入本地备份。

例如当前 BiliTool 已发布宿主机 3000 端口。以后要让它通过独立域名访问：

```bash
cp caddy-sites/bilitool.example.caddy.example caddy-sites/bilitool.example.caddy
nano caddy-sites/bilitool.example.caddy
```

把示例域名改成你自己的域名，并确认 DNS 指向这台 VPS。示例文件会把请求转发到 `host.docker.internal:3000`。然后验证并热加载：

```bash
docker compose exec caddy caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
docker compose exec caddy caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile
```

Caddy 会按 Host 域名分发网站，并为新域名自动申请 HTTPS。现有 BiliTool 容器、Compose 项目和 3000 端口映射都不需要改动。

如果未来某个 Docker 应用没有发布宿主机端口，可让 Caddy 和该应用加入同一个外部 Docker network，再用容器服务名反代；不必为了所有网站都开放宿主机端口。

### 2. Host Proxy

适合现有 Nginx 或 Caddy 运行在宿主机上的情况。项目不启动第二个反向代理，只将 Registry 绑定到 `127.0.0.1` 的一个空闲高位端口（默认从 18765 开始选择）。安装器生成反向代理配置片段，交由你检查并手动加入现有代理配置。

- 不占用 80/443。
- 不修改、重启或覆盖现有 Nginx/Caddy 配置。
- Nginx 模式会额外生成 Basic Auth 密码文件；Caddy 模式会生成 bcrypt 密码哈希。
- Host Proxy 的 Caddy 片段可在现有 Caddyfile 顶层 `import /opt/loon-vps-cleaner/proxy-snippets/loon-cleaner.caddy`；Nginx 片段应在该子域名的 TLS `server {}` 内 `include /opt/loon-vps-cleaner/proxy-snippets/loon-cleaner.nginx.conf;`。

### 3. Docker Proxy

适合现有 Nginx/Caddy 也运行在 Docker 中的情况。你先选择一个已存在的 external Docker network，安装器只把 Registry 加入该网络，并添加稳定网络别名 `loon-vps-cleaner-registry`。项目不发布宿主机端口。

- 现有反向代理容器也必须加入同一个网络。
- 安装器不会擅自修改或重建现有反向代理容器。
- Nginx 模式需要将生成的 `nginx.htpasswd` 只读挂载到代理容器指定路径。

**建议每个网站使用独立子域名**，例如 `cleaner.example.com`。不要把本项目的 `location /` 或 Caddy `handle` 规则直接混入另一个网站的根路径；它们会对未匹配路径返回 404。现有网站继续使用自己的域名和 Compose 项目。

## 安装

先在 DNS 中将专用子域名指向 VPS。Standalone 模式需要公网 TCP 80/443 可达；Host Proxy / Docker Proxy 模式由现有反向代理负责 TLS。

### 先下载并审查安装器（推荐）

```bash
curl -fsSLo loon-cleaner-install.sh https://raw.githubusercontent.com/keepraw/loon-vps-cleaner/main/install.sh
less loon-cleaner-install.sh
sudo bash loon-cleaner-install.sh
```

也可以固定到已审查的完整提交 SHA：

```bash
sudo bash loon-cleaner-install.sh --ref <40位提交SHA>
```

安装器下载源码到 `/opt/loon-vps-cleaner`，然后启动交互式 `setup.sh`。如果目标目录已经存在，会停止而不会覆盖原有安装、`.env` 或数据库。可通过 `--dir /你指定的绝对路径` 指定新安装目录。

### 安装时会做什么

1. 检测 Linux 发行版、版本、Docker、Compose V2 和 Docker daemon。
2. 如果 Docker 已存在，直接复用，不卸载、不替换、不重装。
3. 如果 Docker 不存在，询问是否在 Debian/Ubuntu 上通过 Docker 官方 APT 仓库安装；其他系统需要先手动安装 Docker。
4. 检查 80/443。若端口已占用，默认推荐 Host Proxy；Standalone 会被阻止，避免抢占现有网站端口。
5. 选择 Standalone、Host Proxy 或 Docker Proxy，并根据选择生成本地 `compose.override.yaml`。
6. 生成独立 Compose project name、随机 Sub-Store 内部路径、节点指纹密钥、加密密钥和四个订阅令牌。
7. 创建 `.env`（权限 600）、数据目录和反向代理配置片段，然后只启动本项目容器。

安装器不会运行 `docker compose down`、不会清理其他 Docker 项目、不会删除其他网络/volume，也不会修改现有反向代理配置。

### 部署完成后

- 管理页面：`https://你的域名/manager/`
- Standalone：项目 Caddy 自动申请 HTTPS 证书。
- Host Proxy：将 `proxy-snippets/` 中生成的 Caddy site block 或 Nginx locations 片段加入现有反向代理，检查配置并 reload。
- Docker Proxy：将现有反向代理容器加入所选 external network，再导入生成的配置片段。若使用 Docker Nginx，还需将 `proxy-snippets/nginx.htpasswd` 只读挂载到容器 `/etc/nginx/auth/loon-vps-cleaner.htpasswd`。

Docker Caddy 示例：在现有 Caddy Compose 项目中把 Caddy 服务加入同一个 external network；Nginx 同理。示例：

```yaml
services:
  caddy:
    networks:
      - proxy-public
networks:
  proxy-public:
    external: true
```

Docker Nginx 还需在其服务下增加：

```yaml
volumes:
  - /opt/loon-vps-cleaner/proxy-snippets/nginx.htpasswd:/etc/nginx/auth/loon-vps-cleaner.htpasswd:ro
```

如果安装目录不是 `/opt/loon-vps-cleaner`，请替换为实际路径。

管理页面通过 HTTP Basic Auth 保护；管理员密码最低 10 个字符，不强制大小写或特殊字符。建议使用容易记住但不容易猜到的短语。四个 `/loon/` 订阅地址使用独立随机令牌，供 Loon 无交互下载。

## 日常使用

1. 打开管理页面，添加机场名称、HTTPS 订阅地址和可选 User-Agent。可以添加多个机场。
2. 首次添加会触发刷新；也可以手动刷新单个机场或全部机场。
3. 在节点页面搜索、批量选择并永久排除不喜欢的节点；可恢复节点、设置稳定别名、人工修改地区。
4. 可添加正则排除规则，例如 `(?i)(expire|traffic|0[.]1x)`，并选择作用于单个机场或所有机场。
5. 每天北京时间 05:00 自动重新拉取机场订阅。某个机场拉取失败时，保留该机场上次成功快照，不影响其他机场。
6. 在管理页面复制香港、美国、日本、海外四个私有订阅 URL 到 Loon 的 `[Remote Proxy]`，再由 `[Proxy Group]` 手动选择。

节点指纹由标准化后的连接参数计算，不依赖节点名称。只改名不会绕过排除记录；若机场同时更换了地址和凭据且没有稳定 ID，系统会将可疑替换节点放入人工复核，而不是假装能百分之百认出它。

## 常用维护命令

以下命令均在安装目录执行，例如：

```bash
cd /opt/loon-vps-cleaner

# 查看本项目容器（不会列出或影响其他项目）
docker compose ps

# 查看本项目日志
docker compose logs --tail=100 registry sub-store

# 校验本项目 Compose 配置
docker compose config --quiet

# 备份 .env、SQLite 和 Sub-Store 数据（会短暂停止本项目的 Registry/Sub-Store）
sudo bash backup.sh

# 备份后更新 Sub-Store 镜像并重建本项目 Registry
sudo bash update.sh
```

`backup.sh` 同时保存 `.env`、本地 Compose override、生成的反向代理片段、`caddy-sites/` 自定义网站配置和数据目录。`update.sh` 只更新当前安装目录中的代码和镜像，不会自动下载 GitHub 新代码，也不会改写 `.env`。更新 Registry 源码前先审查 GitHub 变更、备份数据，再按发布说明更新本地代码。

## 端口与网络说明

| 服务 | 端口 | 暴露方式 |
|---|---:|---|
| Sub-Store | 3000 | 仅 Docker 内部网络 |
| Registry | 8000 | 仅 Docker 内部；Host Proxy 模式额外映射到 `127.0.0.1:18765` 等空闲端口 |
| Caddy | 80/443 | 仅 Standalone 模式映射公网 |

BiliTool 等其他服务即使使用宿主机 3000，也不会与 Sub-Store 冲突，因为 Sub-Store 不发布宿主机端口。不同应用使用独立 Compose project name、网络和数据目录。不要使用 `docker system prune` 或 `docker volume prune` 作为本项目的维护步骤；它们可能影响同一台 VPS 上的其他项目。

## 备份与安全

- 不要把真实机场订阅、`.env`、`data/`、`backups/`、生成的 `compose.override.yaml`、`proxy-snippets/loon-cleaner.*` 或本地 `caddy-sites/*.caddy` 提交到 GitHub。
- `.env` 和数据库包含令牌、加密密钥及代理凭据，备份文件也必须保密。
- Loon 订阅 URL 是 bearer token；泄露后别人可能读取你的节点配置。需要时重新生成令牌。
- Sub-Store 管理后台只在 Docker 内部使用，不直接发布到公网。
- Nginx/Caddy 的配置片段由安装器生成，但不会自动改写现有代理配置。检查后再手动导入和 reload。
- 目前自动化测试使用模拟 Sub-Store；真实 VPS、真实机场协议和 iOS Loon 仍需实际验收。首次部署先使用测试 Loon 配置，不要覆盖原配置。

## 开发测试

```bash
python3 -m pip install -r registry/requirements.txt pytest pyyaml
python3 -m pytest -q registry/tests
bash -n install.sh setup.sh update.sh backup.sh
node --check registry/static/app.js
```

CI 还会检查 Compose 基础文件和三种部署 overlay 的静态结构。

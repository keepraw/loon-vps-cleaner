# Loon VPS Cleaner

自托管的多机场订阅清洗服务。Sub-Store 负责机场订阅获取、节点解析和原生 Loon 格式转换；FastAPI + SQLite 负责节点长期身份、人工排除、地区分类和发布缓存。

**它不转发你的日常代理流量，只负责生成订阅。** 支持多个机场、北京时间每日 05:00 更新、节点改名后仍记住排除决定、批量排除/恢复、正则排除、人工改名和地区修正，以及香港、美国、日本、海外四个 Loon 手动选择出口。

## 一个订阅，四个策略组

VPS 管理页面只提供 **一个统一 Loon 订阅 URL**。在 Loon 的 `[Remote Proxy]` 中添加一次即可，不需要复制四次。

| Loon 策略组 | 节点范围 |
|---|---|
| 香港服务 | VPS 标记为 `HK - ` 的节点 |
| 美国服务 | VPS 标记为 `US - ` 的节点 |
| 日本服务 | VPS 标记为 `JP - ` 的节点 |
| 海外服务 | 全部已接受节点，包含香港、美国、日本、台湾、新加坡等 |

为了让一个订阅能拆成四个手动策略组，配置中保留三条极简 `[Remote Filter]`（NameRegex）规则。地区识别仍由 VPS 完成；VPS 在发布节点名称前添加稳定地区前缀，Loon 只按前缀分组，不负责识别机场原始地区名称。没有测速、自动排序或自动切换。

配置示例见仓库根目录的 `loon-four-groups.example.conf`。你只需把管理页面生成的唯一 URL 替换进去。

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
6. 生成独立 Compose project name、随机 Sub-Store 内部路径、节点指纹密钥、加密密钥和订阅访问令牌。
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

管理页面通过 HTTP Basic Auth 保护；管理员密码最低 10 个字符，不强制大小写或特殊字符。建议使用容易记住但不容易猜到的短语。统一 `/loon/all/` 订阅地址使用独立随机令牌，供 Loon 无交互下载；旧版区域 URL 仍保留兼容。

## 使用教程

### 1. 登录管理页面

安装完成后打开：

- 管理地址：https://你的域名/manager/
- 用户名和密码：安装时设置的 Admin username / Admin password

浏览器会弹出 HTTP Basic Auth 登录框。管理页面不要公开分享；机场订阅 URL 和 Loon 订阅 URL 都包含敏感令牌。

### 2. 添加多个机场订阅

在「机场订阅源」区域逐个添加：

1. **机场名称**：填写容易辨认的名字，例如「机场 A」。
2. **订阅 HTTPS 链接**：粘贴机场提供的 Clash / 通用订阅 HTTPS 地址。
3. **User-Agent**：机场有特殊要求时再填写；留空使用默认值 clash.meta/v1.19.23。
4. 点击「添加并刷新」。

每个机场单独保存。可以继续添加机场 B、机场 C；修改订阅 URL 或 User-Agent 时，使用该机场条目右侧的「修改」。

注意：当前只接受公网 HTTPS 订阅地址，不接受本机地址、内网地址或 HTTP 链接。不要把订阅 URL 发到公开 Issue、截图或群聊。

### 3. 刷新机场和检查导入结果

- 添加机场后会自动尝试首次刷新。
- 单独更新：在对应机场条目点击「单独刷新」。
- 全部更新：点击页面顶部「刷新全部机场」。
- 日常自动更新：每天北京时间 05:00。

如果某个机场临时连接失败，系统保留它上一次成功获取的节点快照，不会因为一次失败就清空该机场节点。可查看机场条目的错误信息，修复订阅地址或 User-Agent 后再次刷新。

### 4. 清洗节点

在「节点管理」区域操作。列表每页显示 40 条，可以翻页；使用搜索框、机场筛选和状态筛选缩小范围。

| 操作 | 作用 |
|---|---|
| 排除 | 只排除当前机场中的这条节点；之后节点改名仍可识别 |
| 保留 | 手动保留节点，优先于正则排除规则 |
| 修改显示名称 | 只改管理和输出时显示的名字，不改节点连接参数 |
| 地区下拉框 | 选择 Auto、香港、美国、日本或海外，修正自动识别结果 |
| Global Exclude | 对相同节点指纹做全局排除，适合多个机场重复提供同一节点 |
| Global Restore | 撤销该节点的全局排除 |

**「排除」和「Global Exclude」不同：**前者只作用于当前机场的节点记录；后者按节点指纹跨机场排除。一般只想删掉某机场的一条节点，使用「排除」即可。

恢复节点时点击「恢复自动」；批量处理时先勾选节点，再点击「批量排除」或「批量恢复」。

### 5. 设置长期排除规则

在「持久排除正则」区域添加规则：

- 正则表达式匹配节点原始名称。
- 不区分大小写。
- 作用范围可以选择单个机场，也可以选择「全部机场」。
- 例如：(?i)(expire|traffic|0[.]1x) 可匹配包含 expire、traffic 或 0.1x 的名称。

规则会在每次刷新和发布时重新应用。手动「保留」优先于正则规则；全局排除、手动排除和待复核状态仍然会阻止节点发布。删除规则后，符合条件且没有其他排除标记的节点会重新进入订阅。

建议先用较窄的关键词，检查影响范围后再扩大规则，避免误删有用节点。

### 6. 理解地区分类

VPS 根据节点名称识别香港、美国、日本；也可以在节点列表的地区下拉框中人工覆盖。

统一订阅输出时，VPS 会在节点名前添加地区前缀：

- **HK - **：香港
- **US - **：美国
- **JP - **：日本
- **OTHER - **：其他地区或未归入前三类

「海外」不是互斥的第四个地区，而是**所有已接受节点的总集合**，包含香港、美国、日本、台湾、新加坡和其他地区。

### 7. Loon 只添加一次订阅

管理页面的「Loon 订阅出口」应只显示一条「统一订阅（全部节点）」。点击它右侧的「复制订阅」，得到一个包含全部已接受节点的私有 URL。

在 Loon 配置中只添加一次：

1. 打开正在使用的 Loon 配置文件。
2. 找到现有的 [Remote Proxy] 区块；没有才新建。
3. 添加下面一行，把 URL 替换成管理页面复制的完整地址：

~~~ini
[Remote Proxy]
VPS = https://你的域名/loon/all/你的令牌,enabled=true,parser-enabled=false
~~~

4. 找到 [Remote Filter] 区块，加入三个地区筛选器：

~~~ini
[Remote Filter]
VPS-HK = NameRegex,VPS,FilterKey = "^HK - "
VPS-US = NameRegex,VPS,FilterKey = "^US - "
VPS-JP = NameRegex,VPS,FilterKey = "^JP - "
~~~

5. 找到 [Proxy Group] 区块，加入四个手动策略组：

~~~ini
[Proxy Group]
香港服务 = select,VPS-HK
美国服务 = select,VPS-US
日本服务 = select,VPS-JP
海外服务 = select,VPS
~~~

6. 保存配置，在 Loon 中更新 VPS 订阅。香港、美国、日本组只显示对应前缀的节点；海外服务组显示全部节点。
7. 规则区的 FINAL,海外服务 可以继续使用，作为默认海外出口。

**不要把同名区块重复粘贴多次。** 如果配置文件已经有 [Remote Proxy]、[Remote Filter] 或 [Proxy Group]，只把对应的配置行合并到现有区块中。不要再创建 VPS-HK、VPS-US、VPS-JP 三个 Remote Proxy 订阅；它们是 Remote Filter，不是额外订阅。

仓库提供完整示例：loon-four-groups.example.conf。只需把管理页面生成的唯一 URL 替换进去。

### 8. 更新订阅与自动刷新

机场每天北京时间 05:00 自动更新；你也可以随时在网页点击「刷新全部机场」。节点被排除、恢复、改名或修改地区后，服务会重新发布统一订阅。Loon 端可手动更新 VPS 订阅，或按 Loon 自身的订阅更新设置刷新。

如果管理页面仍显示香港、美国、日本、海外四条独立订阅，说明服务器还在运行旧版 Registry。先按「升级已有部署」章节升级到支持统一订阅的版本，再强制刷新浏览器页面。

### 9. 常见问题

- **节点没有进入香港/美国/日本组**：检查节点名称是否被识别；在网页地区下拉框手动指定，再重新发布并更新 Loon。
- **某节点仍出现在海外组**：这是预期行为，海外组包含全部已接受节点。
- **排除后节点又回来**：确认操作的是「排除」而不是只改了显示名称；若同一节点由多个机场提供，可使用「Global Exclude」。
- **节点显示待确认**：机场可能同时更换了服务器或连接凭据，系统无法证明它是原节点；在复核前不会发布该节点。
- **订阅 URL 返回 404/503**：检查是否复制完整 URL、令牌是否完整，以及管理页面是否已成功发布订阅。
- **页面节点列表较长**：使用搜索、机场/状态筛选和分页；每页默认 40 条。

## 升级已有部署

一键安装器下载的是源码压缩包，不是 Git 仓库。旧的 `update.sh` **不会拉取 GitHub 新源码**，因此不能靠它更新管理页面。

下载并审查 `upgrade.sh`，再使用完整提交 SHA 升级：

```bash
curl -fsSLo /tmp/loon-cleaner-upgrade.sh https://raw.githubusercontent.com/keepraw/loon-vps-cleaner/main/upgrade.sh
less /tmp/loon-cleaner-upgrade.sh
sudo bash /tmp/loon-cleaner-upgrade.sh --ref <40位提交SHA>
```

升级器先执行原有 `backup.sh` 备份，再只覆盖 `registry/` 应用源码，并使用 `docker compose up -d --no-deps --build registry` 重建 Registry。**不会重新安装 Docker、覆盖 .env、重建 Caddy、删除 SQLite、改变机场数据或触碰 BiliTool。** 如果 Registry 启动失败，尝试恢复旧版应用代码。

管理界面性能优化包括独立区块并行加载、总览统计改为线程池且只计算一遍、节点分页从每页 80 条调整为 40 条。

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

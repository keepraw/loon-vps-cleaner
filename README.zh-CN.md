# Loon VPS Cleaner

这是一个可公开审查、部署到自己 Debian 12 VPS 的 Loon 机场订阅清洗服务。

架构：Sub-Store 负责机场订阅解析和原生 Loon 输出，FastAPI + SQLite 负责节点长期身份、手动排除和更新历史，Caddy 负责 HTTPS 与管理页面认证。**VPS 不转发代理流量**。

功能：支持多个机场订阅、北京时间每日 05:00 自动更新、节点改名后仍记住排除决定、正则排除规则、批量排除和恢复、人工重命名和修改地区、失败时保留上一份有效结果。不自动测速、不按延迟排序、不自动选择节点。

## 四个出口

- 香港 `hk`：香港节点。
- 美国 `us`：美国节点。
- 日本 `jp`：日本节点。
- 海外 `overseas`：**全部清洗后节点**，包括以上三个地区及其他地区，不是剩余地区。

四个出口分别有私密 HTTPS 订阅地址，可以复制进 Loon 的手动选择策略组。

## 从 GitHub 安装

仓库发布后，在 Debian 12 VPS 上执行：

```bash
curl -fsSLo loon-cleaner-install.sh https://raw.githubusercontent.com/keepraw/loon-vps-cleaner/main/install.sh
less loon-cleaner-install.sh
sudo bash loon-cleaner-install.sh
```

如需一条命令直接下载安装：

```bash
curl -fsSLo /tmp/loon-cleaner-install.sh https://raw.githubusercontent.com/keepraw/loon-vps-cleaner/main/install.sh && sudo bash /tmp/loon-cleaner-install.sh
```

推荐先审查安装脚本。安装器会下载仓库源码至 `/opt/loon-vps-cleaner`，再执行交互式 `setup.sh`。若原目录存在，会立即停止，不覆盖 `.env`、节点记录或数据。可以使用 `--ref <完整40位提交SHA>` 固定已审查的源码版本。

首次部署需要域名解析到 VPS，TCP 80/443 端口可用。安装过程中输入域名、管理账号和密码；脚本发现未安装 Docker 时会询问是否通过官方 Debian 软件源安装。

安装后进入 `https://你的域名/manager/`，添加一个或多个机场的 HTTPS 订阅地址。首次导入会尝试立即同步，此后每天自动更新。管理页面可以排除、恢复节点，修改节点归属，并复制四个 Loon 私有订阅地址。

## 重要说明

- **不要将真实机场订阅、`.env`、SQLite 数据库、`data/` 和 `backups/` 提交到 GitHub**。它们含有可访问代理服务器的敏感配置。
- `.env.example` 只含示例占位信息，安装时生成强随机令牌和密钥。
- 原始 Sub-Store 后端 API 只在 Docker 网络内使用，不直接暴露公网。
- 安装包里的 GitHub Actions 会运行 Python 测试、JavaScript/Bash 语法检查；使用了模拟 Sub-Store，尚未在真实 Debian 12 VPS / iOS Loon 完整联调。
- `update.sh` 只更新 Docker 容器镜像、重建**本地已有**的 Registry 源码，不会自动把 GitHub 的新提交覆盖到服务器。

详细设计、安全边界、排查命令及本地测试说明见 [English README](README.md)。

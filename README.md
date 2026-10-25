# SubConvert Manager

> 轻量级订阅管理与代理格式转换工具，支持 Clash / V2Ray 双向互转、公共 Token 分发及安全路径隔离。

[![Python](https://img.shields.io/badge/Python-3.9%2B-blue?logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110%2B-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![License](https://img.shields.io/badge/License-MIT-green)](LICENSE)

---

## 目录

- [功能概览](#功能概览)
- [协议支持](#协议支持)
- [快速部署](#快速部署)
  - [一键部署（curl）](#一键部署curl)
  - [手动部署（git clone）](#手动部署git-clone)
  - [Windows 部署](#windows-部署)
- [常用管理命令](#常用管理命令)
- [关键配置](#关键配置)
- [故障排查](#故障排查)
- [变更记录](#变更记录)

---

## 功能概览

| 功能 | 说明 |
|------|------|
| 🔐 管理员初始化 | 首次访问自动跳转 `/setup`，引导设置账号密码 |
| 📦 订阅源管理 | 支持 `clash_url` / `clash_yaml` / `v2ray_text` 三种来源 |
| 🔄 在线格式转换 | Clash → V2Ray（Base64 / Raw）、V2Ray → Clash（play 模板）|
| 🔗 私有订阅接口 | `/s/{sid}/v2ray`、`/s/{sid}/clash` 需登录访问 |
| 🌐 公共订阅接口 | `/pub/s/{sid}/...?token=...` 供客户端直接使用 |
| 🛡️ 安全路径隔离 | `URL_SUFFIX` 为所有路由加路径前缀，防止扫描 |
| 🚦 登录保护 | 连续失败锁定，支持 Basic Auth + Session 双模式 |

---

## 协议支持

当前实现 **14 种协议的分享链接与 Clash/Mihomo YAML 双向转换**。别名合并计数，HTTP/HTTPS 算一种，TLS、Reality、WS 等不单独计为代理协议。

| 协议 | 分享链接前缀 | 范围 |
|------|--------------|------|
| VMess | `vmess://` | V2RayN Base64 JSON、VMess AEAD URI |
| VLESS | `vless://` | TLS、Reality、flow、指纹 |
| Trojan | `trojan://` | 默认 TLS，保留传输及 TLS 参数 |
| Shadowsocks | `ss://`、`shadowsocks://` | SIP002、旧式整体 Base64、SS2022、obfs/v2ray-plugin |
| ShadowsocksR | `ssr://` | protocol、obfs、备注及扩展参数 |
| SOCKS5 | `socks://`、`socks5://`、`socks5h://` | 无认证、明文/百分号编码或 Base64 认证 |
| HTTP/HTTPS | `http://`、`https://` | 认证、TLS、SNI、证书校验选项 |
| Hysteria 1 | `hysteria://` | 字符串认证、混淆、上下行速率 |
| Hysteria 2 | `hysteria2://`、`hy2://` | 认证、Salamander、端口跳跃、SNI、证书指纹 |
| TUIC | `tuic://` | v4 token / v5 UUID+密码、拥塞控制、UDP 模式、ALPN |
| AnyTLS | `anytls://` | 密码、SNI、证书校验，默认 443 |
| Mieru | `mieru://`、`mierus://` | 用户名/密码、多组端口/传输、端口范围、multiplexing |
| WireGuard | `wireguard://` | v2rayN 格式，单 peer、双栈接口地址、密钥、reserved、MTU、DNS |
| SSH | `ssh://` | 用户名/密码认证，默认 22；密钥认证和主机密钥固定使用原生 YAML |

VMess / VLESS / Trojan 支持 TCP、WS、gRPC、HTTP 伪装、H2、HTTPUpgrade，以及 Mihomo 可表达的 XHTTP 基础参数与部分 extra/reuse 设置。XHTTP downloadSettings 等未映射的配置会明确拒绝转换，保留原生 YAML。

输入可为多行 URI 或标准/URL-safe Base64 订阅。Mieru 多组端口会展开为多个节点；重复名称和 `DIRECT` 等保留名称会自动消歧。IPv6 地址和密码特殊字符按 URI 规则处理。

### 原生 YAML 与转换限制

Snell、ShadowQUIC、Gost Relay、Sudoku、MASQUE、TrustTunnel、OpenVPN、Tailscale、ZeroTier、EasyTier **目前仅支持原生 YAML 原样分发**，未实现分享链接转换。不要把这个列表理解为这些协议在其他客户端没有分享格式；本项目没有为它们声明兼容的 URI 编解码器。

WireGuard 多 peer / Amnezia 配置、SSH 密钥和 host-key、ECH、自定义证书、realm 设置、未知 SS 插件等同样应保留原生 YAML。`clash_yaml` / `clash_url` 来源输出 Clash 时保留原文，包括所有协议及参数；能否连接取决于客户端内核版本。

分享格式无法完整表达所有 YAML 设置。网页转换会显示节点跳过原因和未保留字段，单个坏节点不会中断整批转换；全部失败时返回带原因的 HTTP 422。公共/私有订阅响应增加 `X-Conversion-Skipped` 和 `X-Conversion-Warnings` 计数头，诊断不输出原始链接或密码。`v2ray_text` 到 Raw/Base64 的分发仍为原文透传。

`/v2ray` 与 `/v2ray_raw` 接口名为兼容旧订阅保留，输出可能包含 Hysteria、TUIC 等其他协议；接收客户端必须支持对应协议。

### 开发验证

```bash
python -m pip install -r requirements-dev.txt
python -m unittest discover -s tests -v
```

可选内核配置校验：将环境变量 `MIHOMO_BINARY` 设为本机 Mihomo 可执行文件路径后运行同一测试命令，测试会调用内核的 `-t` 检查生成配置；未设置时自动跳过。配置校验不等于真实服务器连通性测试。

格式参考：[Mihomo 订阅转换](https://github.com/MetaCubeX/mihomo/blob/Meta/common/convert/converter.go)、[SIP002](https://shadowsocks.org/doc/sip002.html)、[AnyTLS URI](https://github.com/anytls/anytls-go/blob/main/docs/uri_scheme.md)、[WireGuard v2rayN 格式](https://github.com/2dust/v2rayN/blob/master/v2rayN/ServiceLib/Handler/Fmt/WireguardFmt.cs)。

---

## 快速部署

### 一键部署（curl）

适合全新服务器，脚本会自动拉取仓库、安装依赖并注册系统服务。

```bash
curl -fsSL https://raw.githubusercontent.com/HlONGlin/subconvert-manager/main/control.sh | sudo bash
```

> 没有 `curl`？用 `wget -O - <url> | sudo bash` 替代。

运行后进入交互菜单，选择 **`1) 部署环境`** 即可。脚本会：

1. 将完整仓库克隆到 `/opt/subconvert-manager`
2. 自动安装 Python 依赖（virtualenv）
3. 注册并启动系统服务
4. 打印访问地址与初始化链接

**自定义目标目录：**

```bash
curl -fsSL .../control.sh | sudo env BOOTSTRAP_DIR=/data/subconvert-manager bash
```

**指定分支或私有仓库：**

```bash
curl -fsSL .../control.sh | sudo env REPO_URL=https://github.com/你的账号/仓库.git BRANCH=main bash
```

---

### 手动部署（git clone）

```bash
cd /opt
git clone https://github.com/HlONGlin/subconvert-manager subconvert-manager
cd subconvert-manager
sudo bash control.sh
```

在菜单中选 **`1) 安装或更新`**。

**支持的包管理器：**

| 发行版 | 包管理器 |
|--------|---------|
| Debian / Ubuntu | `apt` |
| RHEL / CentOS / Rocky / Fedora | `dnf` / `yum` |
| openSUSE | `zypper` |
| Arch Linux | `pacman` |
| Alpine | `apk` |

**支持的服务管理器：** `systemd` · `openrc` · `sysv init`

---

### Windows 部署

**方案 A：WSL（推荐）**

在 WSL 内按 Linux 步骤执行即可。

**方案 B：PowerShell 原生**

```powershell
cd C:\path\to\subconvert-manager
py -3 -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
.\.venv\Scripts\python -m uvicorn app:app --host 0.0.0.0 --port 8000
```

首次访问：`http://127.0.0.1:8000/setup`

---

## 常用管理命令

```bash
sudo bash control.sh      # 进入交互控制菜单（推荐）
sudo bash install.sh      # 仅执行安装/更新
sudo bash uninstall.sh    # 卸载并删除全部文件（含 data/）
```

**菜单功能一览：**

```
1) 安装或更新          5) 查看服务状态与访问地址
2) 卸载               6) 修改自定义端口
3) 重启服务            7) 仅显示访问地址
4) 停止服务            8) 从 GitHub 更新版本
                      9) 设置 URL 安全后缀
```

> ⚠️ `uninstall.sh` 会删除整个部署目录，包含代码、`.venv` 和 `data/`，操作不可恢复。

---

## 关键配置

配置文件位于 `config.env`（参考 `config.env.example`）：

```ini
# 监听端口（auto = 安装时自动选择空闲端口）
PORT=8000

# 管理员账号（首次访问 /setup 设置后自动写入）
BASIC_AUTH_USER=
BASIC_AUTH_PASS=

# Session 加密密钥（首次 /setup 自动生成，也可手动指定）
SESSION_SECRET=

# 公共订阅鉴权 Token（客户端订阅链接使用）
SUB_TOKEN=

# URL 安全后缀（启用后访问路径需带此前缀，例如 /abc12/）
URL_SUFFIX=
```

**完整配置项请参考 [`config.env.example`](config.env.example)。**

> 建议上线后立刻完成 `/setup`，并在反向代理侧启用 HTTPS。

---

## 故障排查

<details>
<summary><b>报错：<code>Your local changes would be overwritten by merge</code></b></summary>

控制脚本在检测到本地改动时会自动保留 `config.env` 和 `data/` 后强制覆盖代码。
也可手动触发强制同步：

```bash
BOOTSTRAP_FORCE_UPDATE=1 sudo bash control.sh
```

</details>

<details>
<summary><b>报错：<code>pip not found in virtualenv</code></b></summary>

重建虚拟环境后重新安装：

```bash
cd /opt/subconvert-manager
rm -rf .venv
python3 -m venv .venv
.venv/bin/python -m ensurepip --upgrade || true
.venv/bin/python -m pip install --upgrade pip setuptools wheel
sudo bash install.sh
```

</details>

<details>
<summary><b>无法访问 raw.githubusercontent.com</b></summary>

改为手动 clone：

```bash
cd /opt
git clone https://github.com/HlONGlin/subconvert-manager subconvert-manager
cd subconvert-manager
sudo bash install.sh
```

</details>

<details>
<summary><b>没有 root 权限</b></summary>

安装脚本需要 root 来写服务文件和安装系统依赖，请使用 `sudo` 或切换到 root 用户后再执行。

</details>

---

## 变更记录

### 未发布

- **新增** ClashPlay 风格"部署型"Clash 输出模板（`template=play`）
- **新增** 订阅源维度的默认模板与限速字段：`clash_template` / `rate_limit_mbps`
- **新增** 全局异常处理与统一中文错误页
- **新增** 拉取内容大小限制（默认 2 MB，可通过 `MAX_REMOTE_BYTES` 配置）
- **增强** UI 统一视觉规范：卡片、表格、按钮、空态、复制、Toast
- **增强** 互转页新增模板选择与限速参数
- **增强** 首页安全提醒（默认口令 / Token 缺失高亮提示）
- **工程化** 增加基础单元测试，补齐文档说明
- **安全** 修复 `SESSION_SECRET` 弱默认值，改为运行时随机生成
- **修复** `control.sh` 中 `project_status_text` 的 `$?` 状态捕获逻辑
- **修复** `is_port_available` 中 heredoc 变量插值风险
- **修复** `set_env_key` 中 `sed` 替换值特殊字符转义

### 2026-02-17

- **修复** 401 未认证提示中文化
- **增强** 增加 `/favicon.ico` 空响应，避免浏览器反复 404

---

<div align="center">

仓库地址：[github.com/HlONGlin/subconvert-manager](https://github.com/HlONGlin/subconvert-manager)

</div>

# SubConvert Manager

> 轻量级订阅管理与代理格式转换工具，支持 Clash / V2Ray 双向互转、公共 Token 分发及安全路径隔离。

[![Python](https://img.shields.io/badge/Python-3.9%2B-blue?logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110%2B-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![License](https://img.shields.io/badge/License-MIT-green)](LICENSE)

---

## 目录

- [功能概览](#功能概览)
- [协议支持](#协议支持)
- [一键部署（推荐）](#一键部署推荐)
  - [常用参数](#常用参数)
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
| 🧩 组合订阅 | 多来源合并，支持关键词/正则筛选、重命名、去重与排序 |
| 🔄 在线格式转换 | Clash → V2Ray（Base64 / Raw）、V2Ray → Clash（play 模板）|
| 📤 多客户端输出 | 组合订阅可输出 Clash、V2Ray 与 sing-box JSON；不支持的 sing-box 节点会通过响应头计数 |
| 🩺 来源检查 | 可手动检查订阅源；客户端拉取时同步更新最近检查状态与节点数 |
| 🔗 私有订阅接口 | `/s/{sid}/v2ray`、`/s/{sid}/clash`、`/s/{sid}/singbox` 需登录访问 |
| 🌐 公共订阅接口 | `/pub/s/{sid}/...?token=...` 供客户端直接使用 |
| 🛡️ 安全路径隔离 | `URL_SUFFIX` 为所有路由加路径前缀，防止扫描 |
| 🚦 登录保护 | 连续失败锁定，支持 Basic Auth + Session 双模式 |

### 组合订阅

在首页创建组合订阅后，可选择多个已有来源，并按节点名称配置保留/排除条件。筛选支持关键词或正则表达式；重命名使用 Python 正则替换语法。重复节点按连接参数去重，输出可按名称、协议或来源顺序排列。

每个组合订阅提供以下公开接口，均使用 `SUB_TOKEN` 鉴权：

| 输出 | 接口后缀 |
|------|------|
| Clash YAML | `/pub/p/{id}/clash` |
| V2Ray Base64 | `/pub/p/{id}/v2ray` |
| V2Ray Raw | `/pub/p/{id}/v2ray_raw` |
| sing-box JSON | `/pub/p/{id}/singbox` |

单个订阅源也支持 `/pub/s/{id}/singbox?token=...`（私有管理接口为 `/s/{id}/singbox`）。sing-box 接口默认返回完整配置，追加 `?mode=bare`（已有查询参数时使用 `&mode=bare`）只返回 outbounds 数组；完整配置包含 mixed 入站、DNS、`proxy`/`auto` 分组。WireGuard 使用 endpoint 格式，Reality TLS 自动启用 uTLS 并采用节点指纹或 Chrome。

sing-box 当前转换 Shadowsocks（无插件）、VMess、VLESS、Trojan、Hysteria2、TUIC、AnyTLS、SOCKS5、HTTP 与单 peer WireGuard。其他协议或无法映射的节点会跳过，响应头 `X-Output-Skipped` 返回数量；若没有可输出节点则返回 HTTP 422。Clash 原生 YAML 仍保留原样分发。

来源状态会在手动点击“检查”或订阅接口拉取时更新，不执行后台定时轮询。来源列表显示最近检查时间、状态和解析到的节点数。

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

## 一键部署（推荐）

适用于支持 `systemd` / `openrc` / `sysv init` 的 Linux 服务器。脚本会自动检查运行环境、安装 Python 依赖、创建虚拟环境、写入配置、注册系统服务，并在首次安装时引导你设置管理员账号。

```bash
bash <(curl -fsSL https://github.com/HlONGlin/subconvert-manager/raw/main/one-click.sh)
```

> 没有 `curl` 时，可用 `wget -qO- <同一地址> | sudo bash`；已经 clone 过仓库的，直接 `sudo bash one-click.sh` 即可。

脚本会进入交互式管理菜单：

| 选项 | 操作 |
| --- | --- |
| `1` | 安装或更新 |
| `2` | 卸载服务并删除全部下载内容 |
| `3` | 重启服务 |
| `4` | 停止服务 |
| `5` | 查看服务状态与访问地址 |
| `6` | 修改自定义端口 |
| `7` | 仅显示访问地址 |
| `8` | 从 GitHub 更新网站版本 |
| `9` | 设置网址后缀安全（`URL_SUFFIX`） |
| `0` | 退出菜单 |

首次安装时会提示设置管理员账号密码；直接回车则自动生成随机账号与密码。安装完成后会打印完整访问信息，请妥善保存：

```text
访问地址：http://服务器IP:8000
管理员账号：安装时设置（或自动生成）
管理员密码：仅在安装时显示一次
```

如果跳过了账号设置，打开访问地址后会在 `/setup` 页面引导完成初始化。

脚本默认使用以下路径：

| 内容 | 路径 |
| --- | --- |
| 程序目录 | `/opt/subconvert-manager` |
| 配置文件 | `/opt/subconvert-manager/config.env` |
| 订阅数据 | `/opt/subconvert-manager/data/sources.json` |
| systemd 服务 | `subconvert-manager.service` |

> 卸载（菜单 `2`）会删除程序目录、`data/` 订阅数据与配置文件，需要二次确认；修改端口和设置 `URL_SUFFIX` 不会影响已有数据。

### 常用参数

脚本源码位于仓库根目录：[one-click.sh](./one-click.sh)。除交互菜单外，也支持直接带参数执行：

| 参数 | 说明 |
| --- | --- |
| `--install` | 安装或更新后直接退出，不进入菜单 |
| `--update-only` | 仅同步代码、重装依赖并重启服务（在线更新使用） |
| `--port <端口>` | 指定监听端口；`auto` 表示自动挑选空闲端口 |
| `--suffix <后缀>` | 设置 `URL_SUFFIX`（3-5 位字母/数字/`_`/`-`） |
| `--branch <分支>` | 指定分支，默认 `main` |
| `--dir <目录>` | 指定安装目录，默认 `/opt/subconvert-manager` |
| `--yes` | 非交互模式，所有提问使用默认值 |
| `--no-menu` | 等价于 `--install` |
| `--no-setup-prompt` | 首次安装时不询问管理员账号密码 |
| `-h, --help` | 显示帮助 |
| `-V, --version` | 显示版本号 |

**自动化安装：**

```bash
curl -fsSL https://github.com/HlONGlin/subconvert-manager/raw/main/one-click.sh -o one-click.sh
sudo bash one-click.sh --install --yes --port 8000
```

**指定分支或私有仓库：**

```bash
sudo env REPO_URL=https://github.com/你的账号/仓库.git BRANCH=main bash one-click.sh
```

**在线更新：**

网页「设置 → 更新与备份 → 从 GitHub 更新」会执行 `git pull`；也可以在服务器上直接运行：

```bash
sudo bash /opt/subconvert-manager/one-click.sh --update-only
```

> 旧命令 `quick-install.sh` 仍然可用，它已改为转发到 `one-click.sh`，原有环境变量 `APP_DIR`、`REPO_URL`、`BRANCH`、`OPEN_CONTROL` 继续生效。

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
sudo bash one-click.sh    # 一键部署 / 更新（推荐，可带参数）
sudo bash control.sh      # 进入交互控制菜单
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

### v1.3.0 - 2026-11-08

- 界面全面重做：首页订阅源改为自适应信息卡片，新增状态色条、流量进度条、状态圆点与统计概览，窄屏不再横向滚动。
- 复制订阅链接升级为带格式标识的按钮组，复制成功后按钮变为「已复制 ✓」并在提示中说明复制的是哪种格式。
- 订阅源列表支持列表 / 卡片 / 紧凑三种展示方式，选择会记住；侧栏改用内联 SVG 图标并强化当前页高亮。
- 表单页统一为分组结构，补齐输入校验样式、空状态、骨架屏、焦点样式与减少动效支持。
- 10 套主题补齐文字专用墨色变量，全部达到 WCAG AA 对比度；排版改用系统字体栈并拉开字号字重层级。
- 新增网站图标，9 个页面统一静态资源版本号。
- 一键部署新增 `one-click.sh`：交互菜单、首次安装引导设置管理员账号、`--update-only` 等参数，`quick-install.sh` 转为兼容入口。
- 修复「新增订阅」与主题面板点击外部不关闭的问题。

### v1.2.0 - 2026-11-08

- 订阅源和组合订阅使用独立访问 Token，后台记录访问次数与最近访问时间。
- 后台按配置间隔检查订阅源，并展示流量、到期时间、重置日和失败提醒。
- 新增 10 套可记忆主题与设置页主题预览；首页侧栏和订阅源信息布局适配不同屏幕宽度。

### v1.1.1 - 2026-11-08

- 修复 sing-box Reality uTLS 指纹和 WireGuard endpoint 输出，并增加 sing-box 1.12.3 集成校验。
- 增加 mixed 入站、DNS、自动测速/选择分组和 `mode=bare` 输出。
- 增加 `/admin/settings`、数据备份导入导出、首页总览、组合订阅预览和直接复制 Clash。
- 默认订阅缓存 TTL 调整为 300 秒。

### 2026-02-17

- **修复** 401 未认证提示中文化
- **增强** 增加 `/favicon.ico` 空响应，避免浏览器反复 404

---

<div align="center">

仓库地址：[github.com/HlONGlin/subconvert-manager](https://github.com/HlONGlin/subconvert-manager)

</div>

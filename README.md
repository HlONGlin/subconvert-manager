# SubConvert Manager

> 轻量级订阅管理与代理格式转换工具，支持 Clash / V2Ray 双向互转、公共 Token 分发及安全路径隔离。

[![Python](https://img.shields.io/badge/Python-3.9%2B-blue?logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110%2B-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![License](https://img.shields.io/badge/License-MIT-green)](LICENSE)

---

## 目录

- [功能概览](#功能概览)
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

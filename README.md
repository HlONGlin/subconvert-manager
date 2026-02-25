# SubConvert Manager

订阅源管理与 Clash/V2Ray 转换网站，支持私有管理链接与公共 token 分发链接。

仓库地址：`https://github.com/HlONGlin/subconvert-manager`

## 主要功能

- 首次部署自动进入 `/setup`，设置管理员账号密码
- 管理三类源：`clash_url`、`clash_yaml`、`v2ray_text`
- 在线转换：
- Clash -> V2Ray（Base64 / Raw）
- V2Ray -> Clash（play 模板）
- 订阅输出：
- 管理接口：`/s/{sid}/...`
- 公共接口：`/pub/s/{sid}/...?token=...`
- 登录鉴权：Basic Auth + Session
- 公共订阅鉴权：`SUB_TOKEN`

## 控制脚本

- [control.sh](https://github.com/HlONGlin/subconvert-manager/blob/main/control.sh)

用于安装/更新、重启/停止、换端口、查看访问 URL。

---

## Linux 一键部署（curl）



```bash
curl -fsSL https://raw.githubusercontent.com/HlONGlin/subconvert-manager/main/control.sh | sudo bash
```

使用流程（新版控制器）：

1. 运行脚本后直接进入完整控制菜单
2. 选择第一个按钮 `1) 部署环境（下载仓库并安装）`
3. 脚本会自动从 GitHub 拉取完整仓库到本地并完成部署，随后进入本地仓库内的完整控制器

这个命令会：

- 先进入 `control.sh` 完整菜单
- 选择 `1) 部署环境（下载仓库并安装）` 后，自动拉取完整仓库到 `/opt/subconvert-manager` 并完成首次部署

---

## Linux 普通部署（git clone）

```bash
cd /opt
git clone https://github.com/HlONGlin/subconvert-manager subconvert-manager
cd subconvert-manager
sudo bash control.sh
```

在菜单中选 `1) Install / Update`。

安装脚本会自动识别常见发行版包管理器：

- Debian/Ubuntu: `apt`
- RHEL/CentOS/Rocky/Alma/Fedora: `dnf` / `yum`
- openSUSE: `zypper`
- Arch: `pacman`
- Alpine: `apk`

服务管理器支持：

- `systemd`
- `openrc`
- `sysv init` (`service`)

---

## Windows 部署

### 方案 A：WSL（推荐）

在 WSL 内按 Linux 部署步骤执行即可。

### 方案 B：Windows 原生（PowerShell）

```powershell
cd C:\path\to\subconvert-manager
py -3 -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
.\.venv\Scripts\python -m uvicorn app:app --host 0.0.0.0 --port 8000
```

首次访问：`http://127.0.0.1:8000/setup`

---

## 一键部署不能用时怎么调整

### 1) 机器没有 curl

改用 wget：

```bash
wget -O - https://raw.githubusercontent.com/HlONGlin/subconvert-manager/main/control.sh | sudo bash
```

### 2) 无法访问 raw.githubusercontent.com

改为手动 clone：

```bash
cd /opt
git clone https://github.com/HlONGlin/subconvert-manager subconvert-manager
cd subconvert-manager
sudo bash install.sh
```

### 3) 没有 root 权限

- 一键脚本和安装脚本都需要 root（需要写服务文件、安装依赖）
- 请切换 root 或使用 `sudo`

### 4) 想把仓库拉到别的目录

一键命令可带环境变量：

```bash
curl -fsSL https://raw.githubusercontent.com/HlONGlin/subconvert-manager/main/control.sh | sudo env BOOTSTRAP_DIR=/data/subconvert-manager bash
```

### 5) 想固定分支或私有仓库地址

```bash
curl -fsSL https://raw.githubusercontent.com/HlONGlin/subconvert-manager/main/control.sh | sudo env REPO_URL=https://github.com/HlONGlin/subconvert-manager.git BRANCH=main bash
```

### 6) 报错：`Your local changes to the following files would be overwritten by merge`

- 新版 `control.sh` 在“1) 部署环境（下载仓库并安装）”时，必须先同步 `origin/main`。
- 如果检测到本地代码改动，会提示你是否强制覆盖代码；选择 `y` 时会保留 `config.env` 和 `data/` 后再同步。
- 你也可以直接手动强制同步后再部署：

```bash
BOOTSTRAP_FORCE_UPDATE=1 sudo bash control.sh
```

### 7) 报错：`pip not found in virtualenv`

如果安装日志出现：

`ERROR: pip not found in virtualenv: /opt/subconvert-manager/.venv/bin/pip`

执行下面命令修复后再安装：

```bash
cd /opt/subconvert-manager
rm -rf .venv
python3 -m venv .venv
.venv/bin/python -m ensurepip --upgrade || true
.venv/bin/python -m pip install --upgrade pip setuptools wheel
sudo bash install.sh
```

---

## 常用管理命令

```bash
sudo bash control.sh
sudo bash install.sh
sudo bash uninstall.sh
```

## 关键配置

`config.env` 常用项：

- `PORT`
- `BASIC_AUTH_USER` / `BASIC_AUTH_PASS`
- `SUB_TOKEN`
- `SESSION_SECRET`
- `DATA_FILE`

建议上线后立刻完成 `/setup`，并在反向代理中启用 HTTPS。

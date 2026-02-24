# SubConvert Manager

一个用于管理订阅源、进行 Clash/V2Ray 互转、并生成可分发订阅链接的轻量 Web 面板。

## 网站功能（简要）

- 首次部署自动进入初始化页面（`/setup`）设置管理员账号密码
- 登录后台后可管理三类源：
- `clash_url`（远程 Clash YAML）
- `clash_yaml`（本地 YAML 文本/上传）
- `v2ray_text`（URI 多行或 Base64 订阅）
- 在线转换：
- Clash -> V2Ray（Base64 或 Raw）
- V2Ray -> Clash（play 模板）
- 订阅输出：
- 管理接口：`/s/{sid}/...`
- 公共接口：`/pub/s/{sid}/...?token=...`
- 安全项：
- Basic Auth 登录
- `SUB_TOKEN` 公共订阅鉴权

## 控制脚本（直链）

- [control.sh](https://github.com/HlONGlin/subconvert-manager/blob/main/control.sh)

通过该脚本可完成安装/更新、重启/停止、自动换端口、查看完整访问 URL（自动探测本机和公网 IP）。

---

?????`https://github.com/HlONGlin/subconvert-manager`

## Linux 部署

### 1) 通用方式（推荐）

```bash
cd /opt
git clone https://github.com/HlONGlin/subconvert-manager subconvert-manager
cd subconvert-manager
sudo bash control.sh
```

然后在菜单里选择 `1) Install / Update`。

安装成功后脚本会输出：
- 本地访问地址：`http://<local-ip>:<port>/`
- 公网访问地址（可用时）
- 首次初始化入口：`/setup`

### 2) 不同 Linux 发行版支持说明

`install.sh` 会自动识别包管理器并安装依赖，已支持：
- Debian/Ubuntu（`apt`）
- RHEL/CentOS/Rocky/Alma/Fedora（`dnf`/`yum`）
- openSUSE（`zypper`）
- Arch（`pacman`）
- Alpine（`apk`）

服务管理器支持：
- `systemd`
- `openrc`
- `sysv init`（`service`）

### 3) 常用命令

```bash
# 打开控制菜单
sudo bash control.sh

# 直接安装
sudo bash install.sh

# 卸载服务（保留源码与 data/）
sudo bash uninstall.sh
```

---

## Windows 部署

Windows 不使用 `control.sh`，建议两种方式：

### 方案 A：WSL（推荐，最接近 Linux 部署）

在 WSL 里按 Linux 步骤执行即可：

```bash
git clone https://github.com/HlONGlin/subconvert-manager subconvert-manager
cd subconvert-manager
sudo bash control.sh
```

### 方案 B：Windows 原生（PowerShell）

```powershell
cd C:\path\to\subconvert-manager
py -3 -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
.\.venv\Scripts\python -m uvicorn app:app --host 0.0.0.0 --port 8000
```

访问：
- `http://127.0.0.1:8000/setup`（首次部署）

如需外网访问，请在防火墙放行端口并自行配置反向代理/HTTPS。

---

## 关键配置

配置文件：`config.env`

常用项：
- `PORT`：监听端口（`auto` 或固定数字）
- `BASIC_AUTH_USER` / `BASIC_AUTH_PASS`：后台登录
- `SUB_TOKEN`：公共订阅鉴权 token
- `SESSION_SECRET`：会话加密密钥
- `DATA_FILE`：订阅源存储文件（默认 `data/sources.json`）

## 说明

- 首次上线请务必完成 `/setup`，不要使用默认账号密码。
- 生产环境建议通过 Nginx/Caddy 反向代理并启用 HTTPS。

#!/usr/bin/env bash
# SubConvert Manager 一键部署入口
#
# 用法（推荐）：
#   bash <(curl -fsSL https://raw.githubusercontent.com/HlONGlin/subconvert-manager/main/one-click.sh)
#
# 也支持直接下载后执行：
#   curl -fsSL https://raw.githubusercontent.com/HlONGlin/subconvert-manager/main/one-click.sh -o one-click.sh
#   sudo bash one-click.sh
#
# 非交互安装（适合自动化）：
#   sudo bash one-click.sh --install --yes --port 8000
#
# 在线更新（网页「从 GitHub 更新」或定时任务使用）：
#   sudo bash /opt/subconvert-manager/one-click.sh --update-only
set -Eeuo pipefail
IFS=$'\n\t'

APP_NAME="subconvert-manager"
REPO_URL="${REPO_URL:-https://github.com/HlONGlin/subconvert-manager.git}"
BRANCH="${BRANCH:-main}"
INSTALL_DIR="${INSTALL_DIR:-/opt/subconvert-manager}"
SERVICE_NAME="${SERVICE_NAME:-subconvert-manager}"

# 运行模式：menu（默认，进菜单）/ install（装完即退出）/ update（仅更新）
MODE="menu"
PORT_OVERRIDE=""
SUFFIX_OVERRIDE=""
ASSUME_YES=0
NO_MENU=0
SETUP_PROMPT=auto

log() { printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"; }
warn() { printf '[%s] WARN: %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >&2; }
die() {
  printf '[%s] ERROR: %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >&2
  exit 1
}

has_cmd() { command -v "$1" >/dev/null 2>&1; }

usage() {
  cat <<'EOF'
SubConvert Manager 一键部署

用法：
  one-click.sh [选项]

选项：
  --install            安装或更新后直接退出，不进入菜单
  --update-only        仅同步代码、重装依赖并重启服务（在线更新使用）
  --port <端口>        指定监听端口；auto 表示自动挑选空闲端口
  --suffix <后缀>      设置 URL 安全后缀（3-5 位字母/数字/_/-）
  --branch <分支>      指定分支，默认 main
  --dir <目录>         指定安装目录，默认 /opt/subconvert-manager
  --yes                非交互模式，所有提问使用默认值
  --no-menu            等价于 --install
  --no-setup-prompt    首次安装时不询问管理员账号密码
  -h, --help           显示本帮助
  -V, --version        显示版本号

示例：
  sudo bash one-click.sh
  sudo bash one-click.sh --install --port 8000 --yes
  sudo bash one-click.sh --update-only
EOF
}

parse_args() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --install|--no-menu) MODE="install"; NO_MENU=1 ;;
      --update-only) MODE="update" ;;
      --port)
        [[ $# -ge 2 ]] || die "--port 需要一个参数"
        PORT_OVERRIDE="$2"; shift ;;
      --port=*) PORT_OVERRIDE="${1#*=}" ;;
      --suffix)
        [[ $# -ge 2 ]] || die "--suffix 需要一个参数"
        SUFFIX_OVERRIDE="$2"; shift ;;
      --suffix=*) SUFFIX_OVERRIDE="${1#*=}" ;;
      --branch)
        [[ $# -ge 2 ]] || die "--branch 需要一个参数"
        BRANCH="$2"; shift ;;
      --branch=*) BRANCH="${1#*=}" ;;
      --dir)
        [[ $# -ge 2 ]] || die "--dir 需要一个参数"
        INSTALL_DIR="$2"; shift ;;
      --dir=*) INSTALL_DIR="${1#*=}" ;;
      --yes|-y) ASSUME_YES=1 ;;
      --no-setup-prompt) SETUP_PROMPT="no" ;;
      -h|--help) usage; exit 0 ;;
      -V|--version)
        if [[ -f "$(script_dir)/VERSION" ]]; then
          cat "$(script_dir)/VERSION"
        else
          echo "unknown"
        fi
        exit 0 ;;
      *) die "未知参数：$1（用 --help 查看用法）" ;;
    esac
    shift
  done
}

script_dir() {
  local src="${BASH_SOURCE[0]:-}"
  # 通过 bash <(curl ...) 运行时 BASH_SOURCE 是 /dev/fd/xx，不能当作安装目录
  if [[ -z "$src" || "$src" == /dev/fd/* || "$src" == /proc/* ]]; then
    echo ""
    return
  fi
  (cd "$(dirname "$src")" 2>/dev/null && pwd) || echo ""
}

require_root() {
  if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
    die "请使用 root 运行。例如：curl -fsSL https://raw.githubusercontent.com/HlONGlin/subconvert-manager/main/one-click.sh | sudo bash"
  fi
}

detect_pkg_manager() {
  if has_cmd apt-get; then echo "apt"; return; fi
  if has_cmd dnf; then echo "dnf"; return; fi
  if has_cmd yum; then echo "yum"; return; fi
  if has_cmd zypper; then echo "zypper"; return; fi
  if has_cmd pacman; then echo "pacman"; return; fi
  if has_cmd apk; then echo "apk"; return; fi
  echo "none"
}

ensure_git() {
  has_cmd git && return
  local pm
  pm="$(detect_pkg_manager)"
  log "未检测到 git，尝试通过 $pm 安装"
  case "$pm" in
    apt)
      export DEBIAN_FRONTEND=noninteractive
      apt-get update -y
      apt-get install -y git
      ;;
    dnf) dnf -y install git ;;
    yum) yum -y install git ;;
    zypper) zypper --non-interactive install git ;;
    pacman) pacman -Sy --noconfirm git ;;
    apk) apk add --no-cache git ;;
    *) die "未检测到 git，且当前包管理器不受支持，请先手动安装 git" ;;
  esac
}

resolve_app_dir() {
  local here
  here="$(script_dir)"
  if [[ -n "$here" && -f "$here/install.sh" && -f "$here/control.sh" ]]; then
    APP_DIR="$here"
    log "使用当前目录：$APP_DIR"
    return
  fi
  APP_DIR="$INSTALL_DIR"
}

sync_repo() {
  mkdir -p "$(dirname "$APP_DIR")"

  if [[ -d "$APP_DIR/.git" ]]; then
    if [[ -n "$(git -C "$APP_DIR" status --porcelain 2>/dev/null || true)" ]]; then
      if [[ "$MODE" == "update" ]]; then
        warn "安装目录存在未提交改动，更新时以远端版本为准。"
      else
        warn "安装目录存在本地改动，跳过自动同步，保留当前版本。"
        return
      fi
    fi
    log "同步仓库：$BRANCH"
    if git -C "$APP_DIR" fetch origin "$BRANCH" &&
       git -C "$APP_DIR" checkout "$BRANCH" &&
       git -C "$APP_DIR" reset --hard "origin/$BRANCH"; then
      log "仓库已更新到 origin/$BRANCH"
    else
      warn "仓库同步失败，继续使用当前本地版本。"
    fi
    return
  fi

  if [[ -e "$APP_DIR" ]] && [[ -n "$(ls -A "$APP_DIR" 2>/dev/null || true)" ]]; then
    die "目标目录非空且不是 git 仓库：$APP_DIR"
  fi

  log "克隆仓库到 $APP_DIR"
  git clone --depth 1 -b "$BRANCH" "$REPO_URL" "$APP_DIR"
}

env_file() { echo "$APP_DIR/config.env"; }

get_env_key() {
  local key="$1" file
  file="$(env_file)"
  [[ -f "$file" ]] || return 0
  grep -E "^${key}=" "$file" | head -n1 | cut -d= -f2- | tr -d '\r' | xargs || true
}

set_env_key() {
  local key="$1" value="$2" file
  file="$(env_file)"
  [[ -f "$file" ]] || return 0
  if grep -qE "^${key}=" "$file"; then
    sed -i "s#^${key}=.*#${key}=${value}#" "$file"
  else
    printf '\n%s=%s\n' "$key" "$value" >>"$file"
  fi
}

service_restart() {
  if has_cmd systemctl && [[ -d /run/systemd/system ]]; then
    systemctl restart "$SERVICE_NAME"
  elif has_cmd rc-service; then
    rc-service "$SERVICE_NAME" restart
  elif has_cmd service; then
    service "$SERVICE_NAME" restart
  else
    warn "未识别服务管理器，请手动重启服务。"
  fi
}

run_install() {
  cd "$APP_DIR"
  chmod +x install.sh control.sh uninstall.sh quick-install.sh one-click.sh 2>/dev/null || true
  export DEBIAN_FRONTEND=noninteractive
  if [[ -n "$PORT_OVERRIDE" ]]; then
    INSTALL_PORT_OVERRIDE="$PORT_OVERRIDE" bash install.sh
  else
    bash install.sh
  fi
}

is_default_credentials() {
  local user pass
  user="$(get_env_key BASIC_AUTH_USER)"
  pass="$(get_env_key BASIC_AUTH_PASS)"
  [[ "$user" == "admin" && "$pass" == "change_me_please" ]]
}

prompt_credentials() {
  [[ "$SETUP_PROMPT" == "no" ]] && return 0
  is_default_credentials || return 0

  # 非交互环境：不阻塞，交给网页 /setup
  if [[ "$ASSUME_YES" -eq 1 ]] || [[ ! -t 0 ]]; then
    log "未设置管理员账号，请安装完成后访问 /setup 完成初始化。"
    return 0
  fi

  local user pass pass2
  echo
  echo "==================== 管理员账号 ===================="
  echo "现在设置管理员账号密码，之后可直接登录，无需再访问 /setup。"
  echo "直接回车可自动生成随机账号与密码。"
  echo "===================================================="

  read -r -p "管理员账号 [留空自动生成]：" user || user=""
  user="$(printf '%s' "$user" | tr -d '[:space:]')"
  if [[ -z "$user" ]]; then
    user="admin$(head -c 4 /dev/urandom | od -An -tx1 | tr -d ' \n')"
  fi
  if [[ ${#user} -lt 3 || ${#user} -gt 64 ]]; then
    warn "账号长度需为 3-64 位，已跳过自动设置，请稍后访问 /setup 初始化。"
    return 0
  fi

  read -r -s -p "管理员密码 [留空自动生成]：" pass || pass=""
  echo
  if [[ -z "$pass" ]]; then
    pass="$(head -c 18 /dev/urandom | base64 | tr -d '/+=' | cut -c1-16)"
  else
    read -r -s -p "再次输入密码：" pass2 || pass2=""
    echo
    if [[ "$pass" != "$pass2" ]]; then
      warn "两次密码不一致，已跳过自动设置，请稍后访问 /setup 初始化。"
      return 0
    fi
  fi
  if [[ ${#pass} -lt 8 ]]; then
    warn "密码至少 8 位，已跳过自动设置，请稍后访问 /setup 初始化。"
    return 0
  fi

  set_env_key "BASIC_AUTH_USER" "$user"
  set_env_key "BASIC_AUTH_PASS" "$pass"
  log "管理员账号已写入 config.env，正在重启服务使其生效"
  service_restart || true
  echo
  echo "管理员账号：$user"
  echo "管理员密码：$pass"
  echo "（请立即保存，密码不会再次显示）"
}

apply_suffix_override() {
  [[ -z "$SUFFIX_OVERRIDE" ]] && return 0
  local suffix
  suffix="$(printf '%s' "$SUFFIX_OVERRIDE" | tr -d '[:space:]')"
  if [[ ! "$suffix" =~ ^[A-Za-z0-9_-]{3,5}$ ]]; then
    warn "URL 后缀无效（需 3-5 位字母/数字/_/-），已忽略：$SUFFIX_OVERRIDE"
    return 0
  fi
  set_env_key "URL_SUFFIX" "$suffix"
  log "URL_SUFFIX 已设置为：$suffix"
  service_restart || true
}

resolve_port() {
  local port
  port="$(get_env_key PORT)"
  if [[ "$port" =~ ^[0-9]+$ ]]; then
    echo "$port"
    return
  fi
  local unit
  for unit in "/etc/systemd/system/${SERVICE_NAME}.service" "/etc/init.d/${SERVICE_NAME}"; do
    [[ -f "$unit" ]] || continue
    port="$(grep -oE -- '--port [0-9]+' "$unit" | tail -n1 | awk '{print $2}' || true)"
    if [[ "$port" =~ ^[0-9]+$ ]]; then
      echo "$port"
      return
    fi
  done
  echo ""
}

detect_ip() {
  local ip=""
  ip="$(hostname -I 2>/dev/null | awk '{print $1}' || true)"
  if [[ -z "$ip" ]] && has_cmd ip; then
    ip="$(ip route get 1.1.1.1 2>/dev/null | awk '{print $7; exit}' || true)"
  fi
  [[ -n "$ip" ]] || ip="127.0.0.1"
  echo "$ip"
}

print_summary() {
  local port suffix ip url
  port="$(resolve_port)"
  suffix="$(get_env_key URL_SUFFIX)"
  ip="$(detect_ip)"

  if [[ -n "$port" ]]; then
    url="http://${ip}:${port}"
  else
    url="（端口未识别，请查看服务状态）"
  fi
  if [[ -n "$suffix" && -n "$port" ]]; then
    url="http://${ip}:${port}/${suffix}"
  fi

  echo
  echo "==================== 部署完成 ===================="
  echo "访问地址：$url"
  if is_default_credentials; then
    echo "初始化：打开上面的地址，按提示在 /setup 设置管理员账号密码"
  else
    echo "管理员账号：$(get_env_key BASIC_AUTH_USER)"
    echo "（密码在安装时设置；若遗忘可在网页 /setup 重新初始化）"
  fi
  echo "配置文件：$(env_file)"
  echo "服务名称：$SERVICE_NAME"
  echo
  echo "常用命令："
  echo "  sudo bash $APP_DIR/one-click.sh            # 交互菜单"
  echo "  sudo bash $APP_DIR/one-click.sh --update-only   # 仅更新"
  echo "  sudo bash $APP_DIR/control.sh             # 原有控制菜单"
  echo "=================================================="
}

open_menu() {
  if [[ "$NO_MENU" -eq 1 || "$MODE" != "menu" ]]; then
    return 0
  fi
  if [[ ! -t 0 || ! -t 1 ]]; then
    log "当前不是交互式终端，跳过菜单。"
    return 0
  fi
  log "进入控制菜单：$APP_DIR/control.sh"
  exec bash "$APP_DIR/control.sh"
}

main() {
  parse_args "$@"
  require_root
  resolve_app_dir
  ensure_git
  sync_repo
  run_install
  prompt_credentials
  apply_suffix_override
  print_summary
  open_menu
}

main "$@"

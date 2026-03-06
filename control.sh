#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

resolve_script_path() {
  if [[ -n "${BASH_SOURCE[0]-}" ]]; then
    printf '%s\n' "${BASH_SOURCE[0]}"
    return
  fi

  if [[ -n "${0-}" ]]; then
    printf '%s\n' "$0"
    return
  fi

  printf '.\n'
}

SCRIPT_PATH="$(resolve_script_path)"
if [[ "$SCRIPT_PATH" == "bash" || "$SCRIPT_PATH" == "-bash" || "$SCRIPT_PATH" == "sh" || "$SCRIPT_PATH" == "-sh" ]]; then
  SCRIPT_PATH="."
fi
APP_DIR="$(cd "$(dirname "$SCRIPT_PATH")" 2>/dev/null && pwd || pwd)"
ENV_FILE="$APP_DIR/config.env"
SERVICE_NAME="subconvert-manager"
SERVICE_FILE_SYSTEMD="/etc/systemd/system/${SERVICE_NAME}.service"
SERVICE_FILE_OPENRC="/etc/init.d/${SERVICE_NAME}"
SERVICE_FILE_SYSV="/etc/init.d/${SERVICE_NAME}"
PYTHON_BIN="${PYTHON_BIN:-}"
REPO_URL="${REPO_URL:-https://github.com/HlONGlin/subconvert-manager.git}"
BRANCH="${BRANCH:-main}"
BOOTSTRAP_DIR="${BOOTSTRAP_DIR:-/opt/subconvert-manager}"
BOOTSTRAP_FORCE_UPDATE="${BOOTSTRAP_FORCE_UPDATE:-0}"
CHECK_REPO_LAST_ERROR=""

log() {
  printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"
}

warn() {
  printf '[%s] 警告: %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >&2
}

die() {
  printf '[%s] 错误: %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >&2
  exit 1
}

has_cmd() {
  command -v "$1" >/dev/null 2>&1
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

require_root() {
  if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
    die "请使用 root 权限运行：sudo bash control.sh"
  fi
}

ensure_git() {
  if has_cmd git; then
    return
  fi

  local pm
  pm="$(detect_pkg_manager)"
  warn "未找到 git，尝试通过包管理器安装：$pm"

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
    *)
      die "未找到 git，且当前包管理器不受支持，请先手动安装 git。"
      ;;
  esac
}

repo_has_local_changes() {
  local repo_dir="$1"
  local status_output=""

  if ! status_output="$(git -C "$repo_dir" status --porcelain 2>/dev/null)"; then
    return 2
  fi

  [[ -n "$status_output" ]]
}

sync_repo_to_origin() {
  local repo_dir="$1"
  local backup_env=""
  local backup_data_dir=""
  local synced=0

  if [[ "$BOOTSTRAP_FORCE_UPDATE" == "1" && -f "$repo_dir/config.env" ]]; then
    backup_env="$(mktemp 2>/dev/null || true)"
    if [[ -n "$backup_env" ]]; then
      cp -f "$repo_dir/config.env" "$backup_env"
    fi
  fi

  if [[ "$BOOTSTRAP_FORCE_UPDATE" == "1" && -d "$repo_dir/data" ]]; then
    backup_data_dir="$(mktemp -d 2>/dev/null || true)"
    if [[ -n "$backup_data_dir" && -d "$backup_data_dir" ]]; then
      cp -a "$repo_dir/data/." "$backup_data_dir/" 2>/dev/null || true
    fi
  fi

  if git -C "$repo_dir" fetch origin "$BRANCH" && \
     (git -C "$repo_dir" checkout -f "$BRANCH" || git -C "$repo_dir" checkout -f -B "$BRANCH" "origin/$BRANCH") && \
     git -C "$repo_dir" reset --hard "origin/$BRANCH"; then
    synced=1
  fi

  if [[ -n "$backup_env" && -f "$backup_env" ]]; then
    cp -f "$backup_env" "$repo_dir/config.env"
    rm -f "$backup_env"
  fi

  if [[ -n "$backup_data_dir" && -d "$backup_data_dir" ]]; then
    mkdir -p "$repo_dir/data"
    cp -a "$backup_data_dir/." "$repo_dir/data/" 2>/dev/null || true
    rm -rf "$backup_data_dir"
  fi

  [[ "$synced" -eq 1 ]]
}

is_repo_ready() {
  local repo_dir="$1"
  [[ -f "$repo_dir/control.sh" && -f "$repo_dir/install.sh" && -f "$repo_dir/uninstall.sh" ]]
}

is_bootstrap_mode() {
  local app_dir_real boot_dir_real
  app_dir_real="$(cd "${APP_DIR}" 2>/dev/null && pwd || echo "${APP_DIR}")"
  boot_dir_real="$(cd "${BOOTSTRAP_DIR}" 2>/dev/null && pwd || echo "${BOOTSTRAP_DIR}")"

  if [[ "$app_dir_real" != "$boot_dir_real" ]]; then
    return 0
  fi

  if ! is_repo_ready "$APP_DIR"; then
    return 0
  fi

  return 1
}

sync_repo_to_bootstrap_dir() {
  require_root
  ensure_git

  log "Bootstrap mode: using repository directory $BOOTSTRAP_DIR"
  log "Syncing repository to $BOOTSTRAP_DIR (branch: $BRANCH)"

  mkdir -p "$(dirname "$BOOTSTRAP_DIR")"
  if [[ -d "$BOOTSTRAP_DIR/.git" ]]; then
    local repo_state=1
    if repo_has_local_changes "$BOOTSTRAP_DIR"; then
      repo_state=0
    else
      repo_state="$?"
    fi

    if [[ "$repo_state" -eq 2 ]]; then
      die "Unable to inspect repository state for $BOOTSTRAP_DIR, cannot continue deployment."
    elif [[ "$repo_state" -eq 0 && "$BOOTSTRAP_FORCE_UPDATE" != "1" ]]; then
      warn "Detected local changes in $BOOTSTRAP_DIR."
      BOOTSTRAP_FORCE_UPDATE="1"
      warn "Auto-confirmed force sync to origin/$BRANCH while preserving config.env and data/."
    fi

    if [[ "$repo_state" -eq 0 ]]; then
      warn "Local changes detected and BOOTSTRAP_FORCE_UPDATE=1 is set, forcing sync to origin/$BRANCH while preserving config.env and data/."
    fi
    if ! sync_repo_to_origin "$BOOTSTRAP_DIR"; then
      die "Repository sync failed, deployment aborted."
    fi
  else
    if [[ -e "$BOOTSTRAP_DIR" ]] && [[ -n "$(ls -A "$BOOTSTRAP_DIR" 2>/dev/null || true)" ]]; then
      die "Bootstrap target directory is not empty: $BOOTSTRAP_DIR"
    fi
    git clone --depth 1 -b "$BRANCH" "$REPO_URL" "$BOOTSTRAP_DIR"
  fi

  chmod +x "$BOOTSTRAP_DIR/control.sh" "$BOOTSTRAP_DIR/install.sh" "$BOOTSTRAP_DIR/uninstall.sh" || true
}

check_repo_remote_update() {
  local repo_dir="$1"
  local branch="$2"
  local local_head=""
  local remote_head=""
  local fetch_output=""

  CHECK_REPO_LAST_ERROR=""

  if [[ ! -d "$repo_dir/.git" ]]; then
    CHECK_REPO_LAST_ERROR="部署目录不是 Git 仓库"
    return 3
  fi

  if ! fetch_output="$(git -C "$repo_dir" fetch --quiet origin "$branch" 2>&1)"; then
    CHECK_REPO_LAST_ERROR="$(printf '%s' "$fetch_output" | head -n1)"
    [[ -n "$CHECK_REPO_LAST_ERROR" ]] || CHECK_REPO_LAST_ERROR="git fetch 失败"
    return 2
  fi

  local_head="$(git -C "$repo_dir" rev-parse HEAD 2>/dev/null || true)"
  remote_head="$(git -C "$repo_dir" rev-parse "origin/$branch" 2>/dev/null || true)"

  if [[ -z "$local_head" || -z "$remote_head" ]]; then
    CHECK_REPO_LAST_ERROR="无法解析本地或远端提交"
    return 2
  fi

  if [[ "$local_head" == "$remote_head" ]]; then
    return 1
  fi

  if git -C "$repo_dir" merge-base --is-ancestor "$local_head" "$remote_head" >/dev/null 2>&1; then
    return 0
  fi

  if git -C "$repo_dir" merge-base --is-ancestor "$remote_head" "$local_head" >/dev/null 2>&1; then
    return 1
  fi

  CHECK_REPO_LAST_ERROR="本地与远端分叉，无法自动判断更新"
  return 4
}

bootstrap_handoff_with_update_check() {
  if ! has_cmd git; then
    warn "未找到 git，跳过远端更新检查，直接调用本地版本。"
    return
  fi

  local branch="$BRANCH"
  local update_state=0

  log "检查 GitHub 仓库是否有更新（分支：$branch）..."
  check_repo_remote_update "$BOOTSTRAP_DIR" "$branch"
  update_state=$?

  if [[ "$update_state" -eq 0 ]]; then
    log "检测到新版本，准备同步本地版本。"

    if repo_has_local_changes "$BOOTSTRAP_DIR"; then
      warn "本地仓库存在未提交改动，已跳过自动同步。"
      warn "请手动处理改动后再更新。"
      return
    fi

    if ! sync_repo_to_origin "$BOOTSTRAP_DIR"; then
      warn "自动同步失败，将继续调用本地版本。"
      return
    fi

    log "本地版本已同步到最新。"
    return
  fi

  case "$update_state" in
    1)
      log "GitHub 无更新，调用本地版本。"
      ;;
    3)
      warn "${CHECK_REPO_LAST_ERROR}，跳过远端检查，调用本地版本。"
      ;;
    4)
      warn "${CHECK_REPO_LAST_ERROR}，已跳过自动更新，调用本地版本。"
      ;;
    *)
      warn "检查远端更新失败：${CHECK_REPO_LAST_ERROR:-未知原因}，调用本地版本。"
      ;;
  esac
}

detect_service_mgr() {
  if has_cmd systemctl && [[ -d /run/systemd/system ]]; then
    echo "systemd"
    return
  fi

  if has_cmd rc-service; then
    echo "openrc"
    return
  fi

  if has_cmd service; then
    echo "sysv"
    return
  fi

  echo "none"
}

SERVICE_MGR="$(detect_service_mgr)"

service_restart() {
  case "$SERVICE_MGR" in
    systemd) systemctl restart "$SERVICE_NAME" ;;
    openrc) rc-service "$SERVICE_NAME" restart ;;
    sysv) service "$SERVICE_NAME" restart ;;
    *) die "未找到受支持的服务管理器" ;;
  esac
}

service_stop() {
  case "$SERVICE_MGR" in
    systemd) systemctl stop "$SERVICE_NAME" ;;
    openrc) rc-service "$SERVICE_NAME" stop ;;
    sysv) service "$SERVICE_NAME" stop ;;
    *) die "未找到受支持的服务管理器" ;;
  esac
}

service_status() {
  case "$SERVICE_MGR" in
    systemd) systemctl status "$SERVICE_NAME" --no-pager ;;
    openrc) rc-service "$SERVICE_NAME" status ;;
    sysv) service "$SERVICE_NAME" status ;;
    *) die "未找到受支持的服务管理器" ;;
  esac
}

service_is_running() {
  case "$SERVICE_MGR" in
    systemd)
      systemctl is-active --quiet "$SERVICE_NAME" >/dev/null 2>&1
      return
      ;;
    openrc)
      rc-service "$SERVICE_NAME" status >/dev/null 2>&1
      return
      ;;
    sysv)
      service "$SERVICE_NAME" status >/dev/null 2>&1
      return
      ;;
    *)
      return 2
      ;;
  esac
}

project_status_text() {
  if service_is_running; then
    echo "运行中"
    return
  fi

  if [[ "$?" -ne 1 ]]; then
    echo "未知"
    return
  fi

  if is_bootstrap_mode; then
    echo "未部署"
  else
    echo "未运行"
  fi
}

daemon_reload() {
  case "$SERVICE_MGR" in
    systemd) systemctl daemon-reload ;;
    openrc|sysv|none) ;;
  esac
}

detect_os() {
  if [[ -r /etc/os-release ]]; then
    # shellcheck disable=SC1091
    . /etc/os-release
    printf '%s %s\n' "${NAME:-unknown}" "${VERSION_ID:-}"
    return
  fi
  uname -s
}

pick_python_bin() {
  if [[ -n "$PYTHON_BIN" ]] && has_cmd "$PYTHON_BIN"; then
    echo "$PYTHON_BIN"
    return
  fi
  if has_cmd python3; then
    echo "python3"
    return
  fi
  if has_cmd python; then
    echo "python"
    return
  fi
  die "未找到 python3 或 python"
}

auto_port() {
  local py
  py="$(pick_python_bin)"
  "$py" - <<'PY'
import socket
s = socket.socket()
s.bind(("", 0))
print(s.getsockname()[1])
s.close()
PY
}

is_valid_port() {
  local port="$1"
  [[ "$port" =~ ^[0-9]+$ ]] || return 1
  (( port >= 1 && port <= 65535 ))
}

is_port_available() {
  local port="$1"
  local py
  py="$(pick_python_bin)"
  "$py" - <<PY
import socket
import sys

port = int(${port})
s = socket.socket()
try:
    s.bind(("0.0.0.0", port))
except OSError:
    sys.exit(1)
finally:
    s.close()
sys.exit(0)
PY
}

set_env_key() {
  local key="$1"
  local value="$2"

  touch "$ENV_FILE"
  if grep -qE "^${key}=" "$ENV_FILE"; then
    sed -i "s#^${key}=.*#${key}=${value}#" "$ENV_FILE"
  else
    printf '\n%s=%s\n' "$key" "$value" >>"$ENV_FILE"
  fi
}

get_env_key() {
  local key="$1"
  if [[ ! -f "$ENV_FILE" ]]; then
    return
  fi
  grep -E "^${key}=" "$ENV_FILE" | head -n1 | cut -d= -f2- | tr -d '\r' | xargs || true
}

get_port() {
  local port
  port="$(get_env_key PORT)"
  if [[ -z "$port" || "$port" == "auto" ]]; then
    port="8000"
  fi
  echo "$port"
}

detect_local_ip() {
  local ip=""
  if has_cmd ip; then
    ip="$(ip -4 route get 1.1.1.1 2>/dev/null | awk '{for(i=1;i<=NF;i++) if ($i=="src"){print $(i+1); exit}}')"
  fi
  if [[ -z "$ip" ]] && has_cmd hostname; then
    ip="$(hostname -I 2>/dev/null | awk '{print $1}')"
  fi
  echo "${ip:-127.0.0.1}"
}

detect_public_ip() {
  if ! has_cmd curl; then
    return
  fi
  local ip=""
  ip="$(curl -fsS --max-time 3 https://api.ipify.org 2>/dev/null || true)"
  if [[ -n "$ip" ]]; then
    echo "$ip"
  fi
}

pick_access_url() {
  local port="$1"
  local local_ip="$2"
  local public_ip="$3"

  if [[ -n "$public_ip" && "$public_ip" != "$local_ip" ]]; then
    echo "http://${public_ip}:${port}/"
    return
  fi

  echo "http://${local_ip}:${port}/"
}

show_access_urls() {
  local port local_ip public_ip access_url
  local url_suffix=""
  local sub_token=""
  local suffix_base_url=""
  port="$(get_port)"
  local_ip="$(detect_local_ip)"
  public_ip="$(detect_public_ip || true)"
  access_url="$(pick_access_url "$port" "$local_ip" "$public_ip")"
  url_suffix="$(get_env_key URL_SUFFIX)"
  sub_token="$(get_env_key SUB_TOKEN)"

  if [[ -n "$url_suffix" ]]; then
    suffix_base_url="${access_url%/}/${url_suffix}/"
  else
    suffix_base_url="$access_url"
  fi

  echo "----------------------------------------"
  echo "端口：$port"
  echo "地址：$suffix_base_url"
  echo "内网地址：http://${local_ip}:${port}/"
  if [[ -n "$public_ip" && "$public_ip" != "$local_ip" ]]; then
    echo "公网地址：http://${public_ip}:${port}/"
  fi
  if [[ -n "$url_suffix" ]]; then
    echo "首次初始化页面：http://${local_ip}:${port}/${url_suffix}/setup"
  else
    echo "首次初始化页面：http://${local_ip}:${port}/setup"
  fi

  if [[ -n "$sub_token" ]]; then
    if [[ -n "$url_suffix" ]]; then
      echo "安全后缀：${url_suffix}"
    else
      echo "安全后缀：未设置"
    fi
    echo "订阅示例（请将 <sid> 替换为你的订阅ID）："
    echo "${suffix_base_url}pub/s/<sid>/v2ray?token=${sub_token}"
  else
    echo "提示：SUB_TOKEN 未设置，公共订阅链接暂不可用。"
  fi

  echo "----------------------------------------"
}

show_menu() {
  local bootstrap_mode=0
  local project_status=""
  if is_bootstrap_mode; then
    bootstrap_mode=1
  fi
  project_status="$(project_status_text)"

  echo "=============================="
  echo " 订阅转换管理器控制器"
  echo " 当前项目状态：$project_status"
  echo "=============================="
  if [[ "$bootstrap_mode" -eq 1 ]]; then
    echo "1) 部署环境（下载仓库并安装）"
  else
    echo "1) 安装或更新"
  fi
  echo "2) 卸载服务并删除全部下载内容"
  echo "3) 重启服务"
  echo "4) 停止服务"
  echo "5) 查看服务状态与访问地址"
  echo "6) 修改自定义端口"
  echo "7) 仅显示访问地址"
  echo "8) 从 GitHub 更新网站版本"
  echo "9) 设置网址后缀安全（URL_SUFFIX）"
  echo "0) 退出"
  if [[ "$bootstrap_mode" -eq 1 ]]; then
    echo "提示：首次运行请先选择 1)，部署完成后会自动进入完整控制菜单。"
  fi
  echo "------------------------------"
}

prompt_choice() {
  local __var_name="$1"
  local prompt="$2"
  local input=""

  if [[ -r /dev/tty ]]; then
    if ! read -r -p "$prompt" input </dev/tty; then
      return 1
    fi
  else
    if ! read -r -p "$prompt" input; then
      return 1
    fi
  fi

  printf -v "$__var_name" '%s' "$input"
}

prompt_install_port_choice() {
  local __var_name="$1"
  local input_port=""
  local current_port=""

  if ! prompt_choice input_port "安装/更新端口（1-65535，回车=随机端口）："; then
    warn "未读取到输入，已取消安装/更新。"
    return 1
  fi

  input_port="$(printf '%s' "$input_port" | tr -d '[:space:]')"
  if [[ -z "$input_port" ]]; then
    printf -v "$__var_name" '%s' "auto"
    return 0
  fi

  if ! is_valid_port "$input_port"; then
    warn "无效端口：$input_port。请输入 1-65535，或直接回车使用随机端口。"
    return 1
  fi

  current_port="$(get_port)"
  if [[ "$input_port" != "$current_port" ]] && ! is_port_available "$input_port"; then
    warn "端口已被占用：$input_port，请更换端口。"
    return 1
  fi

  printf -v "$__var_name" '%s' "$input_port"
}

require_deployed_env() {
  if is_bootstrap_mode; then
    warn "当前是引导模式，请先选择 1) 部署环境（下载仓库并安装）。"
    return 1
  fi
  return 0
}

do_install() {
  require_root
  local install_port=""

  if ! prompt_install_port_choice install_port; then
    return
  fi

  if [[ "$install_port" == "auto" ]]; then
    log "未指定端口，将自动选择随机端口。"
  else
    log "使用端口：$install_port"
  fi

  if is_bootstrap_mode; then
    sync_repo_to_bootstrap_dir
    INSTALL_PORT_OVERRIDE="$install_port" bash "$BOOTSTRAP_DIR/install.sh"
    exec bash "$BOOTSTRAP_DIR/control.sh"
  fi

  INSTALL_PORT_OVERRIDE="$install_port" bash "$APP_DIR/install.sh"
  show_access_urls
}

do_uninstall() {
  require_root

  local confirm=""
  if ! prompt_choice confirm "确认卸载并删除全部下载内容？此操作不可恢复 [y/N]: "; then
    warn "未读取到输入，已取消卸载。"
    return
  fi
  confirm="$(printf '%s' "$confirm" | tr '[:upper:]' '[:lower:]')"
  if [[ "$confirm" != "y" && "$confirm" != "yes" ]]; then
    echo "已取消卸载。"
    return
  fi

  bash "$APP_DIR/uninstall.sh"
  echo "已卸载并删除全部下载内容。"
  exit 0
}

do_restart() {
  require_root
  service_restart
  echo "服务已重启。"
  show_access_urls
}

do_stop() {
  require_root
  service_stop
  echo "服务已停止。"
}

do_status() {
  service_status || true
  show_access_urls
}

do_change_port() {
  require_root

  local new_port current_port
  current_port="$(get_port)"

  if ! prompt_choice new_port "请输入自定义端口（1-65535，0 取消）："; then
    warn "未读取到输入，已取消修改端口。"
    return
  fi
  new_port="$(printf '%s' "$new_port" | tr -d '[:space:]')"

  if [[ "$new_port" == "0" ]]; then
    echo "已取消修改端口。"
    return
  fi
  if ! is_valid_port "$new_port"; then
    warn "无效端口：$new_port。请输入 1-65535 之间的数字。"
    return
  fi
  if [[ "$new_port" == "$current_port" ]]; then
    echo "端口未变化：$new_port"
    return
  fi
  if ! is_port_available "$new_port"; then
    warn "端口已被占用：$new_port，请更换端口。"
    return
  fi

  set_env_key "PORT" "$new_port"

  if [[ -f "$SERVICE_FILE_SYSTEMD" ]]; then
    sed -i -E "s/--port [0-9]+/--port ${new_port}/g" "$SERVICE_FILE_SYSTEMD"
  fi
  if [[ -f "$SERVICE_FILE_OPENRC" ]]; then
    sed -i -E "s/--port [0-9]+/--port ${new_port}/g" "$SERVICE_FILE_OPENRC"
  fi
  if [[ -f "$SERVICE_FILE_SYSV" ]]; then
    sed -i -E "s/--port [0-9]+/--port ${new_port}/g" "$SERVICE_FILE_SYSV"
  fi
  daemon_reload

  service_restart
  echo "已切换到自定义端口：$new_port"
  show_access_urls
}

do_update_from_github() {
  require_root
  ensure_git

  if [[ ! -d "$APP_DIR/.git" ]]; then
    die "当前目录不是 Git 仓库，无法更新。"
  fi

  local branch="$BRANCH"
  local update_state=0

  log "检查 GitHub 是否有更新（分支：$branch）..."
  check_repo_remote_update "$APP_DIR" "$branch"
  update_state=$?
  if [[ "$update_state" -ne 0 ]]; then
    if [[ "$update_state" -eq 1 ]]; then
      echo "当前已是最新版本，无需更新。"
      return
    fi

    if [[ "$update_state" -eq 4 ]]; then
      die "${CHECK_REPO_LAST_ERROR}，请先处理本地分支后再更新。"
    fi

    die "检查远端更新失败：${CHECK_REPO_LAST_ERROR:-未知原因}"
  fi

  if repo_has_local_changes "$APP_DIR"; then
    warn "检测到本地未提交改动，已取消自动更新以避免覆盖。"
    warn "请先提交或清理本地改动后再执行更新。"
    return
  fi

  log "检测到新版本，开始更新..."
  if ! git -C "$APP_DIR" checkout "$branch" >/dev/null 2>&1; then
    if ! git -C "$APP_DIR" checkout -B "$branch" "origin/$branch" >/dev/null 2>&1; then
      die "切换分支失败：$branch"
    fi
  fi

  if ! git -C "$APP_DIR" merge --ff-only "origin/$branch"; then
    die "更新失败：无法快进合并，请检查仓库状态。"
  fi

  if service_is_running; then
    service_restart
    echo "已更新到最新版本，并重启服务。"
  else
    echo "已更新到最新版本。服务当前未运行，可按需手动启动。"
  fi

  show_access_urls
}

is_valid_url_suffix() {
  local suffix="$1"
  [[ "$suffix" =~ ^[A-Za-z0-9_-]{3,5}$ ]]
}

generate_random_suffix() {
  local random_suffix=""
  local target_len=3
  target_len=$((RANDOM % 3 + 3))

  random_suffix="$(tr -dc 'A-Za-z0-9' </dev/urandom 2>/dev/null | head -c "$target_len" || true)"
  if [[ -z "$random_suffix" ]]; then
    random_suffix="$(date +%s%N | sha256sum 2>/dev/null | awk '{print $1}' | cut -c1-5 || true)"
  fi
  if [[ -z "$random_suffix" ]]; then
    random_suffix="abc"
  fi
  if [[ ${#random_suffix} -lt 3 ]]; then
    random_suffix="abc"
  fi
  if [[ ${#random_suffix} -gt 5 ]]; then
    random_suffix="${random_suffix:0:5}"
  fi
  echo "$random_suffix"
}

do_set_url_suffix() {
  require_root

  local current_suffix=""
  local new_suffix=""

  current_suffix="$(get_env_key URL_SUFFIX)"
  echo "当前 URL_SUFFIX：${current_suffix:-未设置}"

  if ! prompt_choice new_suffix "请输入新的网址后缀（留空自动生成，3-5位，仅字母数字_-）："; then
    warn "未读取到输入，已取消设置。"
    return
  fi

  new_suffix="$(printf '%s' "$new_suffix" | tr -d '[:space:]')"
  if [[ -z "$new_suffix" ]]; then
    new_suffix="$(generate_random_suffix)"
    log "未输入后缀，已自动生成。"
  fi

  if ! is_valid_url_suffix "$new_suffix"; then
    warn "后缀格式无效：仅支持 3-5 位字母、数字、下划线、短横线。"
    return
  fi

  set_env_key "URL_SUFFIX" "$new_suffix"
  echo "已更新 URL_SUFFIX：$new_suffix"
  echo "注意：后缀通过路径使用，例如 /$new_suffix"

  if service_is_running; then
    service_restart
    echo "服务已重启，新的安全后缀已生效。"
  else
    echo "服务未运行。启动后新的安全后缀会生效。"
  fi

  show_access_urls
}

main() {
  if is_bootstrap_mode && is_repo_ready "$BOOTSTRAP_DIR"; then
    bootstrap_handoff_with_update_check
    log "检测到已部署目录，切换到本地控制器：$BOOTSTRAP_DIR/control.sh"
    exec bash "$BOOTSTRAP_DIR/control.sh" "$@"
  fi

  while true; do
    show_menu
    if ! prompt_choice choice "请选择操作："; then
      warn "未读取到输入，请在交互式终端中运行控制脚本。"
      exit 1
    fi
    case "$choice" in
      1) do_install ;;
      2)
        if require_deployed_env; then
          do_uninstall
        fi
        ;;
      3)
        if require_deployed_env; then
          do_restart
        fi
        ;;
      4)
        if require_deployed_env; then
          do_stop
        fi
        ;;
      5)
        if require_deployed_env; then
          do_status
        fi
        ;;
      6)
        if require_deployed_env; then
          do_change_port
        fi
        ;;
      7)
        if require_deployed_env; then
          show_access_urls
        fi
        ;;
      8)
        if require_deployed_env; then
          do_update_from_github
        fi
        ;;
      9)
        if require_deployed_env; then
          do_set_url_suffix
        fi
        ;;
      0) exit 0 ;;
      *) echo "无效选项，请重新输入。" ;;
    esac
    echo
  done
}

main "$@"

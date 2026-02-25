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
PYTHON_BIN="${PYTHON_BIN:-}"
REPO_URL="${REPO_URL:-https://github.com/HlONGlin/subconvert-manager.git}"
BRANCH="${BRANCH:-main}"
BOOTSTRAP_DIR="${BOOTSTRAP_DIR:-/opt/subconvert-manager}"
BOOTSTRAP_FORCE_UPDATE="${BOOTSTRAP_FORCE_UPDATE:-0}"

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
  local synced=0

  if [[ "$BOOTSTRAP_FORCE_UPDATE" == "1" && -f "$repo_dir/config.env" ]]; then
    backup_env="$(mktemp 2>/dev/null || true)"
    if [[ -n "$backup_env" ]]; then
      cp -f "$repo_dir/config.env" "$backup_env"
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

  [[ "$synced" -eq 1 ]]
}

bootstrap_repo_if_needed() {
  if [[ -f "$APP_DIR/install.sh" && -f "$APP_DIR/uninstall.sh" ]]; then
    return
  fi

  require_root
  ensure_git

  log "引导模式：当前路径不是完整项目目录"
  log "正在同步仓库到 $BOOTSTRAP_DIR（分支：$BRANCH）"

  mkdir -p "$(dirname "$BOOTSTRAP_DIR")"
  if [[ -d "$BOOTSTRAP_DIR/.git" ]]; then
    local repo_state=1
    if repo_has_local_changes "$BOOTSTRAP_DIR"; then
      repo_state=0
    else
      repo_state="$?"
    fi

    if [[ "$repo_state" -eq 2 ]]; then
      warn "Unable to inspect repository state for $BOOTSTRAP_DIR, skipping auto-sync and using local copy."
    elif [[ "$repo_state" -eq 0 && "$BOOTSTRAP_FORCE_UPDATE" != "1" ]]; then
      warn "Detected local changes in $BOOTSTRAP_DIR, skipping auto-sync and using local copy."
      warn "To force sync to origin/$BRANCH, run: BOOTSTRAP_FORCE_UPDATE=1 sudo bash control.sh"
    else
      if [[ "$repo_state" -eq 0 ]]; then
        warn "Local changes detected and BOOTSTRAP_FORCE_UPDATE=1 is set, forcing sync to origin/$BRANCH while preserving config.env."
      fi
      if ! sync_repo_to_origin "$BOOTSTRAP_DIR"; then
        warn "Repository auto-sync failed, continuing with the local version."
      fi
    fi
  else
    if [[ -e "$BOOTSTRAP_DIR" ]] && [[ -n "$(ls -A "$BOOTSTRAP_DIR" 2>/dev/null || true)" ]]; then
      die "引导目标目录非空：$BOOTSTRAP_DIR"
    fi
    git clone --depth 1 -b "$BRANCH" "$REPO_URL" "$BOOTSTRAP_DIR"
  fi

  chmod +x "$BOOTSTRAP_DIR/control.sh" "$BOOTSTRAP_DIR/install.sh" "$BOOTSTRAP_DIR/uninstall.sh" || true
  exec bash "$BOOTSTRAP_DIR/control.sh" "$@"
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

show_access_urls() {
  local port local_ip public_ip
  port="$(get_port)"
  local_ip="$(detect_local_ip)"
  public_ip="$(detect_public_ip || true)"

  echo "----------------------------------------"
  echo "端口：$port"
  echo "内网地址：http://${local_ip}:${port}/"
  if [[ -n "$public_ip" && "$public_ip" != "$local_ip" ]]; then
    echo "公网地址：http://${public_ip}:${port}/"
  fi
  echo "首次初始化页面：http://${local_ip}:${port}/setup"
  echo "----------------------------------------"
}

show_menu() {
  echo "=============================="
  echo " 订阅转换管理器控制器"
  echo "=============================="
  echo "1) 安装或更新"
  echo "2) 卸载服务（保留数据目录）"
  echo "3) 重启服务"
  echo "4) 停止服务"
  echo "5) 查看服务状态与访问地址"
  echo "6) 切换到随机空闲端口"
  echo "7) 仅显示访问地址"
  echo "0) 退出"
  echo "------------------------------"
}

do_install() {
  require_root
  bash "$APP_DIR/install.sh"
  show_access_urls
}

do_uninstall() {
  require_root
  bash "$APP_DIR/uninstall.sh"
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

  local new_port
  new_port="$(auto_port)"
  set_env_key "PORT" "$new_port"

  if [[ "$SERVICE_MGR" == "systemd" && -f "$SERVICE_FILE_SYSTEMD" ]]; then
    sed -i -E "s/--port [0-9]+/--port ${new_port}/g" "$SERVICE_FILE_SYSTEMD"
    daemon_reload
  fi

  service_restart
  echo "已切换到新端口：$new_port"
  show_access_urls
}

main() {
  while true; do
    show_menu
    read -r -p "请选择操作：" choice
    case "$choice" in
      1) do_install ;;
      2) do_uninstall ;;
      3) do_restart ;;
      4) do_stop ;;
      5) do_status ;;
      6) do_change_port ;;
      7) show_access_urls ;;
      0) exit 0 ;;
      *) echo "无效选项，请重新输入。" ;;
    esac
    echo
  done
}

bootstrap_repo_if_needed "$@"
main "$@"

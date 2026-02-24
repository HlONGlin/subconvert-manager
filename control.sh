#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$APP_DIR/config.env"
SERVICE_NAME="subconvert-manager"
SERVICE_FILE_SYSTEMD="/etc/systemd/system/${SERVICE_NAME}.service"
PYTHON_BIN="${PYTHON_BIN:-}"

log() {
  printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"
}

warn() {
  printf '[%s] WARN: %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >&2
}

die() {
  printf '[%s] ERROR: %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >&2
  exit 1
}

has_cmd() {
  command -v "$1" >/dev/null 2>&1
}

require_root() {
  if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
    die "Please run as root: sudo bash control.sh"
  fi
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
    *) die "No supported service manager found" ;;
  esac
}

service_stop() {
  case "$SERVICE_MGR" in
    systemd) systemctl stop "$SERVICE_NAME" ;;
    openrc) rc-service "$SERVICE_NAME" stop ;;
    sysv) service "$SERVICE_NAME" stop ;;
    *) die "No supported service manager found" ;;
  esac
}

service_status() {
  case "$SERVICE_MGR" in
    systemd) systemctl status "$SERVICE_NAME" --no-pager ;;
    openrc) rc-service "$SERVICE_NAME" status ;;
    sysv) service "$SERVICE_NAME" status ;;
    *) die "No supported service manager found" ;;
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
  die "python3/python not found"
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
  echo "Service manager: $SERVICE_MGR"
  echo "Detected OS: $(detect_os)"
  echo "Port: $port"
  echo "Local URL:  http://${local_ip}:${port}/"
  if [[ -n "$public_ip" && "$public_ip" != "$local_ip" ]]; then
    echo "Public URL: http://${public_ip}:${port}/"
  fi
  echo "First-time setup URL: /setup"
  echo "----------------------------------------"
}

show_menu() {
  echo "=============================="
  echo " SubConvert Manager Control"
  echo "=============================="
  echo "1) Install / Update"
  echo "2) Uninstall service (keep data/)"
  echo "3) Restart service"
  echo "4) Stop service"
  echo "5) Service status + access URL"
  echo "6) Change to a random free port"
  echo "7) Show access URL only"
  echo "0) Exit"
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
  echo "Service restarted."
  show_access_urls
}

do_stop() {
  require_root
  service_stop
  echo "Service stopped."
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
  echo "Switched to new port: $new_port"
  show_access_urls
}

main() {
  while true; do
    show_menu
    read -r -p "Select: " choice
    case "$choice" in
      1) do_install ;;
      2) do_uninstall ;;
      3) do_restart ;;
      4) do_stop ;;
      5) do_status ;;
      6) do_change_port ;;
      7) show_access_urls ;;
      0) exit 0 ;;
      *) echo "Invalid option." ;;
    esac
    echo
  done
}

main "$@"

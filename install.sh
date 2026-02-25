#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

SCRIPT_PATH="${BASH_SOURCE[0]:-${0:-.}}"
if [[ "$SCRIPT_PATH" == "bash" || "$SCRIPT_PATH" == "-bash" ]]; then
  SCRIPT_PATH="."
fi
APP_DIR="$(cd "$(dirname "$SCRIPT_PATH")" 2>/dev/null && pwd)"
ENV_FILE="$APP_DIR/config.env"
SERVICE_NAME="subconvert-manager"
SERVICE_FILE_SYSTEMD="/etc/systemd/system/${SERVICE_NAME}.service"
SERVICE_FILE_OPENRC="/etc/init.d/${SERVICE_NAME}"
SERVICE_FILE_SYSV="/etc/init.d/${SERVICE_NAME}"
VENV_DIR="$APP_DIR/.venv"
PYTHON_BIN="${PYTHON_BIN:-}"
UVICORN_HOST="${UVICORN_HOST:-0.0.0.0}"
SERVICE_MGR="${SERVICE_MGR:-}"

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
    die "Please run as root: sudo bash install.sh"
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

detect_service_mgr() {
  if [[ -n "$SERVICE_MGR" ]]; then
    echo "$SERVICE_MGR"
    return
  fi
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

install_system_packages() {
  local pm
  pm="$(detect_pkg_manager)"
  log "Detected package manager: $pm"

  case "$pm" in
    apt)
      export DEBIAN_FRONTEND=noninteractive
      apt-get update -y
      apt-get install -y --no-install-recommends \
        python3 \
        python3-venv \
        python3-pip \
        ca-certificates \
        curl
      ;;
    dnf)
      dnf -y install \
        python3 \
        python3-pip \
        python3-virtualenv \
        ca-certificates \
        curl
      ;;
    yum)
      yum -y install \
        python3 \
        python3-pip \
        ca-certificates \
        curl || true
      ;;
    zypper)
      zypper --non-interactive install --no-recommends \
        python3 \
        python3-pip \
        python3-virtualenv \
        ca-certificates \
        curl
      ;;
    pacman)
      pacman -Sy --noconfirm \
        python \
        python-pip \
        ca-certificates \
        curl
      ;;
    apk)
      apk add --no-cache \
        python3 \
        py3-pip \
        py3-virtualenv \
        ca-certificates \
        curl
      ;;
    *)
      die "Unsupported Linux package manager"
      ;;
  esac
}

ensure_env_file() {
  if [[ ! -f "$ENV_FILE" ]]; then
    cat >"$ENV_FILE" <<'EOF'
PORT=auto
BASIC_AUTH_USER=admin
BASIC_AUTH_PASS=change_me_please
TIMEOUT=15
DATA_FILE=data/sources.json
SUB_TOKEN=
SESSION_SECRET=
AUTH_MODE=both
EOF
    log "Created default config.env"
  fi
}

set_env_key() {
  local key="$1"
  local value="$2"

  if grep -qE "^${key}=" "$ENV_FILE"; then
    sed -i "s#^${key}=.*#${key}=${value}#" "$ENV_FILE"
  else
    printf '\n%s=%s\n' "$key" "$value" >>"$ENV_FILE"
  fi
}

get_env_key() {
  local key="$1"
  grep -E "^${key}=" "$ENV_FILE" | head -n1 | cut -d= -f2- | tr -d '\r' | xargs || true
}

gen_secret() {
  local py
  py="$(pick_python_bin)"
  "$py" - <<'PY'
import secrets
print(secrets.token_urlsafe(32))
PY
}

pick_free_port() {
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

is_port_available() {
  local port="$1"
  local py
  py="$(pick_python_bin)"
  "$py" - <<PY
import socket
port = int(${port})
s = socket.socket()
try:
    s.bind(("0.0.0.0", port))
except OSError:
    print("0")
else:
    print("1")
finally:
    s.close()
PY
}

normalize_port() {
  local raw
  raw="$(get_env_key PORT)"

  if [[ -z "$raw" || "$raw" == "auto" ]]; then
    raw="$(pick_free_port)"
    set_env_key "PORT" "$raw"
    echo "$raw"
    return
  fi

  if [[ ! "$raw" =~ ^[0-9]+$ ]] || (( raw < 1 || raw > 65535 )); then
    warn "Invalid PORT='$raw', auto-selecting a free port"
    raw="$(pick_free_port)"
    set_env_key "PORT" "$raw"
    echo "$raw"
    return
  fi

  if [[ "$(is_port_available "$raw")" != "1" ]]; then
    warn "PORT=$raw is in use, auto-selecting another free port"
    raw="$(pick_free_port)"
    set_env_key "PORT" "$raw"
  fi

  echo "$raw"
}

normalize_runtime_secrets() {
  local sub_token session_secret

  sub_token="$(get_env_key SUB_TOKEN)"
  if [[ -z "$sub_token" ]]; then
    sub_token="$(gen_secret)"
    set_env_key "SUB_TOKEN" "$sub_token"
    log "Generated SUB_TOKEN"
  fi

  session_secret="$(get_env_key SESSION_SECRET)"
  if [[ -z "$session_secret" ]]; then
    session_secret="$(gen_secret)"
    set_env_key "SESSION_SECRET" "$session_secret"
    log "Generated SESSION_SECRET"
  fi
}

ensure_venv() {
  local py
  py="$(pick_python_bin)"
  local vpy="$VENV_DIR/bin/python"

  if [[ ! -d "$VENV_DIR" ]]; then
    log "Creating virtual environment"
    if ! "$py" -m venv "$VENV_DIR"; then
      "$py" -m virtualenv "$VENV_DIR"
    fi
    vpy="$VENV_DIR/bin/python"
  fi

  if [[ ! -x "$vpy" ]]; then
    warn "Virtualenv python not found, recreating venv"
    rm -rf "$VENV_DIR"
    if ! "$py" -m venv "$VENV_DIR"; then
      "$py" -m virtualenv "$VENV_DIR"
    fi
    vpy="$VENV_DIR/bin/python"
  fi

  if ! "$vpy" -m pip --version >/dev/null 2>&1; then
    log "pip missing in virtualenv, trying ensurepip"
    "$vpy" -m ensurepip --upgrade >/dev/null 2>&1 || true
  fi

  if ! "$vpy" -m pip --version >/dev/null 2>&1; then
    warn "ensurepip failed, recreating venv with virtualenv fallback"
    rm -rf "$VENV_DIR"
    if ! "$py" -m venv "$VENV_DIR"; then
      if has_cmd virtualenv; then
        virtualenv "$VENV_DIR"
      else
        "$py" -m pip install --upgrade virtualenv
        "$py" -m virtualenv "$VENV_DIR"
      fi
    fi
    vpy="$VENV_DIR/bin/python"
  fi

  if ! "$vpy" -m pip --version >/dev/null 2>&1; then
    warn "pip still missing after python -m venv, forcing virtualenv recreation"
    rm -rf "$VENV_DIR"

    if has_cmd virtualenv; then
      virtualenv "$VENV_DIR" || die "failed to recreate venv via virtualenv"
    else
      if ! "$py" -m pip install --upgrade pip virtualenv; then
        warn "Failed to install virtualenv via $py -m pip, trying system virtualenv if available"
      fi
      "$py" -m virtualenv "$VENV_DIR" || die "failed to recreate venv via $py -m virtualenv"
    fi

    vpy="$VENV_DIR/bin/python"
  fi

  if [[ ! -x "$VENV_DIR/bin/pip" && -x "$VENV_DIR/bin/pip3" ]]; then
    ln -sf pip3 "$VENV_DIR/bin/pip" || true
  fi

  "$vpy" -m pip --version >/dev/null 2>&1 || die "pip is still unavailable in virtualenv: $VENV_DIR"
}

pip_install_with_retry() {
  local py_bin="$1"
  local requirements="$2"
  local max_retry=3
  local n

  for n in $(seq 1 "$max_retry"); do
    if "$py_bin" -m pip install --no-cache-dir -r "$requirements"; then
      return
    fi
    warn "pip install failed (attempt ${n}/${max_retry})"
    sleep 2
  done

  die "pip install failed after ${max_retry} attempts"
}

install_python_deps() {
  local py_bin="$VENV_DIR/bin/python"
  [[ -x "$py_bin" ]] || die "python not found in virtualenv: $py_bin"
  "$py_bin" -m pip --version >/dev/null 2>&1 || die "pip not available in virtualenv: $VENV_DIR"

  log "Installing Python dependencies"
  "$py_bin" -m pip install --upgrade pip setuptools wheel
  pip_install_with_retry "$py_bin" "$APP_DIR/requirements.txt"
}

ensure_data_file() {
  local data_file data_file_abs

  data_file="$(get_env_key DATA_FILE)"
  [[ -n "$data_file" ]] || data_file="data/sources.json"

  if [[ "$data_file" = /* ]]; then
    data_file_abs="$data_file"
  else
    data_file_abs="$APP_DIR/$data_file"
  fi

  mkdir -p "$(dirname "$data_file_abs")"
  if [[ ! -f "$data_file_abs" ]]; then
    echo '{"sources":[]}' >"$data_file_abs"
    log "Initialized data file: $data_file_abs"
  fi
}

run_self_check() {
  local py_bin="$VENV_DIR/bin/python"
  log "Running syntax self-check"
  "$py_bin" -m py_compile "$APP_DIR/app.py" "$APP_DIR/converter.py" "$APP_DIR/storage.py"
}

write_systemd_service() {
  local port="$1"
  cat >"$SERVICE_FILE_SYSTEMD" <<EOF
[Unit]
Description=SubConvert Manager (Clash <-> V2Ray)
After=network.target

[Service]
Type=simple
WorkingDirectory=${APP_DIR}
EnvironmentFile=${ENV_FILE}
Environment=PYTHONUNBUFFERED=1
ExecStart=${VENV_DIR}/bin/uvicorn app:app --host ${UVICORN_HOST} --port ${port}
Restart=always
RestartSec=2

[Install]
WantedBy=multi-user.target
EOF
}

write_openrc_service() {
  local port="$1"
  cat >"$SERVICE_FILE_OPENRC" <<EOF
#!/sbin/openrc-run
name="${SERVICE_NAME}"
description="SubConvert Manager"
command="${VENV_DIR}/bin/uvicorn"
command_args="app:app --host ${UVICORN_HOST} --port ${port}"
directory="${APP_DIR}"
pidfile="/run/${SERVICE_NAME}.pid"
command_background=true

depend() {
  need net
}
EOF
  chmod +x "$SERVICE_FILE_OPENRC"
}

write_sysv_service() {
  local port="$1"
  cat >"$SERVICE_FILE_SYSV" <<EOF
#!/bin/sh
### BEGIN INIT INFO
# Provides:          ${SERVICE_NAME}
# Required-Start:    \$network \$remote_fs
# Required-Stop:     \$network \$remote_fs
# Default-Start:     2 3 4 5
# Default-Stop:      0 1 6
# Short-Description: SubConvert Manager
### END INIT INFO

DAEMON="${VENV_DIR}/bin/uvicorn"
DAEMON_ARGS="app:app --host ${UVICORN_HOST} --port ${port}"
APP_DIR="${APP_DIR}"
PIDFILE="/var/run/${SERVICE_NAME}.pid"

start() {
  echo "Starting ${SERVICE_NAME}"
  cd "\$APP_DIR" || exit 1
  start-stop-daemon --start --background --make-pidfile --pidfile "\$PIDFILE" --chdir "\$APP_DIR" --exec "\$DAEMON" -- \$DAEMON_ARGS
}

stop() {
  echo "Stopping ${SERVICE_NAME}"
  start-stop-daemon --stop --pidfile "\$PIDFILE" --retry 10
  rm -f "\$PIDFILE"
}

case "\$1" in
  start) start ;;
  stop) stop ;;
  restart) stop; start ;;
  status) [ -f "\$PIDFILE" ] && kill -0 \$(cat "\$PIDFILE") 2>/dev/null && echo "${SERVICE_NAME} is running" && exit 0; echo "${SERVICE_NAME} is not running"; exit 1 ;;
  *) echo "Usage: \$0 {start|stop|restart|status}"; exit 2 ;;
esac
exit 0
EOF
  chmod +x "$SERVICE_FILE_SYSV"
}

install_service() {
  local mgr="$1"
  local port="$2"

  case "$mgr" in
    systemd)
      write_systemd_service "$port"
      systemctl daemon-reload
      systemctl enable --now "$SERVICE_NAME"
      systemctl restart "$SERVICE_NAME"
      ;;
    openrc)
      write_openrc_service "$port"
      rc-update add "$SERVICE_NAME" default || true
      rc-service "$SERVICE_NAME" restart || rc-service "$SERVICE_NAME" start
      ;;
    sysv)
      write_sysv_service "$port"
      if has_cmd update-rc.d; then
        update-rc.d "$SERVICE_NAME" defaults || true
      elif has_cmd chkconfig; then
        chkconfig --add "$SERVICE_NAME" || true
      fi
      service "$SERVICE_NAME" restart || service "$SERVICE_NAME" start
      ;;
    *)
      warn "No supported service manager found. Start manually:"
      warn "cd ${APP_DIR} && ${VENV_DIR}/bin/uvicorn app:app --host ${UVICORN_HOST} --port ${port}"
      ;;
  esac
}

check_port_ready() {
  local port="$1"
  local py
  py="$(pick_python_bin)"
  "$py" - <<PY
import socket
import sys
port = int(${port})
s = socket.socket()
s.settimeout(1)
try:
    s.connect(("127.0.0.1", port))
except Exception:
    sys.exit(1)
finally:
    s.close()
sys.exit(0)
PY
}

wait_service_ready() {
  local mgr="$1"
  local port="$2"
  local max_wait=20
  local i

  if [[ "$mgr" == "none" ]]; then
    return
  fi

  for i in $(seq 1 "$max_wait"); do
    case "$mgr" in
      systemd)
        if systemctl is-active --quiet "$SERVICE_NAME" && check_port_ready "$port"; then
          return
        fi
        ;;
      openrc)
        if rc-service "$SERVICE_NAME" status >/dev/null 2>&1 && check_port_ready "$port"; then
          return
        fi
        ;;
      sysv)
        if service "$SERVICE_NAME" status >/dev/null 2>&1 && check_port_ready "$port"; then
          return
        fi
        ;;
    esac
    sleep 1
  done

  warn "Service may not be ready yet, please check logs manually."
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
  curl -fsS --max-time 3 https://api.ipify.org 2>/dev/null || true
}

print_summary() {
  local port="$1"
  local mgr="$2"
  local local_ip public_ip
  local_ip="$(detect_local_ip)"
  public_ip="$(detect_public_ip)"

  log "Install finished"
  log "Service manager: $mgr"
  log "Service name: $SERVICE_NAME"
  log "Local URL: http://${local_ip}:${port}/"
  if [[ -n "$public_ip" && "$public_ip" != "$local_ip" ]]; then
    log "Public URL: http://${public_ip}:${port}/"
  fi
  log "First-time setup: /setup"
  log "Config file: $ENV_FILE"
}

main() {
  require_root
  local mgr port

  install_system_packages
  ensure_env_file
  normalize_runtime_secrets

  cd "$APP_DIR"
  ensure_venv
  install_python_deps
  ensure_data_file
  run_self_check

  port="$(normalize_port)"
  mgr="$(detect_service_mgr)"

  install_service "$mgr" "$port"
  wait_service_ready "$mgr" "$port"
  print_summary "$port" "$mgr"
}

main "$@"

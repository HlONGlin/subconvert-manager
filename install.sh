#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$APP_DIR/config.env"
SERVICE_NAME="subconvert-manager"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
VENV_DIR="$APP_DIR/.venv"
PYTHON_BIN="${PYTHON_BIN:-python3}"
UVICORN_HOST="${UVICORN_HOST:-0.0.0.0}"

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

ensure_apt_packages() {
  has_cmd apt-get || die "apt-get not found. This installer currently supports Debian/Ubuntu systems only."

  export DEBIAN_FRONTEND=noninteractive
  log "Installing system dependencies"
  apt-get update -y
  apt-get install -y --no-install-recommends \
    python3 \
    python3-venv \
    python3-pip \
    ca-certificates \
    curl
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
  "$PYTHON_BIN" - <<'PY'
import secrets
print(secrets.token_urlsafe(32))
PY
}

pick_free_port() {
  "$PYTHON_BIN" - <<'PY'
import socket
s = socket.socket()
s.bind(("", 0))
print(s.getsockname()[1])
s.close()
PY
}

is_port_available() {
  local port="$1"
  "$PYTHON_BIN" - <<PY
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
    local auto_port
    auto_port="$(pick_free_port)"
    set_env_key "PORT" "$auto_port"
    echo "$auto_port"
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
    warn "PORT=$raw is already in use, auto-selecting another free port"
    raw="$(pick_free_port)"
    set_env_key "PORT" "$raw"
  fi

  echo "$raw"
}

normalize_runtime_secrets() {
  local sub_token
  local session_secret

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
  if [[ ! -d "$VENV_DIR" ]]; then
    log "Creating virtual environment"
    "$PYTHON_BIN" -m venv "$VENV_DIR"
  fi
}

pip_install_with_retry() {
  local pip_bin="$1"
  local requirements="$2"
  local max_retry=3
  local n

  for n in $(seq 1 "$max_retry"); do
    if "$pip_bin" install --no-cache-dir -r "$requirements"; then
      return
    fi
    warn "pip install failed (attempt ${n}/${max_retry})"
    sleep 2
  done

  die "pip install failed after ${max_retry} attempts"
}

install_python_deps() {
  local pip_bin="$VENV_DIR/bin/pip"

  log "Installing Python dependencies"
  "$pip_bin" install --upgrade pip setuptools wheel
  pip_install_with_retry "$pip_bin" "$APP_DIR/requirements.txt"
}

ensure_data_file() {
  local data_file
  local data_file_abs

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

write_service_file() {
  local port="$1"

  cat >"$SERVICE_FILE" <<EOF
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

restart_service() {
  log "Reloading systemd and starting service"
  systemctl daemon-reload
  systemctl enable --now "$SERVICE_NAME"
  systemctl restart "$SERVICE_NAME"
}

wait_service_ready() {
  local max_wait=15
  local i

  for i in $(seq 1 "$max_wait"); do
    if systemctl is-active --quiet "$SERVICE_NAME"; then
      return
    fi
    sleep 1
  done

  systemctl status "$SERVICE_NAME" --no-pager || true
  die "Service failed to start"
}

print_summary() {
  local port="$1"
  log "Install finished"
  log "Service: $SERVICE_NAME"
  log "URL: http://<server-ip>:${port}/"
  log "Config: $ENV_FILE"
  log "If first deployment, change BASIC_AUTH_PASS immediately"
}

main() {
  require_root
  ensure_apt_packages
  ensure_env_file
  normalize_runtime_secrets

  cd "$APP_DIR"
  ensure_venv
  install_python_deps
  ensure_data_file
  run_self_check

  local port
  port="$(normalize_port)"

  write_service_file "$port"
  restart_service
  wait_service_ready
  print_summary "$port"
}

main "$@"

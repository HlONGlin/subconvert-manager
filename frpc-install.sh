#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

SERVICE_NAME="frpc"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"

FRP_VERSION="${FRP_VERSION:-0.51.3}"
FRP_REPO="${FRP_REPO:-fatedier/frp}"
INSTALL_ROOT="${INSTALL_ROOT:-/opt/frp}"
ETC_DIR="${ETC_DIR:-/etc/frp}"
CONF_FILE="${CONF_FILE:-${ETC_DIR}/frpc.ini}"

FRPS_SERVER_ADDR="${FRPS_SERVER_ADDR:-}"
FRPS_SERVER_PORT="${FRPS_SERVER_PORT:-7000}"
FRP_TOKEN="${FRP_TOKEN:-}"

FRPC_PROXY_NAME="${FRPC_PROXY_NAME:-subconvert}"
FRPC_PROXY_TYPE="${FRPC_PROXY_TYPE:-tcp}"
FRPC_LOCAL_IP="${FRPC_LOCAL_IP:-127.0.0.1}"
FRPC_LOCAL_PORT="${FRPC_LOCAL_PORT:-3000}"
FRPC_REMOTE_PORT="${FRPC_REMOTE_PORT:-6000}"
FRPC_USE_ENCRYPTION="${FRPC_USE_ENCRYPTION:-true}"
FRPC_USE_COMPRESSION="${FRPC_USE_COMPRESSION:-true}"

log() {
  printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"
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
    die "Please run as root: curl -fsSL .../frpc-install.sh | sudo bash"
  fi
}

require_systemd() {
  if ! has_cmd systemctl || [[ ! -d /run/systemd/system ]]; then
    die "This script currently supports systemd-based Linux only."
  fi
}

detect_arch() {
  case "$(uname -m)" in
    x86_64|amd64) echo "amd64" ;;
    aarch64|arm64) echo "arm64" ;;
    armv7l|armv7) echo "arm" ;;
    *)
      die "Unsupported architecture: $(uname -m)"
      ;;
  esac
}

ensure_dependencies() {
  local missing=()
  has_cmd curl || missing+=("curl")
  has_cmd tar || missing+=("tar")
  has_cmd install || missing+=("coreutils")
  if [[ "${#missing[@]}" -gt 0 ]]; then
    die "Missing required commands: ${missing[*]}"
  fi
}

download_and_install_frpc() {
  local arch="$1"
  local archive="frp_${FRP_VERSION}_linux_${arch}.tar.gz"
  local url="https://github.com/${FRP_REPO}/releases/download/v${FRP_VERSION}/${archive}"
  local tmpdir src_dir
  tmpdir="$(mktemp -d)"
  trap 'rm -rf "$tmpdir"' EXIT

  log "Downloading $url"
  curl -fL --retry 3 --connect-timeout 10 "$url" -o "${tmpdir}/${archive}"

  tar -xzf "${tmpdir}/${archive}" -C "$tmpdir"
  src_dir="${tmpdir}/frp_${FRP_VERSION}_linux_${arch}"
  [[ -x "${src_dir}/frpc" ]] || die "frpc binary not found in archive"

  mkdir -p "${INSTALL_ROOT}/${FRP_VERSION}" "$ETC_DIR"
  install -m 0755 "${src_dir}/frpc" "${INSTALL_ROOT}/${FRP_VERSION}/frpc"
  ln -sfn "${INSTALL_ROOT}/${FRP_VERSION}/frpc" /usr/local/bin/frpc
}

write_config() {
  mkdir -p "$ETC_DIR"
  cat >"$CONF_FILE" <<EOF
[common]
server_addr = ${FRPS_SERVER_ADDR}
server_port = ${FRPS_SERVER_PORT}
token = ${FRP_TOKEN}

[${FRPC_PROXY_NAME}]
type = ${FRPC_PROXY_TYPE}
local_ip = ${FRPC_LOCAL_IP}
local_port = ${FRPC_LOCAL_PORT}
remote_port = ${FRPC_REMOTE_PORT}
use_encryption = ${FRPC_USE_ENCRYPTION}
use_compression = ${FRPC_USE_COMPRESSION}
EOF
  chmod 0600 "$CONF_FILE"
}

write_service() {
  cat >"$SERVICE_FILE" <<EOF
[Unit]
Description=FRP Client
After=network.target

[Service]
Type=simple
ExecStart=/usr/local/bin/frpc -c ${CONF_FILE}
Restart=always
RestartSec=2

[Install]
WantedBy=multi-user.target
EOF
}

main() {
  require_root
  require_systemd
  ensure_dependencies

  [[ -n "$FRPS_SERVER_ADDR" ]] || die "FRPS_SERVER_ADDR is required"
  [[ -n "$FRP_TOKEN" ]] || die "FRP_TOKEN is required"

  local arch
  arch="$(detect_arch)"
  download_and_install_frpc "$arch"
  write_config
  write_service

  systemctl daemon-reload
  systemctl enable --now "$SERVICE_NAME"
  systemctl restart "$SERVICE_NAME"
  systemctl is-active --quiet "$SERVICE_NAME" || die "frpc service failed to start"

  log "FRPC deployed successfully."
  log "Service: ${SERVICE_NAME}"
  log "Config: ${CONF_FILE}"
  log "Tunnel: ${FRPS_SERVER_ADDR}:${FRPC_REMOTE_PORT} -> ${FRPC_LOCAL_IP}:${FRPC_LOCAL_PORT}"
}

main "$@"

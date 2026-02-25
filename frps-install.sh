#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

SERVICE_NAME="frps"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"

FRP_VERSION="${FRP_VERSION:-0.51.3}"
FRP_REPO="${FRP_REPO:-fatedier/frp}"
INSTALL_ROOT="${INSTALL_ROOT:-/opt/frp}"
ETC_DIR="${ETC_DIR:-/etc/frp}"
CONF_FILE="${CONF_FILE:-${ETC_DIR}/frps.ini}"

FRPS_BIND_PORT="${FRPS_BIND_PORT:-7000}"
FRPS_VHOST_HTTP_PORT="${FRPS_VHOST_HTTP_PORT:-80}"
FRPS_VHOST_HTTPS_PORT="${FRPS_VHOST_HTTPS_PORT:-443}"
FRPS_DASHBOARD_PORT="${FRPS_DASHBOARD_PORT:-7500}"
FRPS_DASHBOARD_USER="${FRPS_DASHBOARD_USER:-admin}"
FRPS_DASHBOARD_PWD="${FRPS_DASHBOARD_PWD:-}"
FRPS_ALLOW_PORTS="${FRPS_ALLOW_PORTS:-2000-30000}"
FRP_TOKEN="${FRP_TOKEN:-}"

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
    die "Please run as root: curl -fsSL .../frps-install.sh | sudo bash"
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

random_token() {
  local n="${1:-32}"
  if has_cmd openssl; then
    openssl rand -hex "$((n / 2))"
    return
  fi
  tr -dc 'A-Za-z0-9' </dev/urandom | head -c "$n"
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

download_and_install_frps() {
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
  [[ -x "${src_dir}/frps" ]] || die "frps binary not found in archive"

  mkdir -p "${INSTALL_ROOT}/${FRP_VERSION}" "$ETC_DIR"
  install -m 0755 "${src_dir}/frps" "${INSTALL_ROOT}/${FRP_VERSION}/frps"
  ln -sfn "${INSTALL_ROOT}/${FRP_VERSION}/frps" /usr/local/bin/frps
}

write_config() {
  mkdir -p "$ETC_DIR"
  cat >"$CONF_FILE" <<EOF
[common]
bind_port = ${FRPS_BIND_PORT}
vhost_http_port = ${FRPS_VHOST_HTTP_PORT}
vhost_https_port = ${FRPS_VHOST_HTTPS_PORT}
dashboard_port = ${FRPS_DASHBOARD_PORT}
dashboard_user = ${FRPS_DASHBOARD_USER}
dashboard_pwd = ${FRPS_DASHBOARD_PWD}
token = ${FRP_TOKEN}
allow_ports = ${FRPS_ALLOW_PORTS}
EOF
  chmod 0600 "$CONF_FILE"
}

write_service() {
  cat >"$SERVICE_FILE" <<EOF
[Unit]
Description=FRP Server
After=network.target

[Service]
Type=simple
ExecStart=/usr/local/bin/frps -c ${CONF_FILE}
Restart=always
RestartSec=2

[Install]
WantedBy=multi-user.target
EOF
}

detect_public_ip() {
  if ! has_cmd curl; then
    return
  fi
  curl -fsS --max-time 3 https://api.ipify.org 2>/dev/null || true
}

main() {
  require_root
  require_systemd
  ensure_dependencies

  if [[ -z "$FRP_TOKEN" ]]; then
    FRP_TOKEN="$(random_token 32)"
    warn "FRP_TOKEN not provided, generated a random token."
  fi
  if [[ -z "$FRPS_DASHBOARD_PWD" ]]; then
    FRPS_DASHBOARD_PWD="$(random_token 20)"
    warn "FRPS_DASHBOARD_PWD not provided, generated a random password."
  fi

  local arch public_ip
  arch="$(detect_arch)"
  download_and_install_frps "$arch"
  write_config
  write_service

  systemctl daemon-reload
  systemctl enable --now "$SERVICE_NAME"
  systemctl restart "$SERVICE_NAME"
  systemctl is-active --quiet "$SERVICE_NAME" || die "frps service failed to start"

  public_ip="$(detect_public_ip || true)"
  [[ -n "$public_ip" ]] || public_ip="<FRPS_PUBLIC_IP>"

  log "FRPS deployed successfully."
  log "Service: ${SERVICE_NAME}"
  log "Config: ${CONF_FILE}"
  log "Dashboard: http://${public_ip}:${FRPS_DASHBOARD_PORT}"
  log "Dashboard user: ${FRPS_DASHBOARD_USER}"
  log "Dashboard password: ${FRPS_DASHBOARD_PWD}"
  log "Token: ${FRP_TOKEN}"
  log "Next (deploy FRPC on your site server):"
  echo "curl -fsSL https://raw.githubusercontent.com/HlONGlin/subconvert-manager/main/frpc-install.sh | sudo env FRPS_SERVER_ADDR=${public_ip} FRPS_SERVER_PORT=${FRPS_BIND_PORT} FRP_TOKEN=${FRP_TOKEN} FRPC_LOCAL_PORT=3000 FRPC_REMOTE_PORT=6000 bash"
}

main "$@"

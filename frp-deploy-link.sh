#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

REPO_OWNER="${REPO_OWNER:-HlONGlin}"
REPO_NAME="${REPO_NAME:-subconvert-manager}"
BRANCH="${BRANCH:-main}"

FRP_VERSION="${FRP_VERSION:-0.51.3}"
FRP_TOKEN="${FRP_TOKEN:-}"

FRPS_BIND_PORT="${FRPS_BIND_PORT:-7000}"
FRPS_VHOST_HTTP_PORT="${FRPS_VHOST_HTTP_PORT:-80}"
FRPS_VHOST_HTTPS_PORT="${FRPS_VHOST_HTTPS_PORT:-443}"
FRPS_DASHBOARD_PORT="${FRPS_DASHBOARD_PORT:-7500}"
FRPS_DASHBOARD_USER="${FRPS_DASHBOARD_USER:-admin}"
FRPS_DASHBOARD_PWD="${FRPS_DASHBOARD_PWD:-}"
FRPS_ALLOW_PORTS="${FRPS_ALLOW_PORTS:-2000-30000}"

FRPS_SERVER_ADDR="${FRPS_SERVER_ADDR:-FRPS_PUBLIC_IP}"
FRPC_LOCAL_PORT="${FRPC_LOCAL_PORT:-3000}"
FRPC_REMOTE_PORT="${FRPC_REMOTE_PORT:-6000}"
FRPC_PROXY_NAME="${FRPC_PROXY_NAME:-subconvert}"
FRPC_PROXY_TYPE="${FRPC_PROXY_TYPE:-tcp}"

random_token() {
  local n="${1:-32}"
  if command -v openssl >/dev/null 2>&1; then
    openssl rand -hex "$((n / 2))"
    return
  fi
  tr -dc 'A-Za-z0-9' </dev/urandom | head -c "$n"
}

sanitize_or_die() {
  local name="$1"
  local value="$2"
  if [[ ! "$value" =~ ^[A-Za-z0-9._:@/-]+$ ]]; then
    printf 'ERROR: %s contains unsafe characters: %s\n' "$name" "$value" >&2
    exit 1
  fi
}

main() {
  if [[ -z "$FRP_TOKEN" ]]; then
    FRP_TOKEN="$(random_token 32)"
  fi
  if [[ -z "$FRPS_DASHBOARD_PWD" ]]; then
    FRPS_DASHBOARD_PWD="$(random_token 20)"
  fi

  sanitize_or_die "REPO_OWNER" "$REPO_OWNER"
  sanitize_or_die "REPO_NAME" "$REPO_NAME"
  sanitize_or_die "BRANCH" "$BRANCH"
  sanitize_or_die "FRP_TOKEN" "$FRP_TOKEN"
  sanitize_or_die "FRPS_DASHBOARD_USER" "$FRPS_DASHBOARD_USER"
  sanitize_or_die "FRPS_DASHBOARD_PWD" "$FRPS_DASHBOARD_PWD"
  sanitize_or_die "FRPS_ALLOW_PORTS" "$FRPS_ALLOW_PORTS"
  sanitize_or_die "FRPS_SERVER_ADDR" "$FRPS_SERVER_ADDR"
  sanitize_or_die "FRPC_PROXY_NAME" "$FRPC_PROXY_NAME"
  sanitize_or_die "FRPC_PROXY_TYPE" "$FRPC_PROXY_TYPE"

  local raw_base
  raw_base="https://raw.githubusercontent.com/${REPO_OWNER}/${REPO_NAME}/${BRANCH}"

  echo "FRPS 一键部署命令（服务器执行）："
  echo "curl -fsSL ${raw_base}/frps-install.sh | sudo env FRP_VERSION=${FRP_VERSION} FRP_TOKEN=${FRP_TOKEN} FRPS_BIND_PORT=${FRPS_BIND_PORT} FRPS_VHOST_HTTP_PORT=${FRPS_VHOST_HTTP_PORT} FRPS_VHOST_HTTPS_PORT=${FRPS_VHOST_HTTPS_PORT} FRPS_DASHBOARD_PORT=${FRPS_DASHBOARD_PORT} FRPS_DASHBOARD_USER=${FRPS_DASHBOARD_USER} FRPS_DASHBOARD_PWD=${FRPS_DASHBOARD_PWD} FRPS_ALLOW_PORTS=${FRPS_ALLOW_PORTS} bash"
  echo
  echo "FRPC 一键部署命令（站点服务器执行）："
  echo "curl -fsSL ${raw_base}/frpc-install.sh | sudo env FRP_VERSION=${FRP_VERSION} FRPS_SERVER_ADDR=${FRPS_SERVER_ADDR} FRPS_SERVER_PORT=${FRPS_BIND_PORT} FRP_TOKEN=${FRP_TOKEN} FRPC_PROXY_NAME=${FRPC_PROXY_NAME} FRPC_PROXY_TYPE=${FRPC_PROXY_TYPE} FRPC_LOCAL_PORT=${FRPC_LOCAL_PORT} FRPC_REMOTE_PORT=${FRPC_REMOTE_PORT} bash"
  echo
  echo "注意：请妥善保管 token，不要泄漏到公开渠道。"
}

main "$@"

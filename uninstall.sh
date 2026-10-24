#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

SCRIPT_PATH="${BASH_SOURCE[0]:-${0:-.}}"
if [[ "$SCRIPT_PATH" == "bash" || "$SCRIPT_PATH" == "-bash" ]]; then
  SCRIPT_PATH="."
fi
APP_DIR="$(cd "$(dirname "$SCRIPT_PATH")" 2>/dev/null && pwd)"
SERVICE_NAME="subconvert-manager"
SERVICE_FILE_SYSTEMD="/etc/systemd/system/${SERVICE_NAME}.service"
SERVICE_FILE_OPENRC="/etc/init.d/${SERVICE_NAME}"
SERVICE_FILE_SYSV="/etc/init.d/${SERVICE_NAME}"
REMOVE_APP_DIR="${REMOVE_APP_DIR:-1}"

has_cmd() {
  command -v "$1" >/dev/null 2>&1
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

if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
  echo "Please run as root: sudo bash uninstall.sh" >&2
  exit 1
fi

mgr="$(detect_service_mgr)"
case "$mgr" in
  systemd)
    systemctl disable --now "$SERVICE_NAME" >/dev/null 2>&1 || true
    rm -f "$SERVICE_FILE_SYSTEMD"
    systemctl daemon-reload || true
    ;;
  openrc)
    rc-service "$SERVICE_NAME" stop >/dev/null 2>&1 || true
    rc-update del "$SERVICE_NAME" default >/dev/null 2>&1 || true
    rm -f "$SERVICE_FILE_OPENRC"
    ;;
  sysv)
    service "$SERVICE_NAME" stop >/dev/null 2>&1 || true
    if has_cmd update-rc.d; then
      update-rc.d -f "$SERVICE_NAME" remove >/dev/null 2>&1 || true
    elif has_cmd chkconfig; then
      chkconfig --del "$SERVICE_NAME" >/dev/null 2>&1 || true
    fi
    rm -f "$SERVICE_FILE_SYSV"
    ;;
  none)
    rm -f "$SERVICE_FILE_SYSTEMD" "$SERVICE_FILE_OPENRC" "$SERVICE_FILE_SYSV"
    ;;
esac

if [[ "$REMOVE_APP_DIR" == "1" ]]; then
  if [[ -z "$APP_DIR" || "$APP_DIR" == "/" || "$APP_DIR" == "." ]]; then
    echo "Refusing to remove unsafe APP_DIR: $APP_DIR" >&2
    exit 1
  fi
  rm -rf "$APP_DIR"
  echo "Uninstalled service and removed all downloaded content: $APP_DIR"
else
  rm -rf "$APP_DIR/.venv"
  echo "Uninstalled service (kept source code and data/)."
fi

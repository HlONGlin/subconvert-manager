#!/usr/bin/env bash
set -e

APP_DIR="$(cd "$(dirname "$0")" && pwd)"
SERVICE_NAME="subconvert-manager"

if [[ $EUID -ne 0 ]]; then
  echo "请用 root 执行：sudo bash uninstall.sh"
  exit 1
fi

systemctl disable --now ${SERVICE_NAME} >/dev/null 2>&1 || true
rm -f /etc/systemd/system/${SERVICE_NAME}.service
systemctl daemon-reload
rm -rf "$APP_DIR/.venv"
echo "已卸载（保留 data/ 与源码）"

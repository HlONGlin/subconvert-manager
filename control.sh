#!/usr/bin/env bash
set -e

APP_DIR="$(cd "$(dirname "$0")" && pwd)"
ENV_FILE="$APP_DIR/config.env"
SERVICE_NAME="subconvert-manager"

require_root() {
  if [[ $EUID -ne 0 ]]; then
    echo "此操作需要 root，请用：sudo bash control.sh"
    exit 1
  fi
}

auto_port() {
python3 - <<'PY'
import socket
s=socket.socket()
s.bind(('',0))
print(s.getsockname()[1])
s.close()
PY
}

show_menu() {
  echo "=============================="
  echo " SubConvert Manager 控制面板"
  echo "=============================="
  echo "1) 安装/更新（自动选端口若 PORT=auto）"
  echo "2) 卸载服务（保留 data/）"
  echo "3) 重启服务"
  echo "4) 停止服务"
  echo "5) 查看状态"
  echo "6) 自动更换端口"
  echo "0) 退出"
  echo "------------------------------"
}

do_install(){ require_root; bash "$APP_DIR/install.sh"; }
do_uninstall(){ require_root; bash "$APP_DIR/uninstall.sh"; }
do_restart(){ require_root; systemctl restart ${SERVICE_NAME}; echo "已重启"; }
do_stop(){ require_root; systemctl stop ${SERVICE_NAME}; echo "已停止"; }
do_status(){ systemctl status ${SERVICE_NAME} --no-pager || true; echo "当前端口: $(grep -E '^PORT=' "$ENV_FILE" | head -n1 | cut -d= -f2)"; }

do_change_port(){
  require_root
  NEWPORT="$(auto_port)"
  if grep -qE '^PORT=' "$ENV_FILE"; then
    sed -i "s/^PORT=.*/PORT=${NEWPORT}/" "$ENV_FILE"
  else
    echo "PORT=${NEWPORT}" >>"$ENV_FILE"
  fi
  if [[ -f "/etc/systemd/system/${SERVICE_NAME}.service" ]]; then
    sed -i "s/--port [0-9]\+/--port ${NEWPORT}/" "/etc/systemd/system/${SERVICE_NAME}.service"
    systemctl daemon-reload
    systemctl restart ${SERVICE_NAME}
    echo "已自动切换端口: ${NEWPORT}"
  else
    echo "未检测到服务，请先安装"
  fi
}

while true; do
  show_menu
  read -r -p "请输入选项: " choice
  case "$choice" in
    1) do_install ;;
    2) do_uninstall ;;
    3) do_restart ;;
    4) do_stop ;;
    5) do_status ;;
    6) do_change_port ;;
    0) exit 0 ;;
    *) echo "无效选项" ;;
  esac
  echo
done

#!/usr/bin/env bash
# 兼容入口：保留旧的一键命令，实际逻辑已迁移到 one-click.sh
#
#   bash <(curl -fsSL https://raw.githubusercontent.com/HlONGlin/subconvert-manager/main/quick-install.sh)
#
# 旧的环境变量仍然可用：
#   APP_DIR       安装目录（等价于 --dir）
#   REPO_URL      仓库地址
#   BRANCH        分支
#   OPEN_CONTROL  auto/0/1，0 表示装完不进菜单（等价于 --no-menu）
set -Eeuo pipefail
IFS=$'\n\t'

ONECLICK_URL="${ONECLICK_URL:-https://raw.githubusercontent.com/HlONGlin/subconvert-manager/main/one-click.sh}"

args=("$@")

has_flag() {
  local want="$1" item
  for item in "${args[@]:-}"; do
    [[ "$item" == "$want" || "$item" == "$want="* ]] && return 0
  done
  return 1
}

# 旧变量 -> 新参数
if [[ -n "${APP_DIR:-}" ]] && ! has_flag "--dir"; then
  args+=("--dir" "$APP_DIR")
fi
case "$(printf '%s' "${OPEN_CONTROL:-auto}" | tr '[:upper:]' '[:lower:]')" in
  0|false|no|off) has_flag "--no-menu" || args+=("--no-menu") ;;
esac

here="$(cd "$(dirname "${BASH_SOURCE[0]:-}")" 2>/dev/null && pwd || true)"
if [[ -n "$here" && -f "$here/one-click.sh" ]]; then
  exec bash "$here/one-click.sh" "${args[@]}"
fi

tmp="$(mktemp)"
if command -v curl >/dev/null 2>&1; then
  curl -fsSL "$ONECLICK_URL" -o "$tmp"
elif command -v wget >/dev/null 2>&1; then
  wget -qO "$tmp" "$ONECLICK_URL"
else
  printf '需要 curl 或 wget 才能下载 one-click.sh\n' >&2
  exit 1
fi

set +e
bash "$tmp" "${args[@]}"
status=$?
set -e
rm -f "$tmp"
exit "$status"

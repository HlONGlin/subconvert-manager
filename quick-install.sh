#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

REPO_URL="${REPO_URL:-https://github.com/HlONGlin/subconvert-manager.git}"
BRANCH="${BRANCH:-main}"
APP_DIR="${APP_DIR:-/opt/subconvert-manager}"
OPEN_CONTROL="${OPEN_CONTROL:-auto}"

log() {
  printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"
}

die() {
  printf '[%s] ERROR: %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >&2
  exit 1
}

warn() {
  printf '[%s] WARN: %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >&2
}

has_cmd() {
  command -v "$1" >/dev/null 2>&1
}

require_root() {
  if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
    die "Please run as root. Example: sudo bash -c \"\$(curl -fsSL https://raw.githubusercontent.com/HlONGlin/subconvert-manager/main/quick-install.sh)\""
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

ensure_git() {
  if has_cmd git; then
    return
  fi

  local pm
  pm="$(detect_pkg_manager)"
  log "git not found, trying to install via package manager: $pm"

  case "$pm" in
    apt)
      export DEBIAN_FRONTEND=noninteractive
      apt-get update -y
      apt-get install -y git
      ;;
    dnf) dnf -y install git ;;
    yum) yum -y install git ;;
    zypper) zypper --non-interactive install git ;;
    pacman) pacman -Sy --noconfirm git ;;
    apk) apk add --no-cache git ;;
    *) die "git not found and unsupported package manager. Install git manually first." ;;
  esac
}

sync_repo() {
  mkdir -p "$(dirname "$APP_DIR")"

  if [[ -d "$APP_DIR/.git" ]]; then
    log "Repository exists, pulling latest from $BRANCH"
    git -C "$APP_DIR" fetch origin "$BRANCH"
    git -C "$APP_DIR" checkout "$BRANCH"
    git -C "$APP_DIR" pull --ff-only origin "$BRANCH"
    return
  fi

  if [[ -e "$APP_DIR" ]] && [[ -n "$(ls -A "$APP_DIR" 2>/dev/null || true)" ]]; then
    die "Target directory is not empty: $APP_DIR"
  fi

  log "Cloning repository to $APP_DIR"
  git clone --depth 1 -b "$BRANCH" "$REPO_URL" "$APP_DIR"
}

should_open_control() {
  local v
  v="$(printf '%s' "$OPEN_CONTROL" | tr '[:upper:]' '[:lower:]')"
  case "$v" in
    1|true|yes|on) return 0 ;;
    0|false|no|off) return 1 ;;
    auto|"")
      [[ -t 0 && -t 1 ]]
      return
      ;;
    *)
      warn "Unknown OPEN_CONTROL='$OPEN_CONTROL', fallback to auto"
      [[ -t 0 && -t 1 ]]
      return
      ;;
  esac
}

main() {
  require_root
  ensure_git
  sync_repo

  cd "$APP_DIR"
  chmod +x control.sh install.sh uninstall.sh quick-install.sh || true

  log "Running install.sh"
  bash install.sh

  if should_open_control; then
    log "Opening control menu: $APP_DIR/control.sh"
    exec bash "$APP_DIR/control.sh"
  fi

  log "Done. You can manage service with:"
  log "sudo bash $APP_DIR/control.sh"
}

main "$@"

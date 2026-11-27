#!/usr/bin/env bash
# Remove the xiaomi-key daemon, its unit, udev rule and (optionally) config.
#
# Usage: scripts/uninstall.sh [options]
#   --purge       also delete ~/.config/xiaomi-key (your action.conf)
#   --no-udev     leave /etc/udev/{rules,hwdb}.d alone
#   --dry-run     print what would happen, change nothing
#   -h, --help    show this help
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PREFIX="${XDG_PREFIX:-$HOME/.local}"
CONFIG_HOME="${XDG_CONFIG_HOME:-$HOME/.config}"

PURGE=0
DO_UDEV=1
DRY_RUN=0

UDEV_DST="/etc/udev/rules.d/60-xiaomi-key.rules"
HWDB_DST="/etc/udev/hwdb.d/70-xiaomi-key-remap.hwdb"
BIN_DIR="$PREFIX/bin"
CONF_DIR="$CONFIG_HOME/xiaomi-key"
UNIT_DST="$CONFIG_HOME/systemd/user/xiaomi-key.service"

info() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[!]\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31m[x]\033[0m %s\n' "$*" >&2; exit 1; }

usage() { awk 'NR > 1 && /^#/ { sub(/^# ?/, ""); print; next } NR > 1 { exit }' "$0"; }

while [[ $# -gt 0 ]]; do
    case "$1" in
        --purge)    PURGE=1; shift ;;
        --no-udev)  DO_UDEV=0; shift ;;
        --dry-run)  DRY_RUN=1; shift ;;
        -h|--help)  usage; exit 0 ;;
        *)          die "unknown option: $1 (see --help)" ;;
    esac
done

run() {
    if [[ $DRY_RUN -eq 1 ]]; then
        printf '    + %s\n' "$*"
        return 0
    fi
    "$@" || true
}

[[ $EUID -ne 0 ]] || die "run this as your own user, not as root"

info "stop and disable the user service"
run systemctl --user disable --now xiaomi-key.service
run rm -f "$UNIT_DST"
run systemctl --user daemon-reload
run systemctl --user reset-failed xiaomi-key.service

info "remove the daemon"
run rm -f "$BIN_DIR/xiaomi-key-daemon.py" "$BIN_DIR/xiaomi-key"

if [[ $DO_UDEV -eq 1 ]]; then
    if [[ -f "$UDEV_DST" || -f "$HWDB_DST" ]]; then
        info "remove the udev rule and/or hwdb remap (sudo)"
        run sudo rm -f "$UDEV_DST"
        if [[ -f "$HWDB_DST" ]]; then
            run sudo rm -f "$HWDB_DST"
            run sudo systemd-hwdb update
        fi
        run sudo udevadm control --reload-rules
        run sudo udevadm trigger --subsystem-match=input --action=change
    fi
else
    warn "left $UDEV_DST and $HWDB_DST in place (--no-udev)"
fi

if [[ $PURGE -eq 1 ]]; then
    info "remove the configuration"
    run rm -rf "$CONF_DIR"
else
    info "configuration kept in $CONF_DIR (use --purge to delete it)"
fi

if [[ -f "$HWDB_DST" ]] && [[ $DO_UDEV -eq 1 ]]; then
    echo
    warn "log out and back in so the key reports KEY_ASSISTANT again"
fi

echo
info "uninstalled"
echo "    the repo itself is untouched: $REPO_ROOT"

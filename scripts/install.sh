#!/usr/bin/env bash
# Install the xiaomi-key daemon (udev ACL rule + systemd --user service).
#
# Usage: scripts/install.sh [options]
#   --prefix DIR      install the daemon under DIR/bin      (default: ~/.local)
#   --no-udev         do not touch /etc/udev/rules.d         (no sudo needed)
#   --no-service      install files only, do not enable the service
#   --force-config    overwrite an existing action.conf (a .bak is kept)
#   --dry-run         print what would happen, change nothing
#   -h, --help        show this help
#
# Everything user-scoped goes to XDG paths; only the udev rule needs sudo.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

PREFIX="${XDG_PREFIX:-$HOME/.local}"
CONFIG_HOME="${XDG_CONFIG_HOME:-$HOME/.config}"
PREFIX_EXPLICIT=0
DO_UDEV=1
DO_SERVICE=1
FORCE_CONFIG=0
DRY_RUN=0

UDEV_SRC="$REPO_ROOT/etc/udev/rules.d/60-xiaomi-key.rules"
HWDB_SRC="$REPO_ROOT/etc/udev/hwdb.d/70-xiaomi-key-remap.hwdb"
UNIT_SRC="$REPO_ROOT/etc/systemd/user/xiaomi-key.service"
DAEMON_SRC="$REPO_ROOT/bin/xiaomi-key-daemon.py"
CONF_SRC="$REPO_ROOT/config/action.conf.example"

UDEV_DST="/etc/udev/rules.d/60-xiaomi-key.rules"
HWDB_DST="/etc/udev/hwdb.d/70-xiaomi-key-remap.hwdb"

info() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
ok()   { printf '\033[1;32m  ok\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[!]\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31m[x]\033[0m %s\n' "$*" >&2; exit 1; }

usage() { awk 'NR > 1 && /^#/ { sub(/^# ?/, ""); print; next } NR > 1 { exit }' "$0"; }

while [[ $# -gt 0 ]]; do
    case "$1" in
        --prefix)      PREFIX="${2:?--prefix needs a directory}"; PREFIX_EXPLICIT=1; shift 2 ;;
        --prefix=*)    PREFIX="${1#*=}"; PREFIX_EXPLICIT=1; shift ;;
        --no-udev)     DO_UDEV=0; shift ;;
        --no-service)  DO_SERVICE=0; shift ;;
        --force-config) FORCE_CONFIG=1; shift ;;
        --dry-run)     DRY_RUN=1; shift ;;
        -h|--help)     usage; exit 0 ;;
        *)             die "unknown option: $1 (see --help)" ;;
    esac
done

run() {
    if [[ $DRY_RUN -eq 1 ]]; then
        printf '    + %s\n' "$*"
        return 0
    fi
    "$@"
}

run_sudo() {
    if [[ $DRY_RUN -eq 1 ]]; then
        printf '    + sudo %s\n' "$*"
        return 0
    fi
    sudo "$@"
}

[[ $EUID -ne 0 ]] || die "run this as your own user, not as root (it calls sudo itself)"
[[ -f "$DAEMON_SRC" ]] || die "cannot find $DAEMON_SRC; run the script from the repo"

PYTHON="$(command -v /usr/bin/python3 || command -v python3 || true)"
[[ -n "$PYTHON" ]] || die "python3 not found; install it first"
"$PYTHON" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' \
    || die "python3 >= 3.9 is required (found $("$PYTHON" -V 2>&1))"

BIN_DIR="$PREFIX/bin"
CONF_DIR="$CONFIG_HOME/xiaomi-key"
UNIT_DIR="$CONFIG_HOME/systemd/user"
DAEMON_DST="$BIN_DIR/xiaomi-key-daemon.py"
CONF_DST="$CONF_DIR/action.conf"

if [[ $DRY_RUN -eq 1 ]]; then
    warn "dry run: nothing will be changed"
fi

info "daemon -> $DAEMON_DST"
run mkdir -p "$BIN_DIR"
run install -m 0755 "$DAEMON_SRC" "$DAEMON_DST"
run ln -sf xiaomi-key-daemon.py "$BIN_DIR/xiaomi-key"

info "config -> $CONF_DST"
run mkdir -p "$CONF_DIR"
if [[ -f "$CONF_DST" ]]; then
    if [[ $FORCE_CONFIG -eq 1 ]]; then
        warn "overwriting the existing config (backup: action.conf.bak)"
        run cp -a "$CONF_DST" "$CONF_DST.bak"
        run install -m 0644 "$CONF_SRC" "$CONF_DST"
    else
        ok "keeping your existing config"
        run install -m 0644 "$CONF_SRC" "$CONF_DST.example"
    fi
else
    run install -m 0644 "$CONF_SRC" "$CONF_DST"
fi

if [[ $DO_UDEV -eq 1 ]]; then
    info "udev rule -> $UDEV_DST (sudo)"
    if [[ -f "$UDEV_DST" ]] && cmp -s "$UDEV_SRC" "$UDEV_DST"; then
        ok "rule already up to date"
    else
        run_sudo install -m 0644 "$UDEV_SRC" "$UDEV_DST"
        run_sudo udevadm control --reload-rules
        run_sudo udevadm trigger --subsystem-match=input --action=change
        ok "installed and re-triggered"
    fi
else
    warn "skipping the udev rule; without it the daemon needs the 'input' group"
fi

if [[ -f "$HWDB_DST" ]]; then
    warn "the hwdb remap is installed ($HWDB_DST)"
    warn "it rewrites the key to F19, so this daemon will not see KEY_ASSISTANT"
    warn "remove it first: scripts/remap-key.sh --remove   (then re-login)"
fi

info "systemd user unit -> $UNIT_DIR/xiaomi-key.service"
run mkdir -p "$UNIT_DIR"
if [[ $DRY_RUN -eq 1 ]]; then
    printf '    + install unit with ExecStart=%s -> %s\n' \
        "$DAEMON_DST" "$UNIT_DIR/xiaomi-key.service"
elif [[ "$DAEMON_DST" == "$HOME/.local/bin/xiaomi-key-daemon.py" ]]; then
    install -m 0644 "$UNIT_SRC" "$UNIT_DIR/xiaomi-key.service"
else
    # Non-default prefix: rewrite the ExecStart line before installing.
    tmp_unit="$(mktemp)"
    trap 'rm -f "$tmp_unit"' EXIT
    sed "s|^ExecStart=.*|ExecStart=$DAEMON_DST|" "$UNIT_SRC" > "$tmp_unit"
    install -m 0644 "$tmp_unit" "$UNIT_DIR/xiaomi-key.service"
fi

if [[ $DO_SERVICE -eq 1 ]]; then
    info "enable the user service"
    run systemctl --user daemon-reload
    run systemctl --user enable --now xiaomi-key.service
    if command -v systemd-analyze >/dev/null 2>&1 && [[ $DRY_RUN -eq 0 ]]; then
        systemd-analyze --user verify "$UNIT_DIR/xiaomi-key.service" >/dev/null 2>&1 \
            || warn "systemd-analyze --user verify reported a problem with the unit"
    fi
else
    warn "service not enabled (--no-service)"
fi

if [[ $DRY_RUN -eq 0 ]]; then
    info "waiting for the device node"
    for _ in $(seq 1 10); do
        [[ -e /dev/input/xiaomi-key ]] && break
        sleep 0.5
    done
    if [[ -e /dev/input/xiaomi-key ]]; then
        ok "/dev/input/xiaomi-key -> $(readlink -f /dev/input/xiaomi-key)"
    else
        warn "no /dev/input/xiaomi-key yet: log out and back in (uaccess ACL)"
    fi

    echo
    "$DAEMON_DST" --check || true
fi

cat <<EOF

Done. Next steps:
  1. press the AI key                (default: short = KRunner, long = konsole)
  2. follow the log                 journalctl --user -u xiaomi-key -f
  3. change the actions             \$EDITOR $CONF_DST
                                    systemctl --user restart xiaomi-key
  4. watch raw events               $DAEMON_DST --test
  5. remove everything              $REPO_ROOT/scripts/uninstall.sh
EOF

if [[ $PREFIX_EXPLICIT -eq 1 ]]; then
    echo
    warn "installed under a custom prefix ($PREFIX): add $BIN_DIR to PATH if needed"
fi

#!/usr/bin/env bash
# Remap the Xiaomi/Redmi AI key to a key code Qt understands (default: F19),
# so it can be bound in System Settings -> Shortcuts.
#
# Usage: scripts/remap-key.sh [install|--verify|--remove] [options]
#   --target NAME     hwdb key name to emit       (default: f19)
#   --device-name RE  override the detected device name glob
#   --verify          only report the current state
#   --remove          uninstall the hwdb remap
#   --dry-run         print what would happen, change nothing
#   -h, --help        show this help
#
# Only one approach can be active: after remapping, the device reports F19 and
# the daemon (which listens for 583) stops seeing the key. Use this OR the
# daemon, then log out and back in so KWin re-reads the key bitmap.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TEMPLATE="$REPO_ROOT/etc/udev/hwdb.d/70-xiaomi-key-remap.hwdb"
HWDB_DST="/etc/udev/hwdb.d/70-xiaomi-key-remap.hwdb"

MODE="install"
TARGET="f19"
DEVICE_NAME=""
DRY_RUN=0

info() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
ok()   { printf '\033[1;32m  ok\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[!]\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31m[x]\033[0m %s\n' "$*" >&2; exit 1; }

usage() { awk 'NR > 1 && /^#/ { sub(/^# ?/, ""); print; next } NR > 1 { exit }' "$0"; }

while [[ $# -gt 0 ]]; do
    case "$1" in
        install)            MODE="install"; shift ;;
        --verify)           MODE="verify"; shift ;;
        --remove)           MODE="remove"; shift ;;
        --target)           TARGET="${2:?--target needs a key name}"; shift 2 ;;
        --target=*)         TARGET="${1#*=}"; shift ;;
        --device-name)      DEVICE_NAME="${2:?--device-name needs a glob}"; shift 2 ;;
        --device-name=*)    DEVICE_NAME="${1#*=}"; shift ;;
        --dry-run)          DRY_RUN=1; shift ;;
        -h|--help)          usage; exit 0 ;;
        *)                  die "unknown argument: $1 (see --help)" ;;
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

PYTHON="$(command -v /usr/bin/python3 || command -v python3 || true)"
[[ -n "$PYTHON" ]] || die "python3 not found"

# First /sys/class/input/eventN whose device name looks like a WMI hotkey block.
detect_device_name() {
    local namefile
    for namefile in /sys/class/input/event*/device/name; do
        [[ -r "$namefile" ]] || continue
        local name
        name="$(cat "$namefile")"
        case "$name" in
            *"WMI keys"*) printf '%s\n' "$name"; return 0 ;;
        esac
    done
    return 1
}

detect_event() {
    local namefile
    for namefile in /sys/class/input/event*/device/name; do
        [[ -r "$namefile" ]] || continue
        if [[ "$(cat "$namefile")" == "$1" ]]; then
            basename "$(dirname "$(dirname "$namefile")")"
            return 0
        fi
    done
    return 1
}

keybit_has() {  # $1 = eventN, $2 = key code
    local cap
    cap="$(cat "/sys/class/input/$1/device/capabilities/key" 2>/dev/null)" || return 1
    CAP="$cap" "$PYTHON" - "$2" <<'PY'
import os
import sys
bits = os.environ["CAP"].split()
value = 0
for index, word in enumerate(reversed(bits)):
    value |= int(word, 16) << (64 * index)
sys.exit(0 if (value >> int(sys.argv[1])) & 1 else 1)
PY
}

verify() {
    local device="${DEVICE_NAME:-}"
    [[ -n "$device" ]] || device="$(detect_device_name || true)"

    echo "=== state ==="
    if [[ -f "$HWDB_DST" ]]; then
        ok "hwdb rule installed: $HWDB_DST"
    else
        warn "hwdb rule not installed"
    fi

    echo
    echo "--- systemd-hwdb query ---"
    if [[ -n "$device" ]]; then
        systemd-hwdb query "evdev:name:$device:*" 2>/dev/null || echo "  (no match)"
    else
        echo "  (no WMI keys device found)"
    fi

    local event=""
    if [[ -n "$device" ]]; then
        event="$(detect_event "$device" || true)"
    fi
    if [[ -z "$event" ]]; then
        warn "cannot find the input device"
        return 0
    fi

    echo
    echo "--- key bitmap of $event ---"
    if keybit_has "$event" 189; then
        ok "F19 (189) is present -> remap is active"
    else
        warn "F19 (189) is absent -> needs log out / log in"
    fi
    if keybit_has "$event" 583; then
        warn "KEY_ASSISTANT (583) still present -> original code is active"
    else
        ok "KEY_ASSISTANT (583) is gone"
    fi
}

check_daemon_conflict() {
    if systemctl --user is-active --quiet xiaomi-key.service 2>/dev/null; then
        warn "the xiaomi-key service is running and listens for 583"
        warn "after remapping it will not see the key: stop it, or set"
        warn "KEY_CODES=189 in ~/.config/xiaomi-key/action.conf"
    fi
}

case "$MODE" in
verify)
    verify
    exit 0
    ;;
remove)
    [[ $EUID -ne 0 ]] || die "run as your own user (the script calls sudo)"
    info "removing the hwdb remap"
    run_sudo rm -f "$HWDB_DST"
    run_sudo systemd-hwdb update
    run_sudo udevadm control --reload-rules
    run_sudo udevadm trigger --subsystem-match=input --action=change
    echo
    ok "removed: log out and back in, the key reports KEY_ASSISTANT again"
    exit 0
    ;;
esac

[[ $EUID -ne 0 ]] || die "run as your own user (the script calls sudo)"
[[ -f "$TEMPLATE" ]] || die "cannot find $TEMPLATE; run the script from the repo"

# hwdb wants a key *name* (as in linux/input.h), not a number.
if [[ "$TARGET" =~ ^[0-9]+$ ]]; then
    die "--target expects a key name such as f19, not a number ($TARGET)"
fi
[[ "$TARGET" =~ ^[a-z0-9_]+$ ]] \
    || die "--target must be a lowercase key name (e.g. f19), got: $TARGET"

if [[ -z "$DEVICE_NAME" ]]; then
    DEVICE_NAME="$(detect_device_name || true)"
fi
[[ -n "$DEVICE_NAME" ]] || die "no '*WMI keys' input device found; pass --device-name GLOB"

info "device: $DEVICE_NAME"
info "target key: $TARGET"

event="$(detect_event "$DEVICE_NAME" || true)"
if [[ -n "$event" ]]; then
    if keybit_has "$event" 583; then
        ok "device still reports KEY_ASSISTANT (583), remap is not active yet"
    elif keybit_has "$event" 189; then
        warn "device already reports F19 (189): already remapped?"
    else
        warn "device reports neither 583 nor 189; check the bitmap manually"
    fi
fi

check_daemon_conflict

info "writing $HWDB_DST (sudo)"
tmp="$(mktemp)"
trap 'rm -f "$tmp"' EXIT
sed "s|^evdev:name:.*|evdev:name:$DEVICE_NAME:*|" "$TEMPLATE" > "$tmp"
run_sudo install -m 0644 "$tmp" "$HWDB_DST"

info "rebuilding the hwdb"
run_sudo systemd-hwdb update
run_sudo udevadm trigger --subsystem-match=input --action=change

echo
verify

cat <<'EOF'

Next steps:
  1. log out and back in
     (KWin/libinput cache the key bitmap when opening the device; a re-login
      is the reliable way to make it re-read 189. `kwin_wayland --replace &`
      sometimes works but is unsupported.)
  2. System Settings -> Keyboard -> Shortcuts -> Add -> Command or Script
  3. click the Trigger field and press the AI key -> it should show "F19"
  4. put the command in the Action field, e.g.
       gdbus call --session --dest org.kde.krunner --object-path /App \
         --method org.kde.krunner.App.toggleDisplay
  5. apply

Verify after the re-login:
  scripts/remap-key.sh --verify
  libinput debug-events --show-keycodes      # should print KEY_F19

Undo: scripts/remap-key.sh --remove   (then re-login)
EOF

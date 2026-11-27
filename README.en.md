# The Xiaomi/Redmi AI key on Linux

[![CI](https://github.com/myml/xiaomi-ai-key-linux/actions/workflows/ci.yml/badge.svg)](https://github.com/myml/xiaomi-ai-key-linux/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.9%2B-3776ab.svg)](https://www.python.org/)

On Xiaomi/Redmi laptops, pressing the AI ("Xiaoai") key does nothing on Linux.
The kernel is fine: the firmware already reports a standard **`KEY_ASSISTANT`
(583)**. The problem is in userspace — **Qt has no mapping for
`XF86Assistant`**, so KWin translates it to `Qt::Key_unknown` (0) and the
desktop shortcut recorder ignores the key.

This project bypasses Qt entirely: it reads `/dev/input/eventN` and turns the
single physical key into **three independent actions** — press, short press and
long press.

- Standard library only, one Python file: no `python-evdev`, no build step, no
  root daemon
- Device discovery by **key capability bitmap**, not by a hardcoded model or
  `event7`/`event8`
- Misconfiguration produces warnings instead of silently doing nothing;
  `--check` diagnoses a whole installation in one command
- 100+ unit tests, GitHub Actions on Python 3.9/3.12/3.13 plus shellcheck

> Detailed documentation is written in Chinese (the maintainer's language) with
> an English TL;DR at the top of each page. Translations are welcome —
> see [CONTRIBUTING.md](CONTRIBUTING.md).

## Quick start

```bash
git clone https://github.com/myml/xiaomi-ai-key-linux
cd xiaomi-ai-key-linux
./scripts/install.sh          # asks for sudo once, for the udev ACL rule
```

Then press the key: **short press opens KRunner, long press opens a terminal**
(the default configuration).

```bash
./bin/xiaomi-key-daemon.py --check        # permissions, device, service, config
journalctl --user -u xiaomi-key -f        # live log
./bin/xiaomi-key-daemon.py --test         # dump raw key events
```

## Why this exists

```
firmware -> redmi_wmi -> KEY_ASSISTANT(583) -> libinput -> KWin
         -> QXkbCommon::keysymToQtKey(XF86Assistant) -> 0 = Qt::Key_unknown -> nothing recorded
```

Measured evidence (Qt 6.11.2):

| evdev name | code | keysym | `Qt::Key` | bindable |
|---|---|---|---|---|
| `KEY_ASSISTANT` | 583 | `XF86Assistant` | `0` | ❌ |
| `KEY_F13` | 183 | `XF86Tools` | `0x010000f1` | ✅ |
| `KEY_SWITCHVIDEOMODE` | 227 | `XF86Display` | `0x010000d1` | ✅ |

So there are two ways out: make the key one that Qt understands (remap it to
F19 with hwdb), or bypass Qt (this daemon). The full chain, the reproduction
commands and the kernel event layout are in
[docs/how-it-works.md](docs/how-it-works.md).

## Compatibility

| Laptop | Input device | Key code | Status |
|---|---|---|---|
| Redmi Book 16 2024 | `Redmibook WMI keys` | 583 `KEY_ASSISTANT` | ✅ verified (Fedora 44 / Plasma 6.7.5 / Wayland / kernel 7.2.6) |
| other Xiaomi/Redmi models | name contains `WMI keys` | to be determined | 🧪 see [docs/other-models.md](docs/other-models.md) |

The daemon is distribution/desktop/display-server agnostic as long as you have
`systemd --user`. On another model you may only have to change `KEY_CODES`.

## Configuration

`~/.config/xiaomi-key/action.conf` (override with `--config` or
`$XIAOMI_KEY_CONFIG`). After editing:

```bash
systemctl --user reload xiaomi-key     # re-read the config, keep the device open
systemctl --user restart xiaomi-key    # when the daemon/udev changed
```

| Option | Default | Meaning |
|---|---|---|
| `DEVICE_NAME` | empty | **Python regex** on the device name; empty = any device reporting the key |
| `KEY_CODES` | `583` | key codes to listen for (comma/space separated); `189` if you remapped to F19 |
| `PRESS` | empty | run the moment the key goes down |
| `SHORT_PRESS` | KRunner | run on release, unless `PRESS`/`LONG_PRESS` handled it |
| `LONG_PRESS` | `konsole` | run after the key is held past the threshold |
| `LONG_PRESS_MS` | `600` | long-press threshold, minimum 50 |
| `FEEDBACK` | empty | show a `notify-send` notification when an action fires |
| `SHELL` | empty | shell used for actions, empty = `/bin/sh` |
| `DRY_RUN` | `0` | log actions instead of running them |
| `LOG_LEVEL` | `info` | `debug` / `info` / `warning` / `error` |

Combinations (all covered by `tests/test_state_machine.py`):

| configured | quick tap | hold |
|---|---|---|
| `PRESS` | press | press |
| `SHORT_PRESS` | short | nothing |
| `PRESS` + `LONG_PRESS` | press | press, then long |
| `SHORT_PRESS` + `LONG_PRESS` | short | long |
| `PRESS` + `SHORT_PRESS` | press only (short can never fire; warned at startup) | — |

So for "short press A, long press B" fill **`SHORT_PRESS` + `LONG_PRESS`** and
leave `PRESS` empty. Kernel autorepeat (`value=2`) is ignored.

```ini
SHORT_PRESS=spectacle -r -b -c -n                    # region screenshot to clipboard
LONG_PRESS=espeak-ng "$(wl-paste)"                   # read the clipboard aloud
LONG_PRESS_MS=600
```

More ready-made commands are in
[`config/action.conf.example`](config/action.conf.example).

## Commands

| Command | Purpose |
|---|---|
| `xiaomi-key-daemon.py` | run normally (systemd does this) |
| `--check` | full diagnosis; non-zero exit on hard failures |
| `--list` | list input devices, their key bitmaps, and which ones match |
| `--test` | print every key event of the device, including unbound codes |
| `--dry-run` | log actions without executing |
| `--device NODE` | use a specific `/dev/input/eventN` |
| `--once` | exit when the device disappears (debugging) |
| `-v` / `-q` | debug logging / errors only |
| `--version` | version |

## Alternative: remap to F19

If you want the key to behave like an ordinary shortcut and live in the same
settings dialog as everything else, remap 583 to F19 with hwdb and bind it in
**System Settings → Shortcuts**:

```bash
./scripts/remap-key.sh          # detects the device name, writes the hwdb rule
# log out and back in (KWin caches the key bitmap)
```

| | daemon (recommended) | hwdb remap |
|---|---|---|
| long press | ✅ | ❌ release event is dropped |
| press / short / long | ✅ three slots | ❌ press only |
| binding | `action.conf` | System Settings |
| re-login needed | no | yes |
| one place for all shortcuts | ❌ | ✅ |

The two approaches are **mutually exclusive**: after remapping the device reports
189, and a daemon listening for 583 sees nothing. `--check` and `install.sh`
detect the conflict. Rationale (why F19, why two scancodes, why `reserved` and
not `0`) is in [docs/how-it-works.md](docs/how-it-works.md).

## Layout

```
bin/xiaomi-key-daemon.py         the daemon (single file, stdlib only)
config/action.conf.example       configuration template
etc/udev/rules.d/                ACL rule (uaccess, no "input" group needed)
etc/udev/hwdb.d/                 F19 remap (alternative approach)
etc/systemd/user/                systemd --user unit
scripts/install.sh               install (--prefix/--dry-run/--no-udev/...)
scripts/uninstall.sh             uninstall (--purge)
scripts/remap-key.sh             remap (install/--verify/--remove)
tests/                           100+ unit tests, no hardware required
docs/                            internals, troubleshooting, other models
```

## FAQ

**Nothing happens.** Run `--check`, then
`libinput debug-events --show-keycodes`: if that shows nothing either, the event
never reaches the kernel. See [docs/troubleshooting.md](docs/troubleshooting.md).

**It fires twice.** Usually a remap without dropping the release scancode
(`0x11901`), or both the daemon and the remap installed at once.

**Long press does nothing.** Physically impossible after a remap; otherwise
check that `LONG_PRESS` is set and `PRESS` is not swallowing the key.

**After a kernel update.** Nothing to do; the daemon reconnects, and a changed
`eventN` does not matter.

## Development

```bash
make test     # python3 -m unittest discover -s tests -t . -v
make lint     # bash -n + shellcheck + byte-compile
make check    # diagnose this machine
```

Tests need no laptop, no root and no desktop session: device discovery runs
against a fake sysfs tree. See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

[MIT](LICENSE). Hardware reports are especially welcome — use the
[hardware report template](.github/ISSUE_TEMPLATE/hardware-report.yml).

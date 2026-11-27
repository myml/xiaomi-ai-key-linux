# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and the project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] - 2026-11-27

First public release. The project started as a personal fix for the Xiaomi AI
key on a Redmi Book 16 2024 and is now packaged for other owners of the same
firmware block.

### Added

- `xiaomi-key-daemon.py`: stdlib-only daemon that reads `/dev/input/eventN`
  directly and binds actions to `KEY_ASSISTANT` (583) without going through
  Qt/KWin, where the key is unmappable.
- Three action slots — `PRESS` (immediate), `SHORT_PRESS` (on release) and
  `LONG_PRESS` (after `LONG_PRESS_MS`) — with documented combination rules.
- Capability-based device discovery: any device whose `capabilities/key`
  bitmap contains one of the configured key codes is a candidate, so the
  daemon is not tied to one laptop model or to `event7`/`event8`.
- `--list` (devices, key bitmaps, which ones match), `--check` (installation
  diagnosis with `[ ok ]`/`[warn]`/`[FAIL]` and a non-zero exit code),
  `--test` (foreground event printer, including unbound key codes),
  `--dry-run`, `--device`, `--once`, `-v/--debug`, `-q/--quiet`.
- `systemctl --user reload xiaomi-key`: the daemon re-reads `action.conf` on
  `SIGUSR1` instead of restarting.
- Configuration warnings instead of silent failures: unknown options, bad
  numbers, invalid regexes, and the dead `PRESS` + `SHORT_PRESS` combination
  are all reported at startup and by `--check`.
- `scripts/install.sh` (`--prefix`, `--no-udev`, `--no-service`,
  `--force-config`, `--dry-run`) and `scripts/uninstall.sh`
  (`--purge`, `--no-udev`, `--dry-run`).
- `scripts/remap-key.sh`: alternative approach that remaps the key to F19 with
  hwdb so the desktop shortcut recorder can bind it; detects the device name on
  the local machine instead of hardcoding it, verifies the resulting key
  bitmap, and warns when the daemon is active.
- udev rule with `uaccess` ACL (no `input` group membership needed) and a
  stable `/dev/input/xiaomi-key` symlink.
- 107 unit tests covering config parsing, key-bitmap decoding, device discovery
  against a fake sysfs tree, the whole press/short/long truth table, and event
  stream reassembly across split reads.
- CI (GitHub Actions) running the test suite on Python 3.9/3.12/3.13 plus
  shellcheck and `bash -n` on the scripts.
- Documentation: how the kernel/WMI/Qt chain works (with the evidence used to
  find it), troubleshooting, and a guide for adapting the project to other
  models.

### Fixed (relative to the initial one-off scripts)

- README pointed at `/dev/input/event7`; the node is not stable across boots.
  Discovery is now capability based and the udev rule creates
  `/dev/input/xiaomi-key`.
- The systemd unit claimed `BindsTo=dev-input-xiaomi\x2dkey.device` while
  actually shipping without it; the comment now explains why there is no
  `BindsTo` (it would defeat `Restart=always`).
- udev/hwdb match patterns use `*` globs. `Redmi?book` can never match
  `Redmibook` because `?` means exactly one character in globs.

[1.0.0]: https://github.com/myml/xiaomi-ai-key-linux/releases/tag/v1.0.0

# Contributing

Thanks for taking a look. This project is small on purpose: one Python file
with no third-party dependencies. Please keep it that way unless there is a
strong reason not to.

## Ground rules

- **No new runtime dependencies.** The daemon has to run on a fresh install
  with nothing but `/usr/bin/python3` (>= 3.9) and systemd.
- **No root.** Everything runs as the logged-in user; `sudo` appears only in
  the install/uninstall scripts for the udev rule.
- **Code and log messages are English.** User-facing docs are Chinese with an
  English summary; `README.en.md` is a full translation. If you add a feature,
  document it in both READMEs (English may be shorter).
- Be kind. See [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).

## Development setup

Nothing to install, no virtualenv, no build step:

```bash
git clone https://github.com/myml/xiaomi-ai-key-linux
cd xiaomi-ai-key-linux
make test          # python3 -m unittest discover -s tests -t . -v
make lint          # bash -n + shellcheck, if available
./bin/xiaomi-key-daemon.py --list
./bin/xiaomi-key-daemon.py --check
./bin/xiaomi-key-daemon.py --help
```

To try a change without touching your installation, point the daemon at a
throwaway config and run it in the foreground:

```bash
cp config/action.conf.example /tmp/test-action.conf
./bin/xiaomi-key-daemon.py --config /tmp/test-action.conf --test
```

## Layout

```
bin/        the daemon (single file)
config/     action.conf template
etc/        udev rule, hwdb remap, systemd user unit
scripts/    install / uninstall / remap
tests/      unittest suite, no hardware required
docs/       long-form documentation
```

Keep it that way: no `src/` package, no `setup.py`. The one-file design is a
feature — you can `scp` the daemon to a laptop and it runs.

## Adding support for another model

1. Find the device and the key code:

   ```bash
   ./bin/xiaomi-key-daemon.py --list
   ./bin/xiaomi-key-daemon.py --test
   ```

   `--test` prints every key event of the device, including codes that are not
   in `KEY_CODES`, which is the fastest way to discover what the firmware
   actually reports.

2. Set `DEVICE_NAME` (optional regex) and `KEY_CODES` in `action.conf`.
3. If the device name is not something like `*WMI keys`, the udev rule needs a
   second match block, or narrow the existing one.
4. Add a row to the compatibility table in `README.md` and
   `docs/other-models.md`, and open the hardware issue template so the
   evidence is captured.

## Tests

- Behaviour changes need a test in `tests/test_state_machine.py` or
  `tests/test_config.py`.
- The truth table in the README is exercised by `tests/test_state_machine.py`.
  If you change a rule, update both.
- `tests/test_packaging.py` cross-checks the shipped files (unit `ExecStart`
  vs. install path, hwdb using `reserved` instead of `=0`, no stale flat
  layout). Update it when you move files.
- Tests must pass without a Xiaomi laptop, without root, and without a desktop
  session. Use `tests/helpers.py`'s fake sysfs tree for device logic.

## Style

- Python 3.9 compatible syntax (CI runs 3.9): no `match`, no `X | Y` at
  runtime, no `tomllib`.
- 4 spaces, ~90 columns, type hints where they help, comments explain *why*.
- `ruff check .` is welcome but not required (CI currently lints with
  `python -m compileall` and shellcheck).
- Shell: `bash`, `set -euo pipefail`, quote expansions, keep `shellcheck`
  clean.

## Commits and pull requests

- Commits: `area: what changed` (e.g. `daemon: ignore autorepeat`,
  `docs: explain the hwdb quirk`). Squash fixups before opening a PR.
- A PR should state: what problem it solves, how it was tested, and the exact
  hardware/desktop it was tested on when the change is touchy.
- Update `CHANGELOG.md` under `## [Unreleased]` for user-visible changes.

## Reporting problems

Use the issue templates. For "the key does nothing" reports, please include:

```bash
./bin/xiaomi-key-daemon.py --check
./bin/xiaomi-key-daemon.py --list
journalctl --user -u xiaomi-key -b --no-pager | tail -50
```

and your laptop model, distribution, kernel, and desktop/compositor.

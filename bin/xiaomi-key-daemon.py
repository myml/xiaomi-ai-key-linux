#!/usr/bin/python3
# -*- coding: utf-8 -*-
"""Bind actions to the Xiaomi / Redmi AI ("assistant") key on Linux.

The daemon reads ``/dev/input/eventN`` directly and never goes through
Qt/KWin, so the raw ``KEY_ASSISTANT`` (583) works even though Qt has no
mapping for ``XF86Assistant`` and therefore cannot record it in the
desktop's shortcut editor.  See docs/how-it-works.md for the full chain.

Standard library only: no python-evdev, no venv, no build step.

Usage::

    xiaomi-key-daemon.py              # run the daemon (normally via systemd --user)
    xiaomi-key-daemon.py --list       # list input devices and exit
    xiaomi-key-daemon.py --check      # diagnose the installation and exit
    xiaomi-key-daemon.py --test       # print key events in the foreground
"""

from __future__ import annotations

import argparse
import errno
import glob
import logging
import os
import re
import select
import shutil
import signal
import struct
import subprocess
import sys
import time
from dataclasses import dataclass, field

__version__ = "1.0.0"

APP_NAME = "xiaomi-key"
LOG = logging.getLogger(APP_NAME)

# --- kernel input ABI -------------------------------------------------------

EV_SYN = 0x00
EV_KEY = 0x01

KEY_F19 = 189
KEY_ASSISTANT = 583

KEY_NAMES = {
    172: "KEY_HOMEPAGE",
    183: "KEY_F13",
    184: "KEY_F14",
    185: "KEY_F15",
    186: "KEY_F16",
    187: "KEY_F17",
    188: "KEY_F18",
    189: "KEY_F19",
    227: "KEY_SWITCHVIDEOMODE",
    228: "KEY_BRIGHTNESSDOWN",
    229: "KEY_BRIGHTNESSUP",
    583: "KEY_ASSISTANT",
}

DEFAULT_KEY_CODES = (KEY_ASSISTANT,)
DEFAULT_LONG_PRESS_MS = 600
MIN_LONG_PRESS_MS = 50

# struct input_event { struct timeval time; __u16 type; __u16 code; __s32 value; }
# `llHHi` matches it natively: 24 bytes on 64-bit Linux (16 byte timeval plus
# 2 + 2 + 4), 16 bytes on 32-bit. Native `struct` alignment does the right thing.
EVENT_STRUCT = struct.Struct("llHHi")

SYSFS_INPUT_DIR = "/sys/class/input"
DEV_INPUT_DIR = "/dev/input"

CONFIG_ENV_VAR = "XIAOMI_KEY_CONFIG"
# Documented default; the effective path honours $XDG_CONFIG_HOME (see
# default_config_path()).
DEFAULT_CONFIG_PATH = "~/.config/xiaomi-key/action.conf"

UDEV_RULE_PATH = "/etc/udev/rules.d/60-xiaomi-key.rules"
HWDB_RULE_PATH = "/etc/udev/hwdb.d/70-xiaomi-key-remap.hwdb"
UNIT_NAME = "xiaomi-key.service"

# Action slots, in firing order.
SLOT_PRESS = "press"
SLOT_SHORT = "short"
SLOT_LONG = "long"


def key_name(code: int) -> str:
    """Human readable name of an evdev key code."""
    return KEY_NAMES.get(code, "KEY_%d" % code)


def _read(path: str) -> str:
    """Read a small sysfs attribute, returning '' when it does not exist."""
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError:
        return ""


# --- device discovery -------------------------------------------------------


def decode_keybit(hexstring: str) -> frozenset:
    """Decode ``capabilities/key`` ("400000000000080 ...") into key codes.

    The kernel prints the bitmap as big-endian 64-bit words, most
    significant word first, so the words have to be consumed in reverse.
    """
    words = hexstring.split()
    value = 0
    for index, word in enumerate(reversed(words)):
        try:
            value |= int(word, 16) << (64 * index)
        except ValueError:
            continue
    codes = []
    code = 0
    while value:
        if value & 1:
            codes.append(code)
        value >>= 1
        code += 1
    return frozenset(codes)


def format_codes(codes) -> str:
    """Render key codes compactly: ``171, 183-187, 583``."""
    ordered = sorted(set(codes))
    if not ordered:
        return "(none)"
    ranges = []
    start = previous = ordered[0]
    for code in ordered[1:]:
        if code == previous + 1:
            previous = code
            continue
        ranges.append((start, previous))
        start = previous = code
    ranges.append((start, previous))
    return ", ".join("%d" % a if a == b else "%d-%d" % (a, b) for a, b in ranges)


@dataclass(frozen=True)
class InputDevice:
    """One ``/dev/input/eventN`` node together with what it can emit."""

    event: str
    name: str
    node: str
    key_codes: frozenset = frozenset()

    @property
    def event_number(self) -> int:
        digits = "".join(ch for ch in self.event if ch.isdigit())
        return int(digits) if digits else 0

    def reports(self, codes) -> bool:
        return bool(self.key_codes & frozenset(codes))


def _compile_pattern(pattern: str):
    if not pattern:
        return None
    try:
        return re.compile(pattern)
    except re.error as exc:
        LOG.warning(
            "DEVICE_NAME is not a valid regular expression (%s); "
            "falling back to capability matching", exc)
        return None


def discover_devices(pattern: str = "",
                     key_codes=DEFAULT_KEY_CODES,
                     sysfs_dir: str = SYSFS_INPUT_DIR,
                     dev_dir: str = DEV_INPUT_DIR):
    """Find input devices that can emit at least one of ``key_codes``.

    Matching is capability based (``capabilities/key``) so it keeps working on
    any laptop that reports ``KEY_ASSISTANT``, whatever the device is called.
    An optional regex narrows the result further.
    """
    regex = _compile_pattern(pattern)
    devices = []
    for syspath in glob.glob(os.path.join(sysfs_dir, "event*")):
        event = os.path.basename(syspath)
        name = _read(os.path.join(syspath, "device", "name")).strip()
        codes = decode_keybit(_read(os.path.join(syspath, "device",
                                                "capabilities", "key")))
        if regex is not None and not regex.search(name):
            continue
        if key_codes:
            if codes:
                if not (frozenset(key_codes) & codes):
                    continue
            elif regex is None:
                # Nothing to match on: no name filter and no capability map.
                continue
        devices.append(InputDevice(event=event, name=name,
                                   node=os.path.join(dev_dir, event),
                                   key_codes=codes))
    devices.sort(key=lambda dev: dev.event_number)
    return devices


def device_from_node(node: str) -> InputDevice:
    """Wrap an explicitly given ``/dev/input/eventN`` path."""
    event = os.path.basename(node)
    syspath = os.path.join(SYSFS_INPUT_DIR, event)
    return InputDevice(
        event=event,
        name=_read(os.path.join(syspath, "device", "name")).strip() or "(unknown)",
        node=node,
        key_codes=decode_keybit(_read(os.path.join(syspath, "device",
                                                      "capabilities", "key"))),
    )


# --- configuration ----------------------------------------------------------


@dataclass
class Config:
    """Contents of ``action.conf`` plus the problems found while parsing it."""

    path: str = "<defaults>"
    device_name: str = ""
    key_codes: tuple = DEFAULT_KEY_CODES
    press: str = ""
    short_press: str = ""
    long_press: str = ""
    long_press_ms: int = DEFAULT_LONG_PRESS_MS
    feedback: str = ""
    shell: str = ""
    dry_run: bool = False
    log_level: str = "info"
    warnings: list = field(default_factory=list)

    def slots(self):
        """Configured actions as ``(slot, command)`` pairs, unset ones dropped."""
        pairs = ((SLOT_PRESS, self.press),
                 (SLOT_SHORT, self.short_press),
                 (SLOT_LONG, self.long_press))
        return [(slot, cmd) for slot, cmd in pairs if cmd]

    def has_action(self) -> bool:
        return bool(self.slots())

    @classmethod
    def from_text(cls, text: str, path: str = "<inline>") -> "Config":
        cfg = cls(path=path)
        for lineno, raw in enumerate(text.splitlines(), 1):
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip().upper()
            value = value.strip()
            where = "%s:%d" % (path, lineno)
            if key == "DEVICE_NAME":
                cfg.device_name = value
            elif key == "KEY_CODES":
                codes = []
                for part in re.split(r"[,\s]+", value):
                    if not part:
                        continue
                    try:
                        code = int(part, 0)
                    except ValueError:
                        cfg.warnings.append(
                            "%s: KEY_CODES entry %r is not a number, ignored"
                            % (where, part))
                        continue
                    if code < 0:
                        cfg.warnings.append(
                            "%s: KEY_CODES entry %r is negative, ignored"
                            % (where, part))
                        continue
                    codes.append(code)
                if codes:
                    cfg.key_codes = tuple(codes)
                else:
                    cfg.warnings.append("%s: KEY_CODES is empty, keeping default"
                                        % where)
            elif key == "PRESS":
                cfg.press = value
            elif key == "SHORT_PRESS":
                cfg.short_press = value
            elif key == "LONG_PRESS":
                cfg.long_press = value
            elif key == "LONG_PRESS_MS":
                try:
                    cfg.long_press_ms = int(value)
                except ValueError:
                    cfg.warnings.append(
                        "%s: LONG_PRESS_MS %r is not a number, keeping %d"
                        % (where, value, cfg.long_press_ms))
            elif key == "FEEDBACK":
                cfg.feedback = value
            elif key == "SHELL":
                cfg.shell = value
            elif key == "DRY_RUN":
                parsed = _parse_bool(value)
                if parsed is None:
                    cfg.warnings.append(
                        "%s: DRY_RUN %r is not a boolean, ignored" % (where, value))
                else:
                    cfg.dry_run = parsed
            elif key == "LOG_LEVEL":
                level = value.lower()
                if level not in _LOG_LEVELS:
                    cfg.warnings.append(
                        "%s: LOG_LEVEL %r is not one of %s, ignored"
                        % (where, value, "/".join(sorted(_LOG_LEVELS))))
                else:
                    cfg.log_level = level
            else:
                cfg.warnings.append("%s: unknown option %r, ignored"
                                    % (where, key))
        cfg._post_validate()
        return cfg

    @classmethod
    def from_file(cls, path: str) -> "Config":
        path = os.path.expanduser(path)
        try:
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
        except FileNotFoundError:
            cfg = cls(path=path)
            cfg.warnings.append(
                "%s: not found, running with built-in defaults" % path)
            cfg._post_validate()
            return cfg
        except OSError as exc:
            cfg = cls(path=path)
            cfg.warnings.append("%s: cannot read (%s), using defaults" % (path, exc))
            cfg._post_validate()
            return cfg
        return cls.from_text(text, path=path)

    def _post_validate(self) -> None:
        if self.long_press_ms < MIN_LONG_PRESS_MS:
            self.warnings.append(
                "LONG_PRESS_MS %d is below the %d ms floor, clamped"
                % (self.long_press_ms, MIN_LONG_PRESS_MS))
            self.long_press_ms = MIN_LONG_PRESS_MS
        if self.press and self.short_press:
            self.warnings.append(
                "PRESS and SHORT_PRESS are both set: SHORT_PRESS can never fire "
                "(PRESS already consumed the press). Drop PRESS if you want "
                "short-press detection.")
        if self.device_name:
            try:
                re.compile(self.device_name)
            except re.error as exc:
                self.warnings.append(
                    "DEVICE_NAME %r is not a valid regular expression (%s); "
                    "matching by key capability only" % (self.device_name, exc))
        if self.shell and not os.path.isabs(self.shell):
            self.warnings.append(
                "SHELL %r should be an absolute path; using it as given"
                % self.shell)
        if self.shell and not os.access(self.shell, os.X_OK):
            self.warnings.append("SHELL %r is not executable" % self.shell)


_LOG_LEVELS = {
    "debug": logging.DEBUG,
    "info": logging.INFO,
    "warning": logging.WARNING,
    "error": logging.ERROR,
}


def _parse_bool(value: str):
    lowered = value.strip().lower()
    if lowered in ("1", "yes", "true", "on"):
        return True
    if lowered in ("0", "no", "false", "off", ""):
        return False
    return None


# --- press / short press / long press state machine -------------------------


@dataclass(frozen=True)
class Fired:
    """An action that reached its trigger condition."""

    slot: str
    command: str


class KeyStateMachine:
    """Short/long-press detection, driven purely by events and timestamps.

    Kept free of I/O so the whole truth table can be unit tested:

    ==========================  =============  =====================
    configured                  quick tap      hold past threshold
    ==========================  =============  =====================
    press                       press          press
    short                       short          --
    press + long                press          press, then long
    short + long                short          long
    press + short               press          press (short is dead)
    ==========================  =============  =====================
    """

    def __init__(self, cfg: Config) -> None:
        self.press = cfg.press
        self.short_press = cfg.short_press
        self.long_press = cfg.long_press
        self.long_press_s = cfg.long_press_ms / 1000.0
        self.reset()

    def reset(self) -> None:
        self._pressed = False
        self._press_at = 0.0
        self._long_fired = False
        self._press_fired = False

    @property
    def pressed(self) -> bool:
        return self._pressed

    def deadline(self):
        """Monotonic time at which the long press fires, or ``None``."""
        if self._pressed and not self._long_fired and self.long_press:
            return self._press_at + self.long_press_s
        return None

    def on_key(self, value: int, now: float):
        """Feed one ``EV_KEY`` value (1 = press, 0 = release, 2 = repeat)."""
        fired = []
        if value == 1:
            self._pressed = True
            self._press_at = now
            self._long_fired = False
            self._press_fired = False
            if self.press:
                fired.append(Fired(SLOT_PRESS, self.press))
                self._press_fired = True
        elif value == 0:
            was_pressed = self._pressed
            consumed = self._press_fired or self._long_fired
            self._pressed = False
            self._long_fired = False
            self._press_fired = False
            if was_pressed and not consumed and self.short_press:
                fired.append(Fired(SLOT_SHORT, self.short_press))
        # value == 2 is kernel autorepeat: ignored on purpose so that holding
        # the key does not machine-gun the press action.
        return fired

    def on_timeout(self, now: float):
        """Called when ``select()`` timed out; fires the long press if due."""
        deadline = self.deadline()
        if deadline is None or now < deadline:
            return []
        self._long_fired = True
        return [Fired(SLOT_LONG, self.long_press)]


# --- event stream -----------------------------------------------------------


class EventReader:
    """Turn raw ``/dev/input`` bytes into events, tolerating partial reads."""

    def __init__(self) -> None:
        self._buffer = bytearray()

    @property
    def pending(self) -> int:
        return len(self._buffer)

    def feed(self, chunk: bytes):
        """Append bytes and return every complete ``(type, code, value)``."""
        self._buffer.extend(chunk)
        events = []
        size = EVENT_STRUCT.size
        offset = 0
        while offset + size <= len(self._buffer):
            _sec, _usec, etype, code, value = EVENT_STRUCT.unpack_from(
                self._buffer, offset)
            offset += size
            events.append((etype, code, value))
        del self._buffer[:offset]
        return events


# --- running actions --------------------------------------------------------


def run_action(cfg: Config, fired: Fired) -> None:
    """Execute one action in its own session so it outlives the daemon's fork."""
    LOG.info("%s -> %s", fired.slot, fired.command)
    if cfg.dry_run:
        return
    kwargs = dict(start_new_session=True, stdin=subprocess.DEVNULL)
    try:
        if cfg.shell:
            subprocess.Popen([cfg.shell, "-c", fired.command], **kwargs)
        else:
            subprocess.Popen(fired.command, shell=True, **kwargs)
    except OSError as exc:
        LOG.error("cannot run action: %s", exc)


def notify(cfg: Config) -> None:
    if not cfg.feedback or cfg.dry_run:
        return
    try:
        subprocess.Popen(
            ["notify-send", "-a", APP_NAME, "-t", "1500", cfg.feedback],
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        LOG.debug("notify-send unavailable, skipping feedback")


def fire(cfg: Config, fired: Fired) -> None:
    run_action(cfg, fired)
    notify(cfg)


# --- session ----------------------------------------------------------------


class _Reload(Exception):
    """Raised from the SIGUSR1 handler to reload the configuration."""


class _Stop(Exception):
    """Raised from the SIGTERM handler to unwind cleanly."""


def _install_signal_handlers() -> None:
    def reload_handler(signum, frame):  # noqa: ARG001 - signal signature
        raise _Reload()

    def stop_handler(signum, frame):  # noqa: ARG001
        raise _Stop()

    signal.signal(signal.SIGUSR1, reload_handler)
    signal.signal(signal.SIGTERM, stop_handler)


def describe_event(cfg: Config, code: int, value: int) -> str:
    """One line of ``--test`` output."""
    state = {0: "release", 1: "press", 2: "repeat"}.get(value, str(value))
    bound = "bound" if code in cfg.key_codes else "not in KEY_CODES"
    # A tab, not spaces: keeps columns aligned enough when piping to less.
    return "  %s code=%-4d %-8s %-16s %s" % (
        time.strftime("%H:%M:%S"), code, state, key_name(code), bound)


def serve_device(fd: int, device: InputDevice, cfg: Config,
                 test_mode: bool = False) -> None:
    """Blocking event loop for one open device. Raises on device errors."""
    reader = EventReader()
    machine = KeyStateMachine(cfg)
    LOG.info("listening on %s (%s)", device.node, device.name)

    while True:
        timeout = None
        if not test_mode:
            deadline = machine.deadline()
            if deadline is not None:
                timeout = max(0.0, deadline - time.monotonic())

        ready, _, _ = select.select([fd], [], [], timeout)
        now = time.monotonic()

        if not ready:
            for fired in machine.on_timeout(now):
                fire(cfg, fired)
            continue

        chunk = os.read(fd, EVENT_STRUCT.size * 64)
        if not chunk:
            raise OSError(errno.ENODEV, "device returned EOF")

        for etype, code, value in reader.feed(chunk):
            if etype != EV_KEY:
                continue
            if test_mode:
                print(describe_event(cfg, code, value), flush=True)
                continue
            if code not in cfg.key_codes:
                LOG.debug("ignoring %s (%d)", key_name(code), code)
                continue
            for fired in machine.on_key(value, time.monotonic()):
                fire(cfg, fired)


def log_banner(cfg: Config) -> None:
    LOG.info("config: %s", cfg.path)
    LOG.info("key codes: %s", ", ".join(
        "%d (%s)" % (code, key_name(code)) for code in cfg.key_codes))
    LOG.info("press: %s", cfg.press or "(unset)")
    LOG.info("short: %s", cfg.short_press or "(unset)")
    LOG.info("long: %s (>%d ms)", cfg.long_press or "(unset)", cfg.long_press_ms)
    if cfg.device_name:
        LOG.info("device pattern: %s", cfg.device_name)
    if cfg.dry_run:
        LOG.info("dry-run: actions are logged, not executed")
    for warning in cfg.warnings:
        LOG.warning("%s", warning)


def run(cfg: Config, args) -> int:
    """Reconnecting supervisor loop."""
    _install_signal_handlers()
    backoff = 1.0
    warned_permission = False

    while True:
        if args.device:
            candidates = [device_from_node(os.path.expanduser(args.device))]
        else:
            candidates = discover_devices(cfg.device_name, cfg.key_codes)

        if not candidates:
            LOG.warning("no input device reporting %s found; retrying in %.0fs",
                        format_codes(cfg.key_codes), backoff)
            LOG.warning("hint: run `%s --list` to see every input device",
                        os.path.basename(sys.argv[0]))
            if args.once:
                return 1
            time.sleep(backoff)
            backoff = min(backoff * 2, 30.0)
            continue

        device = candidates[0]
        if len(candidates) > 1:
            LOG.debug("several matching devices, using %s", device.node)

        try:
            fd = os.open(device.node, os.O_RDONLY)
        except PermissionError:
            if not warned_permission:
                LOG.error("cannot read %s (permission denied)", device.node)
                LOG.error("the udev rule grants your session access; install it "
                          "and re-login: sudo install -m644 "
                          "etc/udev/rules.d/60-xiaomi-key.rules %s",
                          UDEV_RULE_PATH)
                warned_permission = True
            if args.once:
                return 1
            time.sleep(backoff)
            backoff = min(backoff * 2, 30.0)
            continue
        except OSError as exc:
            LOG.warning("cannot open %s: %s; retrying", device.node, exc)
            if args.once:
                return 1
            time.sleep(backoff)
            backoff = min(backoff * 2, 30.0)
            continue

        backoff = 1.0
        warned_permission = False
        try:
            serve_device(fd, device, cfg, test_mode=args.test)
        except _Reload:
            LOG.info("SIGUSR1: reloading %s", cfg.path)
            cfg = Config.from_file(cfg.path)
            log_banner(cfg)
            continue
        except OSError as exc:
            LOG.warning("device error: %s; reconnecting", exc)
        finally:
            try:
                os.close(fd)
            except OSError:
                pass

        if args.once:
            return 0
        time.sleep(1.0)


def setup_logging(level: str) -> None:
    logging.basicConfig(
        level=_LOG_LEVELS.get(level, logging.INFO),
        format="%(levelname)s: %(message)s",
        stream=sys.stderr,
    )


def xdg_config_home() -> str:
    return os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")


def default_config_path() -> str:
    """Effective default config path, honouring $XDG_CONFIG_HOME."""
    return os.path.join(xdg_config_home(), "xiaomi-key", "action.conf")


def load_config(args) -> Config:
    path = args.config or os.environ.get(CONFIG_ENV_VAR) or default_config_path()
    return Config.from_file(path)


def resolve_verbose(cfg: Config, args) -> str:
    if getattr(args, "debug", False):
        return "debug"
    if getattr(args, "quiet", False):
        return "error"
    return cfg.log_level


# --- subcommands ------------------------------------------------------------


def cmd_list(cfg: Config) -> int:
    all_devices = discover_devices(pattern="", key_codes=())
    matched = {dev.event for dev in discover_devices(cfg.device_name, cfg.key_codes)}
    print("input devices (%d):" % len(all_devices))
    for dev in all_devices:
        marker = "->" if dev.event in matched else "  "
        print('%s /dev/input/%-9s %s' % (marker, dev.event, dev.name or "(unknown)"))
        print("     codes: %s" % format_codes(dev.key_codes))
        hits = sorted(frozenset(cfg.key_codes) & dev.key_codes)
        if hits:
            print("     reports: %s" % ", ".join(
                "%d (%s)" % (c, key_name(c)) for c in hits))
    print()
    print("looking for key codes: %s" % format_codes(cfg.key_codes))
    print("device pattern: %s" % (cfg.device_name or "(any device with the key)"))
    if not matched:
        print("no match yet: check `--list` output above, then set KEY_CODES / "
              "DEVICE_NAME in %s" % cfg.path)
        return 1
    return 0


def _check_action_commands(cfg: Config):
    """Yield (status, message) for every configured action command."""
    slots = cfg.slots()
    if not slots:
        yield "warn", "no action configured (PRESS/SHORT_PRESS/LONG_PRESS all empty)"
        return
    for slot, command in slots:
        name = command.split()[0]
        if name in _SHELL_BUILTINS:
            yield "ok", "%s: %r is a shell builtin" % (slot, name)
        elif shutil.which(name):
            yield "ok", "%s: %s found" % (slot, command)
        else:
            yield "warn", "%s: %r not found in PATH" % (slot, name)


_SHELL_BUILTINS = frozenset(
    "true false echo cd test printf sleep exec exit . [ ] :".split())


def cmd_check(cfg: Config, args) -> int:
    results = []

    version = sys.version_info
    results.append(("ok" if version >= (3, 9) else "fail",
                    "python %d.%d.%d (%s)" % (version[0], version[1],
                                              version[2], sys.executable)))

    if os.path.exists(os.path.expanduser(cfg.path)):
        results.append(("ok", "config %s" % cfg.path))
    else:
        results.append(("warn", "config %s missing, defaults in use" % cfg.path))
    for warning in cfg.warnings:
        results.append(("warn", warning))

    results.append(("ok", "key codes %s" % ", ".join(
        "%d (%s)" % (c, key_name(c)) for c in cfg.key_codes)))

    devices = discover_devices(cfg.device_name, cfg.key_codes)
    if devices:
        for dev in devices:
            results.append(("ok", "device %s %r reports %s" % (
                dev.node, dev.name,
                format_codes(frozenset(cfg.key_codes) & dev.key_codes))))
        readable = os.access(devices[0].node, os.R_OK)
        results.append(("ok" if readable else "fail",
                        "%s is readable" % devices[0].node))
        if not readable:
            results.append(("warn", "install the udev rule and re-login: "
                                    "sudo install -m644 etc/udev/rules.d/"
                                    "%s %s" % (os.path.basename(UDEV_RULE_PATH),
                                               UDEV_RULE_PATH)))
        if os.path.islink(os.path.join(DEV_INPUT_DIR, "xiaomi-key")):
            results.append(("ok", "%s/xiaomi-key symlink present" % DEV_INPUT_DIR))
        else:
            results.append(("warn", "%s/xiaomi-key symlink missing "
                                    "(udev rule not applied yet?)" % DEV_INPUT_DIR))
    else:
        results.append(("fail", "no device reporting key code(s) %s found" % (
            format_codes(cfg.key_codes))))
        results.append(("warn", "if the key was remapped with the hwdb rule, "
                                "set KEY_CODES to the remapped code (e.g. 189)"))

    results.append(("ok" if os.path.exists(UDEV_RULE_PATH) else "warn",
                    "udev rule %s" % ("installed" if os.path.exists(UDEV_RULE_PATH)
                                      else "missing (sudo install -m644 "
                                           "etc/udev/rules.d/60-xiaomi-key.rules "
                                           + UDEV_RULE_PATH + ")")))

    remapped = os.path.exists(HWDB_RULE_PATH)
    assistant_bound = KEY_ASSISTANT in cfg.key_codes
    if remapped and assistant_bound:
        results.append(("warn", "hwdb remap installed but KEY_CODES still targets "
                                "583: run `remap-key.sh --remove` or set "
                                "KEY_CODES=189"))
    elif not remapped and not assistant_bound:
        results.append(("warn", "KEY_CODES does not target KEY_ASSISTANT (583) and "
                                "no hwdb remap is installed"))

    unit_path = os.path.join(xdg_config_home(), "systemd", "user", UNIT_NAME)
    unit_installed = os.path.exists(unit_path)
    active = _systemctl_user(["is-active", UNIT_NAME]) == "active"
    results.append(("ok" if unit_installed else "warn",
                    "systemd user unit %s" % ("installed" if unit_installed
                                              else "missing (run install.sh)")))
    results.append(("ok" if active else "warn",
                    "%s is %s" % (UNIT_NAME, "active" if active else "inactive")))

    if cfg.feedback:
        results.append(("ok" if shutil.which("notify-send") else "warn",
                        "notify-send for feedback: %s" % (
                            "found" if shutil.which("notify-send") else "missing")))
    results.extend(_check_action_commands(cfg))

    labels = {"ok": "[ ok ]", "warn": "[warn]", "fail": "[FAIL]"}
    print("xiaomi-key %s --check" % __version__)
    for status, message in results:
        print("%s %s" % (labels[status], message))
    failures = sum(1 for status, _ in results if status == "fail")
    warnings = sum(1 for status, _ in results if status == "warn")
    print()
    print("%d failure(s), %d warning(s)" % (failures, warnings))
    return 1 if failures else 0


def _systemctl_user(arguments):
    try:
        out = subprocess.run(["systemctl", "--user"] + arguments,
                             capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return ""
    return out.stdout.strip()


# --- CLI --------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="xiaomi-key-daemon.py",
        description="Bind actions to the Xiaomi/Redmi AI key on Linux.",
        epilog="Config: ~/.config/xiaomi-key/action.conf "
               "(override with --config or $%s)." % CONFIG_ENV_VAR,
    )
    parser.add_argument("--version", action="version",
                        version="%(prog)s " + __version__)
    parser.add_argument("--config", metavar="PATH",
                        help="configuration file (default: %s)" % DEFAULT_CONFIG_PATH)
    parser.add_argument("--device", metavar="NODE",
                        help="use this /dev/input/eventN instead of auto-detection")
    parser.add_argument("--list", action="store_true",
                        help="list input devices and their key capabilities")
    parser.add_argument("--check", action="store_true",
                        help="diagnose the installation, exit non-zero on failure")
    parser.add_argument("--test", action="store_true",
                        help="print key events in the foreground, run no actions")
    parser.add_argument("--dry-run", action="store_true",
                        help="log actions instead of executing them")
    parser.add_argument("--once", action="store_true",
                        help="exit after the first device disappears")
    parser.add_argument("-v", "--debug", action="store_true",
                        help="verbose logging")
    parser.add_argument("-q", "--quiet", action="store_true",
                        help="errors only")
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    cfg = load_config(args)
    setup_logging(resolve_verbose(cfg, args))

    if args.dry_run:
        cfg.dry_run = True

    if args.list:
        return cmd_list(cfg)
    if args.check:
        return cmd_check(cfg, args)

    log_banner(cfg)
    if args.test:
        LOG.info("test mode: press the key (Ctrl-C to quit)")

    try:
        return run(cfg, args)
    except (KeyboardInterrupt, _Stop):
        LOG.info("stopping")
        return 0


if __name__ == "__main__":
    sys.exit(main())

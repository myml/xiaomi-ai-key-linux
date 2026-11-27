"""Static checks that keep the shipped files consistent with each other.

These catch the mistakes that unit tests cannot: a hwdb rule that disables a
key with ``=0`` (which types a digit zero), a glob written with ``?``, a unit
file that points at a path install.sh does not create, and so on.
"""

import os
import unittest

from tests.helpers import REPO_ROOT, load_daemon

daemon = load_daemon()

REQUIRED_FILES = [
    "README.md",
    "README.en.md",
    "LICENSE",
    "CHANGELOG.md",
    "CONTRIBUTING.md",
    "Makefile",
    ".gitignore",
    "bin/xiaomi-key-daemon.py",
    "config/action.conf.example",
    "etc/udev/rules.d/60-xiaomi-key.rules",
    "etc/udev/hwdb.d/70-xiaomi-key-remap.hwdb",
    "etc/systemd/user/xiaomi-key.service",
    "scripts/install.sh",
    "scripts/uninstall.sh",
    "scripts/remap-key.sh",
    "docs/how-it-works.md",
    "docs/troubleshooting.md",
    "docs/other-models.md",
    ".github/workflows/ci.yml",
    ".github/ISSUE_TEMPLATE/hardware-report.yml",
]

SCRIPTS = ["scripts/install.sh", "scripts/uninstall.sh", "scripts/remap-key.sh"]


def read(relative_path):
    with open(os.path.join(REPO_ROOT, relative_path), encoding="utf-8") as fh:
        return fh.read()


class LayoutTest(unittest.TestCase):
    def test_required_files_exist(self):
        for relative_path in REQUIRED_FILES:
            with self.subTest(path=relative_path):
                self.assertTrue((REPO_ROOT / relative_path).is_file(),
                                "missing %s" % relative_path)

    def test_no_stale_flat_layout(self):
        # The v0 layout had everything in the repository root.
        for name in ("xiaomi-key-daemon.py", "install.sh", "uninstall.sh",
                     "60-xiaomi-key.rules", "70-xiaomi-key-remap.hwdb",
                     "xiaomi-key.service", "action.conf.example"):
            with self.subTest(name=name):
                self.assertFalse((REPO_ROOT / name).exists(),
                                 "%s should live in a subdirectory now" % name)

    def test_scripts_are_executable(self):
        for relative_path in SCRIPTS:
            with self.subTest(path=relative_path):
                mode = os.stat(REPO_ROOT / relative_path).st_mode
                self.assertTrue(mode & 0o111, "%s is not executable" % relative_path)
        mode = os.stat(REPO_ROOT / "bin" / "xiaomi-key-daemon.py").st_mode
        self.assertTrue(mode & 0o111)


class ScriptStyleTest(unittest.TestCase):
    def test_strict_mode(self):
        for relative_path in SCRIPTS:
            with self.subTest(path=relative_path):
                text = read(relative_path)
                self.assertIn("set -euo pipefail", text)
                self.assertTrue(text.startswith("#!/usr/bin/env bash"))

    def test_no_root_execution(self):
        for relative_path in SCRIPTS:
            with self.subTest(path=relative_path):
                self.assertIn("EUID -ne 0", read(relative_path),
                              "%s should refuse to run as root" % relative_path)


class UdevRuleTest(unittest.TestCase):
    def setUp(self):
        self.text = read("etc/udev/rules.d/60-xiaomi-key.rules")

    def test_grants_uaccess_acl(self):
        self.assertIn('TAG+="uaccess"', self.text)

    def test_creates_stable_symlink(self):
        self.assertIn('SYMLINK+="input/xiaomi-key"', self.text)

    def test_no_question_mark_glob(self):
        # udev/hwdb patterns are globs: '?' means exactly one character, so
        # "Redmi?book" can never match "Redmibook".
        self.assertNotIn("Redmi?book", self.text)

    def test_wmi_rule_covers_xiaomi_devices(self):
        self.assertIn("WMI keys", self.text)

    def test_rule_is_scoped(self):
        self.assertIn('SUBSYSTEM!="input"', self.text)
        self.assertIn('KERNEL!="event*"', self.text)


class HwdbRuleTest(unittest.TestCase):
    def setUp(self):
        self.text = read("etc/udev/hwdb.d/70-xiaomi-key-remap.hwdb")

    def test_maps_press_scancode_to_f19(self):
        self.assertIn("KEYBOARD_KEY_11801=f19", self.text)

    def test_drops_release_scancode(self):
        self.assertIn("KEYBOARD_KEY_11901=reserved", self.text)

    def test_disables_with_reserved_not_zero(self):
        # "0" is KEY_0 in systemd's name table: it would type the digit zero.
        for line in self.text.splitlines():
            stripped = line.strip()
            if stripped.startswith("KEYBOARD_KEY_"):
                self.assertFalse(stripped.endswith("=0"),
                                 "use 'reserved' instead of '=0': %s" % stripped)

    def test_match_line_is_a_glob_with_wildcard(self):
        lines = [line for line in self.text.splitlines()
                 if line.startswith("evdev:name:")]
        self.assertEqual(len(lines), 1, "expected exactly one match block")
        self.assertIn("*", lines[0])


class UnitFileTest(unittest.TestCase):
    def setUp(self):
        self.text = read("etc/systemd/user/xiaomi-key.service")

    def test_exec_start_matches_install_path(self):
        self.assertIn("ExecStart=%h/.local/bin/xiaomi-key-daemon.py", self.text)

    def test_reload_sends_sigusr1(self):
        self.assertIn("ExecReload=/bin/kill -USR1 $MAINPID", self.text)

    def test_restarts_after_device_loss_itself(self):
        self.assertIn("Restart=always", self.text)

    def test_starts_with_the_graphical_session(self):
        self.assertIn("After=graphical-session.target", self.text)
        self.assertIn("WantedBy=graphical-session.target", self.text)

    def test_limits_restart_storm_in_unit_section(self):
        unit_section = self.text.split("[Service]")[0]
        self.assertIn("StartLimitIntervalSec=", unit_section)


class ConfigExampleTest(unittest.TestCase):
    def setUp(self):
        self.cfg = daemon.Config.from_text(read("config/action.conf.example"),
                                          path="action.conf.example")

    def test_parses_without_warnings(self):
        self.assertEqual(self.cfg.warnings, [])

    def test_defaults_are_sensible(self):
        self.assertEqual(self.cfg.key_codes, (583,))
        self.assertTrue(self.cfg.short_press)
        self.assertTrue(self.cfg.long_press)
        self.assertEqual(self.cfg.long_press_ms, 600)

    def test_default_config_path_matches_docs(self):
        self.assertEqual(daemon.DEFAULT_CONFIG_PATH,
                         "~/.config/xiaomi-key/action.conf")
        self.assertIn(daemon.DEFAULT_CONFIG_PATH, read("README.md"))


class UrlConsistencyTest(unittest.TestCase):
    """Every GitHub link must point at the same repository."""

    def test_all_github_links_use_one_owner(self):
        import re as _re
        pattern = _re.compile(r"github\.com/([A-Za-z0-9_.-]+)/xiaomi-ai-key-linux")
        owners = set()
        for relative_path in REQUIRED_FILES + [".github/PULL_REQUEST_TEMPLATE.md"]:
            path = REPO_ROOT / relative_path
            if path.suffix not in (".md", ".yml", ".yaml", ".service"):
                continue
            with open(path, encoding="utf-8") as fh:
                owners.update(pattern.findall(fh.read()))
        self.assertEqual(owners, {"myml"},
                         "inconsistent repository URLs: %s" % sorted(owners))


class VersionTest(unittest.TestCase):
    def test_changelog_documents_current_version(self):
        self.assertIn(daemon.__version__, read("CHANGELOG.md"))

    def test_readme_badges_point_at_the_repo(self):
        text = read("README.md")
        self.assertIn("myml/xiaomi-ai-key-linux", text)


if __name__ == "__main__":
    unittest.main()

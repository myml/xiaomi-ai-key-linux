"""action.conf parsing: defaults, valid values, and every warning path."""

import os
import tempfile
import unittest
import unittest.mock

from tests.helpers import load_daemon

daemon = load_daemon()


class ConfigDefaultsTest(unittest.TestCase):
    def test_missing_file_falls_back_to_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "nope.conf")
            cfg = daemon.Config.from_file(path)
        self.assertEqual(cfg.key_codes, daemon.DEFAULT_KEY_CODES)
        self.assertEqual(cfg.long_press_ms, daemon.DEFAULT_LONG_PRESS_MS)
        self.assertEqual(cfg.device_name, "")
        self.assertEqual(cfg.slots(), [])
        self.assertTrue(cfg.warnings, "a missing config should warn")

    def test_empty_config_has_no_warnings(self):
        cfg = daemon.Config.from_text("")
        self.assertEqual(cfg.warnings, [])
        self.assertEqual(cfg.key_codes, daemon.DEFAULT_KEY_CODES)
        self.assertFalse(cfg.has_action())

    def test_expands_tilde(self):
        cfg = daemon.Config.from_file("~/definitely-does-not-exist.conf")
        self.assertNotIn("~", cfg.path)


class ConfigParsingTest(unittest.TestCase):
    def parse(self, text):
        return daemon.Config.from_text(text)

    def test_full_config(self):
        cfg = self.parse(
            "DEVICE_NAME=Redmi WMI keys\n"
            "KEY_CODES=583\n"
            "SHORT_PRESS=krunner\n"
            "LONG_PRESS=konsole\n"
            "LONG_PRESS_MS=800\n"
            "FEEDBACK=done\n"
            "SHELL=/bin/bash\n"
            "DRY_RUN=1\n"
            "LOG_LEVEL=debug\n"
        )
        self.assertEqual(cfg.device_name, "Redmi WMI keys")
        self.assertEqual(cfg.key_codes, (583,))
        self.assertEqual(cfg.short_press, "krunner")
        self.assertEqual(cfg.long_press, "konsole")
        self.assertEqual(cfg.long_press_ms, 800)
        self.assertEqual(cfg.feedback, "done")
        self.assertEqual(cfg.shell, "/bin/bash")
        self.assertTrue(cfg.dry_run)
        self.assertEqual(cfg.log_level, "debug")
        self.assertEqual(cfg.warnings, [])

    def test_comments_blank_lines_and_spacing(self):
        cfg = self.parse(
            "# comment\n"
            "\n"
            "   \n"
            "  SHORT_PRESS =  konsole  \n"
            "; semicolons are not comment characters here\n"
        )
        self.assertEqual(cfg.short_press, "konsole")
        self.assertEqual(cfg.warnings, [])

    def test_hash_inside_command_is_kept(self):
        cfg = self.parse("SHORT_PRESS=sh -c 'echo #42'\n")
        self.assertEqual(cfg.short_press, "sh -c 'echo #42'")

    def test_value_with_equals_sign(self):
        cfg = self.parse("SHORT_PRESS=foo --arg=a=b\n")
        self.assertEqual(cfg.short_press, "foo --arg=a=b")

    def test_key_codes_list(self):
        cfg = self.parse("KEY_CODES=583,189 190\n")
        self.assertEqual(cfg.key_codes, (583, 189, 190))

    def test_key_codes_accepts_hex(self):
        cfg = self.parse("KEY_CODES=0x247\n")
        self.assertEqual(cfg.key_codes, (0x247,))

    def test_key_codes_invalid_entries_warn_but_keep_valid_ones(self):
        cfg = self.parse("KEY_CODES=583,abc,189\n")
        self.assertEqual(cfg.key_codes, (583, 189))
        self.assertEqual(len(cfg.warnings), 1)
        self.assertIn("abc", cfg.warnings[0])

    def test_key_codes_negative_is_ignored(self):
        cfg = self.parse("KEY_CODES=583,-1\n")
        self.assertEqual(cfg.key_codes, (583,))
        self.assertTrue(cfg.warnings)

    def test_key_codes_empty_keeps_default(self):
        cfg = self.parse("KEY_CODES=\n")
        self.assertEqual(cfg.key_codes, daemon.DEFAULT_KEY_CODES)
        self.assertTrue(cfg.warnings)

    def test_long_press_ms_not_a_number(self):
        cfg = self.parse("LONG_PRESS_MS=soon\n")
        self.assertEqual(cfg.long_press_ms, daemon.DEFAULT_LONG_PRESS_MS)
        self.assertTrue(cfg.warnings)

    def test_long_press_ms_clamped(self):
        cfg = self.parse("LONG_PRESS_MS=5\n")
        self.assertEqual(cfg.long_press_ms, daemon.MIN_LONG_PRESS_MS)
        self.assertTrue(cfg.warnings)

    def test_unknown_option_warns(self):
        cfg = self.parse("SHORTPRESS=typo\n")
        self.assertTrue(cfg.warnings)
        self.assertIn("unknown option", cfg.warnings[0])

    def test_press_and_short_press_conflict_warns(self):
        cfg = self.parse("PRESS=a\nSHORT_PRESS=b\n")
        self.assertTrue(any("SHORT_PRESS can never fire" in w
                            for w in cfg.warnings), cfg.warnings)

    def test_invalid_device_name_pattern_warns(self):
        cfg = self.parse("DEVICE_NAME=(unclosed\n")
        self.assertTrue(any("regular expression" in w for w in cfg.warnings),
                        cfg.warnings)

    def test_relative_shell_warns(self):
        cfg = self.parse("SHELL=bash\n")
        self.assertTrue(any("absolute path" in w for w in cfg.warnings),
                        cfg.warnings)

    def test_dry_run_values(self):
        for text, expected in (("DRY_RUN=1", True), ("DRY_RUN=yes", True),
                               ("DRY_RUN=on", True), ("DRY_RUN=0", False),
                               ("DRY_RUN=off", False)):
            with self.subTest(text=text):
                self.assertEqual(self.parse(text).dry_run, expected)

    def test_dry_run_garbage_warns(self):
        cfg = self.parse("DRY_RUN=maybe\n")
        self.assertFalse(cfg.dry_run)
        self.assertTrue(cfg.warnings)

    def test_log_level_validated(self):
        self.assertEqual(self.parse("LOG_LEVEL=WARNING\n").log_level, "warning")
        cfg = self.parse("LOG_LEVEL=loud\n")
        self.assertEqual(cfg.log_level, "info")
        self.assertTrue(cfg.warnings)

    def test_slots_drops_empty(self):
        cfg = self.parse("SHORT_PRESS=a\nLONG_PRESS=c\n")
        self.assertEqual(cfg.slots(), [("short", "a"), ("long", "c")])
        self.assertTrue(cfg.has_action())

    def test_xdg_config_home_is_honoured(self):
        with unittest.mock.patch.dict(os.environ,
                                      {"XDG_CONFIG_HOME": "/tmp/xdg-test"}):
            self.assertEqual(daemon.default_config_path(),
                             "/tmp/xdg-test/xiaomi-key/action.conf")

    def test_xdg_config_home_defaults_to_dot_config(self):
        env = {k: v for k, v in os.environ.items() if k != "XDG_CONFIG_HOME"}
        with unittest.mock.patch.dict(os.environ, env, clear=True):
            self.assertEqual(daemon.default_config_path(),
                             os.path.expanduser("~/.config/xiaomi-key/action.conf"))

    def test_from_file_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "action.conf")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("SHORT_PRESS=konsole\nKEY_CODES=189\n")
            cfg = daemon.Config.from_file(path)
        self.assertEqual(cfg.short_press, "konsole")
        self.assertEqual(cfg.key_codes, (189,))
        self.assertEqual(cfg.path, path)


if __name__ == "__main__":
    unittest.main()

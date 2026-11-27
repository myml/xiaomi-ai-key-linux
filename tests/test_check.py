"""Diagnostics: the daemon/hwdb conflict detection and report formatting."""

import contextlib
import io
import os
import tempfile
import unittest
from unittest import mock

from tests.helpers import load_daemon

daemon = load_daemon()


class CheckTest(unittest.TestCase):
    def run_check(self, config_text, udev_exists, hwdb_exists):
        with tempfile.TemporaryDirectory() as tmp:
            udev = os.path.join(tmp, "60-xiaomi-key.rules")
            hwdb = os.path.join(tmp, "70-xiaomi-key-remap.hwdb")
            for path, exists in ((udev, udev_exists), (hwdb, hwdb_exists)):
                if exists:
                    with open(path, "w", encoding="utf-8") as fh:
                        fh.write("# placeholder\n")
            cfg = daemon.Config.from_text(config_text)
            out = io.StringIO()
            with mock.patch.object(daemon, "UDEV_RULE_PATH", udev), \
                    mock.patch.object(daemon, "HWDB_RULE_PATH", hwdb), \
                    contextlib.redirect_stdout(out):
                code = daemon.cmd_check(cfg, None)
        return code, out.getvalue()

    def test_reports_python_version_and_banner(self):
        code, text = self.run_check("SHORT_PRESS=true\n", True, False)
        self.assertIn("xiaomi-key %s --check" % daemon.__version__, text)
        self.assertIn("python %d.%d" % __import__("sys").version_info[:2], text)
        self.assertIn("failure(s)", text)
        self.assertEqual(code, 0 if "0 failure(s)" in text else 1)

    def test_warns_when_remap_installed_but_key_code_is_still_583(self):
        code, text = self.run_check("KEY_CODES=583\nSHORT_PRESS=true\n", True, True)
        self.assertIn("hwdb remap installed", text)
        self.assertIn("KEY_CODES=189", text)

    def test_warns_when_key_code_remapped_without_hwdb_rule(self):
        code, text = self.run_check("KEY_CODES=189\nSHORT_PRESS=true\n", True, False)
        self.assertIn("no hwdb remap is installed", text)

    def test_reports_config_warnings(self):
        code, text = self.run_check("PRESS=a\nSHORT_PRESS=b\n", True, False)
        self.assertIn("SHORT_PRESS can never fire", text)
        self.assertIn("warning(s)", text)

    def test_reports_missing_action(self):
        code, text = self.run_check(
            "SHORT_PRESS=true\nLONG_PRESS=definitely-not-a-command-xyz\n",
            True, False)
        self.assertIn("definitely-not-a-command-xyz", text)

    def test_reports_missing_udev_rule(self):
        code, text = self.run_check("SHORT_PRESS=true\n", False, False)
        self.assertIn("udev rule missing", text)


if __name__ == "__main__":
    unittest.main()

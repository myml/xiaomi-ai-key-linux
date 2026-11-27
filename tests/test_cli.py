"""End-to-end checks of the command line interface.

These run the real script in a subprocess, so they also cover argument
parsing, exit codes and the shape of the diagnostic output.
"""

import os
import subprocess
import sys
import tempfile
import unittest

from tests.helpers import DAEMON_PATH, load_daemon

daemon = load_daemon()


def run(*args):
    return subprocess.run([sys.executable, str(DAEMON_PATH)] + list(args),
                          capture_output=True, text=True, timeout=30)


class CliTest(unittest.TestCase):
    def test_version(self):
        result = run("--version")
        self.assertEqual(result.returncode, 0)
        self.assertIn(daemon.__version__, result.stdout)

    def test_help(self):
        result = run("--help")
        self.assertEqual(result.returncode, 0)
        for option in ("--list", "--check", "--test", "--dry-run", "--config"):
            self.assertIn(option, result.stdout)

    def test_unknown_option_fails(self):
        result = run("--definitely-not-an-option")
        self.assertEqual(result.returncode, 2)

    def test_list_prints_devices(self):
        result = run("--list")
        self.assertIn(result.returncode, (0, 1),
                      "unexpected exit code %d: %s" % (result.returncode,
                                                       result.stderr))
        self.assertIn("input devices", result.stdout)
        self.assertIn("looking for key codes", result.stdout)

    def test_check_reports_everything_as_lines(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = os.path.join(tmp, "action.conf")
            with open(config, "w", encoding="utf-8") as fh:
                fh.write("KEY_CODES=583\nSHORT_PRESS=true\n")
            result = run("--config", config, "--check")
        self.assertIn("--check", result.stdout)
        self.assertIn("failure(s)", result.stdout)
        self.assertRegex(result.stdout, r"\[( ok |warn|FAIL)\]")

    def test_check_exit_code_matches_failures(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = os.path.join(tmp, "action.conf")
            with open(config, "w", encoding="utf-8") as fh:
                fh.write("KEY_CODES=583\nSHORT_PRESS=true\n")
            result = run("--config", config, "--check")
        expected = 1 if "0 failure(s)" not in result.stdout else 0
        self.assertEqual(result.returncode, expected)

    def test_missing_config_warns_but_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = run("--config", os.path.join(tmp, "nope.conf"), "--check")
        self.assertIn("missing", result.stdout)
        self.assertIn("defaults in use", result.stdout)


if __name__ == "__main__":
    unittest.main()

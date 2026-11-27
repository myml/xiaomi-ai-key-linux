"""Key capability bitmap decoding and device discovery (fake sysfs trees)."""

import os
import tempfile
import unittest

from tests.helpers import load_daemon

daemon = load_daemon()

# Real capabilities/key of "Redmibook WMI keys" on a Redmi Book 16 2024.
REAL_KEYBIT = ("2000000000000000 400000000000080 4000000000000 20000 0 "
               "10000000000 0 1001800001000 f80080000000000 0 0")


def make_device(root, event, name, keybit=""):
    base = os.path.join(root, event, "device")
    os.makedirs(os.path.join(base, "capabilities"), exist_ok=True)
    with open(os.path.join(base, "name"), "w", encoding="utf-8") as fh:
        fh.write(name + "\n")
    with open(os.path.join(base, "capabilities", "key"), "w",
              encoding="utf-8") as fh:
        fh.write(keybit + "\n")


class DecodeKeybitTest(unittest.TestCase):
    def test_real_device_bitmap(self):
        codes = daemon.decode_keybit(REAL_KEYBIT)
        self.assertIn(583, codes)          # KEY_ASSISTANT
        self.assertNotIn(189, codes)       # F19 is only present after remapping
        self.assertEqual(len(codes), 16)
        self.assertEqual(sorted(codes),
                         [171, 183, 184, 185, 186, 187, 204, 227, 228, 240,
                          360, 465, 562, 583, 634, 701])

    def test_empty_bitmap(self):
        self.assertEqual(daemon.decode_keybit(""), frozenset())
        self.assertEqual(daemon.decode_keybit("  \n"), frozenset())

    def test_single_word(self):
        # bit 1 and bit 63 of the only word
        self.assertEqual(daemon.decode_keybit("8000000000000002"),
                         frozenset({1, 63}))

    def test_remapped_bitmap_has_f19(self):
        # F19 (189) lives in the third word from the right.
        bit = 189
        word_index = bit // 64
        shift = bit % 64
        words = [0, 0, 0]
        words[word_index] |= 1 << shift
        text = " ".join("%x" % w for w in reversed(words))
        self.assertIn(189, daemon.decode_keybit(text))

    def test_garbage_does_not_raise(self):
        self.assertEqual(daemon.decode_keybit("zzz 0"), frozenset())


class FormatCodesTest(unittest.TestCase):
    def test_ranges(self):
        self.assertEqual(daemon.format_codes([583, 183, 184, 185, 171]),
                         "171, 183-185, 583")

    def test_single(self):
        self.assertEqual(daemon.format_codes([583]), "583")

    def test_empty(self):
        self.assertEqual(daemon.format_codes([]), "(none)")

    def test_duplicates_collapsed(self):
        self.assertEqual(daemon.format_codes([1, 1, 2]), "1-2")


class DiscoveryTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name
        make_device(self.root, "event0", "Lid Switch")
        make_device(self.root, "event2", "AT Translated Set 2 keyboard",
                    "0 0 ffffffff")  # bits 0..31: no 583, no 189
        make_device(self.root, "event10", "Redmibook WMI keys", REAL_KEYBIT)
        self.devdir = os.path.join(self.root, "dev")
        os.makedirs(self.devdir, exist_ok=True)

    def tearDown(self):
        self._tmp.cleanup()

    def discover(self, pattern="", codes=(583,)):
        return daemon.discover_devices(pattern, codes,
                                       sysfs_dir=self.root,
                                       dev_dir=self.devdir)

    def test_capability_match_without_name_pattern(self):
        found = self.discover()
        self.assertEqual([d.event for d in found], ["event10"])
        self.assertEqual(found[0].node, os.path.join(self.devdir, "event10"))
        self.assertIn(583, found[0].key_codes)

    def test_name_pattern_filters(self):
        self.assertEqual(len(self.discover(pattern="Redmi")), 1)
        self.assertEqual(self.discover(pattern="NoSuchLaptop"), [])

    def test_name_pattern_is_a_regex(self):
        # (?i) works, so the pattern really goes through re.compile
        self.assertEqual(len(self.discover(pattern="(?i)redmi.?book wmi keys")), 1)

    def test_invalid_pattern_falls_back_to_capabilities(self):
        with self.assertLogs(daemon.LOG, level="WARNING"):
            self.assertEqual(len(self.discover(pattern="(broken")), 1)

    def test_device_without_capabilities_needs_a_name_pattern(self):
        make_device(self.root, "event11", "Mystery keys")  # no keybit file
        events = [d.event for d in self.discover()]
        self.assertNotIn("event11", events)
        events = [d.event for d in self.discover(pattern="Mystery")]
        self.assertIn("event11", events)

    def test_other_key_code_finds_nothing(self):
        self.assertEqual(self.discover(codes=(189,)), [])

    def test_numeric_sorting(self):
        make_device(self.root, "event3", "Another Redmi WMI keys", REAL_KEYBIT)
        self.assertEqual([d.event for d in self.discover()],
                         ["event3", "event10"])

    def test_empty_code_set_lists_everything(self):
        events = [d.event for d in self.discover(codes=())]
        self.assertEqual(events, ["event0", "event2", "event10"])


class InputDeviceTest(unittest.TestCase):
    def test_reports(self):
        device = daemon.InputDevice(event="event8", name="x", node="/dev/input/event8",
                                    key_codes=daemon.decode_keybit(REAL_KEYBIT))
        self.assertTrue(device.reports((583,)))
        self.assertTrue(device.reports((189, 583)))
        self.assertFalse(device.reports((189,)))
        self.assertFalse(device.reports(()))

    def test_event_number(self):
        device = daemon.InputDevice(event="event12", name="", node="")
        self.assertEqual(device.event_number, 12)


if __name__ == "__main__":
    unittest.main()

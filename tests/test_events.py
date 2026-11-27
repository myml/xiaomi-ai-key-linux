"""Event stream decoding, including reads that split events in half."""

import struct
import unittest

from tests.helpers import load_daemon

daemon = load_daemon()

EVENT = struct.Struct("llHHi")
EV_KEY = 0x01
EV_SYN = 0x00


def pack(etype, code, value, sec=0, usec=0):
    return EVENT.pack(sec, usec, etype, code, value)


class EventReaderTest(unittest.TestCase):
    def test_unpacks_one_event(self):
        reader = daemon.EventReader()
        self.assertEqual(reader.feed(pack(EV_KEY, 583, 1)), [(EV_KEY, 583, 1)])
        self.assertEqual(reader.pending, 0)

    def test_unpacks_many_events_from_one_read(self):
        reader = daemon.EventReader()
        payload = (pack(EV_KEY, 583, 1)
                   + pack(EV_SYN, 0, 0)
                   + pack(EV_KEY, 583, 0))
        self.assertEqual(reader.feed(payload),
                         [(EV_KEY, 583, 1), (EV_SYN, 0, 0), (EV_KEY, 583, 0)])

    def test_event_split_across_reads(self):
        reader = daemon.EventReader()
        payload = pack(EV_KEY, 583, 1)
        self.assertEqual(reader.feed(payload[:5]), [])
        self.assertEqual(reader.pending, 5)
        self.assertEqual(reader.feed(payload[5:]), [(EV_KEY, 583, 1)])
        self.assertEqual(reader.pending, 0)

    def test_byte_by_byte(self):
        reader = daemon.EventReader()
        payload = pack(EV_KEY, 583, 1)
        events = []
        for index in range(len(payload)):
            events.extend(reader.feed(payload[index:index + 1]))
        self.assertEqual(events, [(EV_KEY, 583, 1)])

    def test_trailing_partial_event_is_kept(self):
        reader = daemon.EventReader()
        payload = pack(EV_KEY, 583, 1) + pack(EV_KEY, 583, 0)
        self.assertEqual(reader.feed(payload + b"\x00\x01"), [(EV_KEY, 583, 1),
                                                              (EV_KEY, 583, 0)])
        self.assertEqual(reader.pending, 2)

    def test_struct_layout_matches_kernel_abi(self):
        # struct input_event: 16 bytes of timeval + u16 + u16 + s32, with the
        # value padded to 4: 24 bytes on 64-bit Linux, 16 bytes on 32-bit.
        self.assertIn(EVENT.size, (16, 24))
        self.assertEqual(EVENT.size, daemon.EVENT_STRUCT.size)

    def test_values_are_signed(self):
        reader = daemon.EventReader()
        # value is a signed 32 bit int; make sure it survives as -1
        self.assertEqual(reader.feed(pack(EV_KEY, 583, -1)), [(EV_KEY, 583, -1)])


class DescribeEventTest(unittest.TestCase):
    def setUp(self):
        self.cfg = daemon.Config.from_text("KEY_CODES=583\n")

    def test_bound_key_is_labelled(self):
        line = daemon.describe_event(self.cfg, 583, 1)
        self.assertIn("KEY_ASSISTANT", line)
        self.assertIn("press", line)
        self.assertIn("bound", line)
        self.assertNotIn("not in KEY_CODES", line)

    def test_unbound_key_is_flagged(self):
        line = daemon.describe_event(self.cfg, 190, 0)
        self.assertIn("KEY_190", line)
        self.assertIn("release", line)
        self.assertIn("not in KEY_CODES", line)

    def test_unknown_value_is_printed_verbatim(self):
        self.assertIn("7", daemon.describe_event(self.cfg, 583, 7))


if __name__ == "__main__":
    unittest.main()

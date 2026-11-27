"""Press / short press / long press truth table.

The state machine is I/O free, so every combination documented in the README
is exercised here with synthetic timestamps.
"""

import unittest

from tests.helpers import load_daemon

daemon = load_daemon()

PRESS, RELEASE, REPEAT = 1, 0, 2
THRESHOLD_MS = 600
THRESHOLD_S = THRESHOLD_MS / 1000.0


def machine(**options):
    cfg = daemon.Config.from_text(
        "LONG_PRESS_MS=%d\n" % THRESHOLD_MS
        + "".join("%s=%s\n" % (name, value) for name, value in options.items()))
    return daemon.KeyStateMachine(cfg)


def slots(fired):
    return [item.slot for item in fired]


class PressOnlyTest(unittest.TestCase):
    def test_press_fires_immediately(self):
        fsm = machine(PRESS="a")
        self.assertEqual(slots(fsm.on_key(PRESS, 0.0)), ["press"])
        self.assertEqual(slots(fsm.on_key(RELEASE, 0.1)), [])

    def test_autorepeat_is_ignored(self):
        fsm = machine(PRESS="a")
        self.assertEqual(slots(fsm.on_key(PRESS, 0.0)), ["press"])
        for moment in (0.1, 0.2, 0.3):
            self.assertEqual(slots(fsm.on_key(REPEAT, moment)), [])

    def test_no_long_press_configured_means_no_deadline(self):
        fsm = machine(PRESS="a")
        fsm.on_key(PRESS, 0.0)
        self.assertIsNone(fsm.deadline())
        self.assertEqual(slots(fsm.on_timeout(10.0)), [])


class ShortOnlyTest(unittest.TestCase):
    def test_short_fires_on_release(self):
        fsm = machine(SHORT_PRESS="b")
        self.assertEqual(slots(fsm.on_key(PRESS, 0.0)), [])
        self.assertEqual(slots(fsm.on_key(RELEASE, 0.2)), ["short"])

    def test_release_without_press_does_nothing(self):
        fsm = machine(SHORT_PRESS="b")
        self.assertEqual(slots(fsm.on_key(RELEASE, 0.0)), [])

    def test_stray_release_after_press_is_not_double_fired(self):
        fsm = machine(SHORT_PRESS="b")
        fsm.on_key(PRESS, 0.0)
        self.assertEqual(slots(fsm.on_key(RELEASE, 0.1)), ["short"])
        self.assertEqual(slots(fsm.on_key(RELEASE, 0.2)), [])


class ShortAndLongTest(unittest.TestCase):
    def test_quick_tap_is_short(self):
        fsm = machine(SHORT_PRESS="b", LONG_PRESS="c")
        fsm.on_key(PRESS, 0.0)
        self.assertEqual(slots(fsm.on_key(RELEASE, 0.2)), ["short"])

    def test_hold_past_threshold_is_long(self):
        fsm = machine(SHORT_PRESS="b", LONG_PRESS="c")
        fsm.on_key(PRESS, 0.0)
        self.assertEqual(slots(fsm.on_timeout(0.3)), [])       # too early
        self.assertEqual(slots(fsm.on_timeout(THRESHOLD_S)), ["long"])
        self.assertEqual(slots(fsm.on_key(RELEASE, 1.0)), [])  # consumed

    def test_long_press_fires_exactly_at_threshold(self):
        fsm = machine(SHORT_PRESS="b", LONG_PRESS="c")
        fsm.on_key(PRESS, 5.0)
        self.assertEqual(slots(fsm.on_timeout(5.0 + THRESHOLD_S - 0.001)), [])
        self.assertEqual(slots(fsm.on_timeout(5.0 + THRESHOLD_S)), ["long"])

    def test_deadline_tracks_press_time(self):
        fsm = machine(SHORT_PRESS="b", LONG_PRESS="c")
        fsm.on_key(PRESS, 10.0)
        self.assertAlmostEqual(fsm.deadline(), 10.0 + THRESHOLD_S)
        fsm.on_key(RELEASE, 10.1)
        self.assertIsNone(fsm.deadline())


class PressAndLongTest(unittest.TestCase):
    def test_press_then_long(self):
        fsm = machine(PRESS="a", LONG_PRESS="c")
        self.assertEqual(slots(fsm.on_key(PRESS, 0.0)), ["press"])
        self.assertEqual(slots(fsm.on_timeout(THRESHOLD_S)), ["long"])
        self.assertEqual(slots(fsm.on_key(RELEASE, 1.0)), [])

    def test_quick_tap_runs_press_only(self):
        fsm = machine(PRESS="a", LONG_PRESS="c")
        fsm.on_key(PRESS, 0.0)
        self.assertEqual(slots(fsm.on_key(RELEASE, 0.1)), [])

    def test_press_action_does_not_swallow_long_action(self):
        fsm = machine(PRESS="a", LONG_PRESS="c")
        fsm.on_key(PRESS, 0.0)
        self.assertIsNotNone(fsm.deadline())


class PressAndShortTest(unittest.TestCase):
    def test_short_is_dead_when_press_is_set(self):
        fsm = machine(PRESS="a", SHORT_PRESS="b")
        self.assertEqual(slots(fsm.on_key(PRESS, 0.0)), ["press"])
        self.assertEqual(slots(fsm.on_key(RELEASE, 0.1)), [])


class RepeatedUseTest(unittest.TestCase):
    def test_second_hold_fires_long_again(self):
        fsm = machine(SHORT_PRESS="b", LONG_PRESS="c")
        fsm.on_key(PRESS, 0.0)
        self.assertEqual(slots(fsm.on_timeout(THRESHOLD_S)), ["long"])
        fsm.on_key(RELEASE, 1.0)
        fsm.on_key(PRESS, 2.0)
        self.assertEqual(slots(fsm.on_timeout(2.0 + THRESHOLD_S)), ["long"])

    def test_new_press_clears_previous_long_state(self):
        fsm = machine(PRESS="a", LONG_PRESS="c")
        fsm.on_key(PRESS, 0.0)
        fsm.on_key(RELEASE, 1.0)
        fsm.on_key(PRESS, 2.0)
        self.assertEqual(slots(fsm.on_key(RELEASE, 2.1)), [])
        self.assertAlmostEqual(fsm.deadline() or -1, -1.0)  # released

    def test_reset_forgets_everything(self):
        fsm = machine(PRESS="a", LONG_PRESS="c")
        fsm.on_key(PRESS, 0.0)
        fsm.reset()
        self.assertFalse(fsm.pressed)
        self.assertIsNone(fsm.deadline())
        self.assertEqual(slots(fsm.on_timeout(10.0)), [])


class UnconfiguredTest(unittest.TestCase):
    def test_nothing_configured_fires_nothing(self):
        fsm = machine()
        self.assertEqual(slots(fsm.on_key(PRESS, 0.0)), [])
        self.assertIsNone(fsm.deadline())
        self.assertEqual(slots(fsm.on_key(RELEASE, 0.1)), [])
        self.assertEqual(slots(fsm.on_timeout(10.0)), [])


if __name__ == "__main__":
    unittest.main()

import unittest

from src.pacing import Pacer, parse_pace_spec


class _FixedRng:
    """uniform() returns the midpoint and records the bounds it was given."""

    def __init__(self):
        self.calls = []

    def uniform(self, lo, hi):
        self.calls.append((lo, hi))
        return (lo + hi) / 2


class ParsePaceSpecTests(unittest.TestCase):
    def test_zero_disables(self):
        self.assertEqual(parse_pace_spec("0"), (0.0, 0.0))

    def test_single_value_is_fixed(self):
        self.assertEqual(parse_pace_spec("3"), (3.0, 3.0))
        self.assertEqual(parse_pace_spec("2.5"), (2.5, 2.5))

    def test_range(self):
        self.assertEqual(parse_pace_spec("2-5"), (2.0, 5.0))
        self.assertEqual(parse_pace_spec(" 1-1 "), (1.0, 1.0))

    def test_invalid_specs_rejected(self):
        for bad in ("", "a", "1-2-3", "-1", "5-2"):
            with self.assertRaises(ValueError, msg=bad):
                parse_pace_spec(bad)


class PacerTests(unittest.TestCase):
    def test_disabled_pacer_never_sleeps(self):
        sleeps = []
        pacer = Pacer(0, 0, sleeper=sleeps.append)
        self.assertEqual(pacer.wait(), 0.0)
        self.assertEqual(sleeps, [])
        self.assertFalse(pacer.enabled)
        self.assertEqual(pacer.snapshot()["waits"], 0)

    def test_wait_sleeps_within_bounds_and_counts(self):
        sleeps = []
        rng = _FixedRng()
        pacer = Pacer(2, 5, rng=rng, sleeper=sleeps.append)

        first, second = pacer.wait(), pacer.wait()

        self.assertEqual(rng.calls, [(2.0, 5.0), (2.0, 5.0)])
        self.assertEqual((first, second), (3.5, 3.5))
        self.assertEqual(sleeps, [3.5, 3.5])
        snap = pacer.snapshot()
        self.assertEqual(snap["waits"], 2)
        self.assertAlmostEqual(snap["total_waited_s"], 7.0)
        self.assertEqual((snap["min_s"], snap["max_s"]), (2.0, 5.0))

    def test_from_spec(self):
        pacer = Pacer.from_spec("1-4")
        self.assertEqual((pacer.min_s, pacer.max_s), (1.0, 4.0))
        self.assertTrue(pacer.enabled)
        self.assertFalse(Pacer.from_spec("0").enabled)

    def test_invalid_bounds_rejected(self):
        with self.assertRaises(ValueError):
            Pacer(-1, 2)
        with self.assertRaises(ValueError):
            Pacer(5, 2)


if __name__ == "__main__":
    unittest.main()

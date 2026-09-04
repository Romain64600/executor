"""Pure-logic tests for the P2-13 read-only search-nav_max probe
(scripts/probe_p2_13_search_navmax.py). The live navigation is not exercised here —
only the render/login read discipline and the FILTERED-vs-WHOLE-FEED verdict."""
import importlib.util
import unittest
from pathlib import Path

from src.extractor import NotLoggedInError


def _load_probe():
    spec = importlib.util.spec_from_file_location(
        "probe_p2_13",
        str(Path(__file__).resolve().parents[1] / "scripts" / "probe_p2_13_search_navmax.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _FakeSession:
    def __init__(self, rows, state, *, login=False):
        self._rows = rows
        self._state = state
        self._login = login
        self.nav = []

    def navigate(self, url):
        self.nav.append(url)

    def is_login_page(self):
        return self._login

    def page_offer_rows(self):
        return list(self._rows)

    def feed_page_state(self):
        return dict(self._state)


class ReadPageTests(unittest.TestCase):
    def setUp(self):
        self.M = _load_probe()

    def test_reads_rows_and_nav_max(self):
        s = _FakeSession([{"id": "1"}, {"id": "2"}],
                         {"feed_ui": True, "nav_max": 3, "href": "u"})
        r = self.M._read_page(s, "http://x", ())
        self.assertEqual((r["rows"], r["nav_max"], r["feed_ui"]), (2, 3, True))

    def test_login_bounce_is_fail_closed(self):
        s = _FakeSession([], {}, login=True)
        with self.assertRaises(NotLoggedInError):
            self.M._read_page(s, "http://x", ())

    def test_rendered_empty_is_zero_rows_not_polled_forever(self):
        # feed_ui True + 0 rows = a real empty result (no poll needed)
        s = _FakeSession([], {"feed_ui": True, "nav_max": 0, "href": "u"})
        r = self.M._read_page(s, "http://x", (99, 99))   # waits never slept (feed_ui already true)
        self.assertEqual((r["rows"], r["nav_max"]), (0, 0))


class VerdictTests(unittest.TestCase):
    def setUp(self):
        self.M = _load_probe()

    def _r(self, rows, nav_max, term="t", feed_ui=True):
        return {"rows": rows, "nav_max": nav_max, "feed_ui": feed_ui, "term": term}

    def test_whole_feed_when_narrow_search_reports_feed_nav(self):
        # a narrow (5-row, single-page) search still reports the whole feed's nav_max
        v, _ = self.M._verdict(42, [self._r(0, 0, "ctl"), self._r(5, 42, "narrow")])
        self.assertEqual(v, "WHOLE-FEED")

    def test_filtered_when_narrow_search_reports_single_page_nav(self):
        # a narrow single-page search reports nav_max 0 (< the whole feed's) → filtered
        v, _ = self.M._verdict(42, [self._r(0, 0, "ctl"), self._r(5, 0, "narrow")])
        self.assertEqual(v, "FILTERED")

    def test_inconclusive_without_a_narrow_nonempty_term(self):
        v, _ = self.M._verdict(42, [self._r(0, 0, "ctl")])
        self.assertEqual(v, "INCONCLUSIVE")

    def test_full_page_result_is_not_treated_as_narrow(self):
        # exactly 100 rows (a full page) is NOT a single-page proof either way
        v, _ = self.M._verdict(42, [self._r(100, 42, "full")])
        self.assertEqual(v, "INCONCLUSIVE")


if __name__ == "__main__":
    unittest.main()

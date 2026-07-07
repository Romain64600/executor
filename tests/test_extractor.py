import json
import re
import unittest

from src.cdp_session import ReadOnlyCdpSession, ReadOnlyEvalError, is_readonly_expression
from src.extractor import (
    PAGE_STATE_JS,
    EmptyPageAnomaly,
    FeedExtractor,
    FeedUnstableError,
    NotLoggedInError,
    feed_url,
    parse_offers_payload,
    parse_page_range,
)
from src.pacing import Pacer
from src.step_guard import StepGuard


def _offer(i, **over):
    base = {"id": str(i), "name": f"Game {i}", "url": f"https://m.test/{i}", "storeId": "127"}
    base.update(over)
    return base


def _state(offers, *, nav_max=0, feed_ui=True, is_login=False):
    return {
        "offers": [json.dumps(o) for o in offers],
        "feed_ui": feed_ui,
        "nav_max": nav_max,
        "is_login": is_login,
    }


def _page_of(url):
    m = re.search(r"[?&]p=(\d+)", url)
    return int(m.group(1)) if m else 1


class FakeSession:
    """Serves PAGE_STATE_JS states keyed on the &p=N of the last navigated URL.

    ``script[page]`` is a list of states consumed one per visit (the last one
    repeats), so tests can simulate transient blank renders and inter-sweep
    re-orderings. Pages absent from the script render as past-the-end.
    """

    def __init__(self, script):
        self.script = {int(k): list(v) for k, v in script.items()}
        self.nav = []
        self._page = 1

    def navigate(self, url, settle=0):
        self.nav.append(url)
        self._page = _page_of(url)

    def evaluate_readonly(self, expression):
        states = self.script.get(self._page)
        if not states:
            return json.dumps(_state([], nav_max=max(self.script) if self.script else 0))
        state = states.pop(0) if len(states) > 1 else states[0]
        return json.dumps(state)

    def visits(self, page):
        return sum(1 for u in self.nav if _page_of(u) == page)


def _extractor(session, **kwargs):
    extractor = FeedExtractor(session, **kwargs)
    extractor.empty_retry_wait_s = 0
    return extractor


class FeedUrlTests(unittest.TestCase):
    def test_first_page_has_no_p_param(self):
        url = feed_url(127)
        self.assertEqual(
            url,
            "https://www.allkeyshop.com/blog/wp-admin/admin.php"
            "?available=all&store=127&page=aks-merchant-feeds-9",
        )
        self.assertNotIn("&p=", feed_url(127, page=1))

    def test_pagination_and_available(self):
        self.assertIn("&p=3", feed_url(127, page=3))
        self.assertIn("available=pending", feed_url(127, available="pending"))


class ParsePayloadTests(unittest.TestCase):
    def test_parses_array_of_json_strings(self):
        payload = json.dumps([json.dumps(_offer(1)), json.dumps(_offer(2))])
        offers = parse_offers_payload(payload)
        self.assertEqual([o["id"] for o in offers], ["1", "2"])

    def test_parses_already_decoded_list(self):
        offers = parse_offers_payload([json.dumps(_offer(1))])
        self.assertEqual(offers[0]["id"], "1")

    def test_html_entities_are_unescaped(self):
        payload = json.dumps([json.dumps({"id": "1", "name": "A &amp; B", "url": "https://x/1"})])
        self.assertEqual(parse_offers_payload(payload)[0]["name"], "A & B")

    def test_empty_payload(self):
        self.assertEqual(parse_offers_payload(""), [])
        self.assertEqual(parse_offers_payload(None), [])
        self.assertEqual(parse_offers_payload("[]"), [])
        self.assertEqual(parse_offers_payload([]), [])


class ExtractSweepTests(unittest.TestCase):
    def test_stable_feed_stops_after_confirming_sweep(self):
        session = FakeSession({
            1: [_state([_offer(1), _offer(2)], nav_max=2)],
            2: [_state([_offer(3)], nav_max=1)],
        })
        snapshot, feed = _extractor(session).extract(run_id="r1", merchant="M", store_id=1)

        self.assertEqual([o.offer_id for o in feed.offers], ["1", "2", "3"])
        self.assertEqual(snapshot.pages_scanned, 2)
        # Sweep 1 + the stability-confirming sweep 2, bounded by the nav: no
        # probe past the advertised last page, ever.
        self.assertEqual(session.visits(1), 2)
        self.assertEqual(session.visits(2), 2)
        self.assertEqual(session.visits(3), 0)

    def test_single_page_feed_never_fetches_page_two(self):
        session = FakeSession({1: [_state([_offer(1)], nav_max=0)]})
        _, feed = _extractor(session).extract(run_id="r1", merchant="M", store_id=1)
        self.assertEqual(len(feed.offers), 1)
        self.assertEqual(session.visits(2), 0)

    def test_unstable_ordering_unions_across_sweeps(self):
        # Sweep 1 never sees offer 4 (the feed re-ordered it onto an
        # already-visited page); sweep 2 catches it; sweep 3 adds nothing.
        session = FakeSession({
            1: [
                _state([_offer(1), _offer(2)], nav_max=2),
                _state([_offer(1), _offer(4)], nav_max=2),
            ],
            2: [_state([_offer(2), _offer(3)], nav_max=1)],
        })
        _, feed = _extractor(session).extract(run_id="r1", merchant="M", store_id=1)
        self.assertEqual([o.offer_id for o in feed.offers], ["1", "2", "3", "4"])
        self.assertEqual(session.visits(1), 3)

    def test_blank_page_one_with_advertised_pages_aborts(self):
        session = FakeSession({1: [_state([], nav_max=8)]})
        with self.assertRaises(EmptyPageAnomaly):
            _extractor(session).extract(run_id="r1", merchant="M", store_id=1)
        self.assertEqual(session.visits(1), 2)  # retried once before aborting

    def test_blank_page_without_feed_ui_aborts(self):
        session = FakeSession({1: [_state([], nav_max=0, feed_ui=False)]})
        with self.assertRaises(EmptyPageAnomaly):
            _extractor(session).extract(run_id="r1", merchant="M", store_id=1)

    def test_blank_mid_range_page_aborts(self):
        # An in-range page (nav still advertises it) rendering 0 rows twice is
        # an anomaly, not an end-of-feed — the old extractor accepted it.
        session = FakeSession({
            1: [_state([_offer(1)], nav_max=3)],
            2: [_state([], nav_max=3)],
            3: [_state([_offer(3)], nav_max=3)],
        })
        with self.assertRaises(EmptyPageAnomaly):
            _extractor(session).extract(run_id="r1", merchant="M", store_id=1)
        self.assertEqual(session.visits(2), 2)

    def test_transient_blank_page_recovers_on_retry(self):
        session = FakeSession({
            1: [_state([], nav_max=2), _state([_offer(1)], nav_max=2)],
            2: [_state([_offer(2)], nav_max=1)],
        })
        _, feed = _extractor(session).extract(run_id="r1", merchant="M", store_id=1)
        self.assertEqual([o.offer_id for o in feed.offers], ["1", "2"])
        self.assertEqual(session.visits(1), 3)  # blank + retry + stability sweep

    def test_legit_empty_feed_confirmed_by_refetch(self):
        session = FakeSession({1: [_state([], nav_max=0)]})
        snapshot, feed = _extractor(session).extract(run_id="r1", merchant="M", store_id=1)
        self.assertEqual(len(feed.offers), 0)
        self.assertEqual(snapshot.pages_scanned, 1)
        self.assertEqual(session.visits(1), 2)  # a blank page is never trusted once

    def test_login_bounce_aborts_immediately(self):
        session = FakeSession({1: [_state([], feed_ui=False, is_login=True)]})
        with self.assertRaises(NotLoggedInError):
            _extractor(session).extract(run_id="r1", merchant="M", store_id=1)
        self.assertEqual(session.visits(1), 1)  # no blind retry on a login bounce

    def test_login_bounce_mid_sweep_aborts(self):
        session = FakeSession({
            1: [_state([_offer(1)], nav_max=2)],
            2: [_state([], feed_ui=False, is_login=True)],
        })
        with self.assertRaises(NotLoggedInError):
            _extractor(session).extract(run_id="r1", merchant="M", store_id=1)

    def test_feed_shrinking_mid_sweep_is_past_end_not_anomaly(self):
        session = FakeSession({
            1: [_state([_offer(1)], nav_max=3), _state([_offer(1)], nav_max=2)],
            2: [_state([_offer(2)], nav_max=3), _state([_offer(2)], nav_max=2)],
            3: [_state([], nav_max=2)],
        })
        _, feed = _extractor(session).extract(run_id="r1", merchant="M", store_id=1)
        self.assertEqual([o.offer_id for o in feed.offers], ["1", "2"])
        self.assertEqual(session.visits(3), 2)  # blank re-checked, then past-end

    def test_unstable_beyond_max_sweeps_aborts(self):
        session = FakeSession({
            1: [
                _state([_offer(1)], nav_max=0),
                _state([_offer(2)], nav_max=0),
                _state([_offer(3)], nav_max=0),
            ],
        })
        with self.assertRaises(FeedUnstableError):
            _extractor(session).extract(run_id="r1", merchant="M", store_id=1, max_sweeps=3)

    def test_advertised_pages_above_cap_abort(self):
        session = FakeSession({1: [_state([_offer(1)], nav_max=41)]})
        with self.assertRaises(FeedUnstableError):
            _extractor(session).extract(run_id="r1", merchant="M", store_id=1, max_pages=40)

    def test_max_sweeps_below_two_is_refused(self):
        with self.assertRaises(ValueError):
            _extractor(FakeSession({})).extract(
                run_id="r1", merchant="M", store_id=1, max_sweeps=1
            )

    def test_guard_signatures_are_sweep_scoped(self):
        guard = StepGuard(max_attempts_per_signature=2)
        session = FakeSession({1: [_state([_offer(1)], nav_max=0)]})
        _extractor(session, guard=guard).extract(run_id="r1", merchant="M", store_id=1)
        sigs = guard.snapshot()["counters"]["attempts_by_signature"]
        self.assertIn("feed:M:s1:p1", sigs)
        self.assertIn("feed:M:s2:p1", sigs)
        self.assertFalse(guard.blocked)

    def test_last_stats_report_coverage(self):
        session = FakeSession({
            1: [_state([_offer(1), _offer(2)], nav_max=2)],
            2: [_state([_offer(3)], nav_max=1)],
        })
        extractor = _extractor(session)
        extractor.extract(run_id="r1", merchant="M", store_id=1)
        self.assertEqual(extractor.last_stats["distinct_offers"], 3)
        self.assertEqual(extractor.last_stats["sweeps"], 2)
        self.assertEqual(extractor.last_stats["rows_seen"], 6)
        self.assertEqual(extractor.last_stats["last_page"], 2)


class PageRangeTests(unittest.TestCase):
    def test_single_page(self):
        self.assertEqual(parse_page_range("3"), (3, 3))

    def test_range(self):
        self.assertEqual(parse_page_range("3-5"), (3, 5))

    def test_invalid_ranges_rejected(self):
        for bad in ("", "a", "0", "5-3", "1-2-3"):
            with self.assertRaises(ValueError, msg=bad):
                parse_page_range(bad)


class ExtractPagesTests(unittest.TestCase):
    def _feed4(self):
        return FakeSession({
            1: [_state([_offer(1)], nav_max=4)],
            2: [_state([_offer(2)], nav_max=4)],
            3: [_state([_offer(3)], nav_max=4)],
            4: [_state([_offer(4)], nav_max=4)],
        })

    def test_slice_fetches_only_requested_pages_once(self):
        session = self._feed4()
        extractor = _extractor(session)
        snapshot, feed = extractor.extract_pages(
            run_id="r1", merchant="M", store_id=1, first_page=2, last_page=3
        )
        self.assertEqual([o.offer_id for o in feed.offers], ["2", "3"])
        self.assertEqual(session.visits(1), 0)
        self.assertEqual(session.visits(2), 1)
        self.assertEqual(session.visits(3), 1)
        self.assertEqual(session.visits(4), 0)
        self.assertEqual(snapshot.pages_scanned, 2)
        stats = extractor.last_stats
        self.assertEqual(stats["mode"], "pages")
        self.assertTrue(stats["partial"])
        self.assertEqual(stats["pages_requested"], [2, 3])
        self.assertEqual(stats["feed_last_page"], 4)

    def test_slice_past_feed_end_stops_cleanly(self):
        session = FakeSession({
            1: [_state([_offer(1)], nav_max=2)],
            2: [_state([_offer(2)], nav_max=2)],
        })
        extractor = _extractor(session)
        _, feed = extractor.extract_pages(
            run_id="r1", merchant="M", store_id=1, first_page=2, last_page=5
        )
        self.assertEqual([o.offer_id for o in feed.offers], ["2"])
        self.assertEqual(session.visits(3), 2)  # a blank page is never trusted once
        self.assertEqual(session.visits(4), 0)
        self.assertEqual(extractor.last_stats["feed_last_page"], 2)

    def test_slice_starting_past_end_returns_zero_offers(self):
        session = FakeSession({1: [_state([_offer(1)], nav_max=0)]})
        snapshot, feed = _extractor(session).extract_pages(
            run_id="r1", merchant="M", store_id=1, first_page=3, last_page=4
        )
        self.assertEqual(len(feed.offers), 0)
        self.assertEqual(snapshot.pages_scanned, 1)
        self.assertEqual(session.visits(4), 0)

    def test_slice_empty_feed_on_page_one(self):
        session = FakeSession({1: [_state([], nav_max=0)]})
        _, feed = _extractor(session).extract_pages(
            run_id="r1", merchant="M", store_id=1, first_page=1, last_page=3
        )
        self.assertEqual(len(feed.offers), 0)
        self.assertEqual(session.visits(1), 2)  # blank confirmed by re-fetch
        self.assertEqual(session.visits(2), 0)

    def test_slice_blank_in_range_page_aborts(self):
        session = FakeSession({
            1: [_state([_offer(1)], nav_max=3)],
            2: [_state([], nav_max=3)],
            3: [_state([_offer(3)], nav_max=3)],
        })
        with self.assertRaises(EmptyPageAnomaly):
            _extractor(session).extract_pages(
                run_id="r1", merchant="M", store_id=1, first_page=1, last_page=3
            )

    def test_slice_login_bounce_aborts(self):
        session = FakeSession({2: [_state([], feed_ui=False, is_login=True)]})
        with self.assertRaises(NotLoggedInError):
            _extractor(session).extract_pages(
                run_id="r1", merchant="M", store_id=1, first_page=2, last_page=2
            )
        self.assertEqual(session.visits(2), 1)  # no blind retry on a login bounce

    def test_slice_dedupes_repeated_ids(self):
        session = FakeSession({
            1: [_state([_offer(1), _offer(2)], nav_max=2)],
            2: [_state([_offer(2), _offer(3)], nav_max=2)],
        })
        _, feed = _extractor(session).extract_pages(
            run_id="r1", merchant="M", store_id=1, first_page=1, last_page=2
        )
        self.assertEqual([o.offer_id for o in feed.offers], ["1", "2", "3"])

    def test_slice_validates_range(self):
        extractor = _extractor(self._feed4())
        with self.assertRaises(ValueError):
            extractor.extract_pages(
                run_id="r1", merchant="M", store_id=1, first_page=0, last_page=1
            )
        with self.assertRaises(ValueError):
            extractor.extract_pages(
                run_id="r1", merchant="M", store_id=1, first_page=3, last_page=2
            )

    def test_slice_guard_signatures(self):
        guard = StepGuard(max_attempts_per_signature=2)
        _extractor(self._feed4(), guard=guard).extract_pages(
            run_id="r1", merchant="M", store_id=1, first_page=2, last_page=2
        )
        sigs = guard.snapshot()["counters"]["attempts_by_signature"]
        self.assertIn("feed:M:s1:p2", sigs)
        self.assertFalse(guard.blocked)


class ExtractorPacingTests(unittest.TestCase):
    def test_slice_paces_between_fetches_never_before_first(self):
        sleeps = []
        pacer = Pacer(1, 1, sleeper=sleeps.append)
        session = FakeSession({
            1: [_state([_offer(1)], nav_max=2)],
            2: [_state([_offer(2)], nav_max=2)],
        })
        _extractor(session, pacer=pacer).extract_pages(
            run_id="r1", merchant="M", store_id=1, first_page=1, last_page=2
        )
        self.assertEqual(len(sleeps), 1)  # 2 fetches → 1 inter-page wait

    def test_sweep_mode_paces_between_fetches(self):
        sleeps = []
        pacer = Pacer(1, 1, sleeper=sleeps.append)
        session = FakeSession({1: [_state([_offer(1)], nav_max=0)]})
        _extractor(session, pacer=pacer).extract(run_id="r1", merchant="M", store_id=1)
        # sweep 1 p1 + confirming sweep 2 p1 = 2 fetches → 1 wait
        self.assertEqual(len(sleeps), 1)

class ReadOnlyGuardTests(unittest.TestCase):
    def test_page_state_js_is_considered_read_only(self):
        self.assertTrue(is_readonly_expression(PAGE_STATE_JS))

    def test_evaluate_readonly_refuses_mutations(self):
        session = ReadOnlyCdpSession("http://172.17.0.1:9223/json/version")
        for expr in (
            "document.querySelector('.button-primary').click()",
            "form.dispatchEvent(new Event('submit'))",
            "s.selectize.setValue('2')",
            "fetch('/wp-admin/admin-ajax.php')",
        ):
            with self.assertRaises(ReadOnlyEvalError):
                session.evaluate_readonly(expr)


if __name__ == "__main__":
    unittest.main()

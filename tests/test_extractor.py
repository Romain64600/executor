import json
import unittest

from src.cdp_session import ReadOnlyCdpSession, ReadOnlyEvalError, is_readonly_expression
from src.extractor import EXTRACT_JS, FeedExtractor, feed_url, parse_offers_payload
from src.step_guard import StepGuard


def _offer(i, **over):
    base = {"id": str(i), "name": f"Game {i}", "url": f"https://m.test/{i}", "storeId": "127"}
    base.update(over)
    return base


class FakeSession:
    """Returns canned pages as the EXTRACT_JS payload (array of data-offer strings)."""

    def __init__(self, pages, login=False):
        self.pages = pages
        self.login = login
        self.login_probes = 0
        self.nav = []
        self._i = 0

    def navigate(self, url, settle=0):
        self.nav.append(url)

    def evaluate_readonly(self, expression):
        if "loginform" in expression:
            self.login_probes += 1
            return self.login
        page = self.pages[self._i] if self._i < len(self.pages) else []
        self._i += 1
        return json.dumps([json.dumps(o) for o in page])


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

    def test_html_entities_are_unescaped(self):
        payload = json.dumps([json.dumps({"id": "1", "name": "A &amp; B", "url": "https://x/1"})])
        self.assertEqual(parse_offers_payload(payload)[0]["name"], "A & B")

    def test_empty_payload(self):
        self.assertEqual(parse_offers_payload(""), [])
        self.assertEqual(parse_offers_payload(None), [])
        self.assertEqual(parse_offers_payload("[]"), [])


class ExtractTests(unittest.TestCase):
    def test_paginates_dedupes_and_stops_on_empty_page(self):
        session = FakeSession([[_offer(1), _offer(2)], [_offer(2), _offer(3)], []])
        extractor = FeedExtractor(session)
        snapshot, feed = extractor.extract(run_id="r1", merchant="Driffle", store_id=127)

        self.assertEqual(snapshot.pages_scanned, 3)
        self.assertEqual([o["id"] for o in snapshot.raw_offers], ["1", "2", "3"])
        self.assertEqual([o.offer_id for o in feed.offers], ["1", "2", "3"])
        self.assertIn("&p=3", session.nav[2])
        self.assertFalse(extractor.guard.blocked)

    def test_stops_after_two_consecutive_no_new(self):
        session = FakeSession([[_offer(1)], [_offer(1)], [_offer(1)], [_offer(9)]])
        extractor = FeedExtractor(session)
        snapshot, _ = extractor.extract(run_id="r1", merchant="M", store_id=1)
        self.assertEqual(snapshot.pages_scanned, 3)  # stopped before page 4
        self.assertEqual([o["id"] for o in snapshot.raw_offers], ["1"])

    def test_empty_feed_yields_empty_snapshot(self):
        session = FakeSession([[]])
        extractor = FeedExtractor(session)
        snapshot, feed = extractor.extract(run_id="r1", merchant="M", store_id=1)
        self.assertEqual(snapshot.pages_scanned, 1)
        self.assertEqual(len(feed.offers), 0)
        # The empty first page is ambiguous → the login probe ran (and said no).
        self.assertEqual(session.login_probes, 1)

    def test_empty_first_page_on_login_page_aborts_loudly(self):
        # Fail-closed: a wp-login bounce must raise, never return a silent
        # empty feed (0 offers is otherwise a legitimate state — seen live
        # 2026-07-07 when the Driffle queue genuinely emptied).
        from src.extractor import NotLoggedInError

        with self.assertRaises(NotLoggedInError):
            FeedExtractor(FakeSession([[]], login=True)).extract(
                run_id="r1", merchant="M", store_id=1
            )

    def test_non_empty_first_page_skips_login_probe(self):
        session = FakeSession([[_offer(1)], []])
        FeedExtractor(session).extract(run_id="r1", merchant="M", store_id=1)
        self.assertEqual(session.login_probes, 0)

    def test_guard_is_exercised_per_page(self):
        session = FakeSession([[_offer(1)], []])
        guard = StepGuard(max_attempts_per_signature=2)
        FeedExtractor(session, guard=guard).extract(run_id="r1", merchant="M", store_id=1)
        snap = guard.snapshot()
        self.assertIn("feed:M:p1", snap["counters"]["attempts_by_signature"])
        self.assertEqual(snap["counters"]["total_failures"], 0)


class ReadOnlyGuardTests(unittest.TestCase):
    def test_extract_js_is_considered_read_only(self):
        self.assertTrue(is_readonly_expression(EXTRACT_JS))

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

import json
import unittest

from src.contracts import (
    ContractError,
    NormalizedFeed,
    NormalizedOffer,
    RawSnapshot,
)


def _raw(**over):
    base = {
        "id": "92015031",
        "name": "Tower! Simulator 3",
        "url": "https://www.driffle.com/tower-simulator-3",
        "storeId": "127",
        "price": "12.34",
        "stock": "y",
    }
    base.update(over)
    return base


class NormalizedOfferTests(unittest.TestCase):
    def test_from_raw_valid(self):
        offer = NormalizedOffer.from_raw(_raw(), merchant="Driffle")
        self.assertEqual(offer.offer_id, "92015031")
        self.assertEqual(offer.merchant, "Driffle")
        self.assertEqual(offer.store_id, "127")
        self.assertEqual(offer.price, "12.34")

    def test_numeric_fields_are_coerced_to_str(self):
        offer = NormalizedOffer.from_raw(_raw(id=123, price=9), merchant="Driffle")
        self.assertEqual(offer.offer_id, "123")
        self.assertEqual(offer.price, "9")

    def test_empty_optional_fields_become_none(self):
        offer = NormalizedOffer.from_raw(_raw(price="", stock=None, storeId=""), merchant="Driffle")
        self.assertIsNone(offer.price)
        self.assertIsNone(offer.stock)
        self.assertIsNone(offer.store_id)

    def test_missing_required_key_raises(self):
        for missing in ("id", "name", "url"):
            raw = _raw()
            raw.pop(missing)
            with self.assertRaises(ContractError):
                NormalizedOffer.from_raw(raw, merchant="Driffle")

    def test_non_http_url_raises(self):
        with self.assertRaises(ContractError):
            NormalizedOffer.from_raw(_raw(url="[URL in feed]"), merchant="Driffle")

    def test_missing_merchant_raises(self):
        with self.assertRaises(ContractError):
            NormalizedOffer.from_raw(_raw(), merchant="")

    def test_to_dict_is_json_serializable(self):
        offer = NormalizedOffer.from_raw(_raw(), merchant="Driffle")
        json.dumps(offer.to_dict())


class RawSnapshotTests(unittest.TestCase):
    def _create(self, **over):
        kwargs = dict(
            run_id="run-1",
            merchant="Driffle",
            store_id=127,
            source_url="https://www.allkeyshop.com/blog/wp-admin/admin.php?store=127",
            raw_offers=[_raw()],
            pages_scanned=1,
            clock=lambda: "2026-07-02T00:00:00Z",
        )
        kwargs.update(over)
        return RawSnapshot.create(**kwargs)

    def test_create_valid(self):
        snap = self._create()
        self.assertEqual(snap.store_id, "127")
        self.assertEqual(snap.fetched_at, "2026-07-02T00:00:00Z")
        self.assertEqual(snap.to_dict()["offer_count"], 1)

    def test_invalid_fields_raise(self):
        with self.assertRaises(ContractError):
            self._create(run_id="")
        with self.assertRaises(ContractError):
            self._create(source_url="ftp://x")
        with self.assertRaises(ContractError):
            self._create(pages_scanned=0)
        with self.assertRaises(ContractError):
            self._create(raw_offers=[{"id": "1"}, "not-a-dict"])

    def test_to_dict_is_json_serializable(self):
        json.dumps(self._create().to_dict())

    def test_feed_last_page_defaults_zero_and_round_trips(self):
        # 2026-07-20: the feed's own page count, used by the submit to
        # auto-default --max-pages.
        self.assertEqual(self._create().to_dict()["feed_last_page"], 0)
        snap = self._create(feed_last_page=357)
        self.assertEqual(snap.feed_last_page, 357)
        self.assertEqual(snap.to_dict()["feed_last_page"], 357)
        # negative is clamped to 0 (unknown), never trusted as a page count
        self.assertEqual(self._create(feed_last_page=-5).feed_last_page, 0)


class NormalizedFeedTests(unittest.TestCase):
    def _snap(self, offers):
        return RawSnapshot.create(
            run_id="run-1",
            merchant="Driffle",
            store_id=127,
            source_url="https://www.allkeyshop.com/blog/wp-admin/admin.php?store=127",
            raw_offers=offers,
            pages_scanned=2,
            clock=lambda: "2026-07-02T00:00:00Z",
        )

    def test_from_snapshot_dedupes_by_id(self):
        snap = self._snap([_raw(id="1"), _raw(id="1"), _raw(id="2")])
        feed = NormalizedFeed.from_snapshot(snap)
        self.assertEqual([o.offer_id for o in feed.offers], ["1", "2"])

    def test_from_snapshot_raises_on_malformed_offer(self):
        snap = self._snap([_raw(id="1"), {"id": "2"}])  # second row missing name/url
        with self.assertRaises(ContractError):
            NormalizedFeed.from_snapshot(snap)

    def test_to_dict_is_json_serializable(self):
        feed = NormalizedFeed.from_snapshot(self._snap([_raw(id="1")]))
        payload = json.dumps(feed.to_dict())
        self.assertIn('"offer_count": 1', payload)

    def test_feed_last_page_propagates_from_snapshot(self):
        snap = RawSnapshot.create(
            run_id="run-1", merchant="Difmark", store_id=167,
            source_url="https://www.allkeyshop.com/blog/wp-admin/admin.php?store=167",
            raw_offers=[_raw(id="1")], pages_scanned=1, feed_last_page=357,
            clock=lambda: "2026-07-02T00:00:00Z",
        )
        feed = NormalizedFeed.from_snapshot(snap)
        self.assertEqual(feed.feed_last_page, 357)
        self.assertEqual(feed.to_dict()["feed_last_page"], 357)


if __name__ == "__main__":
    unittest.main()

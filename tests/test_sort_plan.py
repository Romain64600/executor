import unittest

from src.contracts import NormalizedOffer
from src.extractor import feed_url
from src.sort_plan import build_sort_plan, render_report


def _offer(name, url="https://m.test/x", oid="1", store_id="38"):
    return NormalizedOffer(offer_id=oid, name=name, url=url, merchant="all-stores",
                           store_id=store_id)


class FeedUrlAllStoresTests(unittest.TestCase):
    def test_store_none_omits_store_filter(self):
        # the all-stores view: no store= key at all (probed live 2026-07-23)
        url = feed_url(None)
        self.assertNotIn("store=", url)
        self.assertIn("page=aks-merchant-feeds-9", url)

    def test_store_none_paginates(self):
        self.assertTrue(feed_url(None, page=3).endswith("&p=3"))
        self.assertNotIn("store=", feed_url(None, page=3))

    def test_store_id_still_filters(self):
        self.assertIn("store=38", feed_url("38"))


class BuildSortPlanTests(unittest.TestCase):
    def test_routes_each_category_to_its_list(self):
        offers = [
            _offer("EaseUS Todo Backup Workstation", oid="1", store_id="51"),   # → 16 Softwares
            _offer("Steam Wallet Gift Card 50 USD", oid="2", store_id="38"),    # → 21 Gift cards
            _offer("GAMIVO Epic Random Game Global", oid="3", store_id="51"),   # → 8 Blacklist
            _offer("Celeste Original Soundtrack", oid="4", store_id="38"),      # → 8 Blacklist
            _offer("Elden Ring Steam Key GLOBAL", oid="5", store_id="38"),      # candidate (passes)
        ]
        plan = build_sort_plan(offers, run_id="r1")
        by = plan["by_list"]
        self.assertEqual(by["16"]["count"], 1)
        self.assertEqual(by["21"]["count"], 1)
        self.assertEqual(by["8"]["count"], 2)          # random + soundtrack both → Blacklist
        self.assertEqual(plan["counts"]["candidates"], 1)
        self.assertEqual(plan["counts"]["routed"], 4)
        self.assertEqual(plan["counts"]["total"], 5)

    def test_unrouted_skip_is_not_dropped(self):
        # a currency skip has no target list → unrouted (garder), never lost
        plan = build_sort_plan([_offer("500 FIFA Points")], run_id="r")
        self.assertEqual(plan["counts"]["routed"], 0)
        self.assertEqual(len(plan["unrouted"]), 1)
        self.assertIn("POINTS", plan["unrouted"][0]["reason"])

    def test_every_offer_classified_exactly_once(self):
        offers = [
            _offer("EaseUS Todo Backup", oid="1"),
            _offer("500 FIFA Points", oid="2"),
            _offer("Elden Ring Steam Key GLOBAL", oid="3"),
            _offer("Random Game Key WORLDWIDE", oid="4"),
        ]
        plan = build_sort_plan(offers)
        c = plan["counts"]
        classified = c["routed"] + c["unrouted_skips"] + c["candidates"]
        self.assertEqual(classified, c["total"])

    def test_entry_carries_store_id_and_offer_id_for_the_writer(self):
        plan = build_sort_plan([_offer("GAMIVO Random Bundle Spinner", oid="77", store_id="51")])
        entry = plan["by_list"]["8"]["offers"][0]
        self.assertEqual(entry["offer_id"], "77")
        self.assertEqual(entry["store_id"], "51")

    def test_groups_ordered_largest_first(self):
        offers = ([_offer("Random Game Key", oid=str(i)) for i in range(3)]      # 3 → Blacklist
                  + [_offer("Steam Wallet Gift Card", oid="g")])                 # 1 → Gift cards
        plan = build_sort_plan(offers)
        self.assertEqual(list(plan["by_list"].keys())[0], "8")

    def test_render_report_lists_each_target(self):
        offers = [_offer("EaseUS Todo Backup"), _offer("Random Game Key", oid="2")]
        text = render_report(build_sort_plan(offers, run_id="rX"))
        self.assertIn("Softwares", text)
        self.assertIn("Blacklist", text)
        self.assertIn("rX", text)

    def test_render_report_per_list_limit(self):
        offers = [_offer("Random Game Key", oid=str(i)) for i in range(5)]
        text = render_report(build_sort_plan(offers), per_list_limit=2)
        self.assertIn("+3 autres", text)


if __name__ == "__main__":
    unittest.main()

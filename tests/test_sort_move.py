import json
import tempfile
import unittest
from pathlib import Path

from src.move_auth import (
    grant_from_sort_canary,
    load_sort_authorization,
    sort_batch_authorized,
    sort_extraction_id,
)
from src.sort_move import build_sort_move_plan


def _write(run: Path, name: str, obj) -> None:
    (run / name).write_text(json.dumps(obj), encoding="utf-8")


SORT_PLAN = {
    "run_id": "20260723-sort",
    "by_list": {
        "8": {"list_id": "8", "label": "Blacklist", "count": 3, "offers": [
            {"offer_id": "a1", "store_id": "38", "name": "Random Game Key", "url": "https://g2a/a1"},
            {"offer_id": "a2", "store_id": "51", "name": "GAMIVO Epic Random Game", "url": "https://gamivo/a2"},
            {"offer_id": "a3", "store_id": "38", "name": "Some OST", "url": "https://g2a/a3"},
        ]},
        "21": {"list_id": "21", "label": "Gift cards", "count": 1, "offers": [
            {"offer_id": "g1", "store_id": "162", "name": "Steam Gift Card", "url": "https://x/g1"},
        ]},
    },
}
RAW = {"store_id": "", "source_url": "https://x/admin.php?available=all&page=aks-merchant-feeds-9"}


class BuildSortMovePlanTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.run = Path(self.tmp.name)
        _write(self.run, "sort_plan.json", SORT_PLAN)
        _write(self.run, "raw.json", RAW)

    def test_groups_one_list_by_store(self):
        plan = build_sort_move_plan(self.run, "8")
        self.assertEqual(plan["target_list_label"], "Blacklist")
        self.assertEqual(plan["source_feed_page"], "aks-merchant-feeds-9")
        self.assertEqual(set(plan["by_store"]), {"38", "51"})
        self.assertEqual(len(plan["by_store"]["38"]), 2)
        self.assertEqual(len(plan["by_store"]["51"]), 1)
        self.assertEqual(plan["counts"],
                         {"stores": 2, "offers": 3, "excluded": 0, "already_resolved": 0})

    def test_entries_carry_label_and_url_for_the_mover(self):
        e = build_sort_move_plan(self.run, "8")["by_store"]["38"][0]
        self.assertEqual(e["target_list_label"], "Blacklist")
        self.assertEqual(e["target_list_id"], "8")
        self.assertTrue(e["url"])

    def test_offer_without_store_or_url_is_excluded_not_dropped(self):
        bad = json.loads(json.dumps(SORT_PLAN))
        bad["by_list"]["8"]["offers"].append(
            {"offer_id": "x", "store_id": "", "name": "no store", "url": "https://x/x"})
        bad["by_list"]["8"]["offers"].append(
            {"offer_id": "y", "store_id": "38", "name": "no url", "url": ""})
        _write(self.run, "sort_plan.json", bad)
        plan = build_sort_move_plan(self.run, "8")
        self.assertEqual(plan["counts"]["excluded"], 2)
        self.assertEqual(plan["counts"]["offers"], 3)  # the 3 good ones only

    def test_unknown_list_is_empty(self):
        plan = build_sort_move_plan(self.run, "999")
        self.assertEqual(plan["by_store"], {})
        self.assertEqual(plan["counts"]["offers"], 0)

    def test_incremental_skips_resolved_urls(self):
        from src.submitter import _url_key
        # mark a1's URL as already resolved → incremental drops it, keeps the rest
        resolved = {_url_key("https://g2a/a1")}
        plan = build_sort_move_plan(self.run, "8", resolved=resolved)
        self.assertTrue(plan["incremental"])
        self.assertEqual(plan["counts"]["already_resolved"], 1)
        self.assertEqual(plan["counts"]["offers"], 2)          # a2, a3 remain
        urls = [e["url"] for v in plan["by_store"].values() for e in v]
        self.assertNotIn("https://g2a/a1", urls)

    def test_full_mode_processes_everything(self):
        plan = build_sort_move_plan(self.run, "8", resolved=None)   # None = full
        self.assertFalse(plan["incremental"])
        self.assertEqual(plan["counts"]["already_resolved"], 0)
        self.assertEqual(plan["counts"]["offers"], 3)


class SortAuthorizationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.run = Path(self.tmp.name)
        _write(self.run, "sort_plan.json", SORT_PLAN)

    def _entries(self, *labels):
        return [{"target_list_label": lbl} for lbl in labels]

    def test_no_authorization_refuses_batch(self):
        ok, why = sort_batch_authorized(self.run, self._entries("Blacklist"),
                                        source_feed_page="aks-merchant-feeds-9")
        self.assertFalse(ok)
        self.assertIn("aucune autorisation", why)

    def test_canary_authorizes_that_label_across_stores(self):
        grant_from_sort_canary(
            self.run, source_feed_page="aks-merchant-feeds-9",
            moved_entries=[{"target_list_label": "Blacklist", "current_offer_id": "a1",
                            "url": "https://g2a/a1", "store_id": "38"}],
            clock=lambda: "T")
        # a batch of Blacklist offers on ANOTHER store is now covered (no store in scope)
        ok, why = sort_batch_authorized(
            self.run, self._entries("Blacklist", "Blacklist"),
            source_feed_page="aks-merchant-feeds-9")
        self.assertTrue(ok, why)

    def test_unvalidated_label_refused(self):
        grant_from_sort_canary(
            self.run, source_feed_page="aks-merchant-feeds-9",
            moved_entries=[{"target_list_label": "Blacklist", "current_offer_id": "a1",
                            "url": "https://g2a/a1", "store_id": "38"}],
            clock=lambda: "T")
        ok, why = sort_batch_authorized(self.run, self._entries("Gift cards"),
                                        source_feed_page="aks-merchant-feeds-9")
        self.assertFalse(ok)
        self.assertIn("Gift cards", why)

    def test_unitary_canary_does_not_unlock_batch(self):
        grant_from_sort_canary(
            self.run, source_feed_page="aks-merchant-feeds-9",
            moved_entries=[{"target_list_label": "Blacklist", "url": "u", "store_id": "38"}],
            clock=lambda: "T")  # multi_item defaults False
        ok, why = sort_batch_authorized(self.run, self._entries("Blacklist"),
                                        source_feed_page="aks-merchant-feeds-9",
                                        require_multi_item=True)
        self.assertFalse(ok)
        self.assertIn("multi-item", why)
        # ...but a UNITARY (non-batch) safe run is still covered by the same auth.
        ok2, _ = sort_batch_authorized(self.run, self._entries("Blacklist"),
                                       source_feed_page="aks-merchant-feeds-9")
        self.assertTrue(ok2)

    def test_multi_item_canary_unlocks_batch(self):
        grant_from_sort_canary(
            self.run, source_feed_page="aks-merchant-feeds-9",
            moved_entries=[{"target_list_label": "Blacklist", "url": "u", "store_id": "38"}],
            multi_item=True, clock=lambda: "T")
        ok, why = sort_batch_authorized(self.run, self._entries("Blacklist"),
                                        source_feed_page="aks-merchant-feeds-9",
                                        require_multi_item=True)
        self.assertTrue(ok, why)
        self.assertIn("multi-item", why)

    def test_multi_item_proof_sticks_across_later_unitary_grant(self):
        grant_from_sort_canary(
            self.run, source_feed_page="aks-merchant-feeds-9",
            moved_entries=[{"target_list_label": "Blacklist", "url": "u", "store_id": "38"}],
            multi_item=True, clock=lambda: "T")
        grant_from_sort_canary(  # a later unitary grant must NOT un-prove multi-item
            self.run, source_feed_page="aks-merchant-feeds-9",
            moved_entries=[{"target_list_label": "Gift cards", "url": "u2", "store_id": "38"}],
            multi_item=False, clock=lambda: "T")
        ok, _ = sort_batch_authorized(self.run, self._entries("Blacklist"),
                                      source_feed_page="aks-merchant-feeds-9",
                                      require_multi_item=True)
        self.assertTrue(ok)

    def test_stale_mover_version_invalidates_sort_batch(self):
        # The 3->4 bump must reject any authorization granted by an older mover,
        # on the SORT path (a v3 canary must not cover a v4 batch).
        from src.move_auth import SORT_AUTH_FILE
        grant_from_sort_canary(
            self.run, source_feed_page="aks-merchant-feeds-9",
            moved_entries=[{"target_list_label": "Blacklist", "url": "u", "store_id": "38"}],
            multi_item=True, clock=lambda: "T")
        path = self.run / SORT_AUTH_FILE
        auth = json.loads(path.read_text(encoding="utf-8"))
        auth["mover_version"] = "3"                       # pretend an older mover granted it
        path.write_text(json.dumps(auth), encoding="utf-8")
        ok, why = sort_batch_authorized(self.run, self._entries("Blacklist"),
                                        source_feed_page="aks-merchant-feeds-9",
                                        require_multi_item=True)
        self.assertFalse(ok)
        self.assertIn("mover_version", why)

    def test_authorization_resets_when_sort_plan_changes(self):
        grant_from_sort_canary(
            self.run, source_feed_page="aks-merchant-feeds-9",
            moved_entries=[{"target_list_label": "Blacklist", "url": "u", "store_id": "38"}],
            clock=lambda: "T")
        before = sort_extraction_id(self.run)
        _write(self.run, "sort_plan.json", {"run_id": "changed", "by_list": {}})
        self.assertNotEqual(sort_extraction_id(self.run), before)
        ok, why = sort_batch_authorized(self.run, self._entries("Blacklist"),
                                        source_feed_page="aks-merchant-feeds-9")
        self.assertFalse(ok)
        self.assertIn("hors périmètre", why)

    def test_sort_auth_uses_a_separate_file(self):
        grant_from_sort_canary(
            self.run, source_feed_page="aks-merchant-feeds-9",
            moved_entries=[{"target_list_label": "Blacklist", "url": "u", "store_id": "38"}],
            clock=lambda: "T")
        self.assertIsNotNone(load_sort_authorization(self.run))
        self.assertTrue((self.run / "sort_move_authorization.json").is_file())
        self.assertFalse((self.run / "move_authorization.json").is_file())


if __name__ == "__main__":
    unittest.main()

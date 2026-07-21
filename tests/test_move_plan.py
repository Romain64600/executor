import json
import tempfile
import unittest
from pathlib import Path

from src.move_plan import build_move_plan


class BuildMovePlanTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.run = Path(self.tmp.name) / "20260721-090509-g2a"
        self.run.mkdir()
        (self.run / "skipped.json").write_text(json.dumps([
            {"offer": {"offer_id": "1", "name": "PdfGrabber 9", "url": "https://g2a/1"}, "reason": "skip category: SOFTWARE"},
            {"offer": {"offer_id": "2", "name": "Some Gift Card", "url": "https://g2a/2"}, "reason": "skip category: GIFT CARD"},
            {"offer": {"offer_id": "3", "name": "Kept Game", "url": "https://g2a/3"}, "reason": "console"},
            {"offer": {"offer_id": "4", "name": "Suggested Only", "url": "https://g2a/4"}, "reason": "skip category: SOFTWARE"},
        ]), encoding="utf-8")
        (self.run / "raw.json").write_text(json.dumps({
            "store_id": "38",
            "source_url": "https://x/admin.php?available=all&store=38&page=aks-merchant-feeds-9&p=1",
        }), encoding="utf-8")

    def _write_learning(self, annotations):
        (self.run / "learning.json").write_text(json.dumps({
            "run_id": self.run.name, "annotations": annotations,
        }), encoding="utf-8")

    def test_only_confirmed_dispositions_enter_the_plan(self):
        self._write_learning({
            "1": {"target_list_id": "16", "target_list_label": "Softwares"},      # confirmed
            "2": {"target_list_id": "21", "target_list_label": "Gift cards"},     # confirmed
            "3": {"comment": "à garder"},                                          # no disposition
            "4": {"target_list_id": "16", "target_list_label": "Softwares", "suggested": True},  # unconfirmed
        })
        plan = build_move_plan(self.run)
        ids = {e["offer_id"] for e in plan["entries"]}
        self.assertEqual(ids, {"1", "2"})  # garder + suggested excluded
        self.assertEqual(plan["store_id"], "38")
        self.assertEqual(plan["source_feed_page"], "aks-merchant-feeds-9")
        # the join with skipped.json carried name + url (the writer's identity)
        one = next(e for e in plan["entries"] if e["offer_id"] == "1")
        self.assertEqual((one["name"], one["url"]), ("PdfGrabber 9", "https://g2a/1"))
        # the suggested one is surfaced as excluded, never silently dropped
        self.assertTrue(any(x["offer_id"] == "4" and "D1-b" in x["reason"] for x in plan["excluded"]))

    def test_orphan_annotation_excluded_not_dropped(self):
        # offer_id 99 has a disposition but is no longer in skipped.json
        self._write_learning({"99": {"target_list_id": "16", "target_list_label": "Softwares"}})
        plan = build_move_plan(self.run)
        self.assertEqual(plan["entries"], [])
        self.assertTrue(any(x["offer_id"] == "99" and "orphelin" in x["reason"]
                            for x in plan["excluded"]))

    def test_no_learning_file_empty_plan(self):
        plan = build_move_plan(self.run)
        self.assertEqual(plan["entries"], [])
        self.assertEqual(plan["counts"]["annotations"], 0)


if __name__ == "__main__":
    unittest.main()

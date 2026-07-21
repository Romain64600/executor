import json
import tempfile
import unittest
from pathlib import Path

from src.admin.learning_io import (
    LearningError,
    group_skipped,
    load_annotations,
    save_annotations,
)


class LearningIoTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.run = Path(self.tmp.name) / "run"
        self.run.mkdir()
        self._write_skipped([
            ("1", "Resident Evil 2 / Biohazard RE:2", "https://g2a/1",
             "no AKS product page found (slug not 200)"),
            ("2", "Halo Xbox", "https://g2a/2", "console"),
            ("3", "Some Niche Game", "https://g2a/3",
             "no AKS product page found (slug not 200)"),
        ])

    def _write_skipped(self, rows):
        skipped = [
            {"offer": {"offer_id": o, "name": n, "url": u}, "reason": r}
            for o, n, u, r in rows
        ]
        (self.run / "skipped.json").write_text(json.dumps(skipped), encoding="utf-8")

    def test_group_by_reason_biggest_first(self):
        groups = group_skipped(self.run)
        self.assertEqual(groups[0]["reason"], "no AKS product page found (slug not 200)")
        self.assertEqual(groups[0]["count"], 2)
        self.assertEqual({o["offer_id"] for o in groups[0]["offers"]}, {"1", "3"})
        self.assertEqual(groups[1]["reason"], "console")

    def test_save_and_load_annotations(self):
        save_annotations(self.run, [
            {"offer_id": "1", "region_id": "9", "region_text": "Steam EU (9)",
             "edition_id": "1", "edition_text": "Standard",
             "comment": "le / double-titre casse le slug"},
            {"offer_id": "3", "comment": "jeu de niche, pas sur AKS"},
        ], by="Romain", clock=lambda: "T")
        ann = load_annotations(self.run)
        self.assertEqual(ann["1"]["region_id"], "9")
        self.assertEqual(ann["1"]["region_text"], "Steam EU (9)")
        self.assertEqual(ann["1"]["edition_id"], "1")
        self.assertEqual(ann["1"]["by"], "Romain")
        self.assertEqual(ann["3"]["comment"], "jeu de niche, pas sur AKS")
        self.assertNotIn("2", ann)  # untouched offer not stored

    def test_comment_only_annotation_is_kept(self):
        r = save_annotations(self.run, [{"offer_id": "3", "comment": "x"}],
                             by="R", clock=lambda: "T")
        self.assertEqual(r["saved"], 1)

    def test_empty_row_dropped(self):
        r = save_annotations(self.run, [{"offer_id": "1"}], by="R", clock=lambda: "T")
        self.assertEqual(r["saved"], 0)  # no region/edition/comment → dropped

    def test_bad_offer_id_refused(self):
        with self.assertRaises(LearningError) as ctx:
            save_annotations(self.run, [{"offer_id": "999", "comment": "x"}],
                             by="R", clock=lambda: "T")
        self.assertEqual(ctx.exception.code, "bad_offer")

    def test_non_list_body_refused(self):
        with self.assertRaises(LearningError) as ctx:
            save_annotations(self.run, {"offer_id": "1"}, by="R", clock=lambda: "T")
        self.assertEqual(ctx.exception.code, "bad_body")

    def test_no_skipped_file_empty(self):
        empty = Path(self.tmp.name) / "empty"
        empty.mkdir()
        self.assertEqual(group_skipped(empty), [])
        self.assertEqual(load_annotations(empty), {})


if __name__ == "__main__":
    unittest.main()

import json
import tempfile
import unittest
from pathlib import Path

from src.admin.learning_io import (
    LearningError,
    group_skipped,
    learning_sha,
    load_annotations,
    save_annotations,
)

AKS = "https://www.allkeyshop.com/blog/buy-re2-cd-key-compare-prices/"


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
        self._write_catalog()

    def _write_skipped(self, rows):
        skipped = [
            {"offer": {"offer_id": o, "name": n, "url": u}, "reason": r}
            for o, n, u, r in rows
        ]
        (self.run / "skipped.json").write_text(json.dumps(skipped), encoding="utf-8")

    def _write_catalog(self):
        # the run's session catalog — the fail-closed reference for region/edition ids
        (self.run / "session_catalog.json").write_text(json.dumps({
            "ok": True,
            "regions": {"master_options": [
                {"key": "2", "text": "Steam (2)"}, {"key": "9", "text": "Steam EU (9)"},
            ]},
            "editions": {"master_options": [
                {"key": "1", "text": "Standard"}, {"key": "16", "text": "DLC"},
            ]},
        }), encoding="utf-8")

    def _save(self, rows, **kw):
        kw.setdefault("by", "Romain")
        kw.setdefault("clock", lambda: "T")
        kw.setdefault("base_sha", learning_sha(self.run))
        return save_annotations(self.run, rows, **kw)

    # ------------------------------------------------------------ grouping
    def test_group_by_reason_biggest_first(self):
        groups = group_skipped(self.run)
        self.assertEqual(groups[0]["reason"], "no AKS product page found (slug not 200)")
        self.assertEqual(groups[0]["count"], 2)
        self.assertEqual({o["offer_id"] for o in groups[0]["offers"]}, {"1", "3"})
        self.assertEqual(groups[1]["reason"], "console")

    def test_group_carries_suggestion_and_year(self):
        self._write_skipped([
            ("5", "PdfGrabber 9 Software - GLOBAL", "https://g2a/5",
             "skip category: SOFTWARE"),
            ("6", "Bus-Simulator 2012 Steam Gift", "https://g2a/6",
             "no AKS product page found (slug not 200)"),
        ])
        offers = {o["offer_id"]: o for g in group_skipped(self.run) for o in g["offers"]}
        self.assertEqual(offers["5"]["suggested_list_id"], "16")   # software -> Softwares
        self.assertIsNone(offers["6"]["suggested_list_id"])        # no-AKS -> human pick
        self.assertEqual(offers["6"]["year"], "2012")              # weak hint surfaced

    # ------------------------------------------------------- save + load
    def test_save_and_load_annotations(self):
        self._save([
            {"offer_id": "1", "region_id": "9", "region_text": "Steam EU (9)",
             "edition_id": "1", "edition_text": "Standard",
             "comment": "le / double-titre casse le slug", "aks_url": AKS},
            {"offer_id": "3", "comment": "jeu de niche, pas sur AKS"},
        ])
        ann = load_annotations(self.run)
        self.assertEqual(ann["1"]["region_id"], "9")
        self.assertEqual(ann["1"]["region_text"], "Steam EU (9)")
        self.assertEqual(ann["1"]["edition_id"], "1")
        self.assertEqual(ann["1"]["aks_url"], AKS)
        self.assertEqual(ann["1"]["by"], "Romain")
        self.assertEqual(ann["3"]["comment"], "jeu de niche, pas sur AKS")
        self.assertNotIn("2", ann)  # untouched offer not stored

    def test_comment_only_annotation_is_kept(self):
        self.assertEqual(self._save([{"offer_id": "3", "comment": "x"}])["saved"], 1)

    def test_aks_url_only_annotation_is_kept(self):
        r = self._save([{"offer_id": "1", "aks_url": AKS}])
        self.assertEqual(r["saved"], 1)
        self.assertEqual(load_annotations(self.run)["1"]["aks_url"], AKS)

    def test_target_list_disposition_round_trips(self):
        self._save([{"offer_id": "1", "target_list_id": "16",
                     "target_list_label": "Softwares"}])
        ann = load_annotations(self.run)
        self.assertEqual(ann["1"]["target_list_id"], "16")
        self.assertEqual(ann["1"]["target_list_label"], "Softwares")

    def test_target_list_label_filled_server_side(self):
        self._save([{"offer_id": "2", "target_list_id": "21"}])
        self.assertEqual(load_annotations(self.run)["2"]["target_list_label"], "Gift cards")

    def test_empty_row_dropped(self):
        self.assertEqual(self._save([{"offer_id": "1"}])["saved"], 0)

    # ------------------------------------------------------- refusals (L5)
    def test_bad_offer_id_refused(self):
        with self.assertRaises(LearningError) as ctx:
            self._save([{"offer_id": "999", "comment": "x"}])
        self.assertEqual(ctx.exception.code, "bad_offer")

    def test_non_list_body_refused(self):
        with self.assertRaises(LearningError) as ctx:
            self._save({"offer_id": "1"})
        self.assertEqual(ctx.exception.code, "bad_body")

    def test_unknown_target_list_refused(self):
        for bad in ("999", "delete"):
            with self.assertRaises(LearningError) as ctx:
                self._save([{"offer_id": "1", "target_list_id": bad}])
            self.assertEqual(ctx.exception.code, "bad_list")

    def test_incoherent_list_label_refused(self):
        with self.assertRaises(LearningError) as ctx:
            self._save([{"offer_id": "1", "target_list_id": "16",
                         "target_list_label": "Blacklist"}])
        self.assertEqual(ctx.exception.code, "bad_list_label")

    def test_region_outside_session_catalog_refused(self):
        with self.assertRaises(LearningError) as ctx:
            self._save([{"offer_id": "1", "region_id": "412"}])
        self.assertEqual(ctx.exception.code, "bad_region")

    def test_region_without_catalog_refused(self):
        (self.run / "session_catalog.json").unlink()
        with self.assertRaises(LearningError) as ctx:
            self._save([{"offer_id": "1", "region_id": "9"}])
        self.assertEqual(ctx.exception.code, "bad_region")

    def test_stored_region_survives_catalog_drift(self):
        # L3: a saved id that drifted out of a re-fetched catalog is grandfathered.
        self._save([{"offer_id": "1", "region_id": "9", "comment": "a"}])
        (self.run / "session_catalog.json").write_text(json.dumps({
            "ok": True,
            "regions": {"master_options": [{"key": "77", "text": "Steam EU (77)"}]},
            "editions": {"master_options": [{"key": "1", "text": "Standard"}]},
        }), encoding="utf-8")
        r = self._save([{"offer_id": "1", "region_id": "9", "comment": "b"}])
        self.assertEqual(r["saved"], 1)
        self.assertEqual(load_annotations(self.run)["1"]["region_id"], "9")

    def test_non_aks_url_refused(self):
        with self.assertRaises(LearningError) as ctx:
            self._save([{"offer_id": "1", "aks_url": "javascript:alert(1)"}])
        self.assertEqual(ctx.exception.code, "bad_url")

    def test_oversized_field_refused(self):
        with self.assertRaises(LearningError) as ctx:
            self._save([{"offer_id": "1", "comment": "x" * 2001}])
        self.assertEqual(ctx.exception.code, "too_long")

    # ------------------------------------------------- merge + sha (L2)
    def test_merge_preserves_absent_offers(self):
        self._save([{"offer_id": "1", "comment": "gardée"}])
        self._save([{"offer_id": "3", "comment": "nouvelle"}])
        ann = load_annotations(self.run)
        self.assertEqual(ann["1"]["comment"], "gardée")   # NOT clobbered
        self.assertEqual(ann["3"]["comment"], "nouvelle")

    def test_cleared_deletes_explicitly(self):
        self._save([{"offer_id": "1", "comment": "à supprimer"}])
        r = self._save([{"offer_id": "1", "cleared": True}])
        self.assertEqual(r["cleared"], 1)
        self.assertNotIn("1", load_annotations(self.run))

    def test_stale_base_sha_conflict(self):
        self._save([{"offer_id": "1", "comment": "v1"}])
        with self.assertRaises(LearningError) as ctx:
            save_annotations(self.run, [{"offer_id": "3", "comment": "v2"}],
                             by="R", base_sha=None, clock=lambda: "T")
        self.assertEqual(ctx.exception.code, "conflict")
        self.assertEqual(ctx.exception.http_status, 409)

    def test_first_author_survives_edits(self):
        self._save([{"offer_id": "1", "comment": "v1"}],
                   by="Romain", clock=lambda: "T1")
        self._save([{"offer_id": "1", "comment": "v2"}],
                   by="Autre", clock=lambda: "T2")
        ann = load_annotations(self.run)["1"]
        self.assertEqual((ann["first_by"], ann["first_at"]), ("Romain", "T1"))
        self.assertEqual((ann["by"], ann["at"]), ("Autre", "T2"))

    def test_save_appends_jsonl_log(self):
        self._save([{"offer_id": "1", "comment": "x"}])
        self._save([{"offer_id": "1", "cleared": True}])
        lines = [json.loads(l) for l in
                 (self.run / "learning_log.jsonl").read_text().splitlines()]
        self.assertEqual(len(lines), 2)
        self.assertEqual(lines[0]["touched"], ["1"])
        self.assertEqual(lines[1]["cleared"], ["1"])
        self.assertEqual(lines[0]["after_sha"], lines[1]["before_sha"])

    # ----------------------------------------------- malformed inputs (L10)
    def test_duplicate_offer_id_last_wins(self):
        self._save([{"offer_id": "1", "comment": "a"},
                    {"offer_id": "1", "comment": "b"}])
        self.assertEqual(load_annotations(self.run)["1"]["comment"], "b")

    def test_malformed_skipped_entries_ignored(self):
        # non-dict entry + empty offer_id must neither crash nor whitelist ""
        (self.run / "skipped.json").write_text(json.dumps([
            "junk",
            {"offer": {"offer_id": "", "name": "x", "url": "u"}, "reason": "r"},
            {"offer": {"offer_id": "7", "name": "y", "url": "u"}, "reason": "r"},
        ]), encoding="utf-8")
        self.assertEqual(self._save([{"offer_id": "7", "comment": "ok"}])["saved"], 1)
        with self.assertRaises(LearningError):
            self._save([{"offer_id": "", "comment": "x"}])

    def test_no_skipped_file_empty(self):
        empty = Path(self.tmp.name) / "empty"
        empty.mkdir()
        self.assertEqual(group_skipped(empty), [])
        self.assertEqual(load_annotations(empty), {})


if __name__ == "__main__":
    unittest.main()

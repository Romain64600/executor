import json
import tempfile
import unittest
from pathlib import Path

from src.admin.runs import (
    RunAccessError,
    derive_merchant_store,
    list_runs,
    load_catalog_options,
    read_run_json,
    run_detail,
    run_file,
    safe_run_dir,
    sha256_file,
)


def _offers(merchant="GameSeal", store_ids=("126", "126")):
    return {
        "run_id": "r",
        "merchant": merchant,
        "fetched_at": "2026-07-15T00:00:00Z",
        "offer_count": len(store_ids),
        "offers": [
            {"offer_id": str(i), "name": f"Game {i}", "url": "https://m/x", "store_id": sid}
            for i, sid in enumerate(store_ids)
        ],
    }


def _catalog():
    return {
        "ok": True,
        "offer_id": "1",
        "region_select": "offer[region]",
        "edition_select": "offer[edition]",
        "regions": {"master_options": [{"key": "1", "text": "Publisher (1)"}, {"key": "2", "text": "Steam (2)"}]},
        "editions": {"master_options": [{"key": "1", "text": "Standard"}, {"key": "16", "text": "DLC"}]},
    }


class SafeRunDirTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.runs = Path(self.tmp.name) / "runs"
        (self.runs / "20260715-151202-gameseal").mkdir(parents=True)

    def test_known_run_resolves(self):
        path = safe_run_dir(self.runs, "20260715-151202-gameseal")
        self.assertEqual(path.name, "20260715-151202-gameseal")

    def test_underscore_run_ids_allowed(self):
        (self.runs / "2026-07-13_152243_g2a").mkdir()
        self.assertTrue(safe_run_dir(self.runs, "2026-07-13_152243_g2a").is_dir())

    def test_traversal_rejected(self):
        for bad in ("../x", "a/b", "..", ".", ".hidden", "/etc", "a\\b", "", "x" * 200):
            with self.assertRaises(RunAccessError, msg=bad):
                safe_run_dir(self.runs, bad)

    def test_unknown_run_rejected(self):
        with self.assertRaises(RunAccessError):
            safe_run_dir(self.runs, "20990101-000000-nope")

    def test_file_outside_whitelist_rejected(self):
        run = safe_run_dir(self.runs, "20260715-151202-gameseal")
        for bad in ("raw.json", ".env", "../../.env", "candidates.json.bak"):
            with self.assertRaises(RunAccessError, msg=bad):
                run_file(run, bad)


class DeriveMerchantStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.run = Path(self.tmp.name) / "runs" / "r1"
        self.run.mkdir(parents=True)

    def _write_offers(self, payload):
        (self.run / "offers.json").write_text(json.dumps(payload), encoding="utf-8")

    def test_unique_store_id(self):
        self._write_offers(_offers())
        self.assertEqual(derive_merchant_store(self.run), ("GameSeal", "126"))

    def test_missing_offers_rejected(self):
        with self.assertRaises(RunAccessError):
            derive_merchant_store(self.run)

    def test_ambiguous_store_id_rejected(self):
        self._write_offers(_offers(store_ids=("126", "127")))
        with self.assertRaises(RunAccessError):
            derive_merchant_store(self.run)

    def test_no_store_id_rejected(self):
        self._write_offers(_offers(store_ids=()))
        with self.assertRaises(RunAccessError):
            derive_merchant_store(self.run)

    def test_missing_merchant_rejected(self):
        payload = _offers()
        del payload["merchant"]
        self._write_offers(payload)
        with self.assertRaises(RunAccessError):
            derive_merchant_store(self.run)


class CatalogOptionsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.run = Path(self.tmp.name) / "runs" / "r1"
        self.run.mkdir(parents=True)

    def test_absent_catalog_is_none(self):
        self.assertIsNone(load_catalog_options(self.run))

    def test_not_ok_catalog_is_none(self):
        payload = _catalog()
        payload["ok"] = False
        (self.run / "session_catalog.json").write_text(json.dumps(payload), encoding="utf-8")
        self.assertIsNone(load_catalog_options(self.run))

    def test_options_extracted(self):
        (self.run / "session_catalog.json").write_text(json.dumps(_catalog()), encoding="utf-8")
        options = load_catalog_options(self.run)
        self.assertEqual([o["key"] for o in options["regions"]], ["1", "2"])
        self.assertEqual(options["editions"][1], {"key": "16", "text": "DLC"})


class ListAndDetailTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.runs = Path(self.tmp.name) / "runs"
        self.run = self.runs / "20260715-151202-gameseal"
        self.run.mkdir(parents=True)
        (self.run / "offers.json").write_text(json.dumps(_offers()), encoding="utf-8")
        (self.run / "candidates.json").write_text(json.dumps([{"x": 1}, {"x": 2}]), encoding="utf-8")
        (self.run / "validation.json").write_text(
            json.dumps({"run_id": "20260715-151202-gameseal", "validated_by": "Romain"}),
            encoding="utf-8",
        )
        (self.run / "approved.json").write_text(json.dumps([{"x": 1}]), encoding="utf-8")

    def test_files_in_runs_dir_ignored(self):
        (self.runs / "error-20260714-kinguin.md").write_text("x", encoding="utf-8")
        self.assertEqual(len(list_runs(self.runs)), 1)

    def test_stage_status(self):
        run = list_runs(self.runs)[0]
        self.assertEqual(run["merchant"], "GameSeal")
        stages = run["stages"]
        self.assertTrue(stages["extracted"])
        self.assertTrue(stages["matched"])
        self.assertEqual(stages["candidates_count"], 2)
        self.assertTrue(stages["validated"])
        self.assertEqual(stages["validated_by"], "Romain")
        self.assertEqual(stages["approved_count"], 1)
        self.assertIsNone(stages["submit"])

    def test_dry_run_vs_submit_detection(self):
        (self.run / "submit_plan.json").write_text(
            json.dumps({"created": None, "write_attempts": None, "plan": []}), encoding="utf-8"
        )
        self.assertTrue(list_runs(self.runs)[0]["stages"]["submit"]["dry_run"])
        (self.run / "submit_plan.json").write_text(
            json.dumps({"created": 12, "write_attempts": 12, "plan": [{}]}), encoding="utf-8"
        )
        summary = list_runs(self.runs)[0]["stages"]["submit"]
        self.assertFalse(summary["dry_run"])
        self.assertEqual(summary["created"], 12)

    def test_corrupt_artifact_surfaced_not_hidden(self):
        (self.run / "candidates.json").write_text("{broken", encoding="utf-8")
        runs = list_runs(self.runs)
        self.assertEqual(len(runs), 1)
        self.assertIn("error", runs[0]["stages"])

    def test_detail_shape(self):
        detail = run_detail(self.run)
        self.assertEqual(detail["store_id"], "126")
        self.assertIsNone(detail["store_id_error"])
        self.assertEqual(
            detail["candidates_sha256"], sha256_file(self.run / "candidates.json")
        )
        self.assertFalse(detail["catalog"]["present"])
        self.assertIn("approved.json", detail["files"])
        self.assertNotIn("raw.json", detail["files"])

    def test_detail_reports_store_error(self):
        (self.run / "offers.json").write_text(
            json.dumps(_offers(store_ids=("126", "127"))), encoding="utf-8"
        )
        detail = run_detail(self.run)
        self.assertIsNone(detail["store_id"])
        self.assertIn("store_id", detail["store_id_error"])


class ReadHelpersTests(unittest.TestCase):
    def test_read_run_json_absent_is_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(read_run_json(Path(tmp), "approved.json"))

    def test_sha256_absent_is_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(sha256_file(Path(tmp) / "nope"))


if __name__ == "__main__":
    unittest.main()

"""Sweep-scoped catalog cache of scripts/05_submit.py (Romain GO 2026-09-10): one live
region/edition catalog fetch per sweep instead of one per page."""
import importlib.util
import json
import tempfile
import time
import unittest
from pathlib import Path


def _load():
    spec = importlib.util.spec_from_file_location(
        "m05_cache", str(Path(__file__).resolve().parents[1] / "scripts" / "05_submit.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class CatalogCacheTests(unittest.TestCase):
    def setUp(self):
        self.MOD = _load()
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.path = str(Path(self.tmp.name) / "catalog.json")
        self.catalog = {"ok": True, "offer_id": "1", "regions": {"ok": True}, "editions": {"ok": True}}

    def test_round_trip_same_store_fresh(self):
        self.MOD._write_catalog_cache(self.path, self.catalog, "12")
        loaded = self.MOD._load_catalog_cache(self.path, "12")
        self.assertIsNotNone(loaded); self.assertTrue(loaded["ok"]); self.assertEqual(loaded["offer_id"], "1")

    def test_other_store_or_stale_or_not_ok_is_a_miss(self):
        self.MOD._write_catalog_cache(self.path, self.catalog, "12")
        self.assertIsNone(self.MOD._load_catalog_cache(self.path, "58"))          # other store
        data = json.loads(Path(self.path).read_text()); data["cache_fetched_at"] = time.time() - 3 * 3600
        Path(self.path).write_text(json.dumps(data))
        self.assertIsNone(self.MOD._load_catalog_cache(self.path, "12"))          # stale (> 2 h)
        self.MOD._write_catalog_cache(self.path, {"ok": False, "reason": "x"}, "12")  # never cached
        self.assertIsNone(self.MOD._load_catalog_cache(self.path, "12"))
        self.assertIsNone(self.MOD._load_catalog_cache(None, "12"))               # no cache configured


if __name__ == "__main__":
    unittest.main()

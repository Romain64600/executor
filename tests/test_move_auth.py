import json
import tempfile
import unittest
from pathlib import Path

from src.mover import MOVER_VERSION
from src.move_auth import (
    batch_authorized,
    extraction_id,
    grant_from_canary,
    load_authorization,
)

SOURCE = "aks-merchant-feeds-9"
T = lambda: "T"  # noqa: E731


class MoveAuthTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.run = Path(self.tmp.name) / "run"
        self.run.mkdir()
        self._skipped("v1")

    def _skipped(self, tag):
        (self.run / "skipped.json").write_text(json.dumps(
            [{"offer": {"offer_id": "1", "name": tag, "url": "https://g2a/1"}, "reason": "x"}]
        ), encoding="utf-8")

    def _grant(self, *labels):
        entries = [{"target_list_label": l, "current_offer_id": "100", "url": "https://g2a/1"}
                   for l in labels]
        return grant_from_canary(self.run, store_id="38", source_feed_page=SOURCE,
                                 moved_entries=entries, clock=T)

    def _plan(self, *labels):
        return [{"target_list_label": l} for l in labels]

    def _authorized(self, plan, store="38", source=SOURCE):
        return batch_authorized(self.run, plan, store_id=store, source_feed_page=source)

    # ------------------------------------------------------------- grant
    def test_grant_records_scope_and_validated_lists(self):
        auth = self._grant("Softwares")
        self.assertEqual(auth["mover_version"], MOVER_VERSION)
        self.assertEqual(auth["store_id"], "38")
        self.assertEqual(auth["source_feed_page"], SOURCE)
        self.assertEqual(auth["authorized_target_lists"], ["Softwares"])
        self.assertEqual(auth["version"], 1)
        self.assertTrue(auth["extraction_id"])

    def test_second_canary_extends_and_bumps_version(self):
        self._grant("Softwares")
        auth = self._grant("Gift cards")
        self.assertEqual(auth["authorized_target_lists"], ["Gift cards", "Softwares"])
        self.assertEqual(auth["version"], 2)

    # ------------------------------------------------- batch_authorized
    def test_plan_covered_by_authorization(self):
        self._grant("Softwares")
        ok, why = self._authorized(self._plan("Softwares"))
        self.assertTrue(ok, why)

    def test_no_authorization_refused(self):
        ok, why = self._authorized(self._plan("Softwares"))
        self.assertFalse(ok)
        self.assertIn("aucune autorisation", why)

    def test_unvalidated_target_list_refused(self):
        self._grant("Softwares")
        ok, why = self._authorized(self._plan("Softwares", "Blacklist"))
        self.assertFalse(ok)
        self.assertIn("Blacklist", why)

    def test_store_mismatch_refused(self):
        self._grant("Softwares")
        ok, why = self._authorized(self._plan("Softwares"), store="99")
        self.assertFalse(ok)
        self.assertIn("store_id", why)

    def test_source_mismatch_refused(self):
        self._grant("Softwares")
        ok, why = self._authorized(self._plan("Softwares"), source="aks-merchant-feeds-30")
        self.assertFalse(ok)
        self.assertIn("source_feed_page", why)

    def test_extraction_change_invalidates_authorization(self):
        # RV3: a re-match rewrites skipped.json → the authorization no longer covers
        self._grant("Softwares")
        self._skipped("v2-rematched")
        ok, why = self._authorized(self._plan("Softwares"))
        self.assertFalse(ok)
        self.assertIn("extraction_id", why)

    def test_stale_mover_version_invalidates(self):
        # an authorization from an older move mechanism must not cover a batch
        self._grant("Softwares")
        auth = load_authorization(self.run)
        auth["mover_version"] = "0"  # pretend granted by an older mover
        (self.run / "move_authorization.json").write_text(json.dumps(auth), encoding="utf-8")
        ok, why = self._authorized(self._plan("Softwares"))
        self.assertFalse(ok)
        self.assertIn("mover_version", why)

    def test_scope_change_resets_authorized_lists(self):
        self._grant("Softwares")
        self._skipped("v2")  # extraction changes → next grant resets
        auth = self._grant("Gift cards")
        self.assertEqual(auth["authorized_target_lists"], ["Gift cards"])  # Softwares dropped
        self.assertEqual(auth["version"], 1)


if __name__ == "__main__":
    unittest.main()

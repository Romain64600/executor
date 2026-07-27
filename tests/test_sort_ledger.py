import tempfile
import unittest
from pathlib import Path

from src import sort_ledger
from src.submitter import _url_key


class SortLedgerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def _rec(self, *entries):
        return sort_ledger.record(self.root, list(entries), clock=lambda: "T")

    def test_empty_when_absent(self):
        self.assertEqual(sort_ledger.load(self.root), {})
        self.assertEqual(sort_ledger.resolved_keys({}), set())

    def test_resolved_statuses_only(self):
        self._rec(
            {"url": "https://m/moved", "offer_id": "1", "list_id": "8", "status": "moved"},
            {"url": "https://m/gone", "offer_id": "2", "list_id": "8", "status": "already_gone"},
            {"url": "https://m/blocked", "offer_id": "3", "list_id": "8", "status": "identity_blocked"},
            {"url": "https://m/dud", "offer_id": "4", "list_id": "8", "status": "apply_not_confirmed"},
            {"url": "https://m/other", "offer_id": "5", "list_id": "8", "status": "weird"},
        )
        rk = sort_ledger.resolved_keys(sort_ledger.load(self.root))
        for slug in ("moved", "gone", "blocked", "dud"):
            self.assertIn(_url_key(f"https://m/{slug}"), rk)
        self.assertNotIn(_url_key("https://m/other"), rk)  # non-resolved status

    def test_keyed_by_url_ignores_id_and_no_url(self):
        self._rec({"url": "https://m/x", "offer_id": "99", "status": "moved"},
                  {"url": "", "offer_id": "no-url", "status": "moved"})
        ledger = sort_ledger.load(self.root)
        self.assertIn(_url_key("https://m/x"), ledger)
        self.assertEqual(len(ledger), 1)  # the URL-less entry is dropped

    def test_persists_and_counts_tries(self):
        self._rec({"url": "https://m/x", "offer_id": "1", "status": "apply_not_confirmed"})
        self._rec({"url": "https://m/x", "offer_id": "1", "status": "moved"})  # retried, then moved
        entry = sort_ledger.load(self.root)[_url_key("https://m/x")]
        self.assertEqual(entry["status"], "moved")
        self.assertEqual(entry["tries"], 2)
        self.assertTrue((self.root / "state" / "sort_ledger.json").is_file())


if __name__ == "__main__":
    unittest.main()

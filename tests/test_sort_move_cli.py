"""CLI-level tests for scripts/09_sort_move.py — the fail-closed gates that fire
BEFORE any browser/invariant work (empty list, batch flag + authorization). The
browser_lock in main() is bypassed by calling _main(); build_report is mocked so
nothing touches CDP or the network.
"""

import contextlib
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]


def _load_cli():
    spec = importlib.util.spec_from_file_location(
        "sort_move_cli_under_test", ROOT / "scripts" / "09_sort_move.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MOD = _load_cli()
RED = {"ok": False, "authoritative": False, "checks": []}

SORT_PLAN = {
    "run_id": "20260723-sort",
    "by_list": {
        "8": {"list_id": "8", "label": "Blacklist", "count": 2, "offers": [
            {"offer_id": "a1", "store_id": "38", "name": "Random Game Key", "url": "https://g2a/a1"},
            {"offer_id": "a2", "store_id": "51", "name": "GAMIVO Random", "url": "https://gamivo/a2"},
        ]},
    },
}
RAW = {"store_id": "", "source_url": "https://x/admin.php?available=all&page=aks-merchant-feeds-9"}


class SortMoveCliGateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.run = Path(self.tmp.name) / "20260723-142634-sort-full"
        self.run.mkdir()
        (self.run / "sort_plan.json").write_text(json.dumps(SORT_PLAN), encoding="utf-8")
        (self.run / "raw.json").write_text(json.dumps(RAW), encoding="utf-8")

    def _run_cli(self, *argv):
        out = io.StringIO()
        with mock.patch.object(MOD, "build_report", return_value=RED), \
                mock.patch("sys.argv", ["09_sort_move.py", str(self.run), *argv]), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            code = MOD._main()
        return code, out.getvalue()

    def _grant(self, *labels):
        from src.move_auth import grant_from_sort_canary
        grant_from_sort_canary(
            self.run, source_feed_page="aks-merchant-feeds-9",
            moved_entries=[{"target_list_label": lbl, "url": "u", "store_id": "38"} for lbl in labels],
            clock=lambda: "T")

    def test_empty_list_exits_clean(self):
        code, out = self._run_cli("--list", "999")   # no offers for this list
        self.assertEqual(code, 0)
        self.assertIn("aucune offre", out)

    def test_batch_safe_refused_without_flag(self):
        code, out = self._run_cli("--list", "8", "--execute", "--mode", "safe")
        self.assertEqual(code, 2)
        self.assertIn("i-authorize-batch", out)

    def test_batch_safe_refused_with_flag_but_no_authorization(self):
        code, out = self._run_cli("--list", "8", "--execute", "--mode", "safe", "--i-authorize-batch")
        self.assertEqual(code, 2)
        self.assertIn("autorisation", out)

    def test_batch_safe_refused_for_unvalidated_list(self):
        self._grant("Gift cards")   # authorized a different label
        code, out = self._run_cli("--list", "8", "--execute", "--mode", "safe", "--i-authorize-batch")
        self.assertEqual(code, 2)
        self.assertIn("Blacklist", out)

    def test_batch_safe_passes_gate_with_flag_and_authorization(self):
        self._grant("Blacklist")
        code, out = self._run_cli("--list", "8", "--execute", "--mode", "safe", "--i-authorize-batch")
        self.assertEqual(code, 2)                       # stops at mocked RED invariants
        self.assertNotIn("i-authorize-batch", out)      # NOT blocked by the batch gate
        self.assertIn("invariants", out)

    def test_learning_canary_reaches_invariants_gate(self):
        code, out = self._run_cli("--list", "8", "--execute", "--mode", "learning")
        self.assertEqual(code, 2)
        self.assertIn("invariants", out)

    def test_canary_limit_cannot_be_widened(self):
        code, out = self._run_cli("--list", "8", "--execute", "--mode", "learning", "--limit", "5")
        self.assertEqual(code, 2)
        self.assertIn("canary", out)

    def test_dry_run_reaches_invariants_gate(self):
        code, out = self._run_cli("--list", "8")        # dry-run default
        self.assertEqual(code, 2)
        self.assertIn("invariants", out)


if __name__ == "__main__":
    unittest.main()

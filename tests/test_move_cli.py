"""CLI-level tests for scripts/06_move.py — the fail-closed gates that fire
BEFORE any browser/invariant work (plan-empty, MV6 first-move canary, MV10
override reconciliation). main()'s browser_lock is bypassed by calling _main()
directly; build_report is mocked so nothing touches CDP or the network.
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
        "move_cli_under_test", ROOT / "scripts" / "06_move.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MOD = _load_cli()
RED = {"ok": False, "authoritative": False, "checks": []}


class MoveCliGateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.run = Path(self.tmp.name) / "20260721-090509-g2a"
        self.run.mkdir()
        (self.run / "raw.json").write_text(json.dumps({
            "store_id": "38",
            "source_url": "https://x/admin.php?available=all&store=38&page=aks-merchant-feeds-9&p=1",
        }), encoding="utf-8")
        (self.run / "skipped.json").write_text(json.dumps([
            {"offer": {"offer_id": "1", "name": "PdfGrabber", "url": "https://g2a/1"},
             "reason": "skip category: SOFTWARE"},
        ]), encoding="utf-8")

    def _learning(self, ann):
        (self.run / "learning.json").write_text(json.dumps(
            {"run_id": self.run.name, "annotations": ann}), encoding="utf-8")

    def _run_cli(self, *argv):
        out = io.StringIO()
        with mock.patch.object(MOD, "build_report", return_value=RED), \
                mock.patch("sys.argv", ["06_move.py", str(self.run), *argv]), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            code = MOD._main()
        return code, out.getvalue()

    def test_empty_plan_exits_clean(self):
        # no learning.json → nothing confirmed → exit 0, never touches invariants
        code, out = self._run_cli("--store-id", "38")
        self.assertEqual(code, 0)
        self.assertIn("aucune disposition", out)

    def test_batch_safe_refused_without_flag(self):
        # Romain 2026-07-22: --execute --mode safe requires the explicit
        # --i-authorize-batch flag (in addition to a valid authorization).
        self._learning({"1": {"target_list_id": "16", "target_list_label": "Softwares"}})
        code, out = self._run_cli("--store-id", "38", "--execute", "--mode", "safe")
        self.assertEqual(code, 2)
        self.assertIn("i-authorize-batch", out)

    def test_batch_safe_refused_with_flag_but_no_authorization(self):
        # flag present but no canary authorization covers the plan → refused
        self._learning({"1": {"target_list_id": "16", "target_list_label": "Softwares"}})
        code, out = self._run_cli("--store-id", "38", "--execute", "--mode", "safe",
                                  "--i-authorize-batch")
        self.assertEqual(code, 2)
        self.assertIn("autorisation", out)
        self.assertIn("aucune autorisation", out)

    def test_batch_safe_passes_gate_with_flag_and_authorization(self):
        # flag + a valid authorization covering the plan → the batch gate passes;
        # the run then stops at the mocked RED invariants, NOT at the batch gate.
        from src.move_auth import grant_from_canary
        self._learning({"1": {"target_list_id": "16", "target_list_label": "Softwares"}})
        grant_from_canary(self.run, store_id="38", source_feed_page="aks-merchant-feeds-9",
                          moved_entries=[{"target_list_label": "Softwares",
                                          "current_offer_id": "1", "url": "https://g2a/1"}],
                          clock=lambda: "T")
        code, out = self._run_cli("--store-id", "38", "--execute", "--mode", "safe",
                                  "--i-authorize-batch")
        self.assertEqual(code, 2)                 # stops at mocked RED invariants
        self.assertNotIn("i-authorize-batch", out)  # NOT blocked by the batch gate
        self.assertIn("invariants", out)

    def test_batch_safe_refused_for_unvalidated_target_list(self):
        # authorization covers "Softwares" only; a plan targeting another list is refused
        self._learning({"1": {"target_list_id": "8", "target_list_label": "Blacklist"}})
        from src.move_auth import grant_from_canary
        grant_from_canary(self.run, store_id="38", source_feed_page="aks-merchant-feeds-9",
                          moved_entries=[{"target_list_label": "Softwares",
                                          "current_offer_id": "1", "url": "https://g2a/1"}],
                          clock=lambda: "T")
        code, out = self._run_cli("--store-id", "38", "--execute", "--mode", "safe",
                                  "--i-authorize-batch")
        self.assertEqual(code, 2)
        self.assertIn("Blacklist", out)

    def test_learning_mode_passes_mv6_then_hits_invariants(self):
        # --mode learning is NOT blocked by MV6; it proceeds to the (mocked RED)
        # invariants gate and aborts there instead
        self._learning({"1": {"target_list_id": "16", "target_list_label": "Softwares"}})
        code, out = self._run_cli("--store-id", "38", "--execute", "--mode", "learning")
        self.assertEqual(code, 2)
        self.assertNotIn("1er move", out)
        self.assertIn("invariants", out)

    def test_store_id_override_mismatch_refused(self):
        # MV10: --store-id contradicting raw.json → fail-closed before invariants
        self._learning({"1": {"target_list_id": "16", "target_list_label": "Softwares"}})
        code, out = self._run_cli("--store-id", "99", "--execute", "--mode", "learning")
        self.assertEqual(code, 2)
        self.assertIn("store du run (38)", out)
        self.assertIn("MV10", out)

    def test_dry_run_safe_is_allowed(self):
        # MV6 only guards --execute; a dry-run (default) of the full plan is fine
        self._learning({"1": {"target_list_id": "16", "target_list_label": "Softwares"}})
        code, out = self._run_cli("--store-id", "38", "--mode", "safe")
        self.assertEqual(code, 2)          # stops at the mocked RED invariants
        self.assertNotIn("1er move", out)  # never hit the MV6 guard (write=False)
        self.assertIn("invariants", out)


if __name__ == "__main__":
    unittest.main()

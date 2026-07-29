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
GREEN = {"ok": True, "authoritative": True, "checks": []}


class _FakeMover:
    def __init__(self, *a, **k):
        pass

    def run(self, **k):
        return {
            "aborted": None, "stopped": "limit_reached", "moved": 1, "move_attempts": 1,
            "feed_offers": 1,
            "plan": [{"offer_id": "a1", "current_offer_id": "a1", "name": "Random Game Key",
                      "url": "https://g2a/a1", "store_id": "38", "moved": True, "ready": True,
                      "post_verify": "gone from source + present on target list",
                      "target_list_id": "8", "target_list_label": "Blacklist"}],
        }


class _FakeSession:
    def __init__(self, *a, **k):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

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

    def _grant(self, *labels, multi_item=False):
        from src.move_auth import grant_from_sort_canary
        grant_from_sort_canary(
            self.run, source_feed_page="aks-merchant-feeds-9",
            moved_entries=[{"target_list_label": lbl, "url": "u", "store_id": "38"} for lbl in labels],
            multi_item=multi_item, clock=lambda: "T")

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

    def test_batch_refused_without_multi_item_authorization(self):
        self._grant("Blacklist")  # unitary canary only
        code, out = self._run_cli("--list", "8", "--execute", "--mode", "safe",
                                  "--batch", "--i-authorize-batch")
        self.assertEqual(code, 2)
        self.assertIn("multi-item", out)                # blocked by the batch-auth gate

    def test_batch_passes_gate_with_multi_item_authorization(self):
        self._grant("Blacklist", multi_item=True)
        code, out = self._run_cli("--list", "8", "--execute", "--mode", "safe",
                                  "--batch", "--i-authorize-batch")
        self.assertEqual(code, 2)                        # stops at mocked RED invariants
        self.assertNotIn("multi-item", out)             # NOT blocked by the multi-item gate
        self.assertIn("invariants", out)

    def test_batched_canary_needs_at_least_two(self):
        code, out = self._run_cli("--list", "8", "--execute", "--mode", "learning",
                                  "--batch", "--limit", "1")
        self.assertEqual(code, 2)
        self.assertIn("multi-item", out)

    def test_batched_canary_needs_explicit_limit(self):
        code, out = self._run_cli("--list", "8", "--execute", "--mode", "learning", "--batch")
        self.assertEqual(code, 2)
        self.assertIn("multi-item", out)

    def test_batched_canary_limit_capped(self):
        code, out = self._run_cli("--list", "8", "--execute", "--mode", "learning",
                                  "--batch", "--limit", "9")
        self.assertEqual(code, 2)
        self.assertIn("trop large", out)      # ASCII substring (json.dumps escapes accents)

    def _run_batched_canary(self, max_apply_items):
        """Run a --batch canary through a fake Mover reporting max_apply_items,
        so the REAL 09 seam (max_apply_items → grant → multi_item_proven) runs."""

        class _FakeMoverMI:
            def __init__(self, *a, **k):
                pass

            def run(self, **k):
                return {
                    "aborted": None, "stopped": "limit_reached", "moved": 1, "move_attempts": 1,
                    "feed_offers": 1, "max_apply_items": max_apply_items,
                    "plan": [{"offer_id": "a1", "current_offer_id": "a1", "name": "Random Game Key",
                              "url": "https://g2a/a1", "store_id": "38", "moved": True, "ready": True,
                              "post_verify": "gone from source + present on target list",
                              "target_list_id": "8", "target_list_label": "Blacklist"}],
                }

        out = io.StringIO()
        with mock.patch.object(MOD, "build_report", return_value=GREEN), \
                mock.patch.object(MOD, "Mover", _FakeMoverMI), \
                mock.patch.object(MOD, "WriteSubmitSession", _FakeSession), \
                mock.patch.object(MOD.sort_ledger, "record", lambda *a, **k: {}), \
                mock.patch.object(MOD.sort_ledger, "load", lambda r: {}), \
                mock.patch.object(MOD.sort_ledger, "resolved_keys", lambda led: set()), \
                mock.patch("sys.argv", ["09_sort_move.py", str(self.run), "--list", "8",
                                        "--execute", "--mode", "learning", "--batch", "--limit", "2"]), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            code = MOD._main()
        return code, out.getvalue()

    def test_seam_multiitem_apply_writes_proof_and_unlocks_batch(self):
        # End-to-end: a >=2-item Apply flows through 09's max_apply_items→grant
        # seam → multi_item_proven=True → a later --mode safe --batch passes.
        code, _ = self._run_batched_canary(max_apply_items=2)
        self.assertEqual(code, 0)
        auth = json.loads((self.run / "sort_move_authorization.json").read_text(encoding="utf-8"))
        self.assertTrue(auth["multi_item_proven"])
        code2, out2 = self._run_cli("--list", "8", "--execute", "--mode", "safe",
                                    "--batch", "--i-authorize-batch")
        self.assertEqual(code2, 2)                    # stops at mocked RED invariants
        self.assertNotIn("multi-item", out2)          # NOT blocked by the multi-item gate

    def test_seam_single_item_apply_never_unlocks_batch(self):
        # A --batch canary whose Apply carried only 1 item (max_apply_items=1)
        # must NOT forge the proof, and the safe batch stays refused.
        code, _ = self._run_batched_canary(max_apply_items=1)
        self.assertEqual(code, 0)
        auth = json.loads((self.run / "sort_move_authorization.json").read_text(encoding="utf-8"))
        self.assertFalse(auth["multi_item_proven"])
        code2, out2 = self._run_cli("--list", "8", "--execute", "--mode", "safe",
                                    "--batch", "--i-authorize-batch")
        self.assertEqual(code2, 2)
        self.assertIn("multi-item", out2)             # STILL blocked (no real proof)

    def test_canary_limit_cannot_be_widened(self):
        code, out = self._run_cli("--list", "8", "--execute", "--mode", "learning", "--limit", "5")
        self.assertEqual(code, 2)
        self.assertIn("canary", out)

    def test_deferred_requires_batch_safe(self):
        code, out = self._run_cli("--list", "8", "--execute", "--mode", "learning",
                                  "--batch", "--limit", "2", "--deferred")
        self.assertEqual(code, 2)
        self.assertIn("--deferred", out)

    def test_deferred_rejects_limit(self):
        # --deferred + --limit is contradictory (deferred = whole batch); the gate
        # must reject it, not silently ignore --deferred and fall back to per-group.
        code, out = self._run_cli("--list", "8", "--execute", "--mode", "safe",
                                  "--batch", "--i-authorize-batch", "--limit", "3", "--deferred")
        self.assertEqual(code, 2)
        self.assertIn("--limit", out)

    def test_dry_run_reaches_invariants_gate(self):
        code, out = self._run_cli("--list", "8")        # dry-run default
        self.assertEqual(code, 2)
        self.assertIn("invariants", out)

    def test_execute_finishes_without_crash_after_a_move(self):
        # regression (2026-07-28): _main's final display + ledger block must not
        # crash after a real move — a local `_status` once shadowed the module
        # `_status(entry, write)` and TypeError'd on exit.
        out = io.StringIO()
        with mock.patch.object(MOD, "build_report", return_value=GREEN), \
                mock.patch.object(MOD, "Mover", _FakeMover), \
                mock.patch.object(MOD, "WriteSubmitSession", _FakeSession), \
                mock.patch.object(MOD.sort_ledger, "record", lambda *a, **k: {}), \
                mock.patch.object(MOD.sort_ledger, "load", lambda r: {}), \
                mock.patch.object(MOD.sort_ledger, "resolved_keys", lambda led: set()), \
                mock.patch("sys.argv", ["09_sort_move.py", str(self.run), "--list", "8",
                                        "--execute", "--mode", "learning"]), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            code = MOD._main()
        self.assertEqual(code, 0)                 # ran to completion, no crash
        self.assertIn("MOVED", out.getvalue())    # the display path executed


class LedgerStatusTests(unittest.TestCase):
    """The resolved-offers ledger must record ONLY terminal outcomes — a transient
    miss left in would permanently skip a legitimate offer (the P1.6 deferred
    reflow regression)."""

    def test_terminal_outcomes_are_recorded(self):
        self.assertEqual(MOD._ledger_status({"moved": True}), "moved")
        self.assertEqual(MOD._ledger_status({"skipped": "already moved"}), "already_gone")
        # A true URL→different-product contradiction never self-heals → resolved.
        self.assertEqual(
            MOD._ledger_status({"identity_mismatch": True, "ready": False,
                                "blocker": "fresh-page identity mismatch (name) — NOT moving"}),
            "identity_blocked")

    def test_transient_misses_are_left_out_so_they_retry(self):
        # Each of these is recoverable on a later run — must NOT enter the ledger.
        for entry in (
            {"blocker": "row/bulk-form not present at move time", "ready": False},   # reflow churn
            {"blocker": "row id vanished from the page (re-import?) — URL not here either",
             "ready": False},                                                        # vanished this pass
            {"blocker": "bulk[item][] registration failed — nothing submitted", "ready": False},
            {"blocker": "Apply not clicked — move not submitted", "ready": False},
            {"moved": False, "ready": True, "post_verify": "feed/CDP error after Apply — "
             "offer state UNKNOWN, verify the move by hand"},                        # Bug 2 UNKNOWN
            {"moved": False, "ready": True,
             "post_verify": "STILL on source list after Apply — move NOT confirmed"},
        ):
            self.assertIsNone(MOD._ledger_status(entry),
                              f"{entry.get('blocker') or entry.get('post_verify')!r} must retry")


if __name__ == "__main__":
    unittest.main()

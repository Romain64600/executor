"""CLI seam for scripts/10_data_entry_auto.py — main() must build a valid
SweepConfig and drive run_sweep. Regression guard: a v2 engine rename left the
CLI passing a removed ``page_size`` kwarg, crashing every launch (the review had
flagged the real-stages/CLI wiring as untested)."""
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


def _load_cli():
    spec = importlib.util.spec_from_file_location(
        "m10_cli", str(Path(__file__).resolve().parents[1] / "scripts" / "10_data_entry_auto.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class CliSeamTests(unittest.TestCase):
    def setUp(self):
        self.MOD = _load_cli()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        # Redirect the sweep's run dir into the temp tree.
        self._orig_root = self.MOD.ROOT
        self.MOD.ROOT = Path(self.tmp.name)
        self.addCleanup(lambda: setattr(self.MOD, "ROOT", self._orig_root))

    def _run(self, argv, sweep_recap):
        captured = {}

        def fake_run_sweep(cfg, stages, *, on_page=lambda r: None, **kw):
            # This only runs if main() built a valid SweepConfig — the exact seam
            # that regressed. Also drive on_page with the LIVE recap so main()'s
            # persist() is exercised per page (a target whose recap is still None
            # must not crash persist — the 2026-08-05 None.get() regression).
            captured["cfg"] = cfg
            on_page(sweep_recap)          # live per-page persist
            on_page(sweep_recap)
            return sweep_recap

        with mock.patch.object(self.MOD, "run_sweep", side_effect=fake_run_sweep), \
                mock.patch.object(sys, "argv", ["10_data_entry_auto.py"] + argv):
            code = self.MOD.main()
        return code, captured

    def test_main_builds_config_and_persists_recap(self):
        recap = {"merchant": "Kinguin", "store_id": "58", "pages": [], "total_created": 3, "halted": None}
        code, captured = self._run(["--targets", "Kinguin:58", "--max-pages", "30", "--run-id", "t-auto"], recap)
        self.assertEqual(code, 0)
        # SweepConfig was built with the CLI's kwargs (no removed page_size).
        cfg = captured["cfg"]
        self.assertEqual((cfg.merchant, cfg.store_id, cfg.max_pages, cfg.start_page), ("Kinguin", "58", 30, 1))
        # recap.json persisted with the target's totals.
        rec = json.loads((self.MOD.ROOT / "runs" / "t-auto" / "recap.json").read_text())
        self.assertEqual(rec["total_created"], 3)
        self.assertEqual(rec["targets"][0]["merchant"], "Kinguin")

    def test_main_multi_target(self):
        # P2-2: stores must be the CANONICAL allowlist stores (Eneba is 19, not 70).
        recap = {"pages": [], "total_created": 1, "halted": None}
        code, _ = self._run(["--targets", "Kinguin:58,Eneba:19", "--run-id", "t2"], recap)
        self.assertEqual(code, 0)
        rec = json.loads((self.MOD.ROOT / "runs" / "t2" / "recap.json").read_text())
        self.assertEqual([t["merchant"] for t in rec["targets"]], ["Kinguin", "Eneba"])

    def test_main_rejects_bad_target(self):
        code, _ = self._run(["--targets", "Kinguin:abc", "--run-id", "t3"], {"pages": []})
        self.assertEqual(code, 2)   # non-numeric store id, fail-closed

    def test_main_rejects_non_allowlisted_merchant(self):
        # P2-2 (audit 2026-09-02): safe-auto writes without validation → the allowlist
        # is an authoritative gate enforced at the CLI, not only in the HTTP handler.
        # A parked/non-vetted merchant (Difmark:167) is refused before any write.
        code, captured = self._run(["--targets", "Difmark:167", "--run-id", "t-bad"], {"pages": []})
        self.assertEqual(code, 2)
        self.assertNotIn("cfg", captured)   # never built a sweep / opened a session

    def test_main_rejects_wrong_store_for_allowlisted_merchant(self):
        # A tampered/stale store for a vetted merchant is refused (canonical store).
        code, captured = self._run(["--targets", "Kinguin:99", "--run-id", "t-store"], {"pages": []})
        self.assertEqual(code, 2)
        self.assertNotIn("cfg", captured)

    def test_move_execute_without_triage_is_rejected(self):
        # audit (2026-08-14): --move-execute has no effect without --triage → fail loud
        code, captured = self._run(["--targets", "Kinguin:58", "--move-execute",
                                    "--run-id", "t4"], {"pages": []})
        self.assertEqual(code, 2)
        self.assertNotIn("cfg", captured)   # never reached run_sweep

    def test_move_execute_with_triage_is_accepted(self):
        code, captured = self._run(["--targets", "Kinguin:58", "--triage",
                                    "--move-execute", "--run-id", "t5"],
                                   {"pages": [], "total_created": 0})
        self.assertEqual(code, 0)
        self.assertIn("cfg", captured)


class TriageStageWiringTests(unittest.TestCase):
    """The --triage move stage: dry-run plans the routable skips (no browser), the
    match stage counts them; --triage off keeps the legacy ADD-only Stages."""

    def setUp(self):
        self.MOD = _load_cli()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self._orig_root = self.MOD.ROOT
        self.MOD.ROOT = Path(self.tmp.name)
        self.addCleanup(lambda: setattr(self.MOD, "ROOT", self._orig_root))

    def _run_dir(self, run_id, skipped):
        d = self.MOD.ROOT / "runs" / run_id
        d.mkdir(parents=True, exist_ok=True)
        (d / "skipped.json").write_text(json.dumps(skipped), encoding="utf-8")
        return d

    def test_triage_off_has_no_move_stage(self):
        stages = self.MOD._make_stages("Kinguin", "58", "all", None)
        self.assertIsNone(stages.move)

    def test_dry_run_submit_creates_nothing(self):
        run_id = "run-p1"
        d = self.MOD.ROOT / "runs" / run_id
        d.mkdir(parents=True, exist_ok=True)
        (d / "candidates.json").write_text(json.dumps(
            [{"offer": {"name": "Game A"}, "aks_product_id": "1"},
             {"offer": {"name": "Game B"}, "aks_product_id": "2"}]), encoding="utf-8")
        stages = self.MOD._make_stages("Kinguin", "58", "all", None, dry_run=True)
        out = stages.submit(run_id)
        self.assertTrue(out.clean())
        self.assertEqual(out.created, 0)               # nothing created
        self.assertEqual(len(out.offers), 2)           # 2 WOULD be created
        self.assertIn("dry-run", out.detail)

    def test_dry_run_forces_move_plan_only(self):
        # --dry-run must override --move-execute → move stays a plan (no 06_move)
        run_id = "run-p2"
        d = self.MOD.ROOT / "runs" / run_id
        d.mkdir(parents=True, exist_ok=True)
        (d / "skipped.json").write_text(json.dumps(
            [{"offer": {"offer_id": "1", "name": "X", "url": "https://k/1"},
              "reason": "forbidden region: BRAZIL"}]), encoding="utf-8")
        stages = self.MOD._make_stages("Kinguin", "58", "all", None,
                                       triage=True, move_execute=True, dry_run=True)
        mv = stages.move(run_id)
        self.assertEqual(mv.moved, 0)
        self.assertIn("dry-run", mv.detail)
        self.assertFalse((d / "learning.json").exists())   # no real-move synthesis

    def test_move_execute_no_stale_move_plan_double_count(self):
        # adversarial review 2026-08-17: if the BATCH aborts early (before writing
        # its own move_plan.json), _06move must NOT read the CANARY's stale
        # move_plan.json and double-count its moves. move() unlinks it first.
        run_id = "run-p1"
        d = self.MOD.ROOT / "runs" / run_id
        d.mkdir(parents=True, exist_ok=True)
        (d / "skipped.json").write_text(json.dumps([
            {"offer": {"offer_id": "1", "store_id": "58", "name": "A", "url": "https://k/1"},
             "reason": "skip category: GIFT CARD"},
            {"offer": {"offer_id": "2", "store_id": "58", "name": "B", "url": "https://k/2"},
             "reason": "skip category: GIFT CARD"},
        ]), encoding="utf-8")
        (d / "move_plan.json").write_text(json.dumps({"moved": 2}), encoding="utf-8")  # stale

        def fake_run_child(argv):
            mode = argv[argv.index("--mode") + 1]
            if mode == "learning":                      # canary: writes moved=2, ok
                (d / "move_plan.json").write_text(json.dumps({"moved": 2}), encoding="utf-8")
                return 0
            return 2                                     # safe batch: early abort, NO write

        with mock.patch.object(self.MOD, "_run_child", side_effect=fake_run_child):
            stages = self.MOD._make_stages("Kinguin", "58", "all", None,
                                           triage=True, move_execute=True)
            mv = stages.move(run_id)
        self.assertFalse(mv.clean())                    # batch aborted → halt
        self.assertEqual(mv.moved, 2)                   # canary 2, batch 0 — NOT 4

    def test_move_execute_all_gone_list_skips_not_halts(self):
        # Romain 2026-08-19: a list whose offers were ALL already relocated (parallel
        # operator) → the canary moves 0 with every entry an already-gone skip →
        # skip the list, don't halt the sweep.
        run_id = "run-p1"
        d = self.MOD.ROOT / "runs" / run_id
        d.mkdir(parents=True, exist_ok=True)
        (d / "skipped.json").write_text(json.dumps([
            {"offer": {"offer_id": "1", "store_id": "58", "name": "A", "url": "https://k/1"},
             "reason": "skip category: GIFT CARD"},
            {"offer": {"offer_id": "2", "store_id": "58", "name": "B", "url": "https://k/2"},
             "reason": "skip category: GIFT CARD"},
        ]), encoding="utf-8")

        def fake_run_child(argv):
            (d / "move_plan.json").write_text(json.dumps({"moved": 0, "plan": [
                {"offer_id": "1", "moved": False, "blocker": None,
                 "skipped": "not on source list (already moved?) — proven by full scan"},
                {"offer_id": "2", "moved": False, "blocker": None,
                 "skipped": "not on source list (already moved?) — proven by full scan"},
            ]}), encoding="utf-8")
            return 0

        with mock.patch.object(self.MOD, "_run_child", side_effect=fake_run_child):
            stages = self.MOD._make_stages("Kinguin", "58", "all", None,
                                           triage=True, move_execute=True)
            mv = stages.move(run_id)
        self.assertTrue(mv.clean())                     # skipped, did NOT halt
        self.assertEqual(mv.moved, 0)

    def test_triage_dry_run_plans_without_browser(self):
        run_id = "run-p3"
        d = self._run_dir(run_id, [
            {"offer": {"offer_id": "1", "store_id": "58", "name": "BF BR",
                       "url": "https://k/1"}, "reason": "forbidden region: BRAZIL"},
            {"offer": {"offer_id": "2", "store_id": "58", "name": "BF RU",
                       "url": "https://k/2"}, "reason": "forbidden region: RUSSIA"},
            {"offer": {"offer_id": "3", "store_id": "58", "name": "BF ROW",
                       "url": "https://k/3"}, "reason": "forbidden region: ROW"},
        ])
        stages = self.MOD._make_stages("Kinguin", "58", "all", None, triage=True)
        self.assertIsNotNone(stages.move)
        mv = stages.move(run_id)
        self.assertTrue(mv.clean())
        self.assertEqual(mv.moved, 0)                 # dry-run: nothing moved
        self.assertEqual(len(mv.offers), 2)           # BRAZIL + RUSSIA planned, ROW garder
        self.assertIn("dry-run", mv.detail)
        plan = json.loads((d / "triage_moves.json").read_text())
        self.assertEqual(plan["by_list"]["8"][0]["list_label"], "Blacklist")
        # no 06_move / learning.json in dry-run
        self.assertFalse((d / "learning.json").exists())


if __name__ == "__main__":
    unittest.main()

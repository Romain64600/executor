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
        recap = {"pages": [], "total_created": 1, "halted": None}
        code, _ = self._run(["--targets", "Kinguin:58,Eneba:70", "--run-id", "t2"], recap)
        self.assertEqual(code, 0)
        rec = json.loads((self.MOD.ROOT / "runs" / "t2" / "recap.json").read_text())
        self.assertEqual([t["merchant"] for t in rec["targets"]], ["Kinguin", "Eneba"])

    def test_main_rejects_bad_target(self):
        code, _ = self._run(["--targets", "Kinguin:abc", "--run-id", "t3"], {"pages": []})
        self.assertEqual(code, 2)   # non-numeric store id, fail-closed


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

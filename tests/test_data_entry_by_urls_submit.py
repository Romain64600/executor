"""Stage 12 — the by-urls SUBMIT orchestrator ("Saisir"). Unit-level: the triple
builder fails closed per-merchant (never crashes the batch). The end-to-end
per-merchant loop / halt discipline is covered by ByUrlsSubmitTests
(test_data_entry_auto.py); the real 05_submit path is exercised live, gated behind
the operator's typed GO.
"""
import importlib.util
import tempfile
import unittest
from pathlib import Path


def _load():
    spec = importlib.util.spec_from_file_location(
        "m12", str(Path(__file__).resolve().parents[1] / "scripts" / "12_data_entry_by_urls_submit.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


M = _load()


class _Log:
    def log(self, *a, **k):
        pass


def _cand(oid="1"):
    return {"offer": {"offer_id": oid, "name": "Game", "url": f"https://m/{oid}"},
            "aks_product_id": "205027", "aks_name": "X",
            "region": {"id": "2", "label": "GLOBAL"}, "edition": {"id": "1", "label": "Standard"}}


class SubmitMerchantTests(unittest.TestCase):
    def test_any_triple_error_is_per_merchant_non_clean_not_crash(self):
        # A non-ValidationIOError (e.g. OSError building the triple) must become a
        # per-merchant NON-CLEAN halt, never an uncaught orchestrator crash
        # (adversarial review 2026-08-25).
        orig = M.apply_overrides_and_validate

        def boom(*a, **k):
            raise OSError("disk full")
        M.apply_overrides_and_validate = boom
        self.addCleanup(lambda: setattr(M, "apply_overrides_and_validate", orig))

        sm = M._make_submit_merchant("all", _Log())
        with tempfile.TemporaryDirectory() as d:
            out = sm("G2A", "38", [_cand()], Path(d) / "sub")   # must NOT raise
        self.assertFalse(out.clean())
        self.assertIn("OSError", out.aborted or "")

    def test_main_reads_immutable_copy_not_mutated_source(self):
        # P1 (TOCTOU): with --from-recap-file, main() reads the manager's sha-bound
        # snapshot — NOT runs/<from-run>/recap.json, which a racing re-run may have
        # overwritten between the GO's sha check and this read.
        import json
        captured = {}

        def fake_run(from_recap, **k):
            captured["marker"] = from_recap.get("marker")
            captured["available"] = from_recap.get("available")
            return {"totals": {"created": 0, "attempted": 0, "merchants": 0}, "aborted": None}

        orig_run, orig_root = M.run_by_urls_submit, M.ROOT
        orig_install = M._RUNNER.install
        M.run_by_urls_submit = fake_run
        M._RUNNER.install = lambda: None       # don't clobber the test runner's signal handlers
        self.addCleanup(lambda: setattr(M, "run_by_urls_submit", orig_run))
        self.addCleanup(lambda: setattr(M, "ROOT", orig_root))
        self.addCleanup(lambda: setattr(M._RUNNER, "install", orig_install))

        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            M.ROOT = root
            src = root / "runs" / "20260825-000000-by-urls"
            src.mkdir(parents=True)
            (src / "recap.json").write_text(json.dumps(          # a poisoned/mutated source
                {"available": "pending", "marker": "SOURCE-MUTATED",
                 "games": [], "totals": {"candidates": 0}}), encoding="utf-8")
            copy = root / "runs" / "20260825-001-by-urls-submit" / "source_recap.json"
            copy.parent.mkdir(parents=True)
            copy.write_text(json.dumps(                          # the manager's bound snapshot
                {"available": "all", "marker": "BOUND",
                 "games": [], "totals": {"candidates": 1}}), encoding="utf-8")
            rc = M.main(["--from-run", "20260825-000000-by-urls", "--from-recap-file", str(copy),
                         "--run-id", "20260825-001-by-urls-submit"])
        self.assertEqual(rc, 0)
        self.assertEqual(captured["marker"], "BOUND")            # read the copy, not the source
        self.assertEqual(captured["available"], "all")

    def test_read_submit_plan_success_is_gone_only(self):
        with tempfile.TemporaryDirectory() as d:
            run = Path(d)
            import json
            (run / "submit_plan.json").write_text(json.dumps({"plan": [
                {"merchant_title": "A", "post_save": "gone from feed (available=all)"},
                {"merchant_title": "B", "post_save": "still present"},
            ]}), encoding="utf-8")
            out = M._read_submit_plan(run, 0)
        self.assertEqual(out.created, 1)          # only the "gone" one
        self.assertTrue(out.clean())


if __name__ == "__main__":
    unittest.main()

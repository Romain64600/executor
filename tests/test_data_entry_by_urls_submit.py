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

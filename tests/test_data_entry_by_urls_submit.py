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

    def test_read_submit_plan_uses_submitted_boolean_not_post_save_substring(self):
        # [13] (Fable re-audit 2026-09-06): per-offer created is 05_submit's deterministic
        # `submitted` boolean, NOT a "gone" substring of the human post_save text (which
        # may omit the word for a real creation, or contain it in "…not gone…").
        with tempfile.TemporaryDirectory() as d:
            run = Path(d)
            import json
            (run / "submit_plan.json").write_text(json.dumps({"plan": [
                {"merchant_title": "A", "submitted": True, "post_save": "gone from feed (available=all)"},
                {"merchant_title": "B", "submitted": False, "post_save": "still present"},
                # submitted but post_save phrasing omits the word "gone" → still counted
                {"merchant_title": "C", "submitted": True, "post_save": "offer left the refreshed feed"},
            ]}), encoding="utf-8")
            out = M._read_submit_plan(run, 0)
        self.assertEqual(out.created, 2)          # A and C by `submitted`, not B
        self.assertTrue(out.clean())

    def test_read_submit_plan_unreadable_after_exit0_is_not_clean(self):
        # [14] (Fable re-audit 2026-09-06): a missing/unreadable submit_plan.json after
        # exit 0 must NOT read as a clean merchant (mirror Safe-Auto P2-14) → the batch
        # halts fail-closed instead of crediting a merchant whose plan we couldn't read.
        with tempfile.TemporaryDirectory() as d:
            out = M._read_submit_plan(Path(d), 0)   # no submit_plan.json written
        self.assertFalse(out.clean())
        self.assertEqual(out.created, 0)


def _console_cand(oid="7"):
    """A 2-target console candidate exactly as the by-urls preview stores it (matcher
    Candidate.to_dict: targets[0] mirrors the primary fields, R45)."""
    return {"offer": {"offer_id": oid, "name": "Hades (PS4 / PS5)", "url": f"https://m/{oid}",
                      "merchant": "G2A", "store_id": "38"},
            "aks_product_id": "85104", "aks_url": "https://www.allkeyshop.com/blog/buy-hades-ps4-compare-prices/",
            "aks_name": "Hades PS4", "platform": "PS4",
            "region": {"label": "Playstation Game Code GLOBAL", "id": "88", "implicit": True},
            "edition": {"label": "Standard", "id": "1"},
            "targets": [
                {"platform": "PS4", "aks_product_id": "85104", "aks_url": "https://aks/ps4", "aks_name": "Hades PS4",
                 "region": {"label": "Playstation Game Code GLOBAL", "id": "88"}, "edition": {"label": "Standard", "id": "1"}},
                {"platform": "PS5", "aks_product_id": "85105", "aks_url": "https://aks/ps5", "aks_name": "Hades PS5",
                 "region": {"label": "PS5", "id": "88ps5h"}, "edition": {"label": "Standard", "id": "1"}},
            ]}


class ConsoleFlagTests(unittest.TestCase):
    """[R45] Romain 2026-09-15: the admin launcher passes --consoles / --no-consoles to
    the submit as well; accepted (default ON), informational only — 05_submit reads the
    targets from approved.json, no flag is forwarded."""

    def test_flags(self):
        p = M.build_parser()
        base = ["--from-run", "r", "--run-id", "s"]
        self.assertTrue(p.parse_args(base).consoles)
        self.assertTrue(p.parse_args(base + ["--consoles"]).consoles)
        self.assertFalse(p.parse_args(base + ["--no-consoles"]).consoles)


class MultiTargetWholeTests(unittest.TestCase):
    def test_submit_merchant_writes_the_candidate_whole_with_the_extended_fingerprint(self):
        # The triple carries the 2-target candidate AS IS (targets never split / trimmed)
        # and the approval decision is keyed on the R45 extended fingerprint; 05_submit
        # is spawned UNMODIFIED (no console flag — it reads the targets from approved.json).
        import json
        from src.validation import candidate_fingerprint
        captured = {}

        def fake_apply(sub_run, payload, repo_root=None, created_offer_ids=None):
            captured["payload"] = payload

        def fake_child(argv):
            captured["argv"] = argv
            (Path(argv[2]).parent / "submit_plan.json").write_text(json.dumps({"plan": [
                {"merchant_title": "Hades (PS4 / PS5)", "submitted": True, "post_save": "gone"}]}),
                encoding="utf-8")
            return 0

        orig_apply, orig_child = M.apply_overrides_and_validate, M._run_child
        M.apply_overrides_and_validate, M._run_child = fake_apply, fake_child
        self.addCleanup(lambda: setattr(M, "apply_overrides_and_validate", orig_apply))
        self.addCleanup(lambda: setattr(M, "_run_child", orig_child))

        cand = _console_cand()
        sm = M._make_submit_merchant("all", _Log())
        with tempfile.TemporaryDirectory() as d:
            sub = Path(d) / "sub"
            out = sm("G2A", "38", [cand], sub)
            written = json.loads((sub / "candidates.json").read_text(encoding="utf-8"))
        self.assertTrue(out.clean())
        self.assertEqual(out.created, 1)
        self.assertEqual(written, [cand])                                   # whole, untouched
        self.assertEqual([t["aks_product_id"] for t in written[0]["targets"]], ["85104", "85105"])
        fp = captured["payload"]["decisions"][0]["fingerprint"]
        self.assertEqual(fp, candidate_fingerprint(cand))
        self.assertEqual(fp, "7|85104|88|1|+85105:88ps5h:1")                # R45 extended formula
        self.assertNotIn("--consoles", captured["argv"])
        self.assertNotIn("--no-consoles", captured["argv"])
        self.assertIn("--mode", captured["argv"])

    def test_store_grouping_keeps_multi_target_candidates_whole(self):
        # run_by_urls_submit groups by store and hands each candidate dict through
        # untouched — a 2-target candidate reaches submit_merchant with both targets.
        seen = []

        def submit_merchant(merchant, store_id, candidates, sub_run):
            seen.append((merchant, store_id, candidates))
            return M.SubmitOutcome(ok=True, created=len(candidates))

        recap = {"available": "all", "consoles": True,
                 "games": [{"url": "https://www.allkeyshop.com/blog/buy-hades-ps5-compare-prices/",
                            "resolved": True, "aks_product_id": "85105", "page_kind": "ps5",
                            "search": {"truncated": False},
                            "merchants": [{"merchant": "G2A", "store_id": "38",
                                           "candidates": [_console_cand()], "skipped": []}]}],
                 "totals": {"games": 1, "resolved": 1, "candidates": 1}}
        with tempfile.TemporaryDirectory() as d:
            out = M.run_by_urls_submit(recap, available="all", submit_merchant=submit_merchant,
                                       make_sub_run=lambda sid: Path(d) / f"s{sid}")
        self.assertIsNone(out["aborted"])
        self.assertEqual(len(seen), 1)
        (_m, _s, cands) = seen[0]
        self.assertEqual(cands, [_console_cand()])
        self.assertEqual(len(cands[0]["targets"]), 2)


if __name__ == "__main__":
    unittest.main()

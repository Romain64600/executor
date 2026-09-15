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
    the submit as well; accepted (default ON). 05_submit reads the targets from
    approved.json, no flag is forwarded — but the flag IS checked against the preview
    (ConsolesModeRefusalTests / ConsolesModeMainTests, audit 2026-09-15)."""

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



# ---------------------------------------------------------------------------
# [R45] Audit 2026-09-15 (finding 2): the requested console mode must agree with the
# preview — checked by scripts/12 itself (the direct CLI launch has no admin manager
# guard in front of it), fail-closed BEFORE anything is prepared.
# ---------------------------------------------------------------------------

def _pc_target_cand(oid="3", platform="STEAM"):
    """A single-target PC candidate as a current preview stores it (targets[0] mirrors
    the primary fields)."""
    c = _cand(oid)
    c["platform"] = platform
    c["targets"] = [{"platform": platform, "aks_product_id": "205027", "aks_url": "https://aks/pc",
                     "aks_name": "X", "region": {"label": "GLOBAL", "id": "2"},
                     "edition": {"label": "Standard", "id": "1"}}]
    return c


def _switch_cand(oid="9"):
    """A SINGLE-target console candidate (lone declared Switch key, P1)."""
    return {"offer": {"offer_id": oid, "name": "Legend of Mana (Switch)", "url": f"https://m/{oid}"},
            "aks_product_id": "77001", "aks_name": "Legend of Mana Switch", "platform": "SWITCH",
            "region": {"label": "Nintendo GLOBAL", "id": "99"}, "edition": {"label": "Standard", "id": "1"},
            "targets": [{"platform": "SWITCH", "aks_product_id": "77001", "aks_url": "https://aks/switch",
                         "aks_name": "Legend of Mana Switch",
                         "region": {"label": "Nintendo GLOBAL", "id": "99"},
                         "edition": {"label": "Standard", "id": "1"}}]}


def _preview(candidates, stamp=...):
    """A finished by-urls preview recap with ONE resolved game / ONE merchant group.
    ``stamp``: the recap's ``consoles`` bool; Ellipsis = key absent (older preview)."""
    recap = {"available": "all",
             "games": [{"url": "https://www.allkeyshop.com/blog/buy-x-cd-key-compare-prices/",
                        "resolved": True, "aks_product_id": "205027", "aks_name": "X",
                        "search": {"truncated": False},
                        "merchants": [{"merchant": "G2A", "store_id": "38",
                                       "candidates": list(candidates), "skipped": []}]}],
             "totals": {"games": 1, "resolved": 1, "candidates": len(candidates)}}
    if stamp is not ...:
        recap["consoles"] = stamp
    return recap


class ConsolesModeRefusalTests(unittest.TestCase):
    """The pure decision (``consoles_mode_refusal``)."""

    def test_stamp_mismatch_both_directions(self):
        r = M.consoles_mode_refusal(_preview([_cand()], stamp=True), False)
        self.assertIsNotNone(r)
        self.assertTrue(r[0].startswith("consoles_mismatch:"), r[0])
        self.assertIn("mode consoles de l'aperçu (true = --consoles)", r[0])
        self.assertIn("mode demandé (false = --no-consoles)", r[0])
        self.assertIn("relancer l'aperçu ou le submit avec le même mode", r[0])
        r = M.consoles_mode_refusal(_preview([_cand()], stamp=False), True)
        self.assertIsNotNone(r)
        self.assertIn("(false = --no-consoles) ≠ mode demandé (true = --consoles)", r[0])

    def test_agreeing_stamp_is_accepted(self):
        self.assertIsNone(M.consoles_mode_refusal(_preview([_console_cand()], stamp=True), True))
        self.assertIsNone(M.consoles_mode_refusal(_preview([_cand(), _pc_target_cand()], stamp=False), False))

    def test_no_stamp_no_consoles_refuses_console_or_multi_target_candidates(self):
        # multi-target (PS4 / PS5) → refused, the offender named with its platforms
        r = M.consoles_mode_refusal(_preview([_cand(), _console_cand()]), False)
        self.assertIsNotNone(r)
        reason, offenders = r
        self.assertTrue(reason.startswith("consoles_mismatch:"), reason)
        self.assertIn("--no-consoles demandé", reason)
        self.assertIn("Hades (PS4 / PS5)", reason)
        self.assertIn("PS4, PS5", reason)
        self.assertIn("2 cible(s)", reason)
        self.assertEqual([o["offer_id"] for o in offenders], ["7"])   # the PC one is not listed
        self.assertEqual(offenders[0]["platforms"], ["PS4", "PS5"])
        self.assertEqual(offenders[0]["targets"], 2)
        # a SINGLE-target console key (lone Switch, P1) → refused too
        r = M.consoles_mode_refusal(_preview([_switch_cand()]), False)
        self.assertIsNotNone(r)
        self.assertEqual(r[1][0]["platforms"], ["SWITCH"])
        # a 2-target candidate with no console platform at all (defensive) → refused (>1 target)
        odd = _pc_target_cand("5")
        odd["targets"] = odd["targets"] + [dict(odd["targets"][0], aks_product_id="205028")]
        r = M.consoles_mode_refusal(_preview([odd]), False)
        self.assertIsNotNone(r)
        self.assertEqual(r[1][0]["platforms"], [])
        self.assertEqual(r[1][0]["targets"], 2)

    def test_no_stamp_pc_only_proceeds_and_consoles_mode_never_scans(self):
        self.assertIsNone(M.consoles_mode_refusal(_preview([_cand(), _pc_target_cand()]), False))
        # the scan only bites under --no-consoles: an un-stamped console preview under
        # --consoles (the default) proceeds
        self.assertIsNone(M.consoles_mode_refusal(_preview([_console_cand()]), True))

    def test_non_bool_stamp_is_not_a_stamp(self):
        # a non-bool value (string / null) is NOT compared — the candidate scan decides
        rec = _preview([_cand()], stamp="true")
        self.assertIsNone(M.consoles_mode_refusal(rec, False))
        rec = _preview([_console_cand()], stamp=None)
        self.assertIsNotNone(M.consoles_mode_refusal(rec, False))


class ConsolesModeMainTests(unittest.TestCase):
    """main(): a refusal exits 2 with NOTHING prepared (no sub-run, no triple, the
    orchestrator never called), recap.json aborted, the decision in the run JSONL."""

    def _launch(self, recap, flags):
        import json
        calls = []

        def fake_run(from_recap, **k):
            calls.append(from_recap)
            return {"totals": {"created": 0, "attempted": 0, "merchants": 0}, "aborted": None}

        orig_run, orig_root, orig_install = M.run_by_urls_submit, M.ROOT, M._RUNNER.install
        M.run_by_urls_submit = fake_run
        M._RUNNER.install = lambda: None
        self.addCleanup(lambda: setattr(M, "run_by_urls_submit", orig_run))
        self.addCleanup(lambda: setattr(M, "ROOT", orig_root))
        self.addCleanup(lambda: setattr(M._RUNNER, "install", orig_install))
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            M.ROOT = root
            copy = root / "runs" / "S" / "source_recap.json"
            copy.parent.mkdir(parents=True)
            copy.write_text(json.dumps(recap, ensure_ascii=False), encoding="utf-8")
            rc = M.main(["--from-run", "P", "--from-recap-file", str(copy), "--run-id", "S"] + flags)
            out = root / "runs" / "S" / "recap.json"
            out_recap = json.loads(out.read_text(encoding="utf-8")) if out.exists() else None
            events = [json.loads(line) for line in
                      (root / "logs" / "S.jsonl").read_text(encoding="utf-8").splitlines()]
            prepared = sorted(str(p.relative_to(root)) for p in root.rglob("*")
                              if p.name in ("candidates.json", "approved.json", "offers.json",
                                            "match_meta.json") or p.name.startswith("S-s"))
        return rc, calls, out_recap, events, prepared

    def _assert_refused(self, rc, calls, out_recap, events, prepared):
        self.assertEqual(rc, 2)
        self.assertEqual(calls, [])                       # orchestrator never entered
        self.assertEqual(prepared, [])                    # no sub-run, no triple
        self.assertTrue(out_recap["aborted"].startswith("consoles_mismatch"), out_recap["aborted"])
        self.assertEqual(out_recap["mode"], "submit")
        self.assertEqual(out_recap["merchants"], [])
        self.assertEqual(out_recap["totals"], {"merchants": 0, "attempted": 0, "created": 0})
        aborted = [e for e in events if e["event"] == "submit_run_aborted"]
        self.assertEqual(len(aborted), 1)
        self.assertTrue(aborted[0]["reason"].startswith("consoles_mismatch"))
        self.assertIn("offenders", aborted[0])
        return aborted[0]

    def test_stamp_true_but_no_consoles_requested_is_refused(self):
        res = self._launch(_preview([_cand()], stamp=True), ["--no-consoles"])
        ev = self._assert_refused(*res)
        self.assertIs(ev["consoles"], False)
        self.assertIs(ev["preview_consoles"], True)
        self.assertEqual(ev["offenders"], [])

    def test_stamp_false_but_consoles_requested_is_refused(self):
        for flags in ([], ["--consoles"]):                # default AND explicit
            res = self._launch(_preview([_cand()], stamp=False), flags)
            ev = self._assert_refused(*res)
            self.assertIs(ev["consoles"], True)
            self.assertIs(ev["preview_consoles"], False)

    def test_agreeing_stamp_proceeds(self):
        rc, calls, _out, events, _p = self._launch(_preview([_console_cand()], stamp=True), ["--consoles"])
        self.assertEqual(rc, 0)
        self.assertEqual(len(calls), 1)
        self.assertEqual([e["event"] for e in events if e["event"] == "submit_run_aborted"], [])
        rc, calls, _out, events, _p = self._launch(_preview([_cand(), _pc_target_cand()], stamp=False),
                                                   ["--no-consoles"])
        self.assertEqual(rc, 0)
        self.assertEqual(len(calls), 1)

    def test_no_stamp_no_consoles_console_or_multi_target_candidate_is_refused(self):
        res = self._launch(_preview([_cand(), _console_cand()]), ["--no-consoles"])
        ev = self._assert_refused(*res)
        self.assertIsNone(ev["preview_consoles"])
        self.assertEqual([o["offer_id"] for o in ev["offenders"]], ["7"])
        self.assertIn("Hades (PS4 / PS5)", res[2]["aborted"])
        res = self._launch(_preview([_switch_cand()]), ["--no-consoles"])
        ev = self._assert_refused(*res)
        self.assertEqual(ev["offenders"][0]["platforms"], ["SWITCH"])

    def test_no_stamp_pc_only_candidates_proceed_under_no_consoles(self):
        rc, calls, _out, _ev, prepared = self._launch(_preview([_cand(), _pc_target_cand()]), ["--no-consoles"])
        self.assertEqual(rc, 0)
        self.assertEqual(len(calls), 1)


class UrlsPreviewTargetsTests(unittest.TestCase):
    """[R45] Audit 2026-09-15 (finding 1): the by-urls web preview renders EVERY target
    of a candidate (class ``target-row``) and the Saisir confirmation lists them with the
    total (« N offres sur T pages »). A static-text check (no JS engine on the box); the
    admin app serves these files verbatim (``/games`` → urls.html, ``/urls.js``)."""

    STATIC = Path(__file__).resolve().parents[1] / "src" / "admin" / "static"

    def test_urls_js_renders_every_target(self):
        js = (self.STATIC / "urls.js").read_text(encoding="utf-8")
        self.assertIn('"off ok target-row"', js)            # preview rows, one per target
        self.assertIn('"logline ok target-row"', js)        # confirm-modal lines, one per target
        self.assertIn("function candTargets", js)
        self.assertIn("function fmtTarget", js)
        self.assertIn('" · page "', js)                     # « <platform> · page <id> (<name>) · … »
        self.assertIn('"region_label"', js)                 # flat shape tolerated
        self.assertIn('"edition_label"', js)
        self.assertIn("#confirm-targets", js)
        self.assertIn("#confirm-t", js)
        self.assertIn('"page(s) cible(s) à écrire"', js)   # the preview KPI
        # Romain 2026-09-15 « aligner le récapitulatif sur le lot réellement soumis »: the
        # counts / confirm list come from the batch as scripts/12 builds it — per store,
        # one candidate per fingerprint (the candidate's own key, else the contract formula).
        self.assertIn("function submitBatch", js)
        self.assertIn("function candFingerprint", js)
        self.assertIn("function batchCounts", js)
        self.assertIn("c.fingerprint", js)
        self.assertIn('"|+"', js)                           # the R45 extra-targets suffix
        self.assertIn('"offres à saisir (lot)"', js)
        self.assertIn("batchCounts(submitBatch(rec))", js)  # KPIs + Saisir button
        self.assertIn("submitBatch(RECAP_DATA)", js)        # the GO summary

    def test_urls_html_confirm_modal_carries_the_target_list(self):
        html = (self.STATIC / "urls.html").read_text(encoding="utf-8")
        self.assertIn('id="confirm-targets"', html)
        self.assertIn('id="confirm-t"', html)
        self.assertLess(html.index('id="confirm-targets"'), html.index('id="confirm-go"'))  # before the GO field



# ---------------------------------------------------------------------------
# Romain 2026-09-15 « aligner le récapitulatif sur le lot réellement soumis »: a pure-
# Python port of urls.js submitBatch / candFingerprint, checked against the engine
# (src.data_entry_auto._candidates_by_store) — same key (store_id + FULL fingerprint,
# the engine's _seen set lives per store group), same drops (unresolved / errored game,
# merchant group without store_id), same order.
# ---------------------------------------------------------------------------

def _js_cand_fingerprint(c):
    """Port of urls.js candFingerprint: the candidate's own ``fingerprint`` key, else
    candidate_contract's formula (offer_id|aks_product_id|region_id|edition_id, plus
    "|+pid:rid:eid,…" over the extra targets)."""
    fp = c.get("fingerprint")
    if isinstance(fp, str) and fp:
        return fp

    def s(v):
        return "" if v is None else str(v)
    o = c.get("offer") or {}
    reg = c.get("region") if isinstance(c.get("region"), dict) else {"id": c.get("region_id")}
    ed = c.get("edition") if isinstance(c.get("edition"), dict) else {"id": c.get("edition_id")}
    primary = "|".join(s(v) for v in (o.get("offer_id"), c.get("aks_product_id"), reg.get("id"), ed.get("id")))
    raw = c.get("targets") if isinstance(c.get("targets"), list) else []
    if len(raw) <= 1:
        return primary
    extra = ",".join(":".join(s(v) for v in (t.get("aks_product_id"), (t.get("region") or {}).get("id"),
                                                (t.get("edition") or {}).get("id"))) for t in raw[1:])
    return primary + "|+" + extra


def _js_submit_batch(recap):
    """Port of urls.js submitBatch (rows keep the candidate dict for the comparison)."""
    order, groups = [], {}
    for g in recap.get("games") or []:
        if not g.get("resolved") or g.get("error"):
            continue
        for per in g.get("merchants") or []:
            sid = "" if per.get("store_id") is None else str(per.get("store_id"))
            if not sid:
                continue
            grp = groups.get(sid)
            if grp is None:
                grp = groups[sid] = {"merchant": per.get("merchant") or "", "store_id": sid,
                                     "rows": [], "seen": set()}
                order.append(sid)
            for c in per.get("candidates") or []:
                key = _js_cand_fingerprint(c)
                if key in grp["seen"]:
                    continue
                grp["seen"].add(key)
                grp["rows"].append(c)
    return [groups[sid] for sid in order if groups[sid]["rows"]]


def _js_counts(groups):
    offers = sum(len(g["rows"]) for g in groups)
    targets = sum(max(1, len(c.get("targets") or [])) for g in groups for c in g["rows"])
    return {"offers": offers, "targets": targets, "merchants": len(groups)}


def _game(url, pid, merchants, resolved=True, error=None):
    g = {"url": url, "resolved": resolved, "aks_product_id": pid, "aks_name": "X",
         "search": {"truncated": False}, "merchants": merchants}
    if error:
        g["error"] = error
    return g


def _grp(merchant, store_id, cands):
    g = {"merchant": merchant, "candidates": list(cands), "skipped": []}
    if store_id is not None:
        g["store_id"] = store_id
    return g


def _with_key(c):
    """As the matcher stores a preview candidate (to_dict): with its fingerprint key."""
    return dict(c, fingerprint=M.candidate_fingerprint(c))


class BatchMirrorTests(unittest.TestCase):
    def setUp(self):
        from src.data_entry_auto import _candidates_by_store
        self.engine = _candidates_by_store

    def _same(self, recap):
        got = [{"merchant": g["merchant"], "store_id": g["store_id"], "candidates": g["rows"]}
               for g in _js_submit_batch(recap)]
        self.assertEqual(got, self.engine(recap))
        return got

    def test_hades_ps4_ps5_double_search_is_one_offer_two_pages(self):
        # Two pasted URLs (Hades PS4 + Hades PS5); ONE G2A offer « Hades (PS4 / PS5) »
        # found by both searches, each occurrence carrying two targets. The naive count
        # said « 2 offres sur 4 pages »; the engine keeps ONE candidate → « 1 offre sur
        # 2 pages » — the summary must say the same.
        cand = _with_key(_console_cand("7"))
        recap = {"available": "all", "consoles": True,
                 "games": [_game("https://www.allkeyshop.com/blog/buy-hades-ps4-compare-prices/", "85104",
                                 [_grp("G2A", "38", [cand])]),
                           _game("https://www.allkeyshop.com/blog/buy-hades-ps5-compare-prices/", "85105",
                                 [_grp("G2A", "38", [cand])])],
                 "totals": {"games": 2, "resolved": 2, "candidates": 2}}
        naive_offers = sum(len(p["candidates"]) for g in recap["games"] for p in g["merchants"])
        naive_targets = sum(len(c["targets"]) for g in recap["games"] for p in g["merchants"] for c in p["candidates"])
        self.assertEqual((naive_offers, naive_targets), (2, 4))          # what the UI used to say
        groups = self._same(recap)
        self.assertEqual(len(groups), 1)
        self.assertEqual(len(groups[0]["candidates"]), 1)
        self.assertEqual(_js_counts(_js_submit_batch(recap)), {"offers": 1, "targets": 2, "merchants": 1})

    def test_key_is_store_id_plus_full_fingerprint(self):
        # Same fingerprint under TWO stores → both kept (engine and port agree: the seen
        # set is per store). Same offer with a DIFFERENT target set → a different full
        # fingerprint → both kept (the fingerprint encodes every target).
        a = _with_key(_console_cand("7"))
        b_other_targets = _console_cand("7")
        b_other_targets["targets"] = b_other_targets["targets"][:1]     # lone PS4 target
        b_other_targets = _with_key(b_other_targets)
        self.assertNotEqual(a["fingerprint"], b_other_targets["fingerprint"])
        recap = {"games": [_game("u1", "85104", [_grp("G2A", "38", [a]), _grp("Kinguin", "45", [a])]),
                           _game("u2", "85104", [_grp("G2A", "38", [b_other_targets, a])])],
                 "totals": {"games": 2, "resolved": 2, "candidates": 4}}
        groups = self._same(recap)
        self.assertEqual([(g["store_id"], len(g["candidates"])) for g in groups], [("38", 2), ("45", 1)])

    def test_port_matches_engine_on_a_mixed_fixture_without_fingerprint_keys(self):
        # No `fingerprint` key anywhere → the port's fallback formula must dedupe exactly
        # like candidate_fingerprint: a PC offer under two games (once), an unresolved
        # game and an errored game with candidates (dropped), a merchant group without
        # store_id (dropped), a second store (kept, in first-seen order).
        recap = {"games": [
            _game("u1", "205027", [_grp("G2A", "38", [_cand("1"), _console_cand("7")]),
                                   _grp("NoStore", None, [_cand("99")])]),
            _game("u-unresolved", None, [_grp("G2A", "38", [_cand("50")])], resolved=False),
            _game("u-error", "1", [_grp("G2A", "38", [_cand("51")])], error="aks_throttled"),
            _game("u2", "205027", [_grp("Kinguin", "45", [_cand("2")]),
                                   _grp("G2A", "38", [_cand("1"), _pc_target_cand("3"), _switch_cand("9")])]),
        ], "totals": {"games": 4, "resolved": 3, "candidates": 9}}
        groups = self._same(recap)
        self.assertEqual([(g["merchant"], g["store_id"], [c["offer"]["offer_id"] for c in g["candidates"]])
                          for g in groups],
                         [("G2A", "38", ["1", "7", "3", "9"]), ("Kinguin", "45", ["2"])])
        self.assertEqual(_js_counts(_js_submit_batch(recap)), {"offers": 5, "targets": 6, "merchants": 2})

    def test_fallback_formula_equals_candidate_fingerprint(self):
        for c in (_cand("1"), _pc_target_cand("3"), _console_cand("7"), _switch_cand("9")):
            self.assertNotIn("fingerprint", c)                      # the fallback path is exercised
            self.assertEqual(_js_cand_fingerprint(c), M.candidate_fingerprint(c))
        self.assertEqual(_js_cand_fingerprint(_console_cand("7")), "7|85104|88|1|+85105:88ps5h:1")
        # the candidate's own key wins when present (as the matcher writes it)
        self.assertEqual(_js_cand_fingerprint(dict(_cand("1"), fingerprint="X")), "X")


if __name__ == "__main__":
    unittest.main()

"""Romain's audit of 2026-09-16 — three defects, three fixes.

1. **HIGH — the GO could target a scan other than the one displayed.** Selecting two scans
   quickly let a slow answer from the first repaint over the second, while "Déplacer" used
   the second's id: « un canary peut alors déplacer une offre d'un lot que tu n'as pas
   examiné ». Fixed on three levels — a sequence token drops stale answers, every action
   reads the run the DISPLAYED plan came from, and a real move must carry the plan's
   digest which the server proves is still this run's current plan.
2. **MEDIUM — the sort scan lost the merchant rules.** The all-stores scan labels every row
   "all-stores", so ``merchant_config()`` found nothing even though ``store_id`` was known:
   an MMOGA "… RU Key" row routed Blacklist under its real merchant became an un-routed
   creation candidate. Fixed by restoring the canonical merchant from the store id.
3. **MEDIUM — the night sweep accepted "false" as an activation.** ``all_allowlisted`` was
   read for Python truthiness, so the STRING "false" launched all 14 merchants. Fixed like
   ``consoles``: a real JSON boolean or a 400."""

import json
import pathlib
import unittest

from src.contracts import NormalizedOffer

ROOT = pathlib.Path(__file__).resolve().parent.parent
APP = (ROOT / "src" / "admin" / "app.py").read_text(encoding="utf-8")
SORT_JS = (ROOT / "src" / "admin" / "static" / "sort.js").read_text(encoding="utf-8")


def _offer(name, store_id="12", merchant="all-stores",
           url="https://www.mmoga.com/Steam-Games/Example-Game-RU-Key.html"):
    return NormalizedOffer(offer_id="1", name=name, url=url, merchant=merchant,
                           store_id=store_id, price="9.99")


class MerchantRulesInTheAllStoresScanTests(unittest.TestCase):
    """Finding 2 — the store id restores the merchant identity before classification."""

    def test_the_store_id_resolves_to_the_canonical_merchant(self):
        from src.merchants.registry import merchant_for_store
        self.assertEqual(merchant_for_store("12"), "MMOGA")
        self.assertEqual(merchant_for_store(162), "Wyrel")
        self.assertIsNone(merchant_for_store("999"), "an unknown store must not be guessed")
        self.assertIsNone(merchant_for_store(None))

    def test_the_store_map_agrees_with_the_allowlist(self):
        from src.admin.auto_merchants import AUTO_MERCHANTS
        from src.merchants.registry import MERCHANT_STORE_IDS
        for name, store in AUTO_MERCHANTS:
            with self.subTest(merchant=name):
                self.assertEqual(MERCHANT_STORE_IDS.get(name), store)

    def test_every_registered_merchant_has_a_store_id(self):
        from src.merchants.registry import MERCHANT_CONFIGS, MERCHANT_STORE_IDS
        for name in MERCHANT_STORE_IDS:
            with self.subTest(merchant=name):
                self.assertIn(name.upper(), MERCHANT_CONFIGS)

    def test_the_merchant_rules_fire_in_the_all_stores_scan(self):
        """The reproduction Romain gave: RU / BR / CN MMOGA rows."""

        from src.sort_plan import build_sort_plan
        rows = [_offer(f"Example Game {code} Key",
                       url=f"https://www.mmoga.com/Steam-Games/Example-Game-{code}-Key.html")
                for code in ("RU", "BR", "CN")]
        plan = build_sort_plan(rows, run_id="t")
        self.assertEqual(plan["counts"]["candidates"], 0,
                         "a region-locked MMOGA row must never be a creation candidate")
        self.assertEqual(plan["counts"]["routed"], 3)
        self.assertIn("8", plan["by_list"], "they belong on the Blacklist")

    def test_an_unknown_store_keeps_the_generic_behaviour(self):
        from src.sort_plan import build_sort_plan
        plan = build_sort_plan([_offer("Some Game (PC) - Steam Key - GLOBAL", store_id="999",
                                       url="https://x.test/some-game")], run_id="t")
        self.assertEqual(plan["counts"]["total"], 1)


class DisplayedPlanIsTheActedOnPlanTests(unittest.TestCase):
    """Finding 1 — client side: stale answers dropped, actions bound to the displayed run."""

    def test_a_sequence_token_drops_stale_answers(self):
        self.assertIn("LOAD_SEQ", SORT_JS)
        self.assertIn("if (seq !== LOAD_SEQ) return;", SORT_JS)

    def test_the_actions_read_the_displayed_run_not_the_picker(self):
        """SUPERSEDED-IN-FORM 2026-09-17, same intent, stronger guarantee. This used to
        require the literal ``PLAN_RUN_ID`` in each action URL. The next day's audit showed
        that reading the MUTABLE global at each step was itself the defect (a plan swap
        during an await redirected the move), so the actions now read ``runId`` — a const
        frozen from ``PLAN_RUN_ID`` at the click. What this test protects is unchanged: an
        action must never address the PICKER's ``RUN_ID``. See
        ``test_sort_audit_2026_09_17`` for the freezing itself."""

        self.assertIn("PLAN_RUN_ID", SORT_JS)
        self.assertIn("const runId = PLAN_RUN_ID;", SORT_JS)
        for call in ("/sort/move", "/submit/status?offset=0"):
            with self.subTest(call=call):
                line = [l for l in SORT_JS.splitlines() if call in l and "encodeURIComponent" in l]
                self.assertTrue(line, call)
                for l in line:
                    self.assertIn("encodeURIComponent(runId)", l)
                    self.assertNotIn("encodeURIComponent(RUN_ID)", l)

    def test_the_move_sends_the_plan_digest(self):
        self.assertIn("body.plan_digest", SORT_JS)


class PlanDigestIsProvenServerSideTests(unittest.TestCase):
    """Finding 1 — server side: the approved plan's identity is verified."""

    def test_the_get_serves_a_digest(self):
        self.assertIn("plan_digest=_sort_plan_digest(run_dir)", APP)

    def test_a_real_move_requires_it(self):
        self.assertIn("plan_digest_required", APP)

    def test_a_mismatch_is_a_409(self):
        self.assertIn("plan_changed", APP)
        block = APP[APP.index("plan_changed") - 400:APP.index("plan_changed") + 200]
        self.assertIn("409", block)

    def test_the_digest_follows_the_file(self):
        import tempfile
        from src.admin.app import _sort_plan_digest
        with tempfile.TemporaryDirectory() as tmp:
            run = pathlib.Path(tmp)
            self.assertEqual(_sort_plan_digest(run), "", "absent plan → empty digest")
            (run / "sort_plan.json").write_text(json.dumps({"a": 1}), encoding="utf-8")
            first = _sort_plan_digest(run)
            self.assertTrue(first)
            (run / "sort_plan.json").write_text(json.dumps({"a": 2}), encoding="utf-8")
            self.assertNotEqual(_sort_plan_digest(run), first,
                                "a re-scanned plan must change the digest")


class NightSweepFlagMustBeABooleanTests(unittest.TestCase):
    """Finding 3 — "false" is not an activation."""

    def test_the_server_refuses_a_non_boolean(self):
        self.assertIn("bad_all_allowlisted", APP)

    def test_it_is_checked_before_the_targets_are_filled(self):
        block = APP[APP.index("all_allowlisted = body.get"):]
        block = block[:block.index("if all_allowlisted:")]
        self.assertIn("isinstance(all_allowlisted, bool)", block)


if __name__ == "__main__":
    unittest.main()

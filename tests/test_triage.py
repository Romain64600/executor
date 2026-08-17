"""Tests for the unified per-page triage (src.triage) — ADD / MOVE / SKIP."""

import unittest

from src.contracts import NormalizedOffer
from src.matcher import Candidate, SkippedOffer
from src.triage import (ADD, MOVE, SKIP, Triage, build_page_triage,
                        execute_page_moves, plan_moves_from_skipped, triage_offer)


def _offer(name="Game Steam Key GLOBAL", oid="1", store="10",
           url="https://m/x", merchant="Kinguin"):
    return NormalizedOffer(offer_id=oid, name=name, url=url,
                           merchant=merchant, store_id=store)


def _candidate(offer):
    return Candidate(offer=offer, aks_product_id="42", aks_url="https://aks/x",
                     aks_name=offer.name, platform="STEAM", region_label="GLOBAL",
                     region_id="2", edition_label="Standard", edition_id="1")


class TriageOfferTests(unittest.TestCase):
    def test_candidate_becomes_add(self):
        o = _offer()
        t = triage_offer(o, matcher=lambda off, **k: _candidate(off))
        self.assertEqual(t.action, ADD)
        self.assertIsNotNone(t.candidate)
        self.assertEqual(t.reason, "")
        self.assertIsNone(t.list_id)

    def test_routable_skip_becomes_move(self):
        # a blacklist-region skip → MOVE to Blacklist (8)
        o = _offer()
        t = triage_offer(o, matcher=lambda off, **k: SkippedOffer(off, "forbidden region: BRAZIL"))
        self.assertEqual(t.action, MOVE)
        self.assertEqual(t.list_id, "8")
        self.assertEqual(t.list_label, "Blacklist")
        self.assertIn("BRAZIL", t.reason)

    def test_unroutable_skip_becomes_skip(self):
        # ROW has no list → garder → SKIP
        o = _offer()
        t = triage_offer(o, matcher=lambda off, **k: SkippedOffer(off, "forbidden region: ROW"))
        self.assertEqual(t.action, SKIP)
        self.assertIsNone(t.list_id)
        self.assertIn("ROW", t.reason)

    def test_region_list_skip_moves_to_regional_list(self):
        o = _offer()
        t = triage_offer(o, matcher=lambda off, **k: SkippedOffer(off, "forbidden region: MIDDLE EAST"))
        self.assertEqual((t.action, t.list_id), (MOVE, "34"))

    def test_match_kwargs_forwarded(self):
        seen = {}
        def fake(off, **k):
            seen.update(k)
            return _candidate(off)
        triage_offer(_offer(), matcher=fake, resolver="R")
        self.assertEqual(seen.get("resolver"), "R")

    def test_ig_steam_ru_moves_to_blacklist_via_real_matcher(self):
        # end-to-end through the REAL match_offer: an IG offer whose page resolves
        # to Steam + region RU → MOVE→Blacklist (not a silent GLOBAL ADD).
        import src.matcher as M
        from src.merchant_config import MerchantConfig, MerchantOfferSignals
        saved = M.MERCHANT_CONFIGS["INSTANT GAMING"]
        M.MERCHANT_CONFIGS["INSTANT GAMING"] = MerchantConfig(
            "Instant Gaming",
            offer_page_resolver=lambda u: MerchantOfferSignals(
                platform="STEAM", region_resolved=True, region_base=None, region_label="RU"))
        self.addCleanup(lambda: M.MERCHANT_CONFIGS.__setitem__("INSTANT GAMING", saved))
        o = _offer(name="Battlefield", url="https://ig/x", merchant="Instant Gaming")
        t = triage_offer(o, resolver=lambda n: M.AksResolution(
            slug="s", url="u", product_id="1", aks_name="Battlefield",
            editions={"1": "Standard"}, regions={"2": "GLOBAL"},
            official_platforms=("Steam",)))
        self.assertEqual((t.action, t.list_id), (MOVE, "8"))


class BuildPageTriageTests(unittest.TestCase):
    def test_groups_by_action_and_counts(self):
        offers = [_offer(oid=str(i)) for i in range(5)]
        # 0,1 → ADD ; 2 → MOVE(8) ; 3 → MOVE(34) ; 4 → SKIP
        def fake(off, **k):
            i = int(off.offer_id)
            if i in (0, 1):
                return _candidate(off)
            if i == 2:
                return SkippedOffer(off, "forbidden region: BRAZIL")
            if i == 3:
                return SkippedOffer(off, "forbidden region: MIDDLE EAST")
            return SkippedOffer(off, "forbidden region: ROW")
        page = build_page_triage(offers, matcher=fake)
        self.assertEqual(page["counts"],
                         {"total": 5, "add": 2, "move": 2, "skip": 1, "target_lists": 2})
        self.assertEqual(len(page["add"]), 2)
        self.assertEqual(sorted(page["move_by_list"].keys()), ["34", "8"])
        self.assertEqual(len(page["skip"]), 1)

    def test_move_groups_ordered_largest_first(self):
        # 3 to list 8, 1 to list 34 → list 8 first
        offers = [_offer(oid=str(i)) for i in range(4)]
        def fake(off, **k):
            i = int(off.offer_id)
            reason = "forbidden region: MIDDLE EAST" if i == 3 else "forbidden region: BRAZIL"
            return SkippedOffer(off, reason)
        page = build_page_triage(offers, matcher=fake)
        self.assertEqual(list(page["move_by_list"].keys()), ["8", "34"])
        self.assertEqual(len(page["move_by_list"]["8"]), 3)

    def test_to_dict_shapes_per_action(self):
        add = Triage(ADD, _offer(), candidate=_candidate(_offer())).to_dict()
        self.assertEqual(add["action"], "add")
        self.assertIn("candidate", add)
        move = Triage(MOVE, _offer(), reason="forbidden region: BRAZIL",
                      list_id="8", list_label="Blacklist").to_dict()
        self.assertEqual((move["list_id"], move["list_label"]), ("8", "Blacklist"))
        skip = Triage(SKIP, _offer(), reason="forbidden region: ROW").to_dict()
        self.assertEqual(skip["reason"], "forbidden region: ROW")
        self.assertNotIn("candidate", skip)


class PlanMovesFromSkippedTests(unittest.TestCase):
    """The sweep's move-planning input: skipped.json reasons → target lists."""

    @staticmethod
    def _sk(reason, oid="1", store="10", name="Game", url="https://m/x"):
        return {"offer": {"offer_id": oid, "store_id": store, "name": name, "url": url},
                "reason": reason}

    def test_groups_routable_skips_by_list(self):
        skipped = [
            self._sk("forbidden region: BRAZIL", oid="1"),
            self._sk("forbidden region: RUSSIA", oid="2"),
            self._sk("forbidden region: MIDDLE EAST", oid="3"),
            self._sk("forbidden region: ROW", oid="4"),        # garder → excluded
            self._sk("skip category: SOFTWARE (software/app)", oid="5"),
        ]
        plan = plan_moves_from_skipped(skipped)
        self.assertEqual(plan["movable"], 4)                    # ROW excluded
        self.assertEqual(sorted(plan["by_list"]), ["16", "34", "8"])
        self.assertEqual(len(plan["by_list"]["8"]), 2)          # Brazil + Russia
        self.assertEqual(plan["by_list"]["8"][0]["list_label"], "Blacklist")

    def test_largest_group_first(self):
        skipped = [self._sk("forbidden region: BRAZIL", oid=str(i)) for i in range(3)]
        skipped.append(self._sk("forbidden region: MIDDLE EAST", oid="9"))
        plan = plan_moves_from_skipped(skipped)
        self.assertEqual(list(plan["by_list"]), ["8", "34"])

    def test_empty_and_all_garder(self):
        self.assertEqual(plan_moves_from_skipped([])["movable"], 0)
        garder = [self._sk("forbidden region: ROW"), self._sk("console"),
                  self._sk("no AKS product page found (slug not 200)")]
        self.assertEqual(plan_moves_from_skipped(garder)["movable"], 0)

    def test_row_shape_has_move_fields(self):
        plan = plan_moves_from_skipped([self._sk("forbidden region: BRAZIL", oid="7", store="58")])
        row = plan["by_list"]["8"][0]
        self.assertEqual((row["offer_id"], row["store_id"], row["list_id"]), ("7", "58", "8"))
        self.assertIn("BRAZIL", row["reason"])


class ExecutePageMovesTests(unittest.TestCase):
    """Per-page canary-then-batch orchestration (fail-closed)."""

    def _by_list(self):
        return {"8": [{"offer_id": "1"}, {"offer_id": "2"}],
                "16": [{"offer_id": "3"}]}

    def test_happy_path_canary_then_batch_each_list(self):
        calls = []
        # REAL shape: a successful learning canary ALWAYS stops with "limit_reached"
        # (it moved its 1 and hit the cap) — this must be treated as success, not a
        # fault (regression the adversarial review caught: the batch never ran).
        def canary(lid, rows):
            calls.append(("canary", lid)); return {"ok": True, "moved": 1, "stopped": "limit_reached"}
        def batch(lid, rows): calls.append(("batch", lid)); return {"ok": True, "moved": len(rows) - 1}
        r = execute_page_moves(self._by_list(), run_canary=canary, run_batch=batch)
        self.assertTrue(r["ok"], r.get("detail"))
        self.assertIsNone(r["stopped"])
        # list 8: canary 1 + batch 1 = 2 ; list 16: canary 1 + batch 0 = 1 → total 3
        self.assertEqual(r["moved"], 3)
        # each list is canaried BEFORE it is batched, and the batch DID run
        self.assertEqual(calls, [("canary", "8"), ("batch", "8"), ("canary", "16"), ("batch", "16")])

    def test_canary_limit_reached_is_success_not_a_halt(self):
        # a single-list page: canary limit_reached (moved 1) → batch runs → clean
        batched = []
        r = execute_page_moves(
            {"8": [{"offer_id": "1"}, {"offer_id": "2"}]},
            run_canary=lambda lid, rows: {"ok": True, "moved": 1, "stopped": "limit_reached"},
            run_batch=lambda lid, rows: (batched.append(lid) or {"ok": True, "moved": 1}))
        self.assertTrue(r["ok"])
        self.assertEqual((r["moved"], batched), (2, ["8"]))

    def test_non_benign_stop_fails_closed(self):
        # feed_unreadable / guard_blocked etc. are broken sessions → halt
        for bad in ("feed_unreadable", "guard_blocked", "ten_consecutive_failures"):
            r = execute_page_moves(
                {"8": [{"offer_id": "1"}]},
                run_canary=lambda lid, rows, _b=bad: {"ok": True, "moved": 1, "stopped": _b},
                run_batch=lambda lid, rows: {"ok": True, "moved": 0})
            self.assertFalse(r["ok"], bad)
            self.assertEqual(r["stopped"], bad)

    def test_operator_stop_on_canary_halts_clean_no_batch(self):
        batched = []
        r = execute_page_moves(
            self._by_list(),
            run_canary=lambda lid, rows: {"ok": True, "moved": 1, "stopped": "operator_stop"},
            run_batch=lambda lid, rows: (batched.append(lid) or {"ok": True, "moved": 1}))
        self.assertTrue(r["ok"])                       # clean (not a failure)
        self.assertEqual(r["stopped"], "operator_stop")
        self.assertEqual((r["moved"], batched), (1, []))   # canary counted, no batch

    def test_canary_moved_zero_fails_closed_no_batch(self):
        batched = []
        def canary(lid, rows): return {"ok": True, "moved": 0}    # validated nothing
        def batch(lid, rows): batched.append(lid); return {"ok": True, "moved": 9}
        r = execute_page_moves(self._by_list(), run_canary=canary, run_batch=batch)
        self.assertFalse(r["ok"])
        self.assertIn("moved 0", r["detail"])
        self.assertEqual(batched, [])                            # never batched

    def test_canary_abort_halts(self):
        r = execute_page_moves(
            self._by_list(),
            run_canary=lambda lid, rows: {"ok": False, "aborted": "invariants not green", "moved": 0},
            run_batch=lambda lid, rows: {"ok": True, "moved": 1})
        self.assertFalse(r["ok"])
        self.assertEqual(r["aborted"], "invariants not green")

    def test_batch_abort_halts_after_counting_canary(self):
        def canary(lid, rows): return {"ok": True, "moved": 1}
        def batch(lid, rows): return {"ok": False, "aborted": "guard_blocked", "moved": 0}
        r = execute_page_moves({"8": [{"offer_id": "1"}]}, run_canary=canary, run_batch=batch)
        self.assertFalse(r["ok"])
        self.assertEqual(r["aborted"], "guard_blocked")
        self.assertEqual(r["moved"], 1)                          # the canary move still counted

    def test_mid_batch_abort_counts_the_partial_moves(self):
        # the real prod case: canary moves 1, the batch moves 2 more then aborts on
        # feed_unreadable → the recap must report 3, not 1 (audit integrity).
        def canary(lid, rows): return {"ok": True, "moved": 1, "stopped": "limit_reached"}
        def batch(lid, rows): return {"ok": False, "moved": 2, "aborted": "feed_unreadable_mid_run"}
        r = execute_page_moves({"21": [{"offer_id": str(i)} for i in range(10)]},
                               run_canary=canary, run_batch=batch)
        self.assertFalse(r["ok"])
        self.assertEqual(r["aborted"], "feed_unreadable_mid_run")
        self.assertEqual(r["moved"], 3)                          # 1 canary + 2 batch

    def test_batch_stopped_is_not_clean(self):
        r = execute_page_moves(
            {"8": [{"offer_id": "1"}]},
            run_canary=lambda lid, rows: {"ok": True, "moved": 1},
            run_batch=lambda lid, rows: {"ok": True, "stopped": "feed_unreadable", "moved": 0})
        self.assertFalse(r["ok"])
        self.assertEqual(r["stopped"], "feed_unreadable")

    def test_second_list_canary_failure_stops_there(self):
        seen = []
        def canary(lid, rows):
            seen.append(lid)
            return {"ok": True, "moved": 1} if lid == "8" else {"ok": False, "aborted": "x", "moved": 0}
        def batch(lid, rows): return {"ok": True, "moved": len(rows) - 1}
        r = execute_page_moves(self._by_list(), run_canary=canary, run_batch=batch)
        self.assertFalse(r["ok"])
        self.assertEqual(seen, ["8", "16"])                      # stopped at list 16's canary


if __name__ == "__main__":
    unittest.main()

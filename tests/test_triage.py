"""Tests for the unified per-page triage (src.triage) — ADD / MOVE / SKIP."""

import unittest

from src.contracts import NormalizedOffer
from src.matcher import Candidate, SkippedOffer
from src.triage import (ADD, MOVE, SKIP, Triage, build_page_triage,
                        plan_moves_from_skipped, triage_offer)


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


if __name__ == "__main__":
    unittest.main()

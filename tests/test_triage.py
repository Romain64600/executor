"""Tests for the unified per-page triage (src.triage) — ADD / MOVE / SKIP."""

import unittest

from src.contracts import NormalizedOffer
from src.matcher import Candidate, SkippedOffer
from src.triage import (ADD, MOVE, SKIP, Triage, build_page_triage,
                        triage_offer)


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


if __name__ == "__main__":
    unittest.main()

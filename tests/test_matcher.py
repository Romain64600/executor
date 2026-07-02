import unittest

from src.aks_env import HttpProbeResult
from src.contracts import NormalizedFeed, NormalizedOffer
from src.matcher import (
    AksResolution,
    Candidate,
    SkippedOffer,
    build_slug_candidates,
    dangerous_qualifier,
    detect_edition,
    detect_platform,
    detect_region,
    extra_significant_words,
    match_feed,
    match_offer,
    missing_aks_words,
    precheck_skip,
    resolve_aks,
    tokenize,
)

AKS_PAGE = (
    '<html><head>'
    '<meta property="og:title" content="Buy Neon Beats CD Key Compare Prices">'
    '</head><body>'
    '<div data-product-id="205027"></div>'
    '<script>var x={"editions":{"1":{"name":"Standard"},"7":{"name":"Deluxe"}}};</script>'
    '</body></html>'
)


def _offer(name, url="https://m.test/x", oid="1"):
    return NormalizedOffer(offer_id=oid, name=name, url=url, merchant="Test")


class TokenizeTests(unittest.TestCase):
    def test_normalizes_apostrophes(self):
        self.assertEqual(tokenize("Dragon’s Dogma"), ["DRAGON'S", "DOGMA"])

    def test_r01_all_words_present(self):
        self.assertEqual(
            missing_aks_words("Neon Beats", "Neon Beats - Full Version (PC) - Steam Key - GLOBAL"),
            [],
        )

    def test_r01_apostrophe_mismatch_is_missing(self):
        self.assertEqual(missing_aks_words("Dragon's Dogma", "Dragons Dogma"), ["DRAGON'S"])


class QualifierTests(unittest.TestCase):
    def test_dangerous_qualifier_detected(self):
        self.assertEqual(dangerous_qualifier("Dead Space Remake", "Dead Space"), "REMAKE")

    def test_qualifier_present_in_aks_name_is_ok(self):
        self.assertIsNone(dangerous_qualifier("Dead Space Remake", "Dead Space Remake"))


class PrecheckSkipTests(unittest.TestCase):
    def test_console(self):
        self.assertEqual(precheck_skip(_offer("Halo Xbox Series X")), "console")

    def test_forbidden_region(self):
        self.assertIn("forbidden region", precheck_skip(_offer("Game Steam Key TURKEY")))

    def test_currency_category(self):
        self.assertIn("POINTS", precheck_skip(_offer("500 FIFA Points")))

    def test_multi_game_bundle(self):
        self.assertIn("bundle", precheck_skip(_offer("Game A + Game B")))

    def test_language_restriction(self):
        self.assertIn("language", precheck_skip(_offer("Game (EN/FR) Steam")))

    def test_sea_word_is_not_a_forbidden_region(self):
        self.assertIsNone(precheck_skip(_offer("Sea of Thieves Steam GLOBAL")))

    def test_normal_offer_survives(self):
        self.assertIsNone(precheck_skip(_offer("Neon Beats Steam GLOBAL")))


class DetectTests(unittest.TestCase):
    def test_platform(self):
        self.assertEqual(detect_platform("Game GOG Key"), "GOG")
        self.assertEqual(detect_platform("Game Steam Key"), "STEAM")
        self.assertEqual(detect_platform("Final Fantasy Origin Steam"), "STEAM")  # R14

    def test_region_url_first(self):
        self.assertEqual(detect_region(_offer("X", url="https://g/game-pc-steam-global"), "STEAM"),
                         ("GLOBAL", "2", False))
        self.assertEqual(detect_region(_offer("X", url="https://g/game-steam-eu"), "STEAM"),
                         ("EU", "9", False))

    def test_region_implicit_global(self):
        label, rid, implicit = detect_region(_offer("Game PC Steam CD Key"), "STEAM")
        self.assertEqual((label, rid), ("GLOBAL", "2"))
        self.assertTrue(implicit)

    def test_edition(self):
        self.assertEqual(detect_edition("Game Deluxe Edition"), ("Deluxe", "7"))
        self.assertEqual(detect_edition("Game Ultimate Collection"), ("Ultimate Collection", "348"))
        self.assertEqual(detect_edition("Game"), ("Standard", "1"))


class SlugAndResolveTests(unittest.TestCase):
    def test_slug_candidates_strip_parens_and_suffix(self):
        slugs = build_slug_candidates("Tom Clancy's Rainbow Six Siege (EU) (PC) - Ubisoft - Digital Key")
        self.assertIn("tom-clancys-rainbow-six-siege", slugs)

    def test_resolve_returns_first_real_page(self):
        def fake_http(url, timeout=8):
            return HttpProbeResult(url=url, ok=True, status=200, body=AKS_PAGE)

        res = resolve_aks("Neon Beats", fake_http)
        self.assertIsNotNone(res)
        self.assertEqual(res.product_id, "205027")
        self.assertEqual(res.aks_name, "Neon Beats")
        self.assertIn("7", res.editions)

    def test_resolve_none_when_not_found(self):
        def fake_http(url, timeout=8):
            return HttpProbeResult(url=url, ok=False, status=404, body="")

        self.assertIsNone(resolve_aks("Nope", fake_http))


class MatchOfferTests(unittest.TestCase):
    def _resolver(self, aks_name="Neon Beats", editions=None):
        res = AksResolution(
            slug="neon-beats", url="https://aks/buy-neon-beats", product_id="205027",
            aks_name=aks_name, editions=editions or {"1": {"name": "Standard"}},
        )
        return lambda name: res

    def test_candidate_built(self):
        offer = _offer("Neon Beats - Full Version (PC) - Steam Key - GLOBAL")
        result = match_offer(offer, self._resolver())
        self.assertIsInstance(result, Candidate)
        self.assertEqual(result.aks_product_id, "205027")
        self.assertEqual((result.region_label, result.region_id), ("GLOBAL", "2"))
        self.assertEqual((result.edition_label, result.edition_id), ("Standard", "1"))

    def test_precheck_skip_wins(self):
        self.assertIsInstance(match_offer(_offer("Halo Xbox"), self._resolver()), SkippedOffer)

    def test_dangerous_qualifier_skips(self):
        result = match_offer(_offer("Neon Beats Remastered - Steam"), self._resolver())
        self.assertIsInstance(result, SkippedOffer)
        self.assertIn("qualifier", result.reason)

    def test_name_mismatch_skips(self):
        result = match_offer(_offer("Neon Beats - Steam"), self._resolver(aks_name="Different Game"))
        self.assertIsInstance(result, SkippedOffer)
        self.assertIn("mismatch", result.reason)

    def test_no_aks_page_skips(self):
        result = match_offer(_offer("Neon Beats - Steam"), lambda name: None)
        self.assertIsInstance(result, SkippedOffer)

    def test_normalized_block(self):
        offer = _offer("Neon Beats - Full Version (PC) - Steam Key - GLOBAL")
        block = match_offer(offer, self._resolver()).normalized_block(1)
        self.assertIn("#1 —", block)
        self.assertIn("205027", block)
        self.assertIn("Steam GLOBAL(2), Standard(1)", block)


class DifferentProductTests(unittest.TestCase):
    def _resolver(self, aks_name):
        res = AksResolution("slug", "https://aks/x", "27577", aks_name, {"1": {"name": "Standard"}})
        return lambda name: res

    def test_extra_words_detected(self):
        extras = extra_significant_words(
            "Greedfall",
            "GreedFall - The Dying World - Deluxe Edition (Europe) (PC) - Steam - Digital Key",
        )
        self.assertIn("DYING", extras)
        self.assertIn("WORLD", extras)

    def test_the_dying_world_is_skipped(self):
        offer = _offer("GreedFall - The Dying World - Deluxe Edition (Global) (PC) - Steam - Digital Key")
        result = match_offer(offer, self._resolver("Greedfall"))
        self.assertIsInstance(result, SkippedOffer)
        self.assertIn("extra words", result.reason)

    def test_version_number_is_skipped(self):
        result = match_offer(_offer("FIFA 23 - Steam"), self._resolver("FIFA"))
        self.assertIsInstance(result, SkippedOffer)

    def test_matching_base_game_still_a_candidate(self):
        offer = _offer("Bus Simulator 27 (Global) (PC) - Steam - Digital Key")
        result = match_offer(offer, self._resolver("Bus Simulator 27"))
        self.assertIsInstance(result, Candidate)
        self.assertEqual((result.region_label, result.region_id), ("GLOBAL", "2"))


class GiftRegionTests(unittest.TestCase):
    def test_battlenet_gift_maps_to_570(self):
        offer = _offer("Overwatch Skin Bundle (Global) (PC) - Battle.net Gift",
                       url="https://driffle.com/x-battlenet-gift-p1")
        self.assertEqual(detect_region(offer, "BATTLENET"), ("GIFT", "570", False))

    def test_steam_gift_maps_to_25(self):
        self.assertEqual(detect_region(_offer("Game Steam Gift GLOBAL"), "STEAM"), ("GIFT", "25", False))

    def test_steam_gift_eu_maps_to_259(self):
        self.assertEqual(detect_region(_offer("Game Steam Gift EU"), "STEAM"), ("GIFT EU", "259", False))


class MatchFeedTests(unittest.TestCase):
    def _feed(self, *offers):
        return NormalizedFeed(run_id="r", merchant="Test", fetched_at="t", offers=tuple(offers))

    def test_partitions_and_caps(self):
        res = AksResolution("neon-beats", "https://aks/x", "205027", "Neon Beats", {"1": {"name": "Standard"}})
        resolver = lambda name: res
        feed = self._feed(
            _offer("Neon Beats - Steam GLOBAL", oid="1"),
            _offer("Neon Beats - Steam GLOBAL", oid="2"),
            _offer("Halo Xbox", oid="3"),
        )
        candidates, skipped = match_feed(feed, resolver, max_candidates=1)
        self.assertEqual(len(candidates), 1)
        # one capped + one console skip
        self.assertEqual(len(skipped), 2)
        self.assertTrue(any("cap" in s.reason for s in skipped))


if __name__ == "__main__":
    unittest.main()

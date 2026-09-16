"""R51 (2026-09-16) — the PUBLISHER decision needs the MERCHANT's own page.

Romain, after checking the first Electronicfirst batch and then reproducing it on Gamivo:

    « j ai trouve un exemple ou l on a ajoute l offre en publisher a la place de Steam car on
      a pas la plateforme dans l url et du coup on aurait du ouvrir la page »
    « avant de decider si publisher ou non on doit ouvrir la page marchant pour verifier la
      region et l edition, si on arrive pas a ouvrir la page marchant on skip l offre …
      on devrait ajouter cette securite par defaut pour tous les marchants »

The hole: `[R27]` refuses a token-less title UNLESS the AKS page confirms "Direct Publisher".
But that line describes the GAME (the game also exists as a publisher key) — it says nothing
about what THIS merchant sells. Two Electronicfirst rows (`Of Orcs and Men`, `RoboCop: Rogue
City - Collection`) were entered PUBLISHER while the merchant sells Steam, and Romain's Gamivo
example (`Resident Evil Raccoon City Edition`, a Steam global key) reproduced it live.

R51: the decision now needs the merchant's OWN page, declared per merchant with
``MerchantConfig.publisher_from_merchant_page``. The default is **False**, so the safety is on
for every merchant — with or without a config file. Measured cost over every saved run: 13
distinct candidates (MMOGA 5, Gamivo 6, Electronicfirst 2).

What R51 does NOT change is pinned here too: an explicit platform token, the Steam-only page
(already the R27 skip), the software path, and the "no official platforms" R20 skip."""

import unittest

from src.contracts import NormalizedOffer
from src.matcher import (
    MERCHANT_CONFIGS,
    AksResolution,
    Candidate,
    SkippedOffer,
    match_offer,
)
from src.merchant_config import MerchantConfig

R51_MARK = "(R51)"
R27_MARK = "not defaulted (R27)"


def _offer(name, url="https://merchant.test/some-game", merchant="TestShop", store_id="999"):
    return NormalizedOffer(offer_id="1", name=name, url=url, merchant=merchant,
                           store_id=store_id, price="9.99")


def _page(aks_name="Some Game", platforms=("Steam", "Direct Publisher"), editions=None,
          regions=None):
    return AksResolution(
        slug="some-game", url="https://aks/buy-some-game", product_id="4242",
        aks_name=aks_name,
        editions={"1": {"name": "Standard"}} if editions is None else editions,
        official_platforms=platforms,
        prices=(),
        **({"regions": regions} if regions is not None else {}),
    )


def _match(offer, resolution=None):
    res = resolution if resolution is not None else _page()
    return match_offer(offer, lambda name, **kw: res)


class PublisherGateDefaultTests(unittest.TestCase):
    """The safety is ON by default — for a merchant with no config file at all."""

    def test_a_token_less_title_is_refused_even_when_the_page_confirms_publisher(self):
        result = _match(_offer("Some Game"))
        self.assertIsInstance(result, SkippedOffer)
        self.assertIn(R51_MARK, result.reason)
        self.assertIn("describes the game", result.reason)

    def test_the_reason_names_the_merchant_page(self):
        result = _match(_offer("Some Game"))
        self.assertIn("the merchant page is not read", result.reason)

    def test_romains_gamivo_example(self):
        """« Resident Evil Raccoon City Edition » — steam global, was entered PUBLISHER."""

        offer = _offer(
            "Resident Evil Raccoon City Edition",
            url="https://www.gamivo.com/product/resident-evil-raccoon-city-edition",
            merchant="Gamivo", store_id="51")
        result = _match(offer, _page(aks_name="Resident Evil Raccoon City Edition"))
        self.assertIsInstance(result, SkippedOffer, getattr(result, "platform", None))
        self.assertIn(R51_MARK, result.reason)

    def test_the_two_electronicfirst_rows_of_2026_09_16(self):
        for name, slug in (
            ("Of Orcs and Men", "of-orcs-and-men"),
            ("RoboCop: Rogue City - Collection", "robocop-rogue-city-collection"),
        ):
            with self.subTest(name=name):
                offer = _offer(name, url=f"https://www.electronicfirst.com/{slug}",
                               merchant="Electronicfirst", store_id="70")
                result = _match(offer, _page(aks_name=name))
                self.assertIsInstance(result, SkippedOffer)
                self.assertIn(R51_MARK, result.reason)


class PublisherGateOptInTests(unittest.TestCase):
    """A merchant that DOES read its own page keeps the publisher path."""

    MERCHANT = "PageReaderShop"

    def setUp(self):
        self._saved = dict(MERCHANT_CONFIGS)

    def tearDown(self):
        MERCHANT_CONFIGS.clear()
        MERCHANT_CONFIGS.update(self._saved)

    def _use(self, **kwargs):
        MERCHANT_CONFIGS[self.MERCHANT.upper()] = MerchantConfig(self.MERCHANT, **kwargs)

    def test_opt_in_restores_the_publisher_resolution(self):
        self._use(publisher_from_merchant_page=True)
        result = _match(_offer("Some Game", merchant=self.MERCHANT))
        self.assertIsInstance(result, Candidate, getattr(result, "reason", None))
        self.assertEqual(result.platform, "PUBLISHER")
        self.assertEqual(result.region_id, "1")          # Publisher GLOBAL

    def test_a_config_that_does_not_declare_it_is_still_refused(self):
        self._use()                                       # default False
        result = _match(_offer("Some Game", merchant=self.MERCHANT))
        self.assertIsInstance(result, SkippedOffer)
        self.assertIn(R51_MARK, result.reason)

    def test_the_default_of_the_contract_is_false(self):
        self.assertFalse(MerchantConfig("X").publisher_from_merchant_page,
                         "the safety must be ON for every merchant by default")


class PublisherGateUnchangedBehaviourTests(unittest.TestCase):
    """R51 narrows ONE branch. Everything around it must be untouched."""

    def test_an_explicit_platform_token_is_unaffected(self):
        result = _match(_offer("Some Game PC Steam CD Key"))
        self.assertIsInstance(result, Candidate, getattr(result, "reason", None))
        self.assertEqual(result.platform, "STEAM")

    def test_a_steam_only_page_keeps_the_r27_skip(self):
        result = _match(_offer("Some Game"), _page(platforms=("Steam",)))
        self.assertIsInstance(result, SkippedOffer)
        self.assertIn(R27_MARK, result.reason)
        self.assertNotIn(R51_MARK, result.reason)

    def test_a_page_with_no_official_platforms_keeps_the_r20_skip(self):
        result = _match(_offer("Some Game"), _page(platforms=()))
        self.assertIsInstance(result, SkippedOffer)
        self.assertIn("(R20)", result.reason)

    def test_the_two_skips_are_distinguishable(self):
        """An operator must be able to tell 'the page says nothing' from 'the page says
        publisher but the merchant page was never read'."""

        r27 = _match(_offer("Some Game"), _page(platforms=("Steam",)))
        r51 = _match(_offer("Some Game"))
        self.assertNotEqual(r27.reason, r51.reason)


if __name__ == "__main__":
    unittest.main()

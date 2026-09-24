"""Wyrel grammar (R53, 2026-09-16) — src/merchants/wyrel.py.

Rows are verbatim from the live feed (store 162). Written against page 1 (100 rows), then
CORRECTED on the first real slice (pages 1-10, **990 rows**) — page 1 of 60 could not
enumerate this merchant, and the slice proved two of the first rules wrong:

* the non-game gate no longer needs three agreeing signals. ``marketplace_id`` separates
  nothing (id 12 carries both "Other" rows and "PC" rows) and requiring it produced **98
  false refusals**; a tag next to "Other" is not a contradiction either — those 4 rows are
  in-game currency naming the device. The slot alone is 228/228 non-games `[R53b]`;
* the edition slot no longer refuses everything but "Standard": "Deluxe Edition" and
  "Digital Deluxe" DO map (Deluxe 7) and must enter; what is refused is a tier the generic
  read would silently FLATTEN to Standard — Collectors, Zero, Anniversary, Classic `[R53c]`.

What held under both the review and the slice: `[R53d]` the region is written in FULL in the
title AND repeated as the URL's ``region=`` id (strict bijection, 0 disagreement), so a
proven disagreement is a skip; `[R53e]` the platform-slot vocabulary is OPEN and an unknown
word is refused BY NAME rather than folded into the edition."""

import unittest

from src.merchants import wyrel as w
from src.merchants.registry import merchant_config


def _url(marketplace="2", region="1", edition="780"):
    return ("https://wyrel.com/en/buy-cheap-some-game-1?referal=allkeyshop"
            f"&marketplace_id={marketplace}&edition_id={edition}&region={region}"
            "&coupon=allkeyshop")


class WyrelParseTests(unittest.TestCase):
    def test_the_template_parses_the_real_rows(self):
        for name, expected in (
            ("Hunt Showdown: Shrine Maidens Hell (DLC) Standard PC Global",
             {"tag": "DLC", "platform": "PC", "region": "Global", "delivery": ""}),
            ("Hunt Showdown 1896 Deaths Day (PC) Standard Global",
             {"tag": "PC", "platform": "", "region": "Global", "delivery": ""}),
            ("AENTITY (PC) Standard Europe Steam Gift",
             {"tag": "PC", "platform": "", "region": "Europe", "delivery": "Steam Gift"}),
            ("Vanquish (Xbox) Standard Xbox One Europe",
             {"tag": "Xbox", "platform": "Xbox One", "region": "Europe", "delivery": ""}),
            ("DYSMANTLE (Xbox Series X) Standard Xbox Series X/S Europe",
             {"tag": "Xbox Series X", "platform": "Xbox Series X/S", "region": "Europe",
              "delivery": ""}),
        ):
            with self.subTest(name=name):
                parts = w.parse_title(name)
                self.assertIsNotNone(parts)
                for key, value in expected.items():
                    self.assertEqual(parts[key], value, key)

    def test_a_title_with_no_region_slot_does_not_parse(self):
        self.assertIsNone(w.parse_title("Some Game (PC) Standard"))

    def test_the_region_is_read_from_the_end_only(self):
        # a region word inside the product name must never be mined
        parts = w.parse_title("Europa Universalis IV (PC) Standard Global")
        self.assertEqual(parts["region"], "Global")


class WyrelNonGameGateTests(unittest.TestCase):
    """`[R53b]` — the platform slot "Other" IS the merchant's non-game marker."""

    def test_the_real_non_games_are_refused_and_NAMED(self):
        for name, marketplace, label in (
            ("Rituals Gift Card  7 GBP Standard Other United Kingdom", "1089", "GIFT CARD"),
            ("PayPal Wallet Top Up 135000 JPY  Standard Other Global", "216", "WALLET"),
            ("Crypto Voucher Solana 600 GBP Standard Other Global", "1467", "VOUCHER"),
            ("Honor of Kings 830 Tokens  Standard Other Global", "1693", "CURRENCY"),
        ):
            with self.subTest(name=name):
                reason = w.precheck(name, _url(marketplace=marketplace, region="1"))
                self.assertIsNotNone(reason)
                self.assertIn("skip category", reason)
                self.assertIn(label, reason,
                              "the reason must name the PRODUCT so the list router matches")

    def test_a_tag_next_to_Other_is_still_a_non_game(self):
        """The reviewer's probe on page 1 was "(PS5) … Other", feared to be a real game. The
        990-row slice answered it: the 4 such rows are IN-GAME CURRENCY naming the device it
        is for. The slot alone decides, and the three-signal gate is gone."""

        for name in (
            "eFootball 2023 12000 Coins (Xbox One) Standard Other Global",
            "Apex Legends Apex Coins 6700 Points (PC) Standard Other Global",
            "PUBG 11200 G COIN (PC) Standard Other Global",
        ):
            with self.subTest(name=name):
                reason = w.precheck(name, _url(marketplace="2"))
                self.assertIsNotNone(reason)
                self.assertIn("skip category", reason)

    def test_the_marketplace_id_is_never_a_game_signal(self):
        """Measured on 990 rows: id 12 carries BOTH "Other" rows and "PC" rows, so it
        separates nothing. Requiring it produced 98 false refusals — it is gone."""

        self.assertFalse(hasattr(w, "GAME_MARKETPLACE_IDS"))
        # a real key on an id page 1 never showed must pass
        self.assertIsNone(w.precheck("Some Game (PC) Standard Global",
                                     _url(marketplace="588", region="1")))
        self.assertIsNone(w.precheck("Super Luckys Tale (Nintendo) Standard Switch Europe",
                                     _url(marketplace="9", region="4")))

    def test_a_real_key_is_never_caught(self):
        for name, marketplace in (
            ("Hunt Showdown: Shrine Maidens Hell (DLC) Standard PC Global", "2"),
            ("Vanquish (Xbox) Standard Xbox One Europe", "8"),
            ("AENTITY (PC) Standard Europe Steam Gift", "2"),
        ):
            with self.subTest(name=name):
                reason = w.precheck(name, _url(marketplace=marketplace, region="4"
                                               if "Europe" in name else "1"))
                self.assertIsNone(reason, reason)


class WyrelEditionSlotTests(unittest.TestCase):
    """`[R53c]` — a tier the generic read MAPS enters; one it would flatten is refused."""

    def test_mappable_editions_pass(self):
        for slot in ("Standard", "Deluxe Edition", "Digital Deluxe", "Gold Edition"):
            with self.subTest(slot=slot):
                self.assertIsNone(
                    w.precheck(f"Some Game (PC) {slot} Global", _url(edition="780")))

    def test_a_tier_that_would_be_flattened_is_refused_by_name(self):
        for slot in ("Collectors", "Zero", "Anniversary", "Classic", "Horizon Hobby"):
            with self.subTest(slot=slot):
                reason = w.precheck(f"Some Game (PC) {slot} Global", _url(edition="41"))
                self.assertIsNotNone(reason)
                self.assertIn("R53c", reason)
                self.assertIn(slot, reason, "the refusal must name the tier")


class WyrelRegionCrossCheckTests(unittest.TestCase):
    """`[R53d]` — the title slot and the URL's region= id must agree."""

    def test_agreement_passes(self):
        self.assertIsNone(w.precheck("Some Game (PC) Standard Europe", _url(region="4")))
        self.assertIsNone(w.precheck("Some Game (PC) Standard Global", _url(region="1")))

    def test_a_proven_disagreement_is_refused(self):
        reason = w.precheck("Some Game (PC) Standard Global", _url(region="4"))
        self.assertIsNotNone(reason)
        self.assertIn("R53d", reason)
        self.assertIn("disagree", reason)

    def test_an_unknown_id_is_tolerated(self):
        """An id outside the measured map proves nothing — it must not refuse the row."""

        self.assertIsNone(w.precheck("Some Game (PC) Standard Europe", _url(region="999")))

    def test_a_region_lock_uses_the_shared_label(self):
        self.assertEqual(w.precheck("Some Game (PC) Standard Germany", _url(region="19")),
                         "forbidden region: GERMANY")

    def test_rest_of_the_world_is_refused_as_ROW_not_as_unparsable(self):
        """2026-09-24 : Wyrel écrit « Rest of the world » en toutes lettres (161 lignes,
        `region=5`). Absent du vocabulaire partagé, le titre ne se lisait pas et la ligne
        tombait sur « no region slot » (R53a) — refusée, mais pour une fausse raison. Le
        créneau se lit maintenant, et c'est un verrou : une ROW n'entre que si on prouve
        qu'elle s'active en Europe (Romain, même jour)."""

        for name in ("DOOM Eternal (PC) Deluxe Edition Rest of the world",
                     "Kerbal Space Program Breaking Ground Expansion (DLC) Standard PC "
                     "Rest of the world"):
            self.assertEqual(w.parse_title(name)["region"], "Rest of the world", name)
            self.assertEqual(w.precheck(name, _url(region="5")), "forbidden region: ROW", name)
            self.assertIsNone(w.title_region(name), name)


class WyrelPlatformSlotTests(unittest.TestCase):
    """`[R53e]` — open vocabulary, unknown word refused by name."""

    def test_the_vocabulary_is_wider_than_page_one(self):
        for word in ("PS5", "PS4", "Nintendo Switch", "Switch 2", "Mac", "Xbox Series X|S"):
            with self.subTest(word=word):
                self.assertIn(word, w.PLATFORM_SLOT_WORDS)

    def test_a_declared_slot_parses(self):
        parts = w.parse_title("Some Game (PS5) Standard PS5 Europe")
        self.assertEqual(parts["platform"], "PS5")

    def test_an_unknown_slot_word_is_refused_by_name(self):
        reason = w.precheck("Some Game (Amiga) Standard Amiga500 Europe", _url(region="4"))
        self.assertIsNotNone(reason)
        self.assertIn("R53e", reason)


class WyrelTitleRegionTests(unittest.TestCase):
    def test_bases(self):
        for name, base in (
            ("Some Game (PC) Standard Global", "global"),
            ("Some Game (PC) Standard Europe", "eu"),
            ("Some Game (PC) Standard United States", "us"),
            ("Some Game (PC) Standard United Kingdom", "uk"),
        ):
            with self.subTest(name=name):
                self.assertEqual(w.title_region(name), base)

    def test_a_lock_and_an_unparsable_title_yield_none(self):
        self.assertIsNone(w.title_region("Some Game (PC) Standard Germany"))
        self.assertIsNone(w.title_region("Some Game (PC) Standard"))


class WyrelResolveNameTests(unittest.TestCase):
    def test_every_slot_is_peeled_and_the_name_survives(self):
        for name, expected in (
            ("Hunt Showdown: Shrine Maidens Hell (DLC) Standard PC Global",
             "Hunt Showdown: Shrine Maidens Hell"),
            ("AENTITY (PC) Standard Europe Steam Gift", "AENTITY"),
            ("Vanquish (Xbox) Standard Xbox One Europe", "Vanquish"),
            ("DYSMANTLE (Xbox Series X) Standard Xbox Series X/S Europe", "DYSMANTLE"),
            ("Robbery Bob Man of Steal (PC) Standard Global Steam Gift",
             "Robbery Bob Man of Steal"),
        ):
            with self.subTest(name=name):
                self.assertEqual(w.resolve_name(name), expected)

    def test_a_pack_or_dlc_word_of_the_NAME_survives(self):
        self.assertEqual(
            w.resolve_name("Goat Simulator 3 - Super Duper Pack (DLC) Standard PC Global"),
            "Goat Simulator 3 - Super Duper Pack")

    def test_never_returns_empty(self):
        self.assertTrue(w.resolve_name("(PC) Standard Global").strip())


class WyrelRegistryTests(unittest.TestCase):
    def test_registered_and_domain_locked(self):
        cfg = merchant_config("Wyrel")
        self.assertIs(cfg, w.CONFIG)
        self.assertEqual(cfg.domain, "wyrel.com")
        self.assertIs(cfg.precheck, w.precheck)
        self.assertIs(cfg.title_region, w.title_region)
        self.assertIs(cfg.resolve_name, w.resolve_name)

    def test_no_page_read_and_platform_stays_title_sourced(self):
        cfg = merchant_config("Wyrel")
        self.assertIsNone(cfg.offer_page_resolver)
        self.assertFalse(cfg.publisher_from_merchant_page)
        self.assertTrue(cfg.title_is_platform_source)

    def test_on_the_safe_auto_allowlist_with_its_feed_store(self):
        """Liste blanche le 2026-09-24 (Romain : « Go Wyrel, corrige le motif, puis whitelist
        ce marchand »), avec son store de feed 162 — et dans un groupe de balayage."""

        from src.admin.auto_merchants import AUTO_MERCHANTS
        from src.merchant_groups import GROUPS
        self.assertIn(("Wyrel", "162"), AUTO_MERCHANTS)
        self.assertEqual([g for g, noms in GROUPS.items() if "Wyrel" in noms], ["B"])


if __name__ == "__main__":
    unittest.main()

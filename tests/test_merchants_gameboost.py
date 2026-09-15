"""GameBoost grammar (R47, 2026-09-15) — src/merchants/gameboost.py.

The rows are verbatim from the live feed (store 157, page 1, 2026-09-15). The load-bearing
decision under test is R47: a GameBoost title with NO region word is a fail-closed skip,
never the generic implicit GLOBAL — the region of those rows is only on the merchant page,
which is Cloudflare-blocked (the same blocker that got the 2026-07-15 batch cancelled,
R27)."""

import unittest

from src.merchants import gameboost as gb
from src.merchants.registry import merchant_config


class GameBoostRegionSlotTests(unittest.TestCase):
    def test_region_read_from_the_end_of_the_title(self):
        for name, expected in (
            ("Wardogs (PC) - Steam Key - United States", "United States"),
            ("Wardogs | Supporter Edition (PC) - Steam Key - Canada", "Canada"),
            ("Warhammer: Chaosbane | Slayer Edition (PC) - Steam Key - EUROPE", "EUROPE"),
            ("Hunt: Showdown 1896 - Bones and Bounties (PC) - Steam Key - GLOBAL", "GLOBAL"),
            ("Stronghold 2: Steam Edition Steam Key EU", "EU"),
            ("Sekiro: Shadows Die Twice (GOTY) (Xbox One) (EU)", "EU"),
            ("Marvel’s Spider-Man 2 (Deluxe Edition) (Steam) (NA)", "NA"),
            ("PAYDAY 2: The Butcher's BBQ Pack DLC Steam Key ROW", "ROW"),
            ("Blasphemous - Steam - Key (NORTH AMERICA)", "NORTH AMERICA"),
        ):
            with self.subTest(name=name):
                self.assertEqual(gb.region_slot(name), expected)

    def test_no_region_slot(self):
        for name in (
            "Adaptory (Steam)",
            "Command & Conquer 3: Kane's Wrath (DLC) (EA App)",
            "Dying Light 2: Stay Human (Extras Edition) (Steam)",
            "Forza Motorsport 7 (Ultimate Edition) (Xbox One/Win 10)",
            "StarDrive 2 Gold Pack",
        ):
            with self.subTest(name=name):
                self.assertIsNone(gb.region_slot(name))

    def test_a_region_word_inside_the_game_name_is_not_the_slot(self):
        # only the TRAILING slot counts — mining mid-title would mis-read these
        self.assertIsNone(gb.region_slot("Stronghold 2: Steam Edition Steam Key"))
        self.assertIsNone(gb.region_slot("Europa Universalis IV (Steam)"))
        self.assertIsNone(gb.region_slot("The Last of Us Part II (PS5)"))


class GameBoostPrecheckTests(unittest.TestCase):
    URL = "https://gameboost.com/x-00-1"

    def test_r47_missing_region_is_a_fail_closed_skip(self):
        reason = gb.precheck("Adaptory (Steam)", "https://gameboost.com/adaptory-steam-00-61728")
        self.assertIsNotNone(reason)
        self.assertIn("R47", reason)
        self.assertIn("no region", reason)

    def test_sellable_regions_pass(self):
        for name in (
            "Wardogs (PC) - Steam Key - United States",
            "Hunt: Showdown 1896 - Bones and Bounties (PC) - Steam Key - GLOBAL",
            "Stronghold 2: Steam Edition Steam Key EU",
            "Sekiro: Shadows Die Twice (GOTY) (Xbox One) (EU)",
        ):
            with self.subTest(name=name):
                self.assertIsNone(gb.precheck(name, self.URL))

    def test_region_locks_are_refused_with_the_shared_labels(self):
        for name, label in (
            ("Wardogs (PC) - Steam Key - Turkey", "TURKEY"),
            ("Wardogs | Supporter Edition (PC) - Steam Key - Canada", "CANADA"),
            ("SCUM Eastern Furniture DLC (PC) - Steam Key - ROW", "ROW"),
            ("Blasphemous - Steam - Key (NORTH AMERICA)", "NORTH AMERICA"),
            ("Marvel’s Spider-Man 2 (Deluxe Edition) (Steam) (NA)", "NORTH AMERICA"),
        ):
            with self.subTest(name=name):
                self.assertEqual(gb.precheck(name, self.URL), f"forbidden region: {label}")

    def test_non_game_listings_are_categorical_skips(self):
        for name, url in (
            ("Razer · Chile · 500 CLP", "https://gameboost.com/gift-cards/razer/chile/500-clp"),
            ("Amazon · Poland · 500 PLN", "https://gameboost.com/gift-cards/amazon/poland/500-pln"),
            ("Valorant · Singapore · 26 SGD",
             "https://gameboost.com/valorant/gift-cards/singapore/26-sgd"),
            ("Some Game Account", "https://gameboost.com/some-game/accounts/eu-starter"),
            ("Some Game Boost", "https://gameboost.com/some-game/boosting/rank-1"),
        ):
            with self.subTest(url=url):
                reason = gb.precheck(name, url)
                self.assertIsNotNone(reason)
                self.assertIn("not a game", reason)

    def test_a_game_key_url_is_never_a_non_game_skip(self):
        self.assertIsNone(
            gb.precheck("Wardogs (PC) - Steam Key - United States",
                        "https://gameboost.com/wardogs-pc-steam-key-united-states-00-78984"))


class GameBoostTitleRegionTests(unittest.TestCase):
    def test_bases(self):
        for name, base in (
            ("Wardogs (PC) - Steam Key - United States", "us"),
            ("Warhammer: Chaosbane | Slayer Edition (PC) - Steam Key - EUROPE", "eu"),
            ("Stronghold 2: Steam Edition Steam Key EU", "eu"),
            ("Hunt: Showdown 1896 - Bones and Bounties (PC) - Steam Key - GLOBAL", "global"),
            ("RoadCraft Year 1 Anniversary Edition (PC) - Steam Key - Global", "global"),
        ):
            with self.subTest(name=name):
                self.assertEqual(gb.title_region(name), base)

    def test_no_slot_and_locks_yield_no_base(self):
        self.assertIsNone(gb.title_region("Adaptory (Steam)"))
        self.assertIsNone(gb.title_region("Wardogs (PC) - Steam Key - Turkey"))


class GameBoostResolveNameTests(unittest.TestCase):
    def test_the_trailing_run_is_peeled(self):
        for name, expected in (
            ("Wardogs | Supporter Edition (PC) - Steam Key - United States",
             "Wardogs | Supporter Edition"),
            ("Hunt: Showdown 1896 - Bones and Bounties (PC) - Steam Key - GLOBAL",
             "Hunt: Showdown 1896 - Bones and Bounties"),
            ("Blasphemous - Steam - Key (NORTH AMERICA)", "Blasphemous"),
            ("Date Everything! - Xbox Series X Key, PC - ROW", "Date Everything!"),
            ("Microsoft Flight Simulator 2024 | Premium Deluxe Edition "
             "(Xbox Series X/S, Windows 10) - Xbox Live Key - United States",
             "Microsoft Flight Simulator 2024 | Premium Deluxe Edition"),
            ("Life is Strange: Double Exposure (Ultimate Edition) (Xbox Series X|S)",
             "Life is Strange: Double Exposure (Ultimate Edition)"),
        ):
            with self.subTest(name=name):
                self.assertEqual(gb.resolve_name(name), expected)

    def test_the_other_platform_spellings_are_peeled(self):
        # vocabulary confirmed on the 821 rows of pages 1-10 (2026-09-15)
        for name, expected in (
            # both trailing runs are peeled: the console phrase is a TARGET, not a name word
            ("Star Fox (Nintendo Switch 2) - Nintendo eShop Key - United States", "Star Fox"),
            ("METAL GEAR SOLID V: GROUND ZEROES Steam Gift GLOBAL",
             "METAL GEAR SOLID V: GROUND ZEROES"),
            ("Citizen Sleeper Helion Collection Xbox/One/Series/Xbox/Windows 11 Key "
             "UNITED STATES", "Citizen Sleeper Helion Collection"),
            ("Sid Meier's Civilization VII (Xbox One/ Xbox Series X|S) (EU)",
             "Sid Meier's Civilization VII"),
        ):
            with self.subTest(name=name):
                self.assertEqual(gb.resolve_name(name), expected)

    def test_a_platform_word_inside_the_name_survives(self):
        # the peel is anchored at the END — "Steam Edition" is part of the product
        self.assertEqual(gb.resolve_name("Stronghold 2: Steam Edition Steam Key EU"),
                         "Stronghold 2: Steam Edition")
        self.assertEqual(gb.resolve_name("Nintendo Switch Sports (Switch) (EU)"),
                         "Nintendo Switch Sports")
        self.assertEqual(
            gb.resolve_name("STRANGER OF PARADISE FINAL FANTASY ORIGIN (Deluxe Edition) "
                            "(Steam) (EU)"),
            "STRANGER OF PARADISE FINAL FANTASY ORIGIN (Deluxe Edition)")

    def test_the_edition_is_never_peeled(self):
        self.assertEqual(gb.resolve_name("Sekiro: Shadows Die Twice (GOTY) (Xbox One) (EU)"),
                         "Sekiro: Shadows Die Twice (GOTY)")
        self.assertEqual(gb.resolve_name("Forza Motorsport 7 (Ultimate Edition) (Xbox One/Win 10)"),
                         "Forza Motorsport 7 (Ultimate Edition)")

    def test_never_returns_empty(self):
        self.assertEqual(gb.resolve_name("(Steam)"), "(Steam)")


class GameBoostRegistryTests(unittest.TestCase):
    def test_registered_and_domain_locked(self):
        cfg = merchant_config("GameBoost")
        self.assertIs(cfg, gb.CONFIG)
        self.assertEqual(cfg.domain, "gameboost.com")
        self.assertIs(cfg.precheck, gb.precheck)
        self.assertIs(cfg.title_region, gb.title_region)
        self.assertIs(cfg.resolve_name, gb.resolve_name)
        self.assertIs(cfg.console_region_slot, gb.console_region_slot)

    def test_the_platform_stays_title_sourced_and_the_page_is_never_read(self):
        # R27: GameBoost's offer page is Cloudflare-blocked — no page resolver, ever.
        cfg = merchant_config("GameBoost")
        self.assertIsNone(cfg.offer_page_resolver)
        self.assertTrue(cfg.title_is_platform_source)
        self.assertFalse(cfg.url_platform_scan)

    def test_gameboost_is_not_on_the_safe_auto_allowlist(self):
        from src.admin.auto_merchants import AUTO_MERCHANTS
        self.assertNotIn("GameBoost", [n for n, _ in AUTO_MERCHANTS])
        self.assertNotIn("Gameboost", [n for n, _ in AUTO_MERCHANTS])


if __name__ == "__main__":
    unittest.main()

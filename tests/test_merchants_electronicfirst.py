"""Electronicfirst grammar (R49, 2026-09-15) — src/merchants/electronicfirst.py.

Rows are verbatim from the whole pending feed of the day (store 70, 323 unique rows, four
pages, coverage proven). The load-bearing decision under test is R49c: a CONSOLE row with an
empty region slot is refused — there is no worldwide PSN / Xbox SKU, and left to the generic
implicit GLOBAL seven rows (four of them full games) would have been filed worldwide.

The PC side keeps the generic implicit GLOBAL, but only as long as the merchant never writes
an explicit worldwide word. ``test_the_validity_condition_of_the_implicit_global`` pins that
measurement: the day Electronicfirst writes GLOBAL / Worldwide / WW in a slot, the empty slot
becomes ambiguous and R47's fail-closed skip must be applied to every silent row."""

import unittest

from src.merchants import electronicfirst as ef
from src.merchants.common import sellable_base
from src.merchants.registry import merchant_config

URL = "https://www.electronicfirst.com/x-pc-steam-cd-key"


class ElectronicfirstSlotTests(unittest.TestCase):
    def test_the_code_sits_before_the_platform_phrase(self):
        for name, expected in (
            ("Sonic Superstars: Deluxe Edition featuring LEGO EU Steam CD Key", "EU"),
            ("Fable - Premium Edition Upgrade DLC US Xbox Series X|S / PC CD Key", "US"),
            ("Cities XL (2009) EU PC Steam CD Key", "EU"),
            ("GRANDIA HD Remastered Collection EU XBOX One / Xbox Series X|S CD Key", "EU"),
            ("RIOT- Civil Unrest PC EU XBOX One / Xbox Series X|S CD Key", "EU"),
            ("Two Point Hospital: Healthy Collection Vol. 4 Bundle RoW Steam CD Key", "RoW"),
            ("Warhammer 40,000: Dawn of War IV Commander Edition EU/NA PC Steam CD Key",
             "EU/NA"),
            ("Endzone 2 EU/US/JP PC Steam CD Key", "EU/US/JP"),
        ):
            with self.subTest(name=name):
                self.assertEqual(ef.region_slot(name), expected)

    def test_grammar_b_puts_the_code_last(self):
        for name, expected in (
            ("Mortal Kombat: Legacy Kollection PS4 / PS5 UK", "UK"),
            ("Wreckreation  PS4/PS5 US", "US"),
            ("Age of Empires IV: Anniversary Deluxe Edition PS5 US", "US"),
        ):
            with self.subTest(name=name):
                self.assertEqual(ef.region_slot(name), expected)

    def test_an_empty_slot(self):
        for name in (
            "Worm In Rotating Land PC Steam CD Key",
            "Forza Motorsport Xbox Series X|S / PC CD Key",
            "Le Mans Ultimate",
            "Darksiders Franchise Pack pre-2015 Steam Gift",
        ):
            with self.subTest(name=name):
                self.assertIsNone(ef.region_slot(name))

    def test_a_lower_case_or_name_word_is_never_the_code(self):
        # the slot is written in CAPITALS 323/323 — "Us" / "Row" stay name words
        self.assertIsNone(ef.region_slot("The Last of Us Part II PS5 CD Key"))
        self.assertIsNone(ef.region_slot("Saints Row Gold Edition Steam CD Key"))


class ElectronicfirstPrecheckTests(unittest.TestCase):
    def test_non_game_listings(self):
        for name, marker in (
            ("Lieferando €25 Voucher DE", "STORED VALUE"),
            ("£120 PlayStation PSN Card UK", "STORED VALUE"),
            ("VALORANT USD 14.99 CD Key US", "STORED VALUE"),
            ("Roblox Game eCard 100 Robux", "GAME CARD"),
            ("PS Plus Premium 1 Month (US)", "SUBSCRIPTION"),
            ("Dragon Ball: The Breakers - TP Token 5400 XBOX One CD Key", "TOKEN"),
        ):
            with self.subTest(name=name):
                reason = ef.precheck(name, URL)
                self.assertIsNotNone(reason)
                self.assertIn(marker, reason)

    def test_a_real_game_is_never_taken_for_a_card(self):
        # a bare "Card" / "Game" word must not fire — these two are real games
        self.assertIsNone(ef.precheck("Cards and Towers", URL))
        self.assertIsNone(ef.precheck("Parkour Game 2 PC Steam CD Key", URL))

    def test_software_licences(self):
        for name, url in (
            ("TechSmith Camtasia Studio 8 PC CD Key (2 PCs)", URL),
            ("Kofax OmniPage 19.2 Ultimate Key (Unlimited Devices)", URL),
            ("MS Visio Professional 2019 Bind Key", URL),
            ("MS Office 2013 Professional Plus ISO Key", URL),
            ("Some Suite", "https://www.electronicfirst.com/some-suite-lifetime-key"),
        ):
            with self.subTest(name=name):
                reason = ef.precheck(name, url)
                self.assertIsNotNone(reason)
                self.assertIn("software licence", reason)

    def test_r49a_a_partial_eu_key_is_refused(self):
        for name in (
            "Hero's Hour EU (without DE/NL/PL/AT) PS5 CD Key",
            "Granblue Fantasy: Relink - Day One DLC EU (without DE) PS4 CD Key",
            "Teslagrad 2 EU (without DE/NL/PL) PS5 CD Key",
        ):
            with self.subTest(name=name):
                reason = ef.precheck(name, URL)
                self.assertIsNotNone(reason)
                self.assertIn("R49a", reason)
                self.assertIn("partial EU", reason)

    def test_region_locks_use_the_shared_labels(self):
        for name, label in (
            ("Two Point Hospital: Healthy Collection Vol. 4 Bundle RoW Steam CD Key", "ROW"),
            ("Warhammer 40,000: Dawn of War IV Commander Edition EU/NA PC Steam CD Key",
             "EU NA"),
            ("Destroy All Humans! 2 Reprobed NA PS4 CD Key", "NORTH AMERICA"),
            ("Endzone 2 EU/US/JP PC Steam CD Key", "JAPAN"),
        ):
            with self.subTest(name=name):
                self.assertEqual(ef.precheck(name, URL), f"forbidden region: {label}")

    def test_r49b_a_spelled_out_region_in_the_name_with_an_empty_slot_is_refused(self):
        reason = ef.precheck(
            "Big Adventure: Trip to Europe 9 - Collector's Edition PC Steam CD Key", URL)
        self.assertIsNotNone(reason)
        self.assertIn("R49b", reason)
        self.assertIn("Europe", reason)

    def test_r49c_a_console_row_with_an_empty_slot_is_refused(self):
        # the seven rows that would otherwise be filed worldwide — four are full games
        for name in (
            "Forza Motorsport Xbox Series X|S / PC CD Key",
            "Forza Motorsport Premium Edition Xbox Series X|S / PC CD Key",
            "Microsoft Flight Simulator 2024 Premium Deluxe Edition  Xbox Series X|S / PC Key",
            "Horror Adventure : Zombie Edition VR PS4 / PS5 CD Key",
            "Madden NFL 24 - Travis Kelce 85 OVR MUT Pack XBOX One Key",
            "Super Animal Royale - Season 7 Perks Pack XBOX One / Xbox Series X|S / "
            "Windows 10 CD Key",
        ):
            with self.subTest(name=name):
                reason = ef.precheck(name, URL)
                self.assertIsNotNone(reason, "a silent console row must never be worldwide")
                self.assertIn("R49c", reason)

    def test_a_console_row_that_declares_its_region_passes(self):
        for name in (
            "GRANDIA HD Remastered Collection EU XBOX One / Xbox Series X|S CD Key",
            "Fable - Premium Edition Upgrade DLC US Xbox Series X|S / PC CD Key",
            "Mortal Kombat: Legacy Kollection PS4 / PS5 UK",
        ):
            with self.subTest(name=name):
                self.assertIsNone(ef.precheck(name, URL))

    def test_a_pc_row_with_an_empty_slot_passes(self):
        # the provisional implicit-GLOBAL side — see the module docstring
        for name in (
            "Worm In Rotating Land PC Steam CD Key",
            "Guild Wars 2: Secret of the Obscure Digital Download CD Key",
            "Darksiders Franchise Pack pre-2015 Steam Gift",
        ):
            with self.subTest(name=name):
                self.assertIsNone(ef.precheck(name, URL))


class ElectronicfirstTitleRegionTests(unittest.TestCase):
    def test_bases(self):
        self.assertEqual(ef.title_region("Cities XL (2009) EU PC Steam CD Key"), "eu")
        self.assertEqual(
            ef.title_region("Total War: WARHAMMER III - Thrones of Decay DLC US PC Steam "
                            "CD Key"), "us")
        self.assertEqual(ef.title_region("Mortal Kombat: Legacy Kollection PS4 / PS5 UK"),
                         "uk")

    def test_an_empty_slot_leaves_the_generic_default(self):
        self.assertIsNone(ef.title_region("Worm In Rotating Land PC Steam CD Key"))

    def test_the_slot_is_read_positionally_not_by_scanning(self):
        # "US" inside the product name must not become the region
        self.assertIsNone(ef.title_region("Real VR Fishing - US WEST COAST DLC PC Steam "
                                          "CD Key"))


class ElectronicfirstResolveNameTests(unittest.TestCase):
    def test_the_trailing_run_is_peeled(self):
        for name, expected in (
            ("Worm In Rotating Land PC Steam CD Key", "Worm In Rotating Land"),
            ("Hero's Hour EU (without DE/NL/PL/AT) PS5 CD Key", "Hero's Hour"),
            ("RIOT- Civil Unrest PC EU XBOX One / Xbox Series X|S CD Key",
             "RIOT- Civil Unrest"),
            ("Fable - Premium Edition Upgrade DLC US Xbox Series X|S / PC CD Key",
             "Fable - Premium Edition Upgrade DLC"),
            ("Mortal Kombat: Legacy Kollection PS4 / PS5 UK", "Mortal Kombat: Legacy Kollection"),
            ("Fishing: Barents Sea West EU (retail) Steam CD Key",
             "Fishing: Barents Sea West"),
        ):
            with self.subTest(name=name):
                self.assertEqual(ef.resolve_name(name), expected)

    def test_a_bare_title_is_returned_untouched(self):
        self.assertEqual(ef.resolve_name("Le Mans Ultimate"), "Le Mans Ultimate")

    def test_never_returns_empty(self):
        for name in ("Steam CD Key", "PC Steam CD Key", "EU Steam CD Key"):
            with self.subTest(name=name):
                self.assertTrue(ef.resolve_name(name).strip(),
                                "resolve_name must never hand an empty text to resolution")


class ElectronicfirstRegistryTests(unittest.TestCase):
    def test_registered_and_domain_locked(self):
        cfg = merchant_config("Electronicfirst")
        self.assertIs(cfg, ef.CONFIG)
        self.assertEqual(cfg.domain, "electronicfirst.com")
        self.assertIs(cfg.precheck, ef.precheck)
        self.assertIs(cfg.title_region, ef.title_region)
        self.assertIs(cfg.resolve_name, ef.resolve_name)

    def test_platform_stays_title_sourced_and_no_console_hook(self):
        cfg = merchant_config("Electronicfirst")
        self.assertTrue(cfg.title_is_platform_source)
        self.assertIsNone(cfg.url_platform)
        self.assertFalse(cfg.url_platform_scan)
        self.assertIsNone(cfg.offer_page_resolver)
        self.assertIsNone(cfg.console_url_families)
        self.assertIsNone(cfg.console_region_slot)

    def test_on_the_safe_auto_allowlist_since_2026_09_16(self):
        """Romain, 2026-09-16 : « On va whitelist Eletronicfirst et Gamersoutlet ».
        Dé-parqué le même jour : le défaut qui l'avait fait parquer — 2 lignes entrées
        PUBLISHER au lieu de STEAM sur un titre nu — est fermé par [R51]."""

        from src.admin.auto_merchants import AUTO_MERCHANTS, rejection_reason
        self.assertIn(("Electronicfirst", "70"), AUTO_MERCHANTS)
        self.assertIsNone(rejection_reason("Electronicfirst", "70"))

    # The distinct slot values measured on the WHOLE feed of 2026-09-15 (323 rows).
    CORPUS_SLOTS_2026_09_15 = ("EU", "US", "UK", "NA", "FR", "RoW", "EMEA",
                               "EU/NA", "EU/US/JP", "UK/US")

    def test_the_validity_condition_of_the_implicit_global(self):
        """The PC side may only keep the generic implicit GLOBAL while Electronicfirst
        writes NO explicit worldwide word in its slot. Pinned on the frozen vocabulary of
        2026-09-15: not one of its slot values resolves to "global". Re-measure on every
        fresh corpus — the day a slot reads "global", the empty slot becomes ambiguous and
        R47's fail-closed skip must be applied to every silent row (see the module
        docstring)."""

        for slot in self.CORPUS_SLOTS_2026_09_15:
            with self.subTest(slot=slot):
                self.assertNotEqual(
                    sellable_base(slot), "global",
                    f"{slot!r} now reads as worldwide — re-read R49 before entering the "
                    "silent rows as GLOBAL")

    def test_a_worldwide_word_would_be_visible_if_it_appeared(self):
        """The trigger above is detectable: a "WW" slot WOULD parse and WOULD read global."""

        self.assertEqual(ef.region_slot("Some Game WW PC Steam CD Key"), "WW")
        self.assertEqual(sellable_base("WW"), "global")


if __name__ == "__main__":
    unittest.main()

"""GamersOutlet grammar (R48, 2026-09-15) — src/merchants/gamersoutlet.py.

Rows are verbatim from the whole pending feed of the day (store 31, 20 rows, one page). The
load-bearing decisions under test: the "(<delivery> / <region>)" slot is MANDATORY (the
merchant writes "Global" explicitly 20/20, so a silent title has no proven meaning), and the
accepted stores are this module's own table — the same table ``url_platform`` publishes to
the matcher, so the gate and the platform can never drift."""

import unittest

from src.merchants import gamersoutlet as go
from src.merchants.registry import merchant_config

URL = "https://www.gamers-outlet.net/en/x-pc-steam-key-global"


class GamersOutletSlotTests(unittest.TestCase):
    def test_slot_halves(self):
        for name, expected in (
            ("Polylithic (PC Steam Key / Global)", ("PC Steam Key", "Global")),
            ("Grand Theft Auto V Enhanced (PC Rockstar Key / Global)",
             ("PC Rockstar Key", "Global")),
            ("Adobe Photoshop 2026 (Windows) (Lifetime License / Global)",
             ("Lifetime License", "Global")),
            ("Autodesk AutoCAD 2022 (Windows) (Lifetime/ Global) Commercial Version",
             ("Lifetime", "Global")),
        ):
            with self.subTest(name=name):
                self.assertEqual(go.slot(name), expected)

    def test_the_slot_need_not_end_the_title(self):
        # 1/20 rows carry a qualifier after the slot — the anchor is the GROUP
        self.assertIsNotNone(go.slot("Autodesk AutoCAD 2022 (Windows) (Lifetime/ Global) "
                                     "Commercial Version"))

    def test_no_slot(self):
        self.assertIsNone(go.slot("Bare Title With No Slot"))
        self.assertIsNone(go.slot("Some Game (Windows)"))

    def test_the_region_half_is_the_longest_readable_final_run(self):
        # a console delivery keeps its own slashes; the region is what the shared
        # vocabulary reads as ONE region
        self.assertEqual(go.slot("Halo (Xbox One / Xbox Series X|S Key / Global)"),
                         ("Xbox One / Xbox Series X|S Key", "Global"))
        self.assertEqual(go.slot("Game (PC Steam Key / EU/NA)"), ("PC Steam Key", "EU/NA"))


class GamersOutletPrecheckTests(unittest.TestCase):
    def test_r48_a_title_without_a_slot_is_refused(self):
        reason = go.precheck("Bare Title With No Slot",
                             "https://www.gamers-outlet.net/en/bare-title")
        self.assertIsNotNone(reason)
        self.assertIn("R48", reason)
        self.assertIn("never implicit", reason)

    def test_sellable_regions_pass(self):
        for name in (
            "Polylithic (PC Steam Key / Global)",
            "Grand Theft Auto V (PC Rockstar Key / Global)",
            "Adobe Photoshop 2026 (Windows) (Lifetime License / Global)",
        ):
            with self.subTest(name=name):
                self.assertIsNone(go.precheck(name, URL))

    def test_region_locks_are_refused(self):
        self.assertEqual(
            go.precheck("Game (PC Steam Key / Turkey)",
                        "https://www.gamers-outlet.net/en/game-pc-steam-key-turkey"),
            "forbidden region: TURKEY")
        self.assertEqual(
            go.precheck("Game (PC Steam Key / EU/NA)",
                        "https://www.gamers-outlet.net/en/game-pc-steam-key-eu-na"),
            "forbidden region: EU NA")

    def test_an_unknown_region_word_is_refused_by_name(self):
        reason = go.precheck("Game (PC Steam Key / Neverland)",
                             "https://www.gamers-outlet.net/en/game-pc-steam-key-neverland")
        self.assertIsNotNone(reason)
        self.assertIn("unknown region slot", reason)

    def test_a_store_without_an_aks_bucket_is_refused_never_defaulted(self):
        # the four Robux rows of the corpus stop here, and so would EA / Blizzard spellings
        for name, store in (
            ("Roblox 800 Robux (PC Roblox Key / Global)", "ROBLOX"),
            ("Fifa 21 (PC EA Key / Global)", "EA"),
            ("Diablo IV (PC Blizzard Key / Global)", "BLIZZARD"),
            ("Some Game (PC Windows Store Key / Global)", "WINDOWS STORE"),
        ):
            with self.subTest(store=store):
                reason = go.precheck(name, URL)
                self.assertIsNotNone(reason, f"{store} must not pass")
                self.assertIn("unknown store", reason)
                self.assertIn(store, reason)

    def test_the_title_url_region_conflict_is_refused(self):
        reason = go.precheck("Game (PC Steam Key / EU)",
                             "https://www.gamers-outlet.net/en/game-pc-steam-key-global")
        self.assertIsNotNone(reason)
        self.assertIn("title/URL region conflict", reason)
        reason = go.precheck("Game (PC Steam Key / Global)",
                             "https://www.gamers-outlet.net/en/game-pc-steam-key-turkey")
        self.assertIn("title/URL region conflict", reason or "")

    def test_equivalent_spellings_are_not_a_conflict(self):
        """Audit 2026-09-16: the two sides must MEAN the same region, not spell it the same
        way — the merchant writes "Global" in the title and "-worldwide" in the slug, "EU"
        and "-europe", "US" and "-united-states"."""

        for title, slug in (
            ("Game (PC Steam Key / Global)", "game-pc-steam-key-worldwide"),
            ("Game (PC Steam Key / EU)", "game-pc-steam-key-europe"),
            ("Game (PC Steam Key / US)", "game-pc-steam-key-united-states"),
            ("Game (PC Steam Key / UK)", "game-pc-steam-key-united-kingdom"),
        ):
            with self.subTest(slug=slug):
                self.assertIsNone(
                    go.precheck(title, "https://www.gamers-outlet.net/en/" + slug))

    def test_a_slug_without_a_region_run_is_tolerated(self):
        # the merchant's slugs are not always faithful (one corpus slug drops "-mac-")
        self.assertIsNone(go.precheck("Game (PC Steam Key / Global)",
                                      "https://www.gamers-outlet.net/en/game-pc-steam-key"))

    def test_a_console_delivery_is_handed_to_the_shared_classifier(self):
        self.assertIsNone(go.precheck("Halo (Xbox One / Xbox Series X|S Key / Global)",
                                      "https://www.gamers-outlet.net/en/halo-xbox-key-global"))

    def test_a_software_licence_keeps_the_generic_route(self):
        self.assertIsNone(go.precheck("Microsoft Office 2027 Professional Plus "
                                      "(Lifetime License / Global)", URL))


class GamersOutletTitleRegionTests(unittest.TestCase):
    def test_the_slot_wins_over_a_region_word_in_the_product_name(self):
        # without the hook the generic scan reads the "EU" of the NAME and files a
        # worldwide key under EU
        self.assertEqual(
            go.title_region("Train Sim World 4: EU Loco Add-On (PC Steam Key / Global)"),
            "global")

    def test_bases(self):
        self.assertEqual(go.title_region("Game (PC Steam Key / Global)"), "global")
        self.assertEqual(go.title_region("Game (PC Steam Key / EU)"), "eu")
        self.assertEqual(go.title_region("Game (PC Steam Key / US)"), "us")
        self.assertIsNone(go.title_region("Bare Title"))


class GamersOutletUrlPlatformTests(unittest.TestCase):
    def test_the_slug_store_run(self):
        for url, token in (
            ("https://www.gamers-outlet.net/en/polylithic-pc-steam-key-global", "STEAM"),
            ("https://www.gamers-outlet.net/en/grand-theft-auto-v-pc-rockstar-key-global",
             "ROCKSTAR"),
        ):
            with self.subTest(url=url):
                self.assertEqual(go.url_platform(url), token)

    def test_a_software_slug_declares_no_store(self):
        self.assertIsNone(go.url_platform(
            "https://www.gamers-outlet.net/en/adobe-photoshop-2026-windows-lifetime-license-global"))

    def test_an_unknown_store_slug_declares_nothing(self):
        self.assertIsNone(go.url_platform(
            "https://www.gamers-outlet.net/en/roblox-800-robux-pc-roblox-key-global"))

    def test_the_gate_and_the_platform_read_the_same_table(self):
        # the adversarial review of 2026-09-15: a hand-copied allow-list drifts
        for store in go.STORE_PLATFORM:
            with self.subTest(store=store):
                name = f"Game (PC {store.title()} Key / Global)"
                self.assertIsNone(go.precheck(name, URL), f"{store} is in the table")


class GamersOutletResolveNameTests(unittest.TestCase):
    def test_the_slot_and_the_os_group_are_removed(self):
        for name, expected in (
            ("Polylithic (PC Steam Key / Global)", "Polylithic"),
            ("shapez 2 Supporter Edition (PC Steam Key / Global)",
             "shapez 2 Supporter Edition"),
            ("Adobe Photoshop 2026 (Windows) (Lifetime License / Global)",
             "Adobe Photoshop 2026"),
            ("Autodesk AutoCAD 2022 (Windows) (Lifetime/ Global) Commercial Version",
             "Autodesk AutoCAD 2022 Commercial Version"),
            ("Hunt: Showdown 1896 - Sage of Joseon DLC (PC Steam Key / Global)",
             "Hunt: Showdown 1896 - Sage of Joseon DLC"),
        ):
            with self.subTest(name=name):
                self.assertEqual(go.resolve_name(name), expected)

    def test_never_returns_empty(self):
        self.assertEqual(go.resolve_name("(PC Steam Key / Global)"), "(PC Steam Key / Global)")


class GamersOutletRegistryTests(unittest.TestCase):
    def test_registered_and_domain_locked(self):
        cfg = merchant_config("GamersOutlet")
        self.assertIs(cfg, go.CONFIG)
        self.assertEqual(cfg.domain, "gamers-outlet.net")
        self.assertIs(cfg.precheck, go.precheck)
        self.assertIs(cfg.title_region, go.title_region)
        self.assertIs(cfg.resolve_name, go.resolve_name)
        self.assertIs(cfg.url_platform, go.url_platform)

    def test_no_console_hook_and_no_page_resolver(self):
        cfg = merchant_config("GamersOutlet")
        self.assertIsNone(cfg.offer_page_resolver)
        self.assertIsNone(cfg.console_url_families)
        self.assertIsNone(cfg.console_region_slot)

    def test_off_the_safe_auto_allowlist(self):
        from src.admin.auto_merchants import AUTO_MERCHANTS
        self.assertNotIn("GamersOutlet", [n for n, _ in AUTO_MERCHANTS])


if __name__ == "__main__":
    unittest.main()

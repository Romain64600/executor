"""REGION_IDS vs the live AKS region dropdown (audit 2026-09-16).

Romain, 2026-09-16: « pour les regions Rockstar on a toutes les regions dont tu as besoin
meme la globale, verifie mieux, tu dois pouvoir aller chercher ca dans le drop down des
regions sur l'outil AKS feed. »

He was right, and the same defect existed on two neighbours. The dropdown (`catalog.json`,
867 options, identical across the 11 catalogs saved between 2026-09-10 and 2026-09-15)
carries buckets that `REGION_IDS` never mapped, so the matcher fail-closed on
"no region id for <PLATFORM>/<BASE>" — a FALSE refusal, not a missing bucket. Counted on
every saved run: ROCKSTAR 35 rows (global 29, uk 4, eu 2), EA/US 9, EPIC/US 8.

These tests pin the ids AND the shape of the fix, so a later edit cannot silently drop them
again. The ids are verbatim option values of the dropdown:

    Rockstar (15) · Rockstar US (151) · Rockstar EU (152) · Rockstar UK (158)
    Epic Store US (80us) · Epic Store UK (805)
    Origin US (3us) · Origin UK (3uk)

The plain "Rockstar (15)" option IS the global bucket — the dropdown carries no "Rockstar
GLOBAL" label, exactly like "Publisher (1)"."""

import unittest

from src.matcher import REGION_IDS

# Region LOCKS of the same families — they are forbidden regions, never bases, and must
# never be mapped into REGION_IDS.
ROCKSTAR_LOCK_IDS = {
    "157": "Rockstar APAC", "155": "Rockstar ASIA", "153": "Rockstar EMEA",
    "154": "Rockstar LATAM", "156": "Rockstar ROW", "335": "ROCKSTAR FRANCE",
    "336": "Rockstar Germany", "337": "Rockstar Netherlands", "338": "Rockstar MIDDLE EAST",
}


class RockstarRegionTests(unittest.TestCase):
    def test_the_four_bases_are_mapped(self):
        self.assertEqual(REGION_IDS["ROCKSTAR"]["global"], "15")
        self.assertEqual(REGION_IDS["ROCKSTAR"]["us"], "151")
        self.assertEqual(REGION_IDS["ROCKSTAR"]["eu"], "152")
        self.assertEqual(REGION_IDS["ROCKSTAR"]["uk"], "158")

    def test_the_gmg_gift_bucket_is_unchanged(self):
        self.assertEqual(REGION_IDS["ROCKSTAR"]["gmg_gift"], "159")

    def test_no_lock_is_mapped_as_a_base(self):
        mapped = set(REGION_IDS["ROCKSTAR"].values())
        for lock_id, label in ROCKSTAR_LOCK_IDS.items():
            with self.subTest(label=label):
                self.assertNotIn(lock_id, mapped,
                                 f"{label} is a region LOCK, never a base bucket")


class EpicRegionTests(unittest.TestCase):
    def test_us_and_uk_are_mapped(self):
        self.assertEqual(REGION_IDS["EPIC"]["us"], "80us")
        self.assertEqual(REGION_IDS["EPIC"]["uk"], "805")

    def test_global_and_eu_are_unchanged(self):
        self.assertEqual(REGION_IDS["EPIC"]["global"], "80")
        self.assertEqual(REGION_IDS["EPIC"]["eu"], "80eu")


class EaRegionTests(unittest.TestCase):
    def test_us_and_uk_are_mapped(self):
        # the EA family is spelled "Origin" in the dropdown
        self.assertEqual(REGION_IDS["EA"]["us"], "3us")
        self.assertEqual(REGION_IDS["EA"]["uk"], "3uk")

    def test_global_and_eu_are_unchanged(self):
        self.assertEqual(REGION_IDS["EA"]["global"], "3")
        self.assertEqual(REGION_IDS["EA"]["eu"], "3eu")


class GiftBucketTests(unittest.TestCase):
    """R50, second pass (2026-09-16) — Romain: « si ça existe le fichier marchand ne devrait
    pas affirmer le contraire, fix la config marchand ». The merchant files stated that no
    ``gift_us`` / ``gift_uk`` existed on any platform; the dropdown has carried them all
    along. What genuinely does NOT exist stays absent, and stays fail-closed."""

    def test_steam_gift_bases(self):
        gifts = REGION_IDS["STEAM"]
        self.assertEqual(gifts["gift"], "25")          # Steam Gift (25)
        self.assertEqual(gifts["gift_eu"], "259")      # Steam Gift EU (259)
        self.assertEqual(gifts["gift_us"], "2577")     # Steam Gift US (2577)
        self.assertEqual(gifts["gift_uk"], "2572")     # Steam Gift UK (2572)

    def test_battlenet_gift_bases(self):
        gifts = REGION_IDS["BATTLENET"]
        self.assertEqual(gifts["gift"], "570")         # Battlenet Gift Global (570)
        self.assertEqual(gifts["gift_eu"], "567")      # Battlenet Gift EU (567)
        self.assertEqual(gifts["gift_us"], "568")      # Battlenet Gift US (568)
        self.assertNotIn("gift_uk", gifts, "the dropdown has no Battle.net gift UK")

    def test_ubisoft_gift_bases(self):
        gifts = REGION_IDS["UBISOFT"]
        self.assertEqual(gifts["gift"], "501")         # Ubisoft Gift (501)
        self.assertEqual(gifts["gift_eu"], "504")      # Ubisoft Gift EU (504)
        self.assertEqual(gifts["gift_us"], "505")      # Ubisoft Gift US (505)
        self.assertNotIn("gift_uk", gifts, "the dropdown has no Ubisoft gift UK")

    def test_platforms_the_dropdown_gives_no_plain_gift_stay_unmapped(self):
        for platform in ("EA", "EPIC", "GOG", "PUBLISHER", "ROCKSTAR"):
            with self.subTest(platform=platform):
                self.assertNotIn("gift", REGION_IDS[platform],
                                 "no plain gift option for this platform in the dropdown — "
                                 "the row must keep failing closed")

    def test_gmg_gift_uk_exists_on_no_platform(self):
        for platform, buckets in REGION_IDS.items():
            with self.subTest(platform=platform):
                self.assertNotIn("gmg_gift_uk", buckets)


class RegionTableShapeTests(unittest.TestCase):
    PC_PLATFORMS = ("STEAM", "GOG", "UBISOFT", "EPIC", "EA", "ROCKSTAR", "BATTLENET",
                    "PUBLISHER")

    def test_every_pc_platform_now_carries_the_four_bases(self):
        """After the 2026-09-16 audit every PC platform we resolve has global / eu / us / uk
        — the dropdown carries them all, so a missing one is a mapping bug, not a policy."""

        for platform in self.PC_PLATFORMS:
            with self.subTest(platform=platform):
                for base in ("global", "eu", "us", "uk"):
                    self.assertIn(base, REGION_IDS[platform],
                                  f"{platform} has no {base} bucket mapped — check the "
                                  "dropdown before assuming it does not exist")

    def test_ids_are_non_empty_strings(self):
        for platform, buckets in REGION_IDS.items():
            for base, value in buckets.items():
                with self.subTest(platform=platform, base=base):
                    self.assertIsInstance(value, str)
                    self.assertTrue(value.strip())


if __name__ == "__main__":
    unittest.main()

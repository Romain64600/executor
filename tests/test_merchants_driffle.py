"""tests for src/merchants/driffle.py — the Driffle grammar file (2026-09-14, R32 / R45).

Fixtures are real rows of the 2026-09-12 batch (runs/20260912-020000-auto-driffle-s127-p1..6,
464 rows). The bracket read must give the SAME base as the generic parens / URL scan on
every sellable row (the hook is the explicit, tested source of that read)."""

import dataclasses
import pathlib
import re
import unittest

import src.matcher as M
from src.console_keys import classify_console
from src.matcher import NormalizedOffer, detect_region_base, precheck_skip
from src.merchant_config import MerchantConfig
from src.merchants import driffle
from src.merchants.driffle import (
    CONFIG,
    console_region_slot,
    console_url_families,
    precheck,
    region_bracket,
    title_region,
)

URL = "https://www.driffle.com/x-global-pc-steam-digital-key-p9999999"


def _offer(name, url=URL):
    return NormalizedOffer(offer_id="1", name=name, url=url, merchant="Driffle")


class _Registry(unittest.TestCase):
    def _use(self, cfg):
        saved = M.MERCHANT_CONFIGS.get("DRIFFLE")
        if cfg is None:
            M.MERCHANT_CONFIGS.pop("DRIFFLE", None)
        else:
            M.MERCHANT_CONFIGS["DRIFFLE"] = cfg

        def restore():
            if saved is None:
                M.MERCHANT_CONFIGS.pop("DRIFFLE", None)
            else:
                M.MERCHANT_CONFIGS["DRIFFLE"] = saved

        self.addCleanup(restore)


class BracketTests(unittest.TestCase):
    def test_region_bracket_is_the_first_vocabulary_bracket(self):
        cases = {
            "Fatal Fury City of the Wolves Special Edition (Global) (PC) - Steam - Digital Key": "Global",
            "Uncle Billy's Dream Bundle (Europe) (PC) - Steam - Digital Key": "Europe",
            "Apex Legends 1000 Coins (United States) - EA Play - Digital Key": "United States",
            "SMITE 2 Ultimate Founder's Edition (United Kingdom) (Xbox Series X|S) - Xbox Live - Digital Key": "United Kingdom",
            "Tom Clancy's Rainbow Six Siege (EU) (PC) - Ubisoft - Digital Key": "EU",
            "DRAGON BALL Sparking! ZERO (United States / Canada) (PC) - Steam - Digital Key": "United States / Canada",
            "Microsoft Flight Simulator (2020) 40th Anniversary Edition (Europe) (PC) - Steam - Digital Key": "Europe",
            "Yakuza Kiwami 2 (2025) (Global) (PC) - Steam - Digital Key": "Global",
            "Lords and Villeins Lords and Bards Bundle (EN/CS) (Global) (PC) - Steam - Digital Key": "Global",
            "Need for Speed Unbound Pre-Order Bonus DLC (EN) (Global) (PC) - EA Play - Digital Key": "Global",
            "Mario Kart 8 Deluxe - Booster Course Pass DLC (Hong Kong) (Nintendo Switch) - Nintendo - Digital Key": "Hong Kong",
            "Xbox Game Pass Core (Essential) 1 Month (Latvia) - Xbox Live - Digital Key": "Latvia",
            "Little Nightmares - Tengu Mask DLC (SIEE) (PS4) - PSN - Digital Key": None,
            "EA SPORTS MVP Bundle (Madden NFL 26 Deluxe Edition and College Football 26 Deluxe Edition) (Global) (Xbox Series X|S) - Xbox Live - Digital Key": "Global",
            "World of Warcraft - 5000 Hearthsteel (Global) (PC / Mac) - Battle.net Gift": "Global",
            "PUBG Mobile - 9900 Unknown Cash": None,
            "Game (PC / PS5 / Xbox Series X|S) - Xbox Live - Digital Key": None,
        }
        for title, bracket in cases.items():
            with self.subTest(title=title):
                self.assertEqual(region_bracket(title), bracket)
                self.assertEqual(console_region_slot(title), bracket)


class HooksTests(_Registry):
    SELLABLE = {
        "Fatal Fury City of the Wolves Special Edition (Global) (PC) - Steam - Digital Key": "global",
        "Uncle Billy's Dream Bundle (Europe) (PC) - Steam - Digital Key": "eu",
        "Apex Legends 1000 Coins (United States) - EA Play - Digital Key": "us",
        "Tom Clancy's Rainbow Six Siege (EU) (PC) - Ubisoft - Digital Key": "eu",
        "Yakuza Kiwami 2 (2025) (Global) (PC) - Steam - Digital Key": "global",
    }

    def test_title_region(self):
        for title, base in self.SELLABLE.items():
            with self.subTest(title=title):
                self.assertEqual(title_region(title), base)
                self.assertIsNone(precheck(title, URL))
        self.assertIsNone(title_region("PUBG Mobile - 9900 Unknown Cash"))
        self.assertIsNone(title_region("Little Nightmares - Tengu Mask DLC (SIEE) (PS4) - PSN - Digital Key"))

    def test_read_is_identical_to_the_generic_scan_on_sellable_rows(self):
        rows = {
            "Fatal Fury City of the Wolves Special Edition (Global) (PC) - Steam - Digital Key": "https://www.driffle.com/fatal-fury-city-of-the-wolves-special-edition-global-pc-steam-digital-key-p9928732",
            "Uncle Billy's Dream Bundle (Europe) (PC) - Steam - Digital Key": "https://www.driffle.com/uncle-billys-dream-bundle-europe-pc-steam-digital-key-p9997792",
            "Apex Legends 1000 Coins (United States) - EA Play - Digital Key": "https://www.driffle.com/apex-legends-1000-coins-united-states-ea-play-digital-key-p9936198",
            "SMITE 2 Ultimate Founder's Edition (United Kingdom) (PC) - Steam - Digital Key": "https://www.driffle.com/smite-2-ultimate-founders-edition-united-kingdom-pc-steam-digital-key-p1",
            "Syberia trilogy (Europe) (PC) - Steam - Digital Key": "https://www.driffle.com/syberia-trilogy-eu-pc-steam-digital-key-p9896737",
            "Arena Breakout - Advanced Battle Pass": "https://www.driffle.com/arena-breakout-advanced-battle-pass-p9998821",
        }
        for title, url in rows.items():
            with self.subTest(title=title):
                offer = _offer(title, url)
                self._use(None)
                generic = detect_region_base(offer)
                self._use(CONFIG)
                self.assertEqual(detect_region_base(offer), generic)

    def test_precheck_country_brackets_outside_the_generic_vocabulary(self):
        cases = {
            "Fortnite - 12500 V-Bucks Card (France) - Epic Games - Digital Key": "FRANCE",
            "Tinder Gold 1 Month Subscription (Austria) - Digital Key": "AUSTRIA",
            "Tinder Plus - 1 Month Subscription (Netherlands) - Digital Key": "NETHERLANDS",
            "Tinder Gold 1 Month Subscription (Belgium) - Digital Key": "BELGIUM",
            "Tinder Plus - 12 Months Subscription (Egypt) - Digital Key": "EGYPT",
            "Mario Kart 8 Deluxe - Booster Course Pass DLC (Hong Kong) (Nintendo Switch) - Nintendo - Digital Key": "HONG KONG",
            "Xbox Game Pass Core (Essential) 1 Month (Latvia) - Xbox Live - Digital Key": "LATVIA",
            "Xbox Game Pass Core (Essential) 1 Month (Lithuania) - Xbox Live - Digital Key": "LITHUANIA",
            "Xbox Game Pass Core (Essential) 1 Month (Romania) - Xbox Live - Digital Key": "ROMANIA",
            # the generic vocabulary already had these: same label, same routing
            "MARVEL Tōkon Fighting Souls Ultimate Edition (Asia) (PC) - Steam - Digital Key": "ASIA",
            "For The King II - Smoke and Steel Cosmetic Pack DLC (MENA) (PC) - Steam - Digital Key": "MENA",
            "Xbox 500 TRY Gift Card (Turkey) - Digital Key": "TURKEY",
            "Onimusha 1+2 Pack (ROW) (PC) - Steam - Digital Key": "ROW",
            "FINAL FANTASY (North America) (PC) - Steam Gift": "NORTH AMERICA",
            "DRAGON BALL Sparking! ZERO (United States / Canada) (PC) - Steam - Digital Key": "CANADA",
        }
        for title, label in cases.items():
            with self.subTest(title=title):
                self.assertEqual(precheck(title, URL), f"forbidden region: {label}")
                self.assertIsNone(title_region(title))
        self._use(CONFIG)
        self.assertEqual(precheck_skip(_offer("Fortnite - 12500 V-Bucks Card (France) - Epic Games - Digital Key",
                                              "https://www.driffle.com/fortnite-12500-v-bucks-card-france-epic-games-digital-key-p9998874")),
                         "forbidden region: FRANCE")
        self.assertIn("merchant-domain mismatch", precheck_skip(_offer("Game (Global) (PC) - Steam - Digital Key", "https://www.g2a.com/x")))


class ConsoleHooksTests(unittest.TestCase):
    ROWS = {
        "Sniper Ghost Warrior Contracts 1 and 2 Double Pack (Europe) (Xbox One / Xbox Series X|S) - Xbox Live - Digital Key": "Europe",
        "NBA 2K27 - 15000 VC (Global) (Xbox Series X|S) - Xbox Live - Digital Key": "Global",
        "SMITE 2 Ultimate Founder's Edition (United Kingdom) (Xbox Series X|S) - Xbox Live - Digital Key": "United Kingdom",
        "Mario Kart 8 Deluxe - Booster Course Pass DLC (Hong Kong) (Nintendo Switch) - Nintendo - Digital Key": "Hong Kong",
        "Fortnite - Shaka Surfin' Pack DLC (South Africa) (PC / Xbox One / Xbox Series X|S) - Xbox Live - Digital Key": "South Africa",
        "Everspace 2 Galactic Edition (Europe) (Nintendo Switch 2) - Nintendo - Digital Key": "Europe",
        "Little Nightmares - Tengu Mask DLC (SIEE) (PS4) - PSN - Digital Key": None,
    }

    def test_region_slot_agrees_with_the_shared_read(self):
        for title, slot in self.ROWS.items():
            with self.subTest(title=title):
                self.assertEqual(console_region_slot(title), slot)
                sig = classify_console(title, "https://www.driffle.com/x-europe-xbox-series-xs-xbox-live-digital-key-p1", "Driffle")
                self.assertEqual(sig.region_words[:1], (slot,) if slot else ())

    def test_url_families(self):
        cases = {
            "https://www.driffle.com/sniper-ghost-warrior-contracts-1-and-2-double-pack-europe-xbox-one-xbox-series-xs-xbox-live-digital-key-p9988263": ("XBOX_ONE", "XBOX_SERIES"),
            "https://www.driffle.com/the-elder-scrolls-online-explorers-pack-dlc-europe-ps4-ps5-psn-digital-key-p9955436": ("PS4", "PS5"),
            "https://www.driffle.com/syberia-trilogy-eu-nintendo-switch-nintendo-digital-code-p9896737": ("SWITCH",),
            "https://www.driffle.com/martha-is-dead-digital-deluxe-europe-pc-xbox-one-xbox-series-xs-xbox-live-digital-key-p9988246": ("XBOX_ONE", "XBOX_SERIES"),
            "https://www.driffle.com/x-global-xbox-series-xs-xbox-live-digital-key-p1": ("XBOX_SERIES",),
            "https://www.driffle.com/x-europe-nintendo-switch-2-nintendo-digital-key-p1": ("SWITCH2",),
            "https://www.driffle.com/x-global-ps5-psn-digital-key-p1": ("PS5",),
            "https://www.driffle.com/uncle-billys-dream-bundle-europe-pc-steam-digital-key-p9997792": None,
            "https://www.driffle.com/xbox-500-try-gift-card-turkey-digital-key-p10001137": None,
        }
        for url, families in cases.items():
            with self.subTest(url=url):
                self.assertEqual(console_url_families(url), families)


class ConfigTests(unittest.TestCase):
    def test_config_declares_the_hooks(self):
        self.assertIsInstance(CONFIG, MerchantConfig)
        self.assertEqual((CONFIG.name, CONFIG.domain), ("Driffle", "driffle.com"))
        self.assertIs(CONFIG.precheck, precheck)
        self.assertIs(CONFIG.title_region, title_region)
        self.assertIsNone(CONFIG.resolve_name)                 # the generic parens + tail peel is enough
        fields = {f.name for f in dataclasses.fields(MerchantConfig)}
        if "console_noise" in fields:
            self.assertEqual(CONFIG.console_noise, ("Digital Key", "Digital Code"))
            self.assertIs(CONFIG.console_region_slot, console_region_slot)
            self.assertIs(CONFIG.console_url_families, console_url_families)
        else:
            self.assertEqual(CONFIG.extra["console_hooks_pending"]["console_noise"], ("Digital Key", "Digital Code"))

    def test_module_imports_no_generic_layer(self):
        src = pathlib.Path(driffle.__file__).read_text(encoding="utf-8")
        self.assertIsNone(re.search(r"^\s*(?:from|import)\s+src\.(?:matcher|console_keys|merchants\.registry)\b", src, re.M))


if __name__ == "__main__":
    unittest.main()

"""tests for src/merchants/g2a.py — the G2A grammar file (2026-09-14, R32 / R45).

The PC platform rules (title_is_platform_source=False, url_platform_scan, offer_page_readable,
green gifts) are pinned by tests/test_matcher.py and untouched; here the region tail
declaration, the console slot / URL hooks and the flags. Fixtures: real rows of the
2026-09-12 batch (runs/20260912-020001-auto-g2a-s38-p1..10, 806 rows)."""

import dataclasses
import pathlib
import re
import unittest

from src.console_keys import classify_console
from src.matcher import NormalizedOffer, detect_region, merchant_config, precheck_skip
from src.merchant_config import MerchantConfig
from src.merchants import g2a
from src.merchants.g2a import (
    CONFIG,
    console_region_slot,
    console_url_families,
    precheck,
    region_tail,
    title_region,
)

URL = "https://www.g2a.com/x-pc-steam-key-global-i10000000000001?___currency=EUR"


def _offer(name, url=URL):
    return NormalizedOffer(offer_id="1", name=name, url=url, merchant="G2A")


class TailTests(unittest.TestCase):
    def test_region_tail_verbatim(self):
        cases = {
            "Puzzle Forge Dungeon (PC) - Steam Gift - EUROPE": "EUROPE",
            "Ultimate Zombie Defense 2 (PC) - Steam Key - NORTH AMERICA": "NORTH AMERICA",
            "Train Sim World 6 | Deluxe Edition (Xbox Series X/S, PC) - Xbox Live Key - UNITED KINGDOM": "UNITED KINGDOM",
            "Grand Theft Auto VI | Standard Edition (Xbox Series X/S) - Xbox Live Key - GLOBAL": "GLOBAL",
            "VALORANT Gift Card 45.98 SGD - Riot Key - SINGAPORE": "SINGAPORE",
            "Hunt: Showdown 1896 - Sage of Joseon (PC) - Steam Key - EUROPE / NORTH AMERICA": "EUROPE / NORTH AMERICA",
            "Murder Mystery 2 Icewing - Roblox Player Trade - GLOBAL": "GLOBAL",
            "Call of Duty: Modern Warfare 3 (2011) (PC) - Microsoft Store Key - UNITED STATES": "UNITED STATES",
            "暖雪 Warm Snow (Xbox Series X/S, PC) - Xbox Live Gift - EUROPE": "EUROPE",
            # old grammar
            "Steam Squad Steam Gift GLOBAL": "GLOBAL",
            "Bulletstorm: Full Clip Edition Steam Key CIS": "CIS",
            "The Sapling - Steam - Gift GLOBAL": "GLOBAL",
            "It's Quiz Time Steam Gift EUROPE": "EUROPE",
            # no region slot
            "Some Game": None,
            "Endzone - A World Apart (PC) - Steam Key": None,
            "Game - DLC": None,
            "Halo Campaign Evolved Shadowfrost Armor (All Devices) - Official Website Key": None,
        }
        for title, tail in cases.items():
            with self.subTest(title=title):
                self.assertEqual(region_tail(title), tail)
                self.assertEqual(console_region_slot(title), tail)


class HooksTests(unittest.TestCase):
    def test_title_region_and_precheck(self):
        for title, base in {
            "Puzzle Forge Dungeon (PC) - Steam Gift - EUROPE": "eu",
            "Neon Beats (PC) - GOG Key - GLOBAL": "global",
            "Neon Beats (PC) - Steam Key - UNITED STATES": "us",
            "Train Sim World 6 | Deluxe Edition (Xbox Series X/S, PC) - Xbox Live Key - UNITED KINGDOM": "uk",
            "Steam Squad Steam Gift GLOBAL": "global",
            "It's Quiz Time Steam Gift EUROPE": "eu",
            "Some Game": None,
        }.items():
            with self.subTest(title=title):
                self.assertEqual(title_region(title), base)
                self.assertIsNone(precheck(title, URL))
        for title, label in {
            "Ultimate Zombie Defense 2 (PC) - Steam Key - NORTH AMERICA": "NORTH AMERICA",
            "VALORANT Gift Card 45.98 SGD - Riot Key - SINGAPORE": "SINGAPORE",
            "Hunt: Showdown 1896 - Sage of Joseon (PC) - Steam Key - EUROPE / NORTH AMERICA": "NORTH AMERICA",
            "Uber Gift Card 150 ZAR - Uber Key - SOUTH AFRICA": "SOUTH AFRICA",
            "Steelrising (PC) - Steam Key - CIS": "CIS",
            "Diablo IV: Lord of Hatred (Xbox Series X/S) - Xbox Live Key - JAPAN": "JAPAN",
            "Bulletstorm: Full Clip Edition Steam Key CIS": "CIS",
            "Game (PC) - Steam Key - MONGOLIA": "MONGOLIA",          # unknown tail → fail-closed, its own text
        }.items():
            with self.subTest(title=title):
                self.assertEqual(precheck(title, URL), f"forbidden region: {label}")
                self.assertIsNone(title_region(title))

    def test_registry_reads_this_config_and_detect_region_is_unchanged(self):
        # G2A was already registered through g2a.CONFIG: the hooks are live. The
        # test_matcher G2A fixtures keep their results.
        self.assertIs(merchant_config("G2A"), CONFIG)
        self.assertEqual(detect_region(_offer("Neon Beats (PC) - Steam Key - EUROPE"), "STEAM"), ("EU", "9", False))
        self.assertEqual(detect_region(_offer("Neon Beats (PC) - Steam Key - UNITED STATES"), "STEAM"), ("US", "8", False))
        self.assertEqual(detect_region(_offer("Neon Beats (PC) - GOG Key - GLOBAL"), "GOG"), ("GLOBAL", "6", False))
        self.assertEqual(detect_region(_offer("Puzzle Forge Dungeon (PC) - Steam Gift - EUROPE"), "STEAM"), ("GIFT EU", "259", False))
        url = "https://www.g2a.com/runescape-pc-key-europe-i10000044281020?___currency=EUR&utm_campaign=COM_GLOBAL_PB"
        self.assertEqual(detect_region(_offer("X", url=url), "STEAM"), ("EU", "9", False))
        self.assertEqual(precheck_skip(_offer("Ultimate Zombie Defense 2 (PC) - Steam Key - NORTH AMERICA")),
                         "forbidden region: NORTH AMERICA")
        self.assertEqual(precheck_skip(_offer("VALORANT Gift Card 45.98 SGD - Riot Key - SINGAPORE")),
                         "forbidden region: SINGAPORE")


class ConsoleHooksTests(unittest.TestCase):
    ROWS = {
        "Shadowrun Trilogy (Xbox Series X/S) - Xbox Live Key - EUROPE": "EUROPE",
        "Train Sim World 6 | Deluxe Edition (Xbox Series X/S, PC) - Xbox Live Key - UNITED KINGDOM": "UNITED KINGDOM",
        "Grand Theft Auto VI | Standard Edition (Xbox Series X/S) - Xbox Live Key - GLOBAL": "GLOBAL",
        "Madden NFL 27 (Xbox Series X/S) - Xbox Live Key - CANADA": "CANADA",
        "Sonic Superstars (Nintendo Switch 2) - Nintendo eShop Key - EUROPE": "EUROPE",
        "Power Rangers: Battle for the Grid | Super Edition Xbox One, PC - Xbox Live Key - EUROPE": "EUROPE",
    }

    def test_region_slot_agrees_with_the_shared_read(self):
        for title, slot in self.ROWS.items():
            with self.subTest(title=title):
                self.assertEqual(console_region_slot(title), slot)
                sig = classify_console(title, "https://www.g2a.com/x-xbox-series-x-s-xbox-live-key-europe-i1", "G2A")
                self.assertEqual(sig.region_words[:1], (slot,))

    def test_url_families(self):
        cases = {
            "https://www.g2a.com/train-sim-world-6-deluxe-edition-xbox-series-x-s-pc-xbox-live-key-united-kingdom-i10000512449018": ("XBOX_SERIES",),
            "https://www.g2a.com/power-rangers-battle-for-the-grid-super-edition-xbox-one-pc-xbox-live-key-europe-i10000191702012": ("XBOX_ONE",),
            "https://www.g2a.com/grand-theft-auto-vi-standard-edition-xbox-series-x-s-xbox-live-key-global-i10000206686051?___currency=EUR": ("XBOX_SERIES",),
            "https://www.g2a.com/x-ps5-psn-key-europe-i1": ("PS5",),
            "https://www.g2a.com/sonic-superstars-nintendo-switch-2-nintendo-eshop-key-europe-i1": ("SWITCH2",),
            "https://www.g2a.com/x-ps5-ps4-xbox-series-x-s-xbox-one-call-of-duty-official-key-global-i1": ("PS5", "PS4", "XBOX_SERIES", "XBOX_ONE"),
            "https://www.g2a.com/puzzle-forge-dungeon-pc-steam-gift-europe-i10000501767004?___currency=EUR": None,
            "https://www.g2a.com/red-dead-redemption-2-pc-green-gift-key-global-i1": None,
        }
        for url, families in cases.items():
            with self.subTest(url=url):
                self.assertEqual(console_url_families(url), families)


class ConfigTests(unittest.TestCase):
    def test_pc_flags_untouched_and_hooks_declared(self):
        self.assertIsInstance(CONFIG, MerchantConfig)
        self.assertEqual(CONFIG.name, "G2A")
        self.assertFalse(CONFIG.title_is_platform_source)
        self.assertTrue(CONFIG.url_platform_scan)
        self.assertFalse(CONFIG.offer_page_readable)
        self.assertIsNone(CONFIG.url_platform)
        self.assertIsNone(CONFIG.resolve_name)
        self.assertIsNone(CONFIG.domain)
        self.assertIs(CONFIG.precheck, precheck)
        self.assertIs(CONFIG.title_region, title_region)
        fields = {f.name for f in dataclasses.fields(MerchantConfig)}
        if "console_region_slot" in fields:
            self.assertIs(CONFIG.console_region_slot, console_region_slot)
            self.assertIs(CONFIG.console_url_families, console_url_families)
            self.assertEqual(CONFIG.console_noise, ())
        else:
            self.assertIs(CONFIG.extra["console_hooks_pending"]["console_region_slot"], console_region_slot)

    def test_module_imports_no_generic_layer(self):
        src = pathlib.Path(g2a.__file__).read_text(encoding="utf-8")
        self.assertIsNone(re.search(r"^\s*(?:from|import)\s+src\.(?:matcher|console_keys|merchants\.registry)\b", src, re.M))


if __name__ == "__main__":
    unittest.main()

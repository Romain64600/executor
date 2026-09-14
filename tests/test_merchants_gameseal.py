"""tests for src/merchants/gameseal.py — the GameSeal grammar file (2026-09-14, R32 / R45).

Fixtures: real rows of the July 2026 sweep (runs/20260715-151202-gameseal, 1 610 rows) — the
only GameSeal data; the merchant has never been swept in safe-auto (dry-run first)."""

import dataclasses
import pathlib
import re
import unittest

import src.matcher as M
from src.console_keys import classify_console
from src.matcher import NormalizedOffer, detect_region_base, precheck_skip
from src.merchant_config import MerchantConfig
from src.merchants import gameseal
from src.merchants.gameseal import (
    CONFIG,
    console_region_slot,
    console_url_families,
    precheck,
    region_tail,
    title_region,
)

URL = "https://gameseal.com/porter-in-the-castle-pc-steam-key-global"


def _offer(name, url=URL):
    return NormalizedOffer(offer_id="1", name=name, url=url, merchant="GameSeal")


class _Registry(unittest.TestCase):
    def _use(self, cfg):
        saved = M.MERCHANT_CONFIGS.get("GAMESEAL")
        if cfg is None:
            M.MERCHANT_CONFIGS.pop("GAMESEAL", None)
        else:
            M.MERCHANT_CONFIGS["GAMESEAL"] = cfg

        def restore():
            if saved is None:
                M.MERCHANT_CONFIGS.pop("GAMESEAL", None)
            else:
                M.MERCHANT_CONFIGS["GAMESEAL"] = saved

        self.addCleanup(restore)


class TailTests(unittest.TestCase):
    def test_region_tail_verbatim(self):
        cases = {
            "Porter in the Castle (PC) Steam Key - GLOBAL": "GLOBAL",
            "Moorhuhn Kart (PC) Steam Gift - EU": "EU",
            "Resident Evil 7: Biohazard Gold Edition (PC) Steam Key - NORTH AMERICA": "NORTH AMERICA",
            "Destroy All Humans! (PC) Steam Key - AU": "AU",
            "War Thunder - US Starter Bundle (DFC) (PC) Steam Gift – GLOBAL": "GLOBAL",     # en dash
            "Disneyland Paris by Inspire 5 GBP Key - UNITED KINGDOM": "UNITED KINGDOM",
            "lastminute.com Travel Gift Card 5 EUR Key - BELGIUM": "BELGIUM",
            "Arena of Valor - 150 Voucher Direct Top-Up - EU": "EU",
            "Another World - 20th Anniversary Edition (Xbox One / Xbox Series X|S) Xbox Live Key - EU": "EU",
            "Xbox Game Pass Premium 1 Month - EU": "EU",
            "Xbox Game Pass Essential 1 Month - EU WEST": "EU WEST",
            "Game (PC) Steam Key - EU/NA": "EU/NA",
            "5x Starter Mystery Steam Keys": None,
            "EA Sports: FC 25 XBOX GLOBAL 1050 FC Points Xbox One/Series Global": None,
            "Game - DLC": None,
        }
        for title, tail in cases.items():
            with self.subTest(title=title):
                self.assertEqual(region_tail(title), tail)
                self.assertEqual(console_region_slot(title), tail)


class HooksTests(_Registry):
    def test_title_region(self):
        for title, base in {
            "Porter in the Castle (PC) Steam Key - GLOBAL": "global",
            "Moorhuhn Kart (PC) Steam Gift - EU": "eu",
            "Game (PC) Steam Key - UNITED STATES": "us",
            "Disneyland Paris by Inspire 5 GBP Key - UNITED KINGDOM": "uk",
            "War Thunder - US Starter Bundle (DFC) (PC) Steam Gift – GLOBAL": "global",
            "5x Starter Mystery Steam Keys": None,
        }.items():
            with self.subTest(title=title):
                self.assertEqual(title_region(title), base)
                self.assertIsNone(precheck(title, URL))

    def test_precheck_tails(self):
        for title, label in {
            "Destroy All Humans! (PC) Steam Key - AU": "AUSTRALIA",              # was "extra words: ['AU']"
            "vROVpilot: TITANIC (PC) Steam Gift - NA": "NORTH AMERICA",           # 27 rows, were 404 / "extra words: ['NA']"
            "lastminute.com Travel Gift Card 5 EUR Key - BELGIUM": "BELGIUM",
            "Resident Evil 7: Biohazard Gold Edition (PC) Steam Key - EMEA": "EMEA",
            "VoidBound (PC) Steam Key - ROW": "ROW",
            "Game (PC) Steam Key - EU/NA": "EU NA",                               # the matcher spelling
            "Xbox Game Pass Premium 1 Month - BRAZIL": "BRAZIL",
            "Game (PC) Steam Key - MONGOLIA": "MONGOLIA",                         # unknown tail → fail-closed
        }.items():
            with self.subTest(title=title):
                self.assertEqual(precheck(title, URL), f"forbidden region: {label}")
                self.assertIsNone(title_region(title))

    def test_pipeline(self):
        self._use(CONFIG)
        offer = _offer("Destroy All Humans! (PC) Steam Key - AU", "https://gameseal.com/destroy-all-humans-pc-steam-key-au")
        self.assertEqual(precheck_skip(offer), "forbidden region: AUSTRALIA")
        self.assertEqual(detect_region_base(_offer("Porter in the Castle (PC) Steam Key - GLOBAL")), ("global", "GLOBAL", False, False))
        self.assertEqual(detect_region_base(_offer("Moorhuhn Kart (PC) Steam Gift - EU", "https://gameseal.com/moorhuhn-kart-pc-steam-gift-eu")),
                         ("eu", "EU", False, True))
        self.assertIn("merchant-domain mismatch", precheck_skip(_offer("Game (PC) Steam Key - GLOBAL", "https://www.g2a.com/x")))
        # the /detail/<hex> URL shape is on the domain too
        self.assertIsNone(precheck_skip(_offer("Game (PC) Steam Key - GLOBAL", "https://gameseal.com/detail/019913116fe9736aad9832372663bc77")))


class ConsoleHooksTests(unittest.TestCase):
    def test_region_slot_agrees_with_the_shared_read(self):
        rows = {
            "Another World - 20th Anniversary Edition (Xbox One / Xbox Series X|S) Xbox Live Key - EU": "EU",
            "Rabbids Invasion (Xbox 360 / Xbox One) Xbox Live Key - UNITED STATES": "UNITED STATES",
            "Game (PS4 / PS5) PSN Key - GLOBAL": "GLOBAL",
            "Game (Nintendo Switch) Nintendo Key - UNITED KINGDOM": "UNITED KINGDOM",
        }
        for title, slot in rows.items():
            with self.subTest(title=title):
                self.assertEqual(console_region_slot(title), slot)
                sig = classify_console(title, "https://gameseal.com/x-xbox-one-xbox-series-x-s-xbox-live-key-eu", "GameSeal")
                self.assertEqual(sig.region_words[:1], (slot,))

    def test_url_families(self):
        cases = {
            "https://gameseal.com/another-world-20th-anniversary-edition-xbox-one-xbox-series-x-s-xbox-live-key-eu": ("XBOX_ONE", "XBOX_SERIES"),
            "https://gameseal.com/x-pc-xbox-one-xbox-series-x-s-microsoft-store-key-global": ("XBOX_ONE", "XBOX_SERIES"),
            "https://gameseal.com/x-ps4-ps5-psn-key-global": ("PS4", "PS5"),
            "https://gameseal.com/x-nintendo-switch-nintendo-key-eu": ("SWITCH",),
            "https://gameseal.com/x-xbox-360-xbox-one-xbox-live-key-united-states": "console: Xbox 360 (R45)",
            "https://gameseal.com/porter-in-the-castle-pc-steam-key-global": None,
            "https://gameseal.com/detail/019913116fe9736aad9832372663bc77": None,
        }
        for url, families in cases.items():
            with self.subTest(url=url):
                self.assertEqual(console_url_families(url), families)


class ConfigTests(unittest.TestCase):
    def test_config_declares_the_hooks(self):
        self.assertIsInstance(CONFIG, MerchantConfig)
        self.assertEqual((CONFIG.name, CONFIG.domain), ("GameSeal", "gameseal.com"))
        self.assertIs(CONFIG.precheck, precheck)
        self.assertIs(CONFIG.title_region, title_region)
        self.assertIsNone(CONFIG.resolve_name)
        self.assertIn("dry-run", CONFIG.notes)
        fields = {f.name for f in dataclasses.fields(MerchantConfig)}
        if "console_region_slot" in fields:
            self.assertIs(CONFIG.console_region_slot, console_region_slot)
            self.assertIs(CONFIG.console_url_families, console_url_families)
        else:
            self.assertIs(CONFIG.extra["console_hooks_pending"]["console_region_slot"], console_region_slot)

    def test_module_imports_no_generic_layer(self):
        src = pathlib.Path(gameseal.__file__).read_text(encoding="utf-8")
        self.assertIsNone(re.search(r"^\s*(?:from|import)\s+src\.(?:matcher|console_keys|merchants\.registry)\b", src, re.M))


if __name__ == "__main__":
    unittest.main()

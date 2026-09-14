"""tests for the small merchant files and the shared helpers (2026-09-14, R32 / R45):
src/merchants/common.py, allyouplay.py, cjs.py, and the console-contract additions to
instant_gaming.py and difmark.py."""

import dataclasses
import pathlib
import re
import unittest
from unittest import mock

from src.merchant_config import MerchantConfig, MerchantOfferSignals
from src.merchants import allyouplay, cjs, common, difmark, driffle, g2a, gameseal, instant_gaming, k4g, kinguin
from src.merchants.common import (
    CONSOLE_HOOK_FIELDS,
    REGION_SLUGS,
    compound_region_kind,
    config_has_field,
    forbidden_reason,
    make_config,
    region_alternation,
    region_kind,
    sellable_base,
    skip_not_a_game,
)

MERCHANT_MODULES = (kinguin, k4g, driffle, g2a, gameseal, allyouplay, cjs, instant_gaming, difmark)


class CommonVocabularyTests(unittest.TestCase):
    def test_region_kind_case_rules(self):
        self.assertEqual(region_kind("US"), ("base", "us"))
        self.assertEqual(region_kind("EU"), ("base", "eu"))
        self.assertEqual(region_kind("GB"), ("base", "uk"))
        self.assertEqual(region_kind("European Union"), ("base", "eu"))
        self.assertEqual(region_kind("United  States"), ("base", "us"))
        self.assertEqual(region_kind("GLOBAL"), ("base", "global"))
        self.assertEqual(region_kind("Worldwide"), ("base", "global"))
        # short tokens only in capitals; "RoW" is Kinguin's own spelling
        for word in ("Us", "Uk", "Ca", "Row", "Sea", "us", "eu"):
            self.assertIsNone(region_kind(word), word)
        self.assertEqual(region_kind("RoW"), ("forbidden", "ROW"))
        self.assertEqual(region_kind("ROW"), ("forbidden", "ROW"))
        self.assertEqual(region_kind("SEA"), ("forbidden", "SOUTH EAST ASIA"))
        self.assertEqual(region_kind("UAE"), ("forbidden", "UNITED ARAB EMIRATES"))
        # long names case-insensitive, label = the matcher vocabulary
        self.assertEqual(region_kind("Canada"), ("forbidden", "CANADA"))
        self.assertEqual(region_kind("hong kong"), ("forbidden", "HONG KONG"))
        self.assertEqual(region_kind("South Korea"), ("forbidden", "KOREA"))
        self.assertEqual(region_kind("EU/NA"), ("forbidden", "EU NA"))
        self.assertEqual(region_kind("Asia"), ("forbidden", "ASIA"))
        for word in ("", "  ", "SIEE", "Essential", "2020", "PC", "II", "HD", "EN", "Egypt City"):
            self.assertIsNone(region_kind(word), word)

    def test_compound_slots(self):
        self.assertEqual(compound_region_kind("United States / Canada"), ("forbidden", "CANADA"))
        self.assertEqual(compound_region_kind("EUROPE / NORTH AMERICA"), ("forbidden", "NORTH AMERICA"))
        self.assertEqual(compound_region_kind("EU / Europe"), ("base", "eu"))
        self.assertEqual(compound_region_kind("EU / US"), ("forbidden", "EU / US"))     # two buckets → none
        self.assertIsNone(compound_region_kind("PC / PS5 / Xbox Series X|S"))
        self.assertIsNone(compound_region_kind("EN/CS"))
        self.assertEqual(forbidden_reason("Canada"), "forbidden region: CANADA")
        self.assertIsNone(forbidden_reason("Europe"))
        self.assertIsNone(forbidden_reason("SIEE"))
        self.assertEqual(sellable_base("Europe"), "eu")
        self.assertIsNone(sellable_base("Canada"))

    def test_labels_route_like_the_matcher_vocabulary(self):
        from src.aks_lists import suggest_target_list
        self.assertEqual(suggest_target_list(forbidden_reason("CA")), "33")
        self.assertEqual(suggest_target_list(forbidden_reason("AU")), "32")
        self.assertEqual(suggest_target_list(forbidden_reason("BR")), "8")
        self.assertEqual(suggest_target_list(forbidden_reason("SEA")), "8")           # "asia" keyword
        self.assertIsNone(suggest_target_list(forbidden_reason("RoW")))
        self.assertIsNone(suggest_target_list(forbidden_reason("TR")))

    def test_region_alternation_and_slugs(self):
        import re
        rx = re.compile(r"^(?:" + region_alternation() + r")$", re.IGNORECASE)
        for word in ("US", "CA", "RoW", "Europe", "EUROPE", "hong kong", "United  States", "EU/NA"):
            self.assertIsNotNone(rx.match(word), word)
        for word in ("Us", "Row", "Sea", "ca", "Egypt City"):
            self.assertIsNone(rx.match(word), word)
        for slug in ("united-states", "north-america", "europe", "global", "eu-na", "row", "united-arab-emirates"):
            self.assertIn(slug, REGION_SLUGS)

    def test_skip_strings_mirror_console_keys(self):
        from src.console_keys import SKIP_PC_ONLY, SKIP_XBOX_360, _skip_not_a_game
        self.assertEqual(common.SKIP_XBOX_360, SKIP_XBOX_360)
        self.assertEqual(common.SKIP_PC_ONLY, SKIP_PC_ONLY)
        self.assertEqual(skip_not_a_game("ACCOUNT"), _skip_not_a_game("ACCOUNT"))

    def test_make_config_compat_shim(self):
        hook = lambda url: None   # noqa: E731
        cfg = make_config("X", domain="x.com", console_url_families=hook, console_noise=("A",))
        self.assertIsInstance(cfg, MerchantConfig)
        self.assertEqual((cfg.name, cfg.domain), ("X", "x.com"))
        if config_has_field("console_url_families"):
            self.assertIs(cfg.console_url_families, hook)
            self.assertEqual(cfg.console_noise, ("A",))
            self.assertNotIn("console_hooks_pending", cfg.extra)
        else:
            pending = cfg.extra["console_hooks_pending"]
            self.assertIs(pending["console_url_families"], hook)
            self.assertEqual(pending["console_noise"], ("A",))
        with self.assertRaises(TypeError):
            make_config("X", not_a_field=1)
        self.assertEqual(set(CONSOLE_HOOK_FIELDS),
                         {"console_url_families", "console_pc_declared", "console_region_slot", "console_noise"})

    def test_merchant_modules_never_import_the_generic_layers(self):
        for mod in MERCHANT_MODULES + (common,):
            src = pathlib.Path(mod.__file__).read_text(encoding="utf-8")
            self.assertIsNone(
                re.search(r"^\s*(?:from|import)\s+src\.(?:matcher|console_keys|merchants\.registry)\b", src, re.M),
                f"{mod.__name__} imports a generic layer")


class NeverSweptMerchantsTests(unittest.TestCase):
    def test_allyouplay_and_cjs_declare_identity_only(self):
        for mod, name, domain in ((allyouplay, "Allyouplay", "allyouplay.com"), (cjs, "CJS-CDKeys", "cjs-cdkeys.com")):
            with self.subTest(merchant=name):
                cfg = mod.CONFIG
                self.assertIsInstance(cfg, MerchantConfig)
                self.assertEqual((cfg.name, cfg.domain), (name, domain))
                self.assertIn("dry-run", cfg.notes)
                for hook in ("precheck", "title_region", "resolve_name", "url_platform", "offer_page_resolver"):
                    self.assertIsNone(getattr(cfg, hook), hook)
                for hook in CONSOLE_HOOK_FIELDS:
                    if config_has_field(hook):
                        self.assertEqual(getattr(cfg, hook), () if hook == "console_noise" else None, hook)
                self.assertNotIn("console_hooks_pending", cfg.extra)
                self.assertTrue(pathlib.Path(mod.__file__).name in ("allyouplay.py", "cjs.py"))

    def test_registry_names_of_auto_merchants(self):
        # the spellings the allowlist uses must be the CONFIG names (case-folded by the registry)
        from src.admin.auto_merchants import AUTO_MERCHANTS
        names = {n for n, _ in AUTO_MERCHANTS}
        self.assertIn(allyouplay.CONFIG.name, names)
        self.assertIn(cjs.CONFIG.name, names)


class InstantGamingConsoleTests(unittest.TestCase):
    def test_url_declares_nothing(self):
        for url in ("https://www.instant-gaming.com/en/21871-/", "https://www.instant-gaming.com/en/1-buy-x/", ""):
            self.assertIsNone(instant_gaming.console_url_families(url))
        if config_has_field("console_url_families"):
            self.assertIs(instant_gaming.CONFIG.console_url_families, instant_gaming.console_url_families)
        self.assertIs(instant_gaming.CONFIG.offer_page_resolver, instant_gaming.ig_offer_signals)

    def test_console_platform_read_on_the_ig_page_yields_platform_none(self):
        # a Switch / Xbox / PlayStation read from the page is not in IG_PLATFORM_TEXT_MAP →
        # MerchantOfferSignals.platform None → the R32 resolver path skips (no console entry)
        for raw in ("NINTENDO SWITCH", "XBOX", "PLAYSTATION 5", "XBOX SERIES X|S"):
            self.assertIsNone(instant_gaming.IG_PLATFORM_TEXT_MAP.get(raw), raw)
        attrs = instant_gaming.IgOfferAttributes(raw_platform="NINTENDO SWITCH", raw_region="")
        with mock.patch.object(instant_gaming, "resolve_ig_offer", return_value=attrs):
            sig = instant_gaming.ig_offer_signals("https://www.instant-gaming.com/en/21871-/")
        self.assertIsInstance(sig, MerchantOfferSignals)
        self.assertIsNone(sig.platform)
        self.assertEqual((sig.region_resolved, sig.region_base), (True, "global"))


class DifmarkConsoleTests(unittest.TestCase):
    def test_account_urls_are_the_account_skip(self):
        for url in (
            "https://difmark.com/en/buy-console-account-fatal-run-2089-pc-epic-games-account-149270",
            "https://difmark.com/en/buy-console-account-snap-and-grab-epic-games-account-171159?referal=allkeyshop",
            "https://difmark.com/en/buy-console-account-x-nintendo-switch-2-account-188000",
            "https://difmark.com/en/buy-console-account-rogue-loops-steam-account-166307?marketplace_id=2",
            "https://difmark.com/en/x-nintendo-switch-account-1",
            "https://difmark.com/en/x-account",
        ):
            with self.subTest(url=url):
                self.assertEqual(difmark.console_url_families(url), "console: ACCOUNT — not a game (R45)")
        for url in ("https://difmark.com/en/buy-x-steam-key-1", "https://difmark.com/en/my-account-settings-page", ""):
            with self.subTest(url=url):
                self.assertIsNone(difmark.console_url_families(url))

    def test_config_keeps_the_url_ignore_and_declares_the_hook(self):
        cfg = difmark.CONFIG
        self.assertEqual(cfg.url_ignore_substrings, ("buy-console-account-", "buy-console-account"))
        if config_has_field("console_url_families"):
            self.assertIs(cfg.console_url_families, difmark.console_url_families)
        else:
            self.assertIs(cfg.extra["console_hooks_pending"]["console_url_families"], difmark.console_url_families)


class EveryModuleExportsAConfigTests(unittest.TestCase):
    def test_config_objects(self):
        for mod in MERCHANT_MODULES:
            with self.subTest(module=mod.__name__):
                self.assertIsInstance(mod.CONFIG, MerchantConfig)
                self.assertTrue(mod.CONFIG.name)
                # every declared console hook is a callable / tuple of the right shape
                for hook in CONSOLE_HOOK_FIELDS:
                    if not config_has_field(hook):
                        continue
                    value = getattr(mod.CONFIG, hook)
                    if hook == "console_noise":
                        self.assertIsInstance(value, tuple)
                    else:
                        self.assertTrue(value is None or callable(value), hook)
        self.assertEqual({f.name for f in dataclasses.fields(MerchantConfig)} >= {"precheck", "title_region", "resolve_name"}, True)


if __name__ == "__main__":
    unittest.main()

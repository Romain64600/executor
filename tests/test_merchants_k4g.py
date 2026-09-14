"""tests for src/merchants/k4g.py — the K4G grammar file (2026-09-14, R32 / R45).

Fixtures are real rows of the 2026-09-12 batch (runs/20260912-020000-auto-k4g-s92-p1..7, 592
rows). Pipeline tests patch the registry dict (src.matcher.MERCHANT_CONFIGS) in place."""

import dataclasses
import pathlib
import re
import unittest

import src.matcher as M
from src.console_keys import classify_console
from src.matcher import (
    AksResolution,
    Candidate,
    NormalizedOffer,
    build_slug_candidates,
    detect_region_base,
    match_offer,
    precheck_skip,
)
from src.merchant_config import MerchantConfig
from src.merchants import k4g
from src.merchants.k4g import (
    CONFIG,
    OPEN_QUESTION_ALTERGIFT,
    SKIP_ALTERGIFT,
    console_region_slot,
    console_url_families,
    is_altergift,
    parse_title,
    precheck,
    region_text,
    resolve_name,
    title_region,
)

URL = "https://k4g.com/product/x-steam-global-instant-cd-key-cd-key-AE3VLW0N"


def _offer(name, url=URL):
    return NormalizedOffer(offer_id="1", name=name, url=url, merchant="K4G")


class _Registry(unittest.TestCase):
    def _use(self, cfg):
        saved = M.MERCHANT_CONFIGS.get("K4G")
        if cfg is None:
            M.MERCHANT_CONFIGS.pop("K4G", None)
        else:
            M.MERCHANT_CONFIGS["K4G"] = cfg

        def restore():
            if saved is None:
                M.MERCHANT_CONFIGS.pop("K4G", None)
            else:
                M.MERCHANT_CONFIGS["K4G"] = saved

        self.addCleanup(restore)


class GrammarTests(unittest.TestCase):
    def test_real_rows(self):
        cases = {
            "Broken Sword - Shadow of the Templars: Reforged Europe Steam CD Key": ("Broken Sword - Shadow of the Templars: Reforged", "Europe", "CD Key"),
            "Monster Hunter Wilds Gold Edition Europe Steam CD Key": ("Monster Hunter Wilds Gold Edition", "Europe", "CD Key"),
            "Goblin Vyke: The Thief Tycoon Steam CD Key": ("Goblin Vyke: The Thief Tycoon", None, "CD Key"),
            "Mato Anomalies North America Steam Altergift": ("Mato Anomalies", "North America", "Altergift"),
            "Champions of Anteria United States Ubisoft Connect CD Key": ("Champions of Anteria", "United States", "CD Key"),
            "Age of Empires II: Definitive Edition - Victors and Vanquished North America Steam CD Key": ("Age of Empires II: Definitive Edition - Victors and Vanquished", "North America", "CD Key"),
            "Persona 5 Royal Canada XBOX One/PC/XBOX Series X|S CD Key": ("Persona 5 Royal", "Canada", "CD Key"),
            "Trepang2 Standard Edition Europe PC/XBOX Series X|S CD Key": ("Trepang2 Standard Edition", "Europe", "CD Key"),
            "Pokémon Scarlet Europe Nintendo Switch 2 CD Key": ("Pokémon Scarlet", "Europe", "CD Key"),
            "Borderlands 3 Ultimate Edition Europe PS4/PS5 CD Key": ("Borderlands 3 Ultimate Edition", "Europe", "CD Key"),
            "Playstation Plus CARD 365 Days United Arab Emirates PSN CD Key": ("Playstation Plus CARD 365 Days", "United Arab Emirates", "CD Key"),
            "Xbox Game Pass Essential (Core) Subscription Card 3 Months Mexico XBOX Live CD Key": ("Xbox Game Pass Essential (Core) Subscription Card 3 Months", "Mexico", "CD Key"),
            "Nintendo eShop Card 25 EUR Luxembourg Nintendo CD Key": ("Nintendo eShop Card 25 EUR", "Luxembourg", "CD Key"),
            "Wirm Steam Account": ("Wirm", None, "Account"),
            "Apex Legends 23000 Coins Ea App Manual Top-Up": ("Apex Legends 23000 Coins", None, "Manual Top-Up"),
        }
        for title, (head, region, delivery) in cases.items():
            with self.subTest(title=title):
                m = parse_title(title)
                self.assertIsNotNone(m)
                self.assertEqual((m.group("head"), m.group("region"), m.group("delivery")), (head, region, delivery))
                self.assertEqual(resolve_name(title), head)
                self.assertEqual(region_text(title), region)

    def test_vendor_titles_are_outside_the_grammar(self):
        for title in (
            "Mifinity eVoucher 100 DKK Denmark Mifinity CD Key",
            "Trend Micro Device Security Pro 3 Years / 6 Devices Trend Micro CD Key",
            "EaseUS Data Recovery Wizard Professional (Mac) 1 Month / 1 Device EaseUS CD Key",
            "Pokémon GO Coins 15500 PokemonGO Manual Top-Up",
            "Bumble Premium 1 Month Bumble Manual Top-Up",
        ):
            with self.subTest(title=title):
                self.assertIsNone(parse_title(title))
                self.assertEqual(resolve_name(title), title)
                self.assertIsNone(precheck(title, URL))
                self.assertIsNone(title_region(title))

    def test_slug_equals_the_generic_peel(self):
        # the test_matcher K4G fixtures: the peeled name yields the SAME first slug
        for title, slug in {
            "Kingdom Two Crowns Call of Olympus Europe Steam CD Key": "kingdom-two-crowns-call-of-olympus",
            "Champions of Anteria United States Ubisoft Connect CD Key": "champions-of-anteria",
            "FIFA 21 Ultimate Edition Europe Steam CD Key": "fifa-21-ultimate-edition",
            "Endless Space - Disharmony Steam CD Key": "endless-space-disharmony",
            "Assassin's Creed Origins Ubisoft Connect CD Key": "assassins-creed-origins",
        }.items():
            with self.subTest(title=title):
                self.assertEqual(build_slug_candidates(resolve_name(title))[0], slug)
                self.assertEqual(build_slug_candidates(title)[0], slug)


class HooksTests(_Registry):
    def test_title_region(self):
        for title, base in {
            "Monster Hunter Wilds Gold Edition Europe Steam CD Key": "eu",
            "Champions of Anteria United States Ubisoft Connect CD Key": "us",
            "Game United Kingdom Steam CD Key": "uk",
            "Tom Clancy's Ghost Recon Breakpoint Gold Edition Global XBOX One/Series X|S CD Key": "global",
            "Goblin Vyke: The Thief Tycoon Steam CD Key": None,
            "Mato Anomalies North America Steam Altergift": None,
        }.items():
            with self.subTest(title=title):
                self.assertEqual(title_region(title), base)

    def test_precheck_forbidden_names(self):
        for title, label in {
            "Age of Empires II: Definitive Edition - Victors and Vanquished North America Steam CD Key": "NORTH AMERICA",
            "Persona 5 Royal Canada XBOX One/PC/XBOX Series X|S CD Key": "CANADA",
            "Xbox Game Pass Essential (Core) Subscription Card 3 Months Mexico XBOX Live CD Key": "MEXICO",
            "Playstation Plus CARD 365 Days United Arab Emirates PSN CD Key": "UNITED ARAB EMIRATES",
            "Nintendo eShop Card 25 EUR Luxembourg Nintendo CD Key": "LUXEMBOURG",
            "Game Asia Steam CD Key": "ASIA",
            "Game EMEA Steam CD Key": "EMEA",
        }.items():
            with self.subTest(title=title):
                self.assertEqual(precheck(title, URL), f"forbidden region: {label}")
        self.assertIsNone(precheck("Monster Hunter Wilds Gold Edition Europe Steam CD Key", URL))

    def test_altergift_is_an_explicit_skip_until_romain_rules(self):
        for title in ("Seafrog Steam Altergift", "Mato Anomalies North America Steam Altergift",
                      "Middle-earth: The Shadow Bundle Europe Steam Altergift"):
            with self.subTest(title=title):
                self.assertTrue(is_altergift(title))
                self.assertEqual(precheck(title, URL), SKIP_ALTERGIFT)
        self.assertFalse(is_altergift("Thief Simulator Europe Steam CD Key"))
        self.assertTrue(SKIP_ALTERGIFT.startswith("skip category: ALTERGIFT"))
        self.assertIn("Altergift", OPEN_QUESTION_ALTERGIFT)
        from src.aks_lists import suggest_target_list
        self.assertIsNone(suggest_target_list(SKIP_ALTERGIFT))       # garder, never a list move

    def test_pipeline_europe_row_enters_eu_on_the_peeled_name(self):
        page = AksResolution(slug="monster-hunter-wilds", url="https://aks/buy-monster-hunter-wilds-cd-key-compare-prices/",
                             product_id="1", aks_name="Monster Hunter Wilds",
                             editions={"1": {"name": "Standard"}, "10": {"name": "Gold"}},
                             official_platforms=("Steam",))
        offer = _offer("Monster Hunter Wilds Gold Edition Europe Steam CD Key",
                       "https://k4g.com/product/monster-hunter-wilds-steam-europe-instant-cd-key-gold-edition-cd-key-ABCDEFGH")
        asked = []

        def resolver(name, **kw):
            asked.append(name)
            return page

        self._use(None)                      # generic (no config)
        self.assertEqual(detect_region_base(offer)[:3], ("eu", "EU", False))
        self._use(CONFIG)
        self.assertEqual(detect_region_base(offer)[:3], ("eu", "EU", False))     # identical read
        r = match_offer(offer, resolver=resolver)
        self.assertIsInstance(r, Candidate, getattr(r, "reason", None))
        self.assertEqual((r.platform, r.region_label, r.region_id, r.edition_label), ("STEAM", "EU", "9", "Gold"))
        self.assertEqual(asked, ["Monster Hunter Wilds Gold Edition"])

    def test_pipeline_precheck(self):
        self._use(CONFIG)
        self.assertEqual(precheck_skip(_offer("Seafrog Steam Altergift")), SKIP_ALTERGIFT)
        self.assertEqual(precheck_skip(_offer("Persona 5 Royal Canada XBOX One/PC/XBOX Series X|S CD Key",
                                              "https://k4g.com/product/persona-5-royal-pc-xbox-one-series-x-s-canada-cd-key-cd-key-IY4ZKGPV")),
                         "forbidden region: CANADA")
        self.assertEqual(precheck_skip(_offer("Wirm Steam Account")), "skip category: STEAM ACCOUNT")   # generic, unchanged
        self.assertIn("merchant-domain mismatch", precheck_skip(_offer("Game Steam CD Key", "https://www.g2a.com/x")))


class ConsoleHooksTests(unittest.TestCase):
    ROWS = {
        "Icarus Console Edition Europe XBOX Series X|S CD Key": "Europe",
        "Mortal Kombat 11 Ultimate Add-On Bundle United States XBOX Series X|S CD Key": "United States",
        "Persona 5 Royal United Kingdom XBOX One/PC/XBOX Series X|S CD Key": "United Kingdom",
        "Persona 5 Royal Canada XBOX One/PC/XBOX Series X|S CD Key": "Canada",
        "Tom Clancy's Ghost Recon Breakpoint Gold Edition Global XBOX One/Series X|S CD Key": "Global",
        "Stardew Valley United States Nintendo Switch 2 CD Key": "United States",
        "Home Sweet Home Europe XBOX One/Series X|S CD Key": "Europe",
        "Far Cry 6 - Jungle Expedition SIEE PS5 CD Key": None,          # SIEE is not a region
        "Trepang2 Standard Edition PC/XBOX Series X|S CD Key": None,
    }

    def test_region_slot_verbatim_and_agrees_with_the_shared_read(self):
        for title, slot in self.ROWS.items():
            with self.subTest(title=title):
                self.assertEqual(console_region_slot(title), slot)
                sig = classify_console(title, "https://k4g.com/product/x-xbox-series-x-s-xbox-europe-cd-key-cd-key-AAAAAAAA", "K4G")
                self.assertEqual(sig.region_words[:1], (slot,) if slot else ())

    def test_url_families(self):
        cases = {
            "https://k4g.com/product/persona-5-royal-pc-xbox-one-series-x-s-canada-cd-key-cd-key-IY4ZKGPV": ("XBOX_ONE", "XBOX_SERIES"),
            "https://k4g.com/product/home-sweet-home-xbox-one-series-x-s-xbox-europe-instant-cd-key-cd-key-5ZF2STXM": ("XBOX_ONE", "XBOX_SERIES"),
            "https://k4g.com/product/company-of-heroes-3-xbox-series-x-s-xbox-europe-cd-key-standard-edition-cd-key-XR09AGQY": ("XBOX_SERIES",),
            "https://k4g.com/product/pokemon-scarlet-nintendo-switch-2-europe-cd-key-cd-key-3FWB2QK5": ("SWITCH2",),
            "https://k4g.com/product/borderlands-3-ps4-ps5-europe-instant-cd-key-ultimate-edition-cd-key-QF8DZERN": ("PS4", "PS5"),
            "https://k4g.com/product/moving-out-2-f-a-r-tastic-four-playstation-5-europe-cd-key-cd-key-W8SDTVYC": ("PS5",),
            "https://k4g.com/product/x-nintendo-switch-europe-cd-key-cd-key-AAAAAAAA": ("SWITCH",),
            # a product NAME "Nintendo Switch 2 Edition Upgrade Pack" is not a run; PC rows say nothing
            "https://k4g.com/product/x-nintendo-switch-2-edition-upgrade-pack-steam-europe-cd-key-cd-key-AAAAAAAA": None,
            "https://k4g.com/product/goblin-vyke-the-thief-tycoon-steam-global-instant-cd-key-cd-key-AE3VLW0N": None,
            "https://k4g.com/product/x-playstation-5-siee-cd-key-cd-key-AAAAAAAA": None,     # unknown region slot
        }
        for url, families in cases.items():
            with self.subTest(url=url):
                self.assertEqual(console_url_families(url), families)


class ConfigTests(unittest.TestCase):
    def test_config_declares_the_hooks(self):
        self.assertIsInstance(CONFIG, MerchantConfig)
        self.assertEqual((CONFIG.name, CONFIG.domain), ("K4G", "k4g.com"))
        self.assertIs(CONFIG.precheck, precheck)
        self.assertIs(CONFIG.title_region, title_region)
        self.assertIs(CONFIG.resolve_name, resolve_name)
        self.assertTrue(CONFIG.title_is_platform_source)
        fields = {f.name for f in dataclasses.fields(MerchantConfig)}
        if "console_region_slot" in fields:
            self.assertIs(CONFIG.console_region_slot, console_region_slot)
            self.assertIs(CONFIG.console_url_families, console_url_families)
            self.assertEqual(CONFIG.console_noise, ())
        else:
            self.assertIs(CONFIG.extra["console_hooks_pending"]["console_region_slot"], console_region_slot)

    def test_module_imports_no_generic_layer(self):
        src = pathlib.Path(k4g.__file__).read_text(encoding="utf-8")
        self.assertIsNone(re.search(r"^\s*(?:from|import)\s+src\.(?:matcher|console_keys|merchants\.registry)\b", src, re.M))


if __name__ == "__main__":
    unittest.main()

"""tests for src/merchants/gamivo.py — the CONSOLE hooks (R32 / R45, 2026-09-14).

Romain's rule: « pour la détection région / édition / plateforme, tu as un fichier de
config par marchand ». Gamivo's console grammar (fused URL runs "xboxoneseries" /
"xbox-series-pc" / "ps-ps5" / "nintendo-nintendo-switch-2", the title-tail region, the
"EN" / "EN/PL/CS" language tail) lives in ``src/merchants/gamivo.py`` and is read by the
shared classifier through the ``MerchantConfig`` hooks. Fixtures = the 5 Gamivo rows of
the 2026-09-12 review corpus (study §7 rows 26-30, moved here from
tests/test_console_keys.py), the 25 URL runs and the tail cases of the 2026-09-14 review.
The PC-side hooks (precheck / title_region / resolve_name / url_platform, R46) are
tested in tests/test_matcher.py.
"""

import unittest

from src.console_keys import (
    SKIP_PC_ONLY,
    ConsoleSignal,
    classify_console,
    resolve_name_and_regions,
    resolve_name_of,
    skip_not_a_game,
)
from src.merchants import gamivo
from src.merchants.registry import merchant_config

ONE_SERIES = ("XBOX_ONE", "XBOX_SERIES")
NO_GEN = "console: no declared generation (R45)"
PC_ONLY = "console: PC-only Xbox Live key (R45)"

# (title, url, families, pc_declared, skip_reason, resolve_name) — study §7 rows 26-30:
# the platform is ONLY in the URL (569/572 console rows of the 2026-09-12 batch).
ROWS = [
    ("Ravenswatch EN United Kingdom",
     "https://www.gamivo.com/product/ravenswatch-xbox-xboxoneseries-uk-standard",
     ONE_SERIES, False, None, "Ravenswatch"),
    ("KIBORG EN Colombia",
     "https://www.gamivo.com/product/kiborg-xbox-xbox-one-series-co-standard",
     ONE_SERIES, False, None, "KIBORG"),
    ("Death Stranding - Director's Cut EN United Kingdom",
     "https://www.gamivo.com/product/death-stranding-directors-cut-xbox-xboxserieswindows-uk-standard",
     ("XBOX_SERIES",), True, None, "Death Stranding - Director's Cut"),
    ("Riders Republic Premium Edition United States",
     "https://www.gamivo.com/product/riders-republic-xbox-xbox-one-series-us-premium",
     ONE_SERIES, False, None, "Riders Republic Premium Edition"),
    ("FIFA 23 EN/PL/CS/RU/TR EU",
     "https://www.gamivo.com/product/fifa-23-ps-ps5-eu-en-pl-cz-tr-ru-standard",
     ("PS5",), False, None, "FIFA 23"),
]
BASE = "https://www.gamivo.com/product/game-{run}-uk-standard"


def _slot(sig):
    return sig.region_base, sig.region_label, sig.region_words


class ConfigBindingTests(unittest.TestCase):
    def test_config_declares_the_console_grammar(self):
        cfg = gamivo.CONFIG
        self.assertIs(cfg.console_url_families, gamivo.console_url_families)
        self.assertIs(cfg.console_pc_declared, gamivo.console_pc_declared)
        self.assertIs(cfg.console_region_slot, gamivo.console_region_slot)
        self.assertEqual(cfg.console_noise, (gamivo.CONSOLE_LANG_TAIL_RE,))
        # the R46 PC-side hooks are untouched
        self.assertIs(cfg.precheck, gamivo.precheck)
        self.assertIs(cfg.url_platform, gamivo.url_platform)

    def test_registry_binds_the_module_config(self):
        self.assertIs(merchant_config("Gamivo"), gamivo.CONFIG)
        self.assertIs(merchant_config("GAMIVO"), gamivo.CONFIG)


class UrlRunHookTests(unittest.TestCase):
    CASES = {
        "xbox-xbox-series": (("XBOX_SERIES",), False, None),
        "xbox-series": (("XBOX_SERIES",), False, None),
        "xbox-xboxseries": (("XBOX_SERIES",), False, None),
        "xbox-xbox-series-pc": (("XBOX_SERIES",), True, None),
        "xbox-series-pc": (("XBOX_SERIES",), True, None),
        "xbox-xbox-series-windows": (("XBOX_SERIES",), True, None),
        "xbox-xboxserieswindows": (("XBOX_SERIES",), True, None),
        "xbox-xbox-one-series": (ONE_SERIES, False, None),
        "xbox-xboxoneseries": (ONE_SERIES, False, None),
        "xbox-one-series": (ONE_SERIES, False, None),
        "xbox-one-series-pc": (ONE_SERIES, True, None),
        "xbox-xbox-one-series-windows": (ONE_SERIES, True, None),
        "xbox-xbox-one-series-pc": (ONE_SERIES, True, None),
        "xbox-xboxoneserieswindows": (ONE_SERIES, True, None),
        "xbox-xbox-one-series-xbox-pc": (ONE_SERIES, True, None),
        "xbox-xboxone": (("XBOX_ONE",), False, None),
        "xbox-one": (("XBOX_ONE",), False, None),
        "xbox-pc": ((), False, PC_ONLY),
        "xbox-xbox-windows": ((), False, NO_GEN),        # Xbox + Windows, no generation
        "xbox-xboxwindows": ((), False, NO_GEN),
        "ps-ps5": (("PS5",), False, None),
        "psn-ps5": (("PS5",), False, None),
        "ps-ps4-ps5": (("PS4", "PS5"), False, None),
        "nintendo-nintendo-switch": (("SWITCH",), False, None),
        "nintendo-nintendo-switch-2": (("SWITCH2",), False, None),
    }

    def test_hook_reads_the_fused_run(self):
        for run, (families, pc, skip) in self.CASES.items():
            url = BASE.format(run=run)
            with self.subTest(run=run):
                expected = PC_ONLY if skip == PC_ONLY else (families or None)
                self.assertEqual(gamivo.console_url_families(url), expected)
                self.assertEqual(gamivo.console_pc_declared("Game EN United Kingdom", url), pc)
        self.assertEqual(gamivo.console_url_families(BASE.format(run="xbox-pc")), SKIP_PC_ONLY)
        # a PC run / no run → nothing
        self.assertIsNone(gamivo.console_url_families("https://www.gamivo.com/product/tiny-tinas-wonderlands-pc-steam-us-standard"))
        self.assertIsNone(gamivo.console_url_families(""))

    def test_classifier_reads_the_hook(self):
        for run, (families, pc, skip) in self.CASES.items():
            with self.subTest(run=run):
                sig = classify_console("Game EN United Kingdom", BASE.format(run=run), "Gamivo")
                self.assertIsNotNone(sig, run)
                self.assertEqual((sig.families, sig.pc_declared, sig.skip_reason), (families, pc, skip))
                self.assertEqual(sig.resolve_name, "Game")
                self.assertEqual(_slot(sig), ("uk", None, ("United Kingdom",)))

    def test_merchant_name_selects_the_hooks_without_a_host(self):
        sig = classify_console("Game EN United Kingdom", "/product/game-xbox-xboxoneseries-uk-standard", "Gamivo")
        self.assertEqual(sig.families, ONE_SERIES)
        sig = classify_console("Game EN United Kingdom", "/product/game-xbox-xboxoneseries-uk-standard", "gamivo")
        self.assertEqual(sig.families, ONE_SERIES)

    def test_switch_2_and_switch_from_the_url_only(self):
        sig = classify_console("Game EN United Kingdom", "https://www.gamivo.com/product/game-nintendo-nintendo-switch-2-uk-standard", "Gamivo")
        self.assertEqual((sig.families, sig.skip_reason), (("SWITCH2",), None))
        sig = classify_console("Game", "https://www.gamivo.com/product/game-nintendo-nintendo-switch-uk-standard", "Gamivo")
        self.assertEqual(sig.families, ("SWITCH",))

    def test_leading_name_run_is_not_the_declaration(self):
        sig = classify_console("Nintendo Switch Sports EN United Kingdom",
                               "https://www.gamivo.com/product/nintendo-switch-sports-nintendo-nintendo-switch-uk-standard", "Gamivo")
        self.assertEqual((sig.families, sig.region_base, sig.resolve_name), (("SWITCH",), "uk", "Nintendo Switch Sports"))


class RegionSlotHookTests(unittest.TestCase):
    def test_slot_is_the_title_tail(self):
        for title, expected in {"Ravenswatch EN United Kingdom": "United Kingdom", "KIBORG EN Colombia": "Colombia",
                                "FIFA 23 EN/PL/CS/RU/TR EU": "EU", "Storebound ROW": "ROW",
                                "Lowes Gift Card USD US $73": None, "Game": None}.items():
            with self.subTest(title=title):
                self.assertEqual(gamivo.console_region_slot(title), expected)

    def test_tail_exposed_like_the_r46_hook(self):
        cases = {
            ("Ravenswatch EN United Kingdom", "https://www.gamivo.com/product/ravenswatch-xbox-xboxoneseries-uk-standard"): (("uk", None, ("United Kingdom",)), "Ravenswatch"),
            ("Riders Republic Premium Edition United States", "https://www.gamivo.com/product/riders-republic-xbox-xbox-one-series-us-premium"): (("us", None, ("United States",)), "Riders Republic Premium Edition"),
            ("Tiny Tina's Wonderlands EN United States", "https://www.gamivo.com/product/tiny-tinas-wonderlands-xbox-xbox-one-series-us-standard"): (("us", None, ("United States",)), "Tiny Tina's Wonderlands"),
            ("KIBORG EN Colombia", "https://www.gamivo.com/product/kiborg-xbox-xbox-one-series-co-standard"): ((None, "COLOMBIA", ("Colombia",)), "KIBORG"),
            ("Kingdom Come Deliverance II Royal Edition EN Canada", "https://www.gamivo.com/product/x-xbox-xbox-series-ca-royal"): ((None, "CANADA", ("Canada",)), "Kingdom Come Deliverance II Royal Edition"),
            ("FIFA 23 EN/PL/CS/RU/TR EU", "https://www.gamivo.com/product/fifa-23-ps-ps5-eu-en-pl-cz-tr-ru-standard"): (("eu", None, ("EU",)), "FIFA 23"),
            ("The Blood of Dawnwalker - Pre-Order Bonus DLC EN Global", "https://www.gamivo.com/product/x-xbox-xbox-series-global-standard"): (("global", None, ("Global",)), "The Blood of Dawnwalker - Pre-Order Bonus DLC"),
            ("Storebound ROW", "https://www.gamivo.com/product/storebound-xbox-xbox-series-row-standard"): ((None, "ROW", ("ROW",)), "Storebound"),
            ("Game EN Singapore", "https://www.gamivo.com/product/game-xbox-xbox-series-sg-standard"): ((None, "SINGAPORE", ("Singapore",)), "Game"),
            # a Gamivo-only region word (not in the shared list) is still a lock — the hook's text
            ("Game EN France", "https://www.gamivo.com/product/game-xbox-xbox-series-fr-standard"): ((None, "FRANCE", ("France",)), "Game France"),
        }
        for (title, url), (slot, name) in cases.items():
            with self.subTest(title=title):
                sig = classify_console(title, url, "Gamivo")
                self.assertIsNone(sig.skip_reason)
                self.assertEqual((_slot(sig), sig.resolve_name), (slot, name))


class LanguageTailNoiseTests(unittest.TestCase):
    """The "EN" / "EN/PL/CS/RU/TR" tail before the region is Gamivo's own furniture
    (``console_noise``) — moved out of the shared grammar on 2026-09-14."""

    def test_lang_tail_is_stripped_for_gamivo_only(self):
        cases = {
            "Ravenswatch EN United Kingdom": "Ravenswatch",
            "Kingdom Come Deliverance II Royal Edition EN Canada": "Kingdom Come Deliverance II Royal Edition",
            "FIFA 23 EN/PL/CS/RU/TR EU": "FIFA 23",
            "Death Stranding - Director's Cut EN United Kingdom": "Death Stranding - Director's Cut",
            "The Blood of Dawnwalker - Pre-Order Bonus DLC EN Global": "The Blood of Dawnwalker - Pre-Order Bonus DLC",
        }
        for title, expected in cases.items():
            with self.subTest(title=title):
                self.assertEqual(resolve_name_of(title, "Gamivo"), expected)
                self.assertEqual(resolve_name_of(title, "gamivo"), expected)
        # WITHOUT the merchant the shared grammar strips the region tail only — the
        # language code is not shared vocabulary (a bare 2-letter word may be a name)
        self.assertEqual(resolve_name_of("Ravenswatch EN United Kingdom"), "Ravenswatch EN")
        self.assertNotEqual(resolve_name_of("FIFA 23 EN/PL/CS/RU/TR EU"), "FIFA 23")
        self.assertEqual(resolve_name_and_regions("Ravenswatch EN United Kingdom", "Gamivo"),
                         ("Ravenswatch", ("United Kingdom",)))

    def test_only_iso_codes_before_a_region_word(self):
        # a Roman numeral / acronym is not a language code (the R46 ruling, case-sensitive)
        self.assertEqual(resolve_name_of("Final Fantasy XV Global", "Gamivo"), "Final Fantasy XV")
        self.assertEqual(resolve_name_of("Game of Canada", "Gamivo"), "Game of")   # "of" is not "EN"
        # the code is stripped only when a region word CLOSES the title
        self.assertEqual(resolve_name_of("Game EN Deluxe Edition", "Gamivo"), "Game EN Deluxe Edition")
        sig = classify_console("Final Fantasy XV Global", "https://www.gamivo.com/product/x-xbox-xbox-series-global-standard", "Gamivo")
        self.assertEqual((sig.resolve_name, _slot(sig)), ("Final Fantasy XV", ("global", None, ("Global",))))


class ClassifyRowsTests(unittest.TestCase):
    def test_corpus_rows(self):
        for i, (title, url, families, pc, skip, name) in enumerate(ROWS, 26):
            with self.subTest(row=i, title=title):
                sig = classify_console(title, url, "Gamivo")
                self.assertIsInstance(sig, ConsoleSignal)
                self.assertEqual((sig.families, sig.pc_declared, sig.skip_reason, sig.resolve_name),
                                 (families, pc, skip, name))
                self.assertEqual(sig.resolve_name, resolve_name_of(title, "Gamivo"))

    def test_five_corpus_rows(self):
        self.assertEqual(len(ROWS), 5)

    def test_non_game_gift_card_url(self):
        sig = classify_console("Nintendo eShop PLN PL 32zł", "https://www.gamivo.com/product/nintendo-eshop-pln-pl-32zl-gift-cards", "Gamivo")
        self.assertEqual((sig.skip_reason, sig.families), (skip_not_a_game("GIFT CARD"), ()))

    def test_pc_row_returns_none(self):
        self.assertIsNone(classify_console("Tiny Tina's Wonderlands EN United States",
                                           "https://www.gamivo.com/product/tiny-tinas-wonderlands-pc-steam-us-standard", "Gamivo"))


if __name__ == "__main__":
    unittest.main()

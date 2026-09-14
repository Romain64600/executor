"""tests for src/merchants/mmoga.py — the CONSOLE hooks (R32 / R45, 2026-09-14).

Romain's rule: « pour la détection région / édition / plateforme, tu as un fichier de
config par marchand ». The MMOGA console grammar (URL category segment, "<CODE> Key" /
"[EU]" region slot, "Download Code" delivery phrase) lives in ``src/merchants/mmoga.py``
and is read by the shared classifier through the ``MerchantConfig`` hooks. Fixtures = the
10 MMOGA rows of the 2026-09-12 review corpus (study §7 rows 1-10, moved here from
tests/test_console_keys.py) plus the MMOGA cases of the 2026-09-14 review.
"""

import unittest

from src.console_keys import (
    SKIP_XBOX_360,
    ConsoleSignal,
    classify_console,
    resolve_name_and_regions,
    resolve_name_of,
    skip_not_a_game,
)
from src.merchants import mmoga
from src.merchants.registry import merchant_config

ONE_SERIES = ("XBOX_ONE", "XBOX_SERIES")
NO_GEN = "console: no declared generation (R45)"
XBOX_360 = "console: Xbox 360 (R45)"

# (title, url, families, pc_declared, skip_reason, resolve_name) — study §7 rows 1-10.
ROWS = [
    ("NBA 2K25 (Xbox One / Series X|S Download Code) - EU",
     "https://www.mmoga.com/Xbox-Live/Xbox-One-Game-Keys/NBA-2K25-Xbox-One-Series-XS-Download-Code-EU.html?ref=615",
     ONE_SERIES, False, None, "NBA 2K25"),
    ("FIFA 23 - Ultimate Edition ( Xbox One / Series X|S Download Code ) - EU",
     "https://www.mmoga.com/Xbox-Live/Xbox-One-Game-Keys/FIFA-23-Ultimate-Edition-Xbox-One-Series-XS-Download-Code-EU.html?ref=615",
     ONE_SERIES, False, None, "FIFA 23 - Ultimate Edition"),
    ("UFC 5 (Xbox Series X|S Download Code) - EU",
     "https://www.mmoga.com/Xbox-Live/Xbox-Series-XS-Game-Keys/UFC-5-Xbox-Series-XS-Download-Code-EU.html?ref=615",
     ("XBOX_SERIES",), False, None, "UFC 5"),
    ("Grounded 2 Xbox Series X|S / Windows",
     "https://www.mmoga.com/Xbox-Live/Xbox-Series-XS-Game-Keys/Grounded-2-Xbox-Series-XS-Windows.html?ref=615",
     ("XBOX_SERIES",), True, None, "Grounded 2"),
    ("Assassin's Creed Odyssey - Ultimate Edition (Xbox One Download Code)",
     "https://www.mmoga.com/Xbox-Live/Xbox-One-Game-Keys/Assassins-Creed-Odyssey-Ultimate-Edition-Xbox-One-Download-Code.html?ref=615",
     ("XBOX_ONE",), False, None, "Assassin's Creed Odyssey - Ultimate Edition"),
    ("MLB The Show 23 (PS4 / PS5 Download Code) - EU",
     "https://www.mmoga.com/Playstation-Network/Playstation-4-Game-Keys/MLB-The-Show-23-PS4-PS5-Download-Code-EU.html?ref=615",
     ("PS4", "PS5"), False, None, "MLB The Show 23"),
    ("Medieval Dynasty - PS5 Download Code [EU]",
     "https://www.mmoga.com/Playstation-Network/Playstation-5-Game-Keys/Medieval-Dynasty-PS5-Download-Code-EU.html?ref=615",
     ("PS5",), False, None, "Medieval Dynasty"),
    ("Instant Sports Paradise - Nintendo Switch Download Code [EU]",
     "https://www.mmoga.com/Nintendo/Switch/Instant-Sports-Paradise-Nintendo-Switch-Download-Code-EU.html?ref=615",
     ("SWITCH",), False, None, "Instant Sports Paradise"),
    ("PSN Card 80 Euro [Austria] - Playstation Network Credit",
     "https://www.mmoga.com/Playstation-Network/PSN-Cards-AT/PSN-Card-80-Euro-Austria-Playstation-Network-Credit.html?ref=615",
     (), False, skip_not_a_game("PSN CARD"), None),
    ("Xbox Game Pass Essential 6 Months [EU]",
     "https://www.mmoga.com/Xbox-Live/Xbox-360-Game-Keys/Xbox-Game-Pass-Essential-6-Months-EU.html?ref=615",
     (), False, skip_not_a_game("GAME PASS"), None),
]
XONE_CAT = "https://www.mmoga.com/Xbox-Live/Xbox-One-Game-Keys/x.html?ref=615"


def _slot(sig):
    return sig.region_base, sig.region_label, sig.region_words


class ConfigBindingTests(unittest.TestCase):
    def test_config_declares_the_console_grammar(self):
        cfg = mmoga.CONFIG
        self.assertIs(cfg.console_url_families, mmoga.console_url_families)
        self.assertIs(cfg.console_region_slot, mmoga.console_region_slot)
        self.assertIsNone(cfg.console_pc_declared)              # MMOGA URLs never say PC
        self.assertEqual(cfg.console_noise, ("Download Code",))
        # the PC-side hooks are untouched
        self.assertIs(cfg.precheck, mmoga.precheck)
        self.assertIs(cfg.title_region, mmoga.title_region)
        self.assertIs(cfg.resolve_name, mmoga.resolve_name)

    def test_registry_binds_the_module_config(self):
        self.assertIs(merchant_config("MMOGA"), mmoga.CONFIG)
        self.assertIs(merchant_config("mmoga"), mmoga.CONFIG)


class UrlFamiliesHookTests(unittest.TestCase):
    def test_category_segment(self):
        cases = {
            "https://www.mmoga.com/Xbox-Live/Xbox-One-Game-Keys/Some-Game.html?ref=615": ("XBOX_ONE",),
            "https://www.mmoga.com/Xbox-Live/Xbox-Series-XS-Game-Keys/Some-Game-EU.html?ref=615": ("XBOX_SERIES",),
            "https://www.mmoga.com/Playstation-Network/Playstation-4-Game-Keys/Some-Game.html": ("PS4",),
            "https://www.mmoga.com/Playstation-Network/Playstation-5-Game-Keys/Some-Game.html": ("PS5",),
            "https://www.mmoga.com/Nintendo/Switch/Some-Game.html": ("SWITCH",),
            "https://www.mmoga.com/Xbox-Live/Xbox-360-Game-Keys/Some-Game.html": XBOX_360,
            "https://www.mmoga.com/Steam-Games/Among-Us.html": None,          # a PC category
            "https://www.mmoga.com/EA-Games/Battlefield-4-Premium.html?ref=615": None,
            "": None,
        }
        for url, expected in cases.items():
            with self.subTest(url=url):
                self.assertEqual(mmoga.console_url_families(url), expected)
        self.assertEqual(mmoga.console_url_families(cases and list(cases)[5]), SKIP_XBOX_360)

    def test_card_and_subscription_categories_are_non_game(self):
        for cat, marker in (("Playstation-Network/PSN-Cards-DE", "PSN CARDS DE"),
                            ("Nintendo/Nintendo-eShop-Cards", "NINTENDO ESHOP CARDS"),
                            ("Playstation-Network/Playstation-Plus", "PLAYSTATION PLUS"),
                            ("Xbox-Live/Xbox-Live-Cards", "XBOX LIVE CARDS"),
                            ("Xbox-Live/Xbox-Live-Gold", "XBOX LIVE GOLD")):
            url = f"https://www.mmoga.com/{cat}/Thing-50-Euro.html?ref=615"
            with self.subTest(cat=cat):
                self.assertEqual(mmoga.console_url_families(url), skip_not_a_game(marker))
                sig = classify_console("Thing 50 Euro", url, "MMOGA")
                self.assertEqual(sig.skip_reason, skip_not_a_game(marker))
                self.assertEqual(sig.families, ())


class RegionSlotHookTests(unittest.TestCase):
    def test_region_code_slot(self):
        cases = {
            "Medieval Dynasty - PS5 Download Code [EU]": "EU",
            # "(… Key EU)" with a "|" inside the bracket is outside the PC tail grammar of
            # mmoga.region_code — the shared bracket read covers it (see the classifier case)
            "Game (Xbox Series X|S Key EU)": None,
            "Game (Steam Key EU)": "EU",
            "Game - Xbox One Download Code - US Key": "US",
            "Game - Xbox One Download Code [US]": "US",
            "Game (Xbox One Download Code) [DE]": None,       # bare [XX]: only a KNOWN code (mmoga.region_code)
            "Game (Xbox One Download Code) (TR)": "TR",
            "NBA 2K25 (Xbox One / Series X|S Download Code) - EU": None,   # the dash tail is the shared read
            "Among Us Key": None,
        }
        for title, expected in cases.items():
            with self.subTest(title=title):
                self.assertEqual(mmoga.console_region_slot(title), expected)

    def test_tails_exposed_like_the_merchant_hook(self):
        cases = {
            "NBA 2K25 (Xbox One / Series X|S Download Code) - EU": ("eu", None, ("EU",)),
            "Medieval Dynasty - PS5 Download Code [EU]": ("eu", None, ("EU",)),
            "Overwatch - Legendary Edition (Xbox One Download Code) - EU Key": ("eu", None, ("EU",)),
            "Game (Xbox Series X|S Key EU)": ("eu", None, ("EU",)),
            "Game - Xbox One Download Code [US]": ("us", None, ("US",)),
            "Game - Xbox One Download Code - US Key": ("us", None, ("US",)),
            "Game - Xbox One Download Code [DE]": (None, "GERMANY", ("DE",)),
            "Game - Xbox One Download Code [AT]": (None, "AUSTRIA", ("AT",)),
            "Game - Xbox One Download Code (TR)": (None, "TURKEY", ("TR",)),
        }
        for title, slot in cases.items():
            with self.subTest(title=title):
                sig = classify_console(title, XONE_CAT, "MMOGA")
                self.assertIsNone(sig.skip_reason)
                self.assertEqual(_slot(sig), slot)
                # the tail is gone from the name, whatever its spelling
                self.assertFalse(set(sig.resolve_name.split()) & {"EU", "US", "DE", "AT", "TR", "[EU]", "[US]"})
                self.assertNotIn("Key", sig.resolve_name)

    def test_no_region_next_to_the_phrase(self):
        sig = classify_console("Assassin's Creed Odyssey - Ultimate Edition (Xbox One Download Code)", XONE_CAT, "MMOGA")
        self.assertEqual(_slot(sig), (None, None, ()))
        self.assertEqual(sig.resolve_name, "Assassin's Creed Odyssey - Ultimate Edition")


class ClassifyRowsTests(unittest.TestCase):
    def test_corpus_rows(self):
        for i, (title, url, families, pc, skip, name) in enumerate(ROWS, 1):
            with self.subTest(row=i, title=title):
                sig = classify_console(title, url, "MMOGA")
                self.assertIsInstance(sig, ConsoleSignal)
                self.assertEqual((sig.families, sig.pc_declared, sig.skip_reason), (families, pc, skip))
                if name is not None:
                    self.assertEqual(sig.resolve_name, name)
                self.assertNotIn("XBOX_PC", sig.families)
                self.assertEqual(sig.resolve_name, resolve_name_and_regions(title, "MMOGA")[0])

    def test_ten_corpus_rows(self):
        self.assertEqual(len(ROWS), 10)

    def test_category_is_the_fallback_and_the_title_wins(self):
        # category alone (title without a phrase) → the category's generation
        sig = classify_console("Some Game - EU", "https://www.mmoga.com/Xbox-Live/Xbox-Series-XS-Game-Keys/Some-Game-EU.html?ref=615", "MMOGA")
        self.assertEqual((sig.families, sig.region_base), (("XBOX_SERIES",), "eu"))
        sig = classify_console("Some Game", "https://www.mmoga.com/Playstation-Network/Playstation-4-Game-Keys/Some-Game.html", "MMOGA")
        self.assertEqual(sig.families, ("PS4",))
        sig = classify_console("Some Game", "https://www.mmoga.com/Playstation-Network/Playstation-5-Game-Keys/Some-Game.html", "MMOGA")
        self.assertEqual(sig.families, ("PS5",))
        sig = classify_console("Some Game", "https://www.mmoga.com/Nintendo/Switch/Some-Game.html", "MMOGA")
        self.assertEqual(sig.families, ("SWITCH",))
        sig = classify_console("Some Game", "https://www.mmoga.com/Xbox-Live/Xbox-360-Game-Keys/Some-Game.html", "MMOGA")
        self.assertEqual(sig.skip_reason, XBOX_360)
        # cross-gen title filed under the One category: the TITLE decides (both platforms)
        self.assertEqual(classify_console(ROWS[0][0], ROWS[0][1], "MMOGA").families, ONE_SERIES)
        # a PS5 title filed under the PS4 category: the title wins too
        sig = classify_console("Game (PS5 Download Code) - EU",
                               "https://www.mmoga.com/Playstation-Network/Playstation-4-Game-Keys/Game.html", "MMOGA")
        self.assertEqual(sig.families, ("PS5",))

    def test_non_game_wins_over_the_xbox_360_category(self):
        # the Xbox-360 GAME category holds a Game Pass subscription: the shared title marker rules
        sig = classify_console(ROWS[9][0], ROWS[9][1], "MMOGA")
        self.assertEqual(sig.skip_reason, skip_not_a_game("GAME PASS"))
        for title, url, marker in (
            ("Xbox Game Pass Ultimate 1 Month [EU]", XONE_CAT, "GAME PASS"),
            ("Xbox Live Gold - 3 month subscription [EU]", "https://www.mmoga.com/Xbox-Live/Xbox-Live-Gold/x.html", "XBOX LIVE GOLD"),
            ("Playstation Network Card 50 Euros [ES]", "https://www.mmoga.com/Playstation-Network/PSN-Cards-ES/x.html", "PLAYSTATION NETWORK CARD"),
        ):
            with self.subTest(title=title):
                sig = classify_console(title, url, "MMOGA")
                self.assertEqual((sig.skip_reason, sig.families), (skip_not_a_game(marker), ()))

    def test_switch_2_edition_name_suffix_filed_under_switch_is_refused(self):
        # a Switch 2 Edition filed under the /Nintendo/Switch/ category with a bare
        # "(Switch Download Code)" phrase → the category says SWITCH, the name suffix says
        # Switch 2 → fail-closed contradiction, never a Switch (1) entry
        sig = classify_console("Some Game - Nintendo Switch 2 Edition (Switch Download Code) - EU",
                               "https://www.mmoga.com/Nintendo/Switch/x.html?ref=615", "MMOGA")
        self.assertEqual(sig.families, ("SWITCH",))
        self.assertEqual(sig.skip_reason, "console: product name suffix 'Nintendo Switch 2 Edition' contradicts "
                                          "the declared platform SWITCH — not entered (R45)")

    def test_leading_name_runs_keep_the_word(self):
        cases = [
            ("Nintendo World Championships - NES Edition (Switch Download Code) - EU",
             "https://www.mmoga.com/Nintendo/Switch/Nintendo-World-Championships-NES-Edition-Switch-Download-Code-EU.html?ref=615",
             ("SWITCH",), "eu", "Nintendo World Championships - NES Edition"),
            ("Xbox Fitness (Xbox One Download Code) - EU",
             "https://www.mmoga.com/Xbox-Live/Xbox-One-Game-Keys/Xbox-Fitness-Xbox-One-Download-Code-EU.html?ref=615",
             ("XBOX_ONE",), "eu", "Xbox Fitness"),
        ]
        for title, url, families, base, name in cases:
            with self.subTest(title=title):
                sig = classify_console(title, url, "MMOGA")
                self.assertEqual((sig.families, sig.skip_reason, sig.region_base, sig.resolve_name),
                                 (families, None, base, name))

    def test_pc_row_returns_none(self):
        self.assertIsNone(classify_console("Among Us", "https://www.mmoga.com/Steam-Games/Among-Us.html", "MMOGA"))
        self.assertIsNone(classify_console("Borderlands 2 EU Key", "https://www.mmoga.com/Steam-Games/Borderlands-2-EU-Key.html?ref=615", "MMOGA"))


class ResolveNameTests(unittest.TestCase):
    def test_download_code_and_tails(self):
        cases = {
            "NBA 2K25 (Xbox One / Series X|S Download Code) - EU": "NBA 2K25",
            "FIFA 23 - Ultimate Edition ( Xbox One / Series X|S Download Code ) - EU": "FIFA 23 - Ultimate Edition",
            "Medieval Dynasty - PS5 Download Code [EU]": "Medieval Dynasty",
            "Overwatch - Legendary Edition (Xbox One Download Code) - EU Key": "Overwatch - Legendary Edition",
            "Toki - Nintendo Switch Download Code": "Toki",
            "Halo 5 Guardians - Xbox One Download Code": "Halo 5 Guardians",
            "Payday 3 - Gold Edition (Xbox Series X|S / Windows) - EU": "Payday 3 - Gold Edition",
            "Formula One - PS5 Download Code [EU]": "Formula One",
        }
        for title, expected in cases.items():
            with self.subTest(title=title):
                self.assertEqual(resolve_name_of(title, "MMOGA"), expected)
                self.assertEqual(classify_console(title, XONE_CAT, "MMOGA").resolve_name, expected)

    def test_noise_phrase_is_case_insensitive_whole_words(self):
        # the declared phrase is stripped wherever MMOGA writes it; "Downloadable" is not it
        self.assertEqual(resolve_name_of("Game - PS5 download code [EU]", "MMOGA"), "Game")
        self.assertEqual(resolve_name_of("Downloadable Content Pack - PS5 [EU]", "MMOGA"), "Downloadable Content Pack")


if __name__ == "__main__":
    unittest.main()

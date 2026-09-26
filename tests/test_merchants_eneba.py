"""tests for src/merchants/eneba.py — the CONSOLE hooks (R32 / R45, 2026-09-14).

Romain's rule: « pour la détection région / édition / plateforme, tu as un fichier de
config par marchand ». Eneba's console grammar (leading store segment, the platform slot
before the "<STORE> Key" marker, "-pc-" PC-only keys, "-windows-" next to the run, the
region after the key word) lives in ``src/merchants/eneba.py`` and is read by the shared
classifier through the ``MerchantConfig`` hooks. Fixtures = the 7 Eneba rows of the
2026-09-12 review corpus (study §7 rows 11-17, moved here from tests/test_console_keys.py),
the URL cases of the 2026-09-14 review and the two real rows whose region slot the hook
corrects.
"""

import unittest

from src.console_keys import (
    SKIP_XBOX_360,
    XBOX_WINDOWS_KEY,
    ConsoleSignal,
    classify_console,
    resolve_name_of,
    skip_not_a_game,
)
from src.merchants import eneba
from src.merchants.registry import merchant_config

ONE_SERIES = ("XBOX_ONE", "XBOX_SERIES")
NO_GEN = "console: no declared generation (R45)"
WINDOWS = "windows"         # the hook's ``(XBOX_WINDOWS_KEY,)`` — a PC key sold through Xbox Live
XBOX_360 = "console: Xbox 360 (R45)"

# (title, url, families, pc_declared, skip_reason, resolve_name) — study §7 rows 11-17.
# P4 Xbox (Romain 2026-09-25, « Xbox sur les deux »): a generation-less "XBOX LIVE Key" row
# (rows 14 and 17) now reads as One + Series (``generation_inferred``) — before: NO_GEN. Row 17
# stays refused downstream, by precheck (V-Bucks currency, SOUTH AFRICA lock).
ROWS = [
    ("Nickelodeon Extreme Tennis: Next! (Xbox Series X|S) XBOX LIVE Key EUROPE",
     "https://www.eneba.com/xbox-nickelodeon-extreme-tennis-next-xbox-series-x-s-xbox-live-key-europe",
     ("XBOX_SERIES",), False, None, "Nickelodeon Extreme Tennis: Next!"),
    ("MOTORSLICE (Windows/Xbox Series X|S) XBOX LIVE Key UNITED STATES",
     "https://www.eneba.com/xbox-motorslice-windows-xbox-series-x-s-xbox-live-key-united-states",
     ("XBOX_SERIES",), True, None, "MOTORSLICE"),
    ("Thomas & Friends™: Wonders of Sodor PC/XBOX LIVE Key UNITED STATES",
     "https://www.eneba.com/xbox-thomas-friendstm-wonders-of-sodor-pc-xbox-live-key-united-states",
     # « PC/XBOX LIVE » = a PC key sold through Xbox Live (Romain 2026-09-26, « 1. »): a
     # windows_key signal, the AKS PC page decides (before: "PC-only Xbox Live key" refusal)
     ONE_SERIES, False, None, "Thomas & Friends™: Wonders of Sodor"),
    ("POLSKA GUROM XBOX LIVE Key UNITED STATES",
     "https://www.eneba.com/xbox-polska-gurom-xbox-live-key-united-states",
     ONE_SERIES, False, None, "POLSKA GUROM"),
    ("Let's Sing 2025 - International Hits (DLC) (PS4/PS5) PSN Key EUROPE",
     "https://www.eneba.com/psn-lets-sing-2025-international-hits-dlc-ps4-ps5-psn-key-europe",
     ("PS4", "PS5"), False, None, "Let's Sing 2025 - International Hits (DLC)"),
    ("Split Fiction (Nintendo Switch 2) eShop Key HONG KONG",
     "https://www.eneba.com/nintendo-split-fiction-nintendo-switch-2-eshop-key-hong-kong",
     ("SWITCH2",), False, None, "Split Fiction"),           # 2026-09-14: a family
    ("Fortnite: Deep Freeze Bundle + 1000 V-Bucks XBOX LIVE Key SOUTH AFRICA",
     "https://www.eneba.com/xbox-fortnite-deep-freeze-bundle-1000-v-bucks-xbox-live-key-south-africa",
     ONE_SERIES, False, None, "Fortnite: Deep Freeze Bundle + 1000 V-Bucks"),
]


def _slot(sig):
    return sig.region_base, sig.region_label, sig.region_words


class ConfigBindingTests(unittest.TestCase):
    def test_config_declares_the_console_grammar(self):
        cfg = eneba.CONFIG
        self.assertIs(cfg.console_url_families, eneba.console_url_families)
        self.assertIs(cfg.console_pc_declared, eneba.console_pc_declared)
        self.assertIs(cfg.console_region_slot, eneba.console_region_slot)
        self.assertEqual(cfg.console_noise, ())
        self.assertEqual(cfg.url_platform_prefixes.get("uplay"), "UBISOFT")    # R29 untouched

    def test_registry_binds_the_module_config(self):
        self.assertIs(merchant_config("Eneba"), eneba.CONFIG)
        self.assertIs(merchant_config("eneba"), eneba.CONFIG)


class UrlSlotHookTests(unittest.TestCase):
    CASES = {
        "https://www.eneba.com/xbox-x-xbox-series-x-s-xbox-live-key-europe": (("XBOX_SERIES",), False, None),
        "https://www.eneba.com/xbox-x-windows-xbox-series-x-s-xbox-live-key-europe": (("XBOX_SERIES",), True, None),
        "https://www.eneba.com/xbox-x-xbox-series-x-s-windows-xbox-live-key-europe": (("XBOX_SERIES",), True, None),
        "https://www.eneba.com/xbox-x-xbox-one-xbox-series-x-s-xbox-live-key-europe": (ONE_SERIES, False, None),
        "https://www.eneba.com/xbox-x-xbox-one-series-x-s-xbox-live-key-europe": (ONE_SERIES, False, None),
        "https://www.eneba.com/psn-x-ps4-ps5-psn-key-europe": (("PS4", "PS5"), False, None),
        "https://www.eneba.com/psn-x-ps5-psn-key-europe": (("PS5",), False, None),
        "https://www.eneba.com/psn-x-ps4-psn-key-europe": (("PS4",), False, None),
        "https://www.eneba.com/nintendo-x-nintendo-switch-eshop-key-europe": (("SWITCH",), False, None),
        "https://www.eneba.com/nintendo-x-nintendo-switch-2-eshop-key-europe": (("SWITCH2",), False, None),
        "https://www.eneba.com/nintendo-x-nintendo-switch-nintendo-eshop-key-europe": (("SWITCH",), False, None),
        "https://www.eneba.com/xbox-x-xbox-series-x-s-xbox-key-united-states": (("XBOX_SERIES",), False, None),  # "XBOX Key" (2 real rows)
        "https://www.eneba.com/xbox-x-pc-xbox-live-key-europe": (ONE_SERIES, False, WINDOWS),
        "https://www.eneba.com/xbox-x-windows-xbox-live-key-europe": (ONE_SERIES, False, WINDOWS),
        # the Xbox store's own "(Windows) Key" form — no store-key marker (2026-09-26)
        "https://www.eneba.com/xbox-x-windows-key-europe": (ONE_SERIES, False, WINDOWS),
        "https://www.eneba.com/xbox-x-xbox-360-xbox-live-key-europe": ((), False, XBOX_360),
        # the URL declares nothing; the TITLE's "XBOX LIVE" is P4's generation-less Xbox
        "https://www.eneba.com/xbox-x-xbox-live-key-europe": (ONE_SERIES, False, None),
    }

    def test_hook_reads_the_slot_before_the_key_marker(self):
        for url, (families, pc, skip) in self.CASES.items():
            with self.subTest(url=url):
                expected = skip if skip == XBOX_360 else (families or None)
                if skip == WINDOWS:
                    expected = (XBOX_WINDOWS_KEY,)
                if url.endswith("/xbox-x-xbox-live-key-europe"):
                    expected = None                     # the hook reads nothing; P4 is the title's
                self.assertEqual(eneba.console_url_families(url), expected)
                self.assertEqual(eneba.console_pc_declared("X XBOX LIVE Key EUROPE", url), pc)
        self.assertEqual(eneba.console_url_families("https://www.eneba.com/xbox-x-pc-xbox-live-key-europe"),
                         (XBOX_WINDOWS_KEY,))
        # a "(Windows) Key" outside the Xbox store is not this grammar
        self.assertIsNone(eneba.console_url_families("https://www.eneba.com/steam-x-windows-key-europe"))
        self.assertEqual(eneba.console_url_families("https://www.eneba.com/xbox-x-xbox-360-xbox-live-key-europe"), SKIP_XBOX_360)

    def test_classifier_reads_the_hook(self):
        for url, (families, pc, skip) in self.CASES.items():
            with self.subTest(url=url):
                sig = classify_console("X XBOX LIVE Key EUROPE", url, "Eneba")   # title-less generation
                self.assertEqual((sig.families, sig.pc_declared, sig.skip_reason),
                                 (families, pc, None if skip == WINDOWS else skip))
                self.assertEqual(sig.windows_key, skip == WINDOWS)
                self.assertEqual(_slot(sig), ("eu", None, ("EUROPE",)))

    def test_leading_segment_is_the_store_never_a_generation(self):
        # "One Last Breath" sold through Xbox Live: the leading "xbox-" is the store; the
        # "one" that follows is the game — NOT an Xbox One key (13/16 rows were this artefact)
        self.assertIsNone(eneba.console_url_families("https://www.eneba.com/xbox-one-last-breath-xbox-live-key-europe"))
        sig = classify_console("Halo Infinite", "https://www.eneba.com/xbox-one-last-breath-xbox-live-key-europe", "Eneba")
        self.assertIsNotNone(sig)
        self.assertEqual((sig.families, sig.skip_reason), ((), NO_GEN))
        # an INNER "-xbox-one-" right before the marker IS a declaration
        sig = classify_console("One Last Breath XBOX LIVE Key EUROPE",
                               "https://www.eneba.com/xbox-one-last-breath-xbox-one-xbox-live-key-europe", "Eneba")
        self.assertEqual((sig.families, sig.skip_reason, sig.resolve_name), (("XBOX_ONE",), None, "One Last Breath"))
        # the merchant NAME selects the hooks — no host needed; the leading "xbox-one" is still
        # never Xbox One: the title's generation-less "XBOX LIVE" is P4's cross-gen reading
        sig = classify_console("Game XBOX LIVE Key EUROPE", "/xbox-one-last-breath-xbox-live-key-europe", "eneba")
        self.assertEqual((sig.skip_reason, sig.families, sig.generation_inferred), (None, ONE_SERIES, True))

    def test_run_inside_the_game_name_is_not_the_slot(self):
        # the slug mirrors the title: "Nintendo Switch Sports" opens the slug, the platform
        # slot before "eshop-key" is empty → nothing declared (fail-closed)
        self.assertIsNone(eneba.console_url_families("https://www.eneba.com/nintendo-nintendo-switch-sports-eshop-key-europe"))
        for title in ("Nintendo Switch Sports", "Nintendo Switch Sports eShop Key EUROPE"):
            sig = classify_console(title, "https://www.eneba.com/nintendo-nintendo-switch-sports-eshop-key-europe", "Eneba")
            self.assertEqual((sig.families, sig.skip_reason, sig.resolve_name), ((), NO_GEN, "Nintendo Switch Sports"))
        # a real platform slot AFTER the mirrored name still declares
        sig = classify_console("Nintendo Switch Sports (Nintendo Switch) eShop Key EUROPE",
                               "https://www.eneba.com/nintendo-nintendo-switch-sports-nintendo-switch-eshop-key-europe", "Eneba")
        self.assertEqual((sig.families, sig.resolve_name), (("SWITCH",), "Nintendo Switch Sports"))
        sig = classify_console("Xbox Fitness", "https://www.eneba.com/xbox-fitness-xbox-one-xbox-live-key-europe", "Eneba")
        self.assertEqual((sig.families, sig.resolve_name), (("XBOX_ONE",), "Xbox Fitness"))
        # the LAST marker counts: a game called "Key of Heaven"
        self.assertEqual(eneba.console_url_families("https://www.eneba.com/xbox-key-of-heaven-xbox-one-xbox-live-key-europe"), ("XBOX_ONE",))

    def test_no_marker_means_the_url_says_nothing(self):
        # fail-closed: without the "<STORE> Key" marker there is no platform slot to read
        self.assertIsNone(eneba.console_url_families("https://www.eneba.com/xbox-x-xbox-series-x-s-united-states"))
        self.assertIsNone(eneba.console_url_families(""))
        sig = classify_console("X XBOX LIVE Key", "https://www.eneba.com/xbox-x-xbox-series-x-s-united-states", "Eneba")
        # the URL run is NOT read (no marker); the title's "XBOX LIVE" is P4's inferred One + Series
        self.assertEqual((sig.families, sig.skip_reason, sig.generation_inferred), (ONE_SERIES, None, True))

    def test_xbox_plus_windows_without_a_generation(self):
        # P4 + P2 (Romain 2026-09-25): One + Series inferred, PC declared by the "Xbox + Windows" run
        sig = classify_console("Sokmeal Time Xbox + Windows Pack XBOX LIVE Key EUROPE",
                               "https://www.eneba.com/xbox-sokmeal-time-xbox-windows-pack-xbox-live-key-europe", "Eneba")
        self.assertEqual((sig.families, sig.pc_declared, sig.skip_reason), (ONE_SERIES, True, None))

    def test_windows_next_to_the_xbox_live_store_only_is_a_pc_key(self):
        # "(Windows) XBOX LIVE Key" — a PC key sold through Xbox Live (33 Eneba rows of the
        # 21/09 corpus). Romain 2026-09-26 (« 1. »): no longer refused — a windows_key signal,
        # never P2's "Xbox + PC" (pc_declared stays False): the AKS PC page decides.
        sig = classify_console("Manor Lords (Windows) XBOX LIVE Key EUROPE",
                               "https://www.eneba.com/xbox-manor-lords-windows-xbox-live-key-europe", "Eneba")
        self.assertEqual((sig.families, sig.pc_declared, sig.skip_reason, sig.windows_key),
                         (ONE_SERIES, False, None, True))
        # the same grammar with "xbox" in the URL only (Eneba's "(Windows) Key", 3 rows)
        sig = classify_console("Call of Duty®: Black Ops II (2012) (Windows) Key UNITED STATES",
                               "https://www.eneba.com/xbox-call-of-duty-r-black-ops-ii-2012-windows-key-united-states",
                               "Eneba")
        self.assertEqual((sig.skip_reason, sig.windows_key, sig.region_base), (None, True, "us"))

    def test_url_only_switch_2(self):
        sig = classify_console("Game eShop Key", "https://www.eneba.com/nintendo-game-nintendo-switch-2-eshop-key-europe", "Eneba")
        self.assertEqual((sig.families, sig.skip_reason), (("SWITCH2",), None))


class RegionSlotHookTests(unittest.TestCase):
    def test_region_after_the_key_word(self):
        for title, expected in {
            "Barn Finders (Xbox Series X|S) XBOX LIVE Key EUROPE": "EUROPE",
            "Lou's Lagoon Deluxe Edition (Xbox Series X|S) XBOX LIVE Key UNITED STATES": "UNITED STATES",
            "Split Fiction (Nintendo Switch 2) eShop Key HONG KONG": "HONG KONG",
            "Game (Xbox One) Xbox Live Key EU": "EU",
            "Game XBOX LIVE Key": None,
            "Game (Xbox One) Xbox Live Key Europe": None,      # not the uppercase grammar → shared read
            "Keys of Fate (Xbox One)": None,
        }.items():
            with self.subTest(title=title):
                self.assertEqual(eneba.console_region_slot(title), expected)

    def test_slot_exposed_through_the_classifier(self):
        cases = {
            "Barn Finders and Treasure Hunter Simulator Bundle (Xbox Series X|S) XBOX LIVE Key EUROPE": ("eu", None, ("EUROPE",)),
            "Lou's Lagoon Deluxe Edition (Xbox Series X|S) XBOX LIVE Key UNITED STATES": ("us", None, ("UNITED STATES",)),
            "Gnomes Garden 3: The thief of castles (Xbox Series X|S) XBOX LIVE Key UNITED KINGDOM": ("uk", None, ("UNITED KINGDOM",)),
            "LocoCycle (Xbox Series X|S) XBOX LIVE Key GLOBAL": ("global", None, ("GLOBAL",)),
            "Halloween - Digital Deluxe Edition (Xbox Series X|S) XBOX LIVE Key POLAND": (None, "POLAND", ("POLAND",)),
            "Crypt of the NecroDancer (Xbox Series X|S) XBOX LIVE Key MEXICO": (None, "MEXICO", ("MEXICO",)),
            "Assassin's Creed Origins (Xbox One) Xbox Live Key GERMANY": (None, "GERMANY", ("GERMANY",)),
            "Game (Xbox One) Xbox Live Key AUSTRIA": (None, "AUSTRIA", ("AUSTRIA",)),
            "Game (Xbox One) Xbox Live Key TURKEY": (None, "TURKEY", ("TURKEY",)),
            "Game (Xbox One) Xbox Live Key SOUTH AFRICA": (None, "SOUTH AFRICA", ("SOUTH AFRICA",)),
            "Split Fiction (Nintendo Switch 2) eShop Key HONG KONG": (None, "HONG KONG", ("HONG KONG",)),
            "Game (Xbox One) Xbox Live Key FRANCE": (None, "FRANCE", ("FRANCE",)),   # outside the shared list: still a lock
        }
        for title, slot in cases.items():
            with self.subTest(title=title):
                sig = classify_console(title, "https://www.eneba.com/xbox-x", "Eneba")
                self.assertIsNone(sig.skip_reason)
                self.assertEqual(_slot(sig), slot)
        # a region on a generation-less row is reported too (P4: inferred One + Series)
        sig = classify_console("POLSKA GUROM XBOX LIVE Key UNITED STATES",
                               "https://www.eneba.com/xbox-polska-gurom-xbox-live-key-united-states", "Eneba")
        self.assertEqual((sig.skip_reason, _slot(sig)), (None, ("us", None, ("UNITED STATES",))))
        # … and on a refused one (bare PSN, no generation — P4 PlayStation stays a refusal)
        sig = classify_console("Game PSN Key UNITED STATES", "https://www.eneba.com/psn-game-psn-key-united-states", "Eneba")
        self.assertEqual((sig.skip_reason, _slot(sig)), (NO_GEN, ("us", None, ("UNITED STATES",))))

    def test_hook_text_wins_over_a_stray_bracket_word(self):
        # the two real rows of the 2026-09-12 batch the hook corrects (the only classifier
        # diffs of the 2026-09-14 refactor): "(Without DE)" is a language note, "USA" is
        # part of the game name — the key is EUROPE
        sig = classify_console("Dying Light Essentials Edition (Without DE) XBOX LIVE Key EUROPE",
                               "https://www.eneba.com/xbox-dying-light-essentials-edition-without-de-xbox-live-key-europe", "Eneba")
        self.assertEqual((_slot(sig), sig.skip_reason), (("eu", None, ("EUROPE",)), None))   # P4: inferred
        sig = classify_console("Truck Simulator Cargo Driver 2025 - USA (Windows/Xbox Series X|S) XBOX LIVE Key EUROPE",
                               "https://www.eneba.com/xbox-truck-simulator-cargo-driver-2025-usa-windows-xbox-series-x-s-xbox-live-key-europe", "Eneba")
        self.assertEqual((sig.families, sig.pc_declared, sig.skip_reason, _slot(sig)),
                         (("XBOX_SERIES",), True, None, ("eu", None, ("EUROPE",))))


class ClassifyRowsTests(unittest.TestCase):
    def test_corpus_rows(self):
        for i, (title, url, families, pc, skip, name) in enumerate(ROWS, 11):
            with self.subTest(row=i, title=title):
                sig = classify_console(title, url, "Eneba")
                self.assertIsInstance(sig, ConsoleSignal)
                self.assertEqual((sig.families, sig.pc_declared, sig.skip_reason, sig.resolve_name),
                                 (families, pc, skip, name))
                self.assertEqual(sig.resolve_name, resolve_name_of(title, "Eneba"))
        # the Switch 2 HONG KONG row: family declared, region forbidden (the matcher skips on the label)
        sig = classify_console(ROWS[5][0], ROWS[5][1], "Eneba")
        self.assertEqual((sig.families, sig.skip_reason, sig.region_label), (("SWITCH2",), None, "HONG KONG"))

    def test_seven_corpus_rows(self):
        self.assertEqual(len(ROWS), 7)

    def test_real_rows_of_the_review(self):
        sig = classify_console("NHL® 27 Deluxe Edition XBOX Series X|S (Xbox Series X|S) XBOX LIVE Key EUROPE",
                               "https://www.eneba.com/xbox-nhl-r-27-deluxe-edition-xbox-series-x-s-xbox-series-x-s-xbox-live-key-europe", "Eneba")
        self.assertEqual((sig.families, sig.resolve_name), (("XBOX_SERIES",), "NHL® 27 Deluxe Edition"))
        for region, base in (("UNITED STATES", "us"), ("EUROPE", "eu")):
            sig = classify_console(f"Get Them Out! (Series) (Xbox Series X|S) XBOX LIVE Key {region}",
                                   f"https://www.eneba.com/xbox-get-them-out-series-xbox-series-x-s-xbox-live-key-{base}", "Eneba")
            self.assertEqual((sig.families, sig.skip_reason, sig.resolve_name, sig.region_base),
                             (("XBOX_SERIES",), None, "Get Them Out! (Series)", base))
        sig = classify_console("Xbox Live Gift Card 500 TRY Xbox Live Key TURKEY", "https://www.eneba.com/xbox-x", "Eneba")
        self.assertEqual((sig.skip_reason, sig.families), (skip_not_a_game("XBOX LIVE GIFT CARD"), ()))

    def test_pc_row_returns_none(self):
        self.assertIsNone(classify_console("Elden Ring Steam Key GLOBAL",
                                           "https://www.eneba.com/steam-elden-ring-steam-key-global", "Eneba"))


if __name__ == "__main__":
    unittest.main()

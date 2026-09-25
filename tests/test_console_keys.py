"""tests for src/console_keys.py — R45 console keys (2026-09-12, review fixes 2026-09-14),
SHARED vocabulary only since the 2026-09-14 refactor (R32 / R45, Romain: « pour la
détection région / édition / plateforme, tu as un fichier de config par marchand »).

Fixtures = the shared-grammar rows of the 40 representative feed rows of the 2026-09-12
read-only extraction (docs/feeds study §7: 18 rows here — Kinguin, K4G, Driffle, G2A,
GameSeal, merchants whose grammar is the shared one; the 10 MMOGA, 7 Eneba and 5 Gamivo
rows moved to tests/test_merchants_<merchant>.py with their merchant grammar) plus the
design examples (DESIGN_consoles_R45 §2), the real rows quoted by the 2026-09-14
adversarial review (region slot, Switch 2 family, accounts, bare "Xbox One/Series",
leading name token) and SMALL excerpts of real AKS page bodies (the
``<ul class="aks-offer-tabulations">`` block). The merchant HOOK plumbing is tested with
a fake merchant injected into the registry; the module is pinned to name no merchant.
"""

import io
import re
import subprocess
import sys
import tokenize
import unittest
from pathlib import Path
from unittest import mock

from src.console_keys import (
    CONSOLE_FAMILIES,
    CONSOLE_PAGE_KIND,
    CONSOLE_PAGE_KINDS,
    CONSOLE_PLATFORM_LABEL,
    CONSOLE_REGION_IDS,
    CONSOLE_REGION_LABELS,
    DECLARABLE_FAMILIES,
    SKIP_NO_GENERATION,
    SKIP_PC_ONLY,
    SKIP_RESIDUE,
    SKIP_SWITCH_2,
    SKIP_XBOX_360,
    ConsoleSignal,
    SlugRead,
    classify_console,
    console_marker_in_url,
    console_page_identity,
    extract_console_pages,
    extract_page_platform,
    path_tokens,
    region_slot_of,
    resolve_name_and_regions,
    resolve_name_of,
    skip_not_a_game,
    slug_families,
)
from src.merchant_config import MerchantConfig
from src.merchants import registry

ONE_SERIES = ("XBOX_ONE", "XBOX_SERIES")
NO_GEN = "console: no declared generation (R45)"
# RETIRED 2026-09-14 (Switch 2 pages exist, Nintendo bucket): kept only to assert that the
# classifier never emits it any more.
SWITCH_2 = "console: Switch 2 has no AKS bucket (R45)"
XBOX_360 = "console: Xbox 360 (R45)"
PC_ONLY = "console: PC-only Xbox Live key (R45)"
RESIDUE = "console: unparsed platform residue (R45)"
REPO = Path(__file__).resolve().parents[1]


def _not_a_game(marker: str) -> str:
    return f"console: {marker} — not a game (R45)"


# (title, url, merchant, families, pc_declared, skip_reason, resolve_name) — the 18
# shared-grammar rows of the study §7 (rows 18-25 Kinguin, 31-34 K4G, 35-37 Driffle,
# 38-39 G2A, 40 GameSeal), verbatim titles/URLs. These merchants have no console hooks:
# the shared title grammar + the plain slug runs read them.
ROWS = [
    # 18-25 Kinguin
    ("Infected Cowboys Bundle EU XBOX One / Xbox Series X|S CD Key",
     "https://www.kinguin.net/category/844910/infected-cowboys-bundle-eu-xbox-one-xbox-series-x-s-cd-key",
     "Kinguin", ONE_SERIES, False, None, "Infected Cowboys Bundle"),
    ("MechWarrior 5: Mercenaries CA Xbox One / Xbox Series X|S / PC CD Key",
     "https://www.kinguin.net/category/841718/mechwarrior-5-mercenaries-ca-xbox-one-xbox-series-x-s-pc-cd-key",
     "Kinguin", ONE_SERIES, True, None, "MechWarrior 5: Mercenaries"),
    ("Hoomanz! Xbox Series X|S / PC CD Key",
     "https://www.kinguin.net/category/808670/hoomanz-xbox-series-x-s-pc-cd-key",
     "Kinguin", ("XBOX_SERIES",), True, None, "Hoomanz!"),
    ("Life is Strange Remastered Collection EU PS4/PS5 CD Key",
     "https://www.kinguin.net/category/141837/life-is-strange-remastered-collection-eu-ps4-ps5-cd-key",
     "Kinguin", ("PS4", "PS5"), False, None, "Life is Strange Remastered Collection"),
    ("CloverPit EU Nintendo Switch 2 CD Key",
     "https://www.kinguin.net/category/764730/cloverpit-eu-nintendo-switch-2-cd-key",
     "Kinguin", ("SWITCH2",), False, None, "CloverPit"),             # 2026-09-14: a family
    ("Blocky Farm XBOX One / Xbox Series X|S Account",
     "https://www.kinguin.net/category/523387/blocky-farm-xbox-one-xbox-series-x-s-account",
     "Kinguin", (), False, _not_a_game("ACCOUNT"), "Blocky Farm"),
    ("NHL 22 PS4 Access",
     "https://www.kinguin.net/category/366235/nhl-22-ps4-access",
     "Kinguin", (), False, _not_a_game("ACCESS"), "NHL 22"),
    ("NHL 27 UK Deluxe Edition Xbox Series X|S CD Key",
     "https://www.kinguin.net/category/830178/nhl-27-uk-deluxe-edition-xbox-series-x-s-cd-key",
     "Kinguin", ("XBOX_SERIES",), False, None, "NHL 27 UK Deluxe Edition"),
    # 31-34 K4G
    ("Persona 5 Royal Canada XBOX One/PC/XBOX Series X|S CD Key",
     "https://k4g.com/product/persona-5-royal-pc-xbox-one-series-x-s-canada-cd-key-cd-key-IY4ZKGPV",
     "K4G", ONE_SERIES, True, None, "Persona 5 Royal"),
    ("Home Sweet Home Europe XBOX One/Series X|S CD Key",
     "https://k4g.com/product/home-sweet-home-xbox-one-series-x-s-xbox-europe-instant-cd-key-cd-key-5ZF2STXM",
     "K4G", ONE_SERIES, False, None, "Home Sweet Home"),
    ("Pokémon Scarlet Europe Nintendo Switch 2 CD Key",
     "https://k4g.com/product/pokemon-scarlet-nintendo-switch-2-europe-cd-key-cd-key-3FWB2QK5",
     "K4G", ("SWITCH2",), False, None, "Pokémon Scarlet"),           # 2026-09-14: a family
    ("Borderlands 3 Ultimate Edition Europe PS4/PS5 CD Key",
     "https://k4g.com/product/borderlands-3-ps4-ps5-europe-instant-cd-key-ultimate-edition-cd-key-QF8DZERN",
     "K4G", ("PS4", "PS5"), False, None, "Borderlands 3 Ultimate Edition"),
    # 35-37 Driffle
    ("Sniper Ghost Warrior Contracts 1 and 2 Double Pack (Europe) (Xbox One / Xbox Series X|S) - Xbox Live - Digital Key",
     "https://www.driffle.com/sniper-ghost-warrior-contracts-1-and-2-double-pack-europe-xbox-one-xbox-series-xs-xbox-live-digital-key-p9988263",
     "Driffle", ONE_SERIES, False, None, "Sniper Ghost Warrior Contracts 1 and 2 Double Pack"),
    ("The Elder Scrolls Online - Explorer's Pack DLC (Europe) (PS4 / PS5) - PSN - Digital Key",
     "https://www.driffle.com/the-elder-scrolls-online-explorers-pack-dlc-europe-ps4-ps5-psn-digital-key-p9955436",
     "Driffle", ("PS4", "PS5"), False, None, "The Elder Scrolls Online - Explorer's Pack DLC"),
    ("Syberia trilogy (Europe) (Nintendo Switch) - Nintendo - Digital Key",
     "https://www.driffle.com/syberia-trilogy-eu-nintendo-switch-nintendo-digital-code-p9896737",
     "Driffle", ("SWITCH",), False, None, "Syberia trilogy"),
    # 38-39 G2A ("X/S" spelling)
    ("Train Sim World 6 | Deluxe Edition (Xbox Series X/S, PC) - Xbox Live Key - UNITED KINGDOM",
     "https://www.g2a.com/train-sim-world-6-deluxe-edition-xbox-series-x-s-pc-xbox-live-key-united-kingdom-i10000512449018",
     "G2A", ("XBOX_SERIES",), True, None, "Train Sim World 6 | Deluxe Edition"),
    ("Power Rangers: Battle for the Grid | Super Edition Xbox One, PC - Xbox Live Key - EUROPE",
     "https://www.g2a.com/power-rangers-battle-for-the-grid-super-edition-xbox-one-pc-xbox-live-key-europe-i10000191702012",
     "G2A", ("XBOX_ONE",), True, None, "Power Rangers: Battle for the Grid | Super Edition"),
    # 40 GameSeal
    ("Another World - 20th Anniversary Edition (Xbox One / Xbox Series X|S) Xbox Live Key - EU",
     "https://gameseal.com/another-world-20th-anniversary-edition-xbox-one-xbox-series-x-s-xbox-live-key-eu",
     "GameSeal", ONE_SERIES, False, None, "Another World - 20th Anniversary Edition"),
]


class BucketTableTests(unittest.TestCase):
    def test_families_and_page_kinds(self):
        # SWITCH2 (2026-09-14): its own AKS page kind (Street Fighter 6 Nintendo Switch 2
        # id 188436, ELDEN RING Tarnished Edition Nintendo Switch 2 id 188441)
        self.assertEqual(CONSOLE_FAMILIES, ("XBOX_ONE", "XBOX_SERIES", "XBOX_PC", "PS4", "PS5", "SWITCH", "SWITCH2"))
        self.assertEqual(CONSOLE_PAGE_KIND, {
            "XBOX_ONE": "xbox-one", "XBOX_SERIES": "xbox-series", "XBOX_PC": "cd-key",
            "PS4": "ps4", "PS5": "ps5", "SWITCH": "nintendo-switch", "SWITCH2": "nintendo-switch-2"})
        self.assertEqual(CONSOLE_PAGE_KINDS, ("ps4", "ps5", "xbox-one", "xbox-series",
                                              "nintendo-switch", "nintendo-switch-2", "cd-key"))
        for fam in CONSOLE_FAMILIES:
            self.assertIn(CONSOLE_PAGE_KIND[fam], CONSOLE_PAGE_KINDS)
            self.assertIn(fam, CONSOLE_REGION_IDS)
            self.assertIn(fam, CONSOLE_PLATFORM_LABEL)
        self.assertEqual(set(CONSOLE_REGION_IDS), set(CONSOLE_FAMILIES))
        self.assertEqual(DECLARABLE_FAMILIES, tuple(f for f in CONSOLE_FAMILIES if f != "XBOX_PC"))

    def test_every_family_base_id(self):
        # §0 table — the feed modal's region catalog (867 entries, 9 identical catalogs)
        expected = {
            ("XBOX_ONE", "global"): "24", ("XBOX_ONE", "eu"): "24eu", ("XBOX_ONE", "us"): "24us", ("XBOX_ONE", "uk"): "226",
            ("XBOX_SERIES", "global"): "300", ("XBOX_SERIES", "eu"): "302", ("XBOX_SERIES", "us"): "303", ("XBOX_SERIES", "uk"): "305",
            ("XBOX_PC", "global"): "306", ("XBOX_PC", "eu"): "241", ("XBOX_PC", "us"): "242", ("XBOX_PC", "uk"): "240",
            ("PS4", "global"): "88", ("PS4", "eu"): "88eu", ("PS4", "us"): "88us", ("PS4", "uk"): "88uk",
            # P3, DÉCIDÉ Romain 2026-09-25 : PS5 hors GLOBAL = les cases PlayStation de PS4
            ("PS5", "global"): "88ps5h", ("PS5", "eu"): "88eu", ("PS5", "us"): "88us", ("PS5", "uk"): "88uk",
            ("SWITCH", "global"): "99", ("SWITCH", "eu"): "99eu", ("SWITCH", "us"): "99us", ("SWITCH", "uk"): "992",
            # Switch 2 offers use the NINTENDO family bucket (2026-09-14: prices region 99,
            # regions map {99: GLOBAL}, activationPlatform nintendo-eshop on both saved pages)
            ("SWITCH2", "global"): "99", ("SWITCH2", "eu"): "99eu", ("SWITCH2", "us"): "99us", ("SWITCH2", "uk"): "992",
        }
        flat = {(fam, base): rid for fam, bases in CONSOLE_REGION_IDS.items() for base, rid in bases.items()}
        self.assertEqual(flat, expected)
        self.assertEqual(CONSOLE_REGION_IDS["SWITCH2"], CONSOLE_REGION_IDS["SWITCH"])
        # PS5: its own GLOBAL bucket, the PlayStation EU / US / UK buckets of PS4 (P3,
        # Romain 2026-09-25 — AKS already files PS5 offers there), no gift anywhere
        self.assertEqual(CONSOLE_REGION_IDS["PS5"], {"global": "88ps5h", "eu": "88eu", "us": "88us", "uk": "88uk"})
        self.assertEqual({b: r for b, r in CONSOLE_REGION_IDS["PS5"].items() if b != "global"},
                         {b: r for b, r in CONSOLE_REGION_IDS["PS4"].items() if b != "global"})
        for bases in CONSOLE_REGION_IDS.values():
            self.assertFalse(any(k.startswith("gift") or k.startswith("gmg") for k in bases))

    def test_every_label_is_the_catalog_master_text_without_suffix_and_bom(self):
        expected = {
            "24": "Xbox One Game Code", "24eu": "Xbox Game Code EUROPE", "24us": "Xbox Game Code US",
            "226": "Xbox Game Code UK",
            "300": "Xbox Series", "302": "Xbox Series EU Game Code", "303": "Xbox Series US Game Code",
            "305": "Xbox Series Uk Game Code",
            "306": "Xbox/PC GLOBAL", "241": "XBOX/PC EU", "242": "XBOX/PC US", "240": "XBOX/PC UK",
            "88": "Playstation Game Code GLOBAL", "88eu": "Playstation Game Code EUROPE",
            "88us": "Playstation Game Code US", "88uk": "Playstation Game Code UK",
            "88ps5h": "PS5",
            "99": "NINTENDO GAME CODE GLOBAL", "99eu": "Nintendo GAME CODE EU", "99us": "Nintendo GAME CODE US",
            "992": "Nintendo GAME CODE UK",
        }
        self.assertEqual(CONSOLE_REGION_LABELS, expected)
        all_ids = {rid for bases in CONSOLE_REGION_IDS.values() for rid in bases.values()}
        self.assertEqual(set(CONSOLE_REGION_LABELS), all_ids)
        for label in CONSOLE_REGION_LABELS.values():
            self.assertNotIn("﻿", label)          # 306's master text carries a BOM; we don't
            self.assertFalse(label.endswith(")"))       # no " (id)" suffix
            self.assertEqual(label, label.strip())

    def test_platform_labels(self):
        self.assertEqual(CONSOLE_PLATFORM_LABEL, {
            "XBOX_ONE": "Xbox One", "XBOX_SERIES": "Xbox Series X|S",
            "XBOX_PC": "Xbox / PC (Play Anywhere)", "PS4": "PS4", "PS5": "PS5",
            "SWITCH": "Nintendo Switch", "SWITCH2": "Nintendo Switch 2"})

    def test_skip_reasons_are_byte_exact(self):
        self.assertEqual(SKIP_NO_GENERATION, NO_GEN)
        self.assertEqual(SKIP_PC_ONLY, PC_ONLY)
        self.assertEqual(SKIP_XBOX_360, XBOX_360)
        self.assertEqual(SKIP_RESIDUE, RESIDUE)
        self.assertEqual(skip_not_a_game("PSN CARD"), _not_a_game("PSN CARD"))


class NoMerchantInSharedModuleTests(unittest.TestCase):
    """Romain's rule (2026-09-14): the shared classifier names no merchant in CODE — every
    merchant grammar is a hook of src/merchants/<merchant>.py. Comments and docstrings may
    quote real rows; identifiers and string literals may not name a merchant."""

    MERCHANTS = ("mmoga", "gamivo", "eneba", "kinguin", "k4g", "driffle", "g2a", "gameseal",
                 "allyouplay", "cjs", "difmark", "instant")

    @staticmethod
    def _code_tokens(source: str) -> list[str]:
        out: list[str] = []
        prev = None                       # last significant token type (comments / NL skipped)
        for tok in tokenize.generate_tokens(io.StringIO(source).readline):
            if tok.type in (tokenize.COMMENT, tokenize.NL):
                continue
            docstring = tok.type == tokenize.STRING and prev in (
                None, tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT, tokenize.ENCODING)
            if tok.type not in (tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT,
                                tokenize.ENCODING, tokenize.ENDMARKER) and not docstring:
                out.append(tok.string)
            prev = tok.type
        return out

    def test_tokenizer_helper_distinguishes_docstrings(self):
        tokens = self._code_tokens('"""doc gamivo"""\nx = "lit"  # gamivo comment\ndef f():\n    """gamivo"""\n    return "ok"\n')
        self.assertEqual(tokens, ["x", "=", '"lit"', "def", "f", "(", ")", ":", "return", '"ok"'])

    def test_console_keys_names_no_merchant_in_code(self):
        source = (REPO / "src" / "console_keys.py").read_text(encoding="utf-8")
        offenders = [t for t in self._code_tokens(source) if any(m in t.lower() for m in self.MERCHANTS)]
        self.assertEqual(offenders, [])


class ImportOrderTests(unittest.TestCase):
    """The registry lives in src/merchants/registry.py; src.console_keys reaches it through a
    function-level import, so every import order is cycle-free (2026-09-14)."""

    def test_every_import_order_works(self):
        orders = (
            "import src.matcher, src.console_keys, src.merchants.registry",
            "import src.console_keys, src.merchants.registry, src.matcher",
            "import src.merchants.registry, src.console_keys, src.matcher",
            "import src.merchants.eneba, src.merchants.gamivo, src.merchants.mmoga, src.console_keys, src.matcher",
            "import src.console_keys as c; assert c.classify_console('Game PS5 CD Key', '', 'Kinguin').families == ('PS5',)",
        )
        for code in orders:
            with self.subTest(code=code):
                r = subprocess.run([sys.executable, "-c", code], cwd=str(REPO), capture_output=True, text=True)
                self.assertEqual(r.returncode, 0, r.stderr)


class HookPlumbingTests(unittest.TestCase):
    """The four console hooks of MerchantConfig (2026-09-14) through a FAKE merchant injected
    into the registry — the plumbing, not any real merchant's grammar."""

    def _with(self, **hooks):
        cfg = MerchantConfig("Hookshop", **hooks)
        return mock.patch.dict(registry.MERCHANT_CONFIGS, {"HOOKSHOP": cfg})

    def test_merchant_without_config_gets_the_shared_reading_whatever_the_host(self):
        # a merchant NAME selects the hooks; the URL host is irrelevant
        sig = classify_console("X XBOX LIVE Key EUROPE", "https://www.gamivo.com/product/game-xbox-xboxoneseries-uk-standard", "Shop")
        # a fused run is not shared vocabulary: the families come from the title's
        # generation-less "XBOX LIVE" (P4, 2026-09-25), INFERRED — not from the URL run
        self.assertEqual((sig.families, sig.skip_reason, sig.generation_inferred),
                         (("XBOX_ONE", "XBOX_SERIES"), None, True))
        sig = classify_console("X XBOX LIVE Key EUROPE", "https://www.eneba.com/xbox-one-last-breath-xbox-live-key-europe", "Shop")
        self.assertEqual(sig.families, ("XBOX_ONE",))                      # the plain "xbox-one" run, no store rule
        sig = classify_console("Some Game - EU", "https://www.mmoga.com/Xbox-Live/Xbox-Series-XS-Game-Keys/Some-Game-EU.html", "Shop")
        self.assertEqual(sig.families, ("XBOX_SERIES",))                   # "xbox-series" is a plain run too
        self.assertIsNone(registry.merchant_config("Shop"))

    def test_url_hook_is_consulted_only_when_the_title_declares_no_family(self):
        calls = []

        def hook(url):
            calls.append(url)
            return ("PS4",)

        with self._with(console_url_families=hook):
            sig = classify_console("Game PSN Key", "https://example.com/g", "Hookshop")
            self.assertEqual((sig.families, sig.skip_reason), (("PS4",), None))
            sig = classify_console("Game (PS5) PSN Key", "https://example.com/g", "Hookshop")
            self.assertEqual(sig.families, ("PS5",))
        self.assertEqual(calls, ["https://example.com/g"])
        # the hook REPLACES the shared slug reading for that merchant
        with self._with(console_url_families=lambda url: None):
            sig = classify_console("Game PSN Key", "https://example.com/game-ps5-psn-key", "Hookshop")
            self.assertEqual((sig.families, sig.skip_reason), ((), NO_GEN))
        sig = classify_console("Game PSN Key", "https://example.com/game-ps5-psn-key", "Hookshop")   # no config any more
        self.assertEqual(sig.families, ("PS5",))

    def test_url_hook_skip_reasons_and_fail_closed_validation(self):
        with self._with(console_url_families=lambda url: SKIP_PC_ONLY):
            sig = classify_console("Game XBOX LIVE Key", "https://example.com/g", "Hookshop")
            self.assertEqual((sig.families, sig.skip_reason), ((), PC_ONLY))
        with self._with(console_url_families=lambda url: skip_not_a_game("PSN CARDS AT")):
            sig = classify_console("Thing PSN", "https://example.com/g", "Hookshop")
            self.assertEqual(sig.skip_reason, _not_a_game("PSN CARDS AT"))
        # outside the contract: a non-"console:" string, an unknown family, the target bucket
        with self._with(console_url_families=lambda url: "PS5"):
            sig = classify_console("Game PSN Key", "https://example.com/g", "Hookshop")
            self.assertEqual(sig.families, ())
            self.assertTrue(sig.skip_reason.startswith("console: merchant URL hook returned 'PS5'"), sig.skip_reason)
        for bad in (("PLAYSTATION",), ("XBOX_PC",), ("PS5", "XBOX_PC")):
            with self._with(console_url_families=lambda url, b=bad: b):
                sig = classify_console("Game PSN Key", "https://example.com/g", "Hookshop")
                self.assertEqual(sig.families, ())
                self.assertIn("declared unknown platform", sig.skip_reason)
                self.assertTrue(sig.skip_reason.endswith("(R45)"))
        # duplicates are folded, order kept
        with self._with(console_url_families=lambda url: ("PS5", "PS4", "PS5")):
            sig = classify_console("Game PSN Key", "https://example.com/g", "Hookshop")
            self.assertEqual(sig.families, ("PS5", "PS4"))
        # the title's Xbox 360 wins before the hook is even asked
        with self._with(console_url_families=lambda url: ("PS5",)):
            sig = classify_console("Game (Xbox 360) XBOX LIVE Key", "https://example.com/g", "Hookshop")
            self.assertEqual(sig.skip_reason, XBOX_360)

    def test_pc_hook_is_or_ed_with_the_shared_title_check(self):
        with self._with(console_url_families=lambda url: ("XBOX_SERIES",),
                        console_pc_declared=lambda name, url: "-windows-" in url):
            sig = classify_console("Game XBOX LIVE Key", "https://example.com/game-windows-x", "Hookshop")
            self.assertEqual((sig.families, sig.pc_declared), (("XBOX_SERIES",), True))
            sig = classify_console("Game XBOX LIVE Key", "https://example.com/game-x", "Hookshop")
            self.assertEqual((sig.families, sig.pc_declared), (("XBOX_SERIES",), False))
            # the shared title phrase still counts on its own
            sig = classify_console("Game (Xbox Series X|S / Windows) XBOX LIVE Key", "https://example.com/game-x", "Hookshop")
            self.assertEqual((sig.families, sig.pc_declared), (("XBOX_SERIES",), True))
            # the hook alone never makes a PC declaration a family
            sig = classify_console("Game XBOX LIVE Key", "https://example.com/game-windows-x", "Hookshop")
            self.assertNotIn("XBOX_PC", sig.families)

    def test_region_slot_hook_first_then_the_shared_reads(self):
        with self._with(console_region_slot=lambda name: "Hong Kong" if "HK-LOCK" in name else None):
            sig = classify_console("Game HK-LOCK (PS5) - EU", "https://example.com/g", "Hookshop")
            self.assertEqual((sig.region_base, sig.region_label, sig.region_words), (None, "HONG KONG", ("Hong Kong",)))
            sig = classify_console("Game (PS5) - EU", "https://example.com/g", "Hookshop")
            self.assertEqual((sig.region_base, sig.region_label, sig.region_words), ("eu", None, ("EU",)))
        # the mapping text → base / label is the shared vocabulary
        self.assertEqual(region_slot_of(("United Kingdom",)), ("uk", None))
        self.assertEqual(region_slot_of(("EUROPE",)), ("eu", None))
        self.assertEqual(region_slot_of(("CA",)), (None, "CANADA"))
        self.assertEqual(region_slot_of(("Hong Kong",)), (None, "HONG KONG"))
        self.assertEqual(region_slot_of(("Narnia",)), (None, "NARNIA"))
        self.assertEqual(region_slot_of(("EU", "UK")), (None, None))
        self.assertEqual(region_slot_of(()), (None, None))
        # an empty / blank hook answer is "no slot"
        with self._with(console_region_slot=lambda name: "  "):
            sig = classify_console("Game (PS5) - EU", "https://example.com/g", "Hookshop")
            self.assertEqual(sig.region_words, ("EU",))

    def test_noise_phrase_and_pattern(self):
        pattern = re.compile(r"\(valid until [A-Z][a-z]+ \d{4}\)")
        with self._with(console_noise=("Instant Delivery", pattern)):
            self.assertEqual(resolve_name_of("Game (valid until March 2027) PS5 Instant Delivery - EU", "Hookshop"), "Game")
            self.assertEqual(resolve_name_of("Game PS5 instant   delivery", "Hookshop"), "Game")      # literal: any case / spacing
            self.assertEqual(resolve_name_of("Instantly Delivered Game PS5", "Hookshop"), "Instantly Delivered Game")
            self.assertEqual(resolve_name_and_regions("Game PS5 Instant Delivery - EU", "Hookshop"), ("Game", ("EU",)))
            sig = classify_console("Game (valid until March 2027) PS5 Instant Delivery - EU", "https://example.com/g", "Hookshop")
            self.assertEqual((sig.families, sig.resolve_name, sig.region_base), (("PS5",), "Game", "eu"))
        # without the config the phrase stays (it is not shared vocabulary)
        self.assertEqual(resolve_name_of("Game PS5 Instant Delivery - EU", "Hookshop"), "Game Instant Delivery")
        self.assertEqual(resolve_name_of("Game PS5 Instant Delivery - EU"), "Game Instant Delivery")

    def test_config_defaults_are_empty(self):
        cfg = MerchantConfig("Plain")
        self.assertIsNone(cfg.console_url_families)
        self.assertIsNone(cfg.console_pc_declared)
        self.assertIsNone(cfg.console_region_slot)
        self.assertEqual(cfg.console_noise, ())


class SlugFamiliesTests(unittest.TestCase):
    def test_shared_slug_runs(self):
        cases = {
            "game-xbox-one-cd-key": (("XBOX_ONE",), False, None, (1, 3)),
            "game-xbox-series-x-s-cd-key": (("XBOX_SERIES",), False, None, (1, 5)),
            "game-xbox-one-xbox-series-xs-cd-key": (ONE_SERIES, False, None, (1, 6)),
            "game-pc-xbox-one-series-x-s": (ONE_SERIES, True, None, (2, 7)),
            "game-ps4-ps5-cd-key": (("PS4", "PS5"), False, None, (1, 3)),
            "game-playstation-5": (("PS5",), False, None, (1, 3)),
            "game-nintendo-switch-2-cd-key": (("SWITCH2",), False, None, (1, 4)),
            "game-xbox-360-cd-key": ((), False, XBOX_360, None),
            "game-xbox-live-key": ((), False, None, None),
        }
        for slug, (families, pc, skip, span) in cases.items():
            with self.subTest(slug=slug):
                read = slug_families(path_tokens(slug))
                self.assertIsInstance(read, SlugRead)
                self.assertEqual((read.families, read.pc_declared, read.skip_reason, read.span), (families, pc, skip, span))
        self.assertEqual(path_tokens("https://example.com/A-B/c_d?x=ps5"), ["a", "b", "c", "d"])


class ClassifyRowsTests(unittest.TestCase):
    """The shared-grammar rows: families, pc_declared, skip_reason, resolve_name."""

    def test_shared_rows(self):
        for i, (title, url, merchant, families, pc, skip, name) in enumerate(ROWS, 1):
            with self.subTest(row=i, title=title):
                sig = classify_console(title, url, merchant)
                self.assertIsInstance(sig, ConsoleSignal)
                self.assertEqual(sig.families, families)
                self.assertEqual(sig.pc_declared, pc)
                self.assertEqual(sig.skip_reason, skip)
                if name is not None:
                    self.assertEqual(sig.resolve_name, name)
                self.assertNotIn("XBOX_PC", sig.families)
                self.assertNotEqual(sig.skip_reason, SWITCH_2)     # retired 2026-09-14
                if skip is None:
                    self.assertTrue(sig.families)
                    self.assertTrue(sig.resolve_name)
                    self.assertEqual(len(sig.families), len(set(sig.families)))
                # the same reading whatever the merchant NAME (no hooks for these grammars)
                self.assertEqual(classify_console(title, url, "Shop"), sig)

    def test_eighteen_shared_rows_of_the_forty(self):
        # 40 study rows = 18 here + 10 MMOGA + 7 Eneba + 5 Gamivo (tests/test_merchants_*.py)
        self.assertEqual(len(ROWS), 18)

    def test_signal_is_frozen(self):
        sig = classify_console(*ROWS[0][:3])
        with self.assertRaises(Exception):
            sig.families = ()  # type: ignore[misc]


class ClassifyGrammarTests(unittest.TestCase):
    def test_pc_row_returns_none(self):
        self.assertIsNone(classify_console("Elden Ring Steam Key GLOBAL", "https://example.com/steam-elden-ring-steam-key-global", "Shop"))
        self.assertIsNone(classify_console("Among Us", "https://example.com/Steam-Games/Among-Us.html", "Shop"))
        # "PS Plus" without a console TOKEN (PS is not one) is not a console row either —
        # the matcher's other categorical scans keep ruling it
        self.assertIsNone(classify_console("PS Plus 12 Months", "https://example.com/x", "Shop"))

    def test_bare_switch_title_is_a_console_row_without_generation(self):
        # "Switch" alone in a platform SLOT is a console marker, never a family
        sig = classify_console("Think Logic! Sudoku Binary Suguru (Switch) (EU)",
                               "https://gameboost.com/think-logic-sudoku-binary-suguru-switch-eu-00-43867", "GameBoost")
        self.assertIsNotNone(sig)
        self.assertEqual(sig.skip_reason, NO_GEN)
        # 2026-09-25 (bug reported by Romain): a "Switch" in the NAME of a title that declares
        # a PC store is a PC row — "Switch Galaxy Ultra Steam CD Key" used to be refused here.
        self.assertIsNone(classify_console("Switch Galaxy Ultra Steam CD Key",
                                           "https://www.kinguin.net/category/1/switch-galaxy-ultra-steam-cd-key",
                                           "Kinguin"))

    def test_generic_url_grammar(self):
        base = "https://example.com/game-{run}-cd-key"
        cases = {
            "xbox-one": (("XBOX_ONE",), False, None),
            "xbox-series-x-s": (("XBOX_SERIES",), False, None),
            "xbox-series-xs": (("XBOX_SERIES",), False, None),
            "xbox-series": (("XBOX_SERIES",), False, None),
            "xbox-one-series-x-s": (ONE_SERIES, False, None),
            "xbox-one-xbox-series-xs": (ONE_SERIES, False, None),
            "pc-xbox-one-series-x-s": (ONE_SERIES, True, None),
            "xbox-series-x-s-pc": (("XBOX_SERIES",), True, None),
            "ps4": (("PS4",), False, None), "ps5": (("PS5",), False, None),
            "ps4-ps5": (("PS4", "PS5"), False, None),
            "playstation-4": (("PS4",), False, None), "playstation-5": (("PS5",), False, None),
            "nintendo-switch": (("SWITCH",), False, None),
            "nintendo-switch-2": (("SWITCH2",), False, None),
            "xbox-360": ((), False, XBOX_360),
            # P4 (Romain 2026-09-25): the title's generation-less "XBOX LIVE" reads as One + Series
            "xbox-live": (ONE_SERIES, False, None),
        }
        for run, (families, pc, skip) in cases.items():
            with self.subTest(run=run):
                sig = classify_console("Game XBOX LIVE Key", base.format(run=run), "SomeShop")
                self.assertEqual((sig.families, sig.pc_declared, sig.skip_reason), (families, pc, skip))
        # the slug is the LAST path segment ("/category/<id>/<slug>")
        sig = classify_console("Game XBOX LIVE Key", "https://www.kinguin.net/category/1/game-ps5-cd-key", "Kinguin")
        self.assertEqual(sig.families, ("PS5",))

    def test_title_phrase_spellings(self):
        cases = {
            "Game (Xbox One / Series X|S) - EU": (ONE_SERIES, False),
            "Game (Xbox One / Xbox Series X|S)": (ONE_SERIES, False),
            "Game XBOX One/Series X|S CD Key": (ONE_SERIES, False),
            "Game Xbox One & Xbox Series X|S XBOX LIVE Key": (ONE_SERIES, False),
            "Game Xbox One, Xbox Series X/S, Windows": (ONE_SERIES, True),
            "Game Xbox Series X|S / Windows 10": (("XBOX_SERIES",), True),
            "Game Xbox Series X|S/Windows": (("XBOX_SERIES",), True),
            "Game Xbox Series X": (("XBOX_SERIES",), False),
            "Game Xbox Series": (("XBOX_SERIES",), False),
            "Game (Xbox Series X/S, PC)": (("XBOX_SERIES",), True),
            "Game PC/XBOX One/Series X|S CD Key": (ONE_SERIES, True),
            "Game (Windows/Xbox Series X|S) XBOX LIVE Key EUROPE": (("XBOX_SERIES",), True),
            "Game XBOX One/PC/XBOX Series X|S CD Key": (ONE_SERIES, True),
            "Game (PS5)": (("PS5",), False), "Game PlayStation 5": (("PS5",), False),
            "Game (PS4)": (("PS4",), False), "Game PlayStation 4": (("PS4",), False),
            "Game (PS4 / PS5)": (("PS4", "PS5"), False), "Game PS4/PS5": (("PS4", "PS5"), False),
            "Game PS4 & PS5": (("PS4", "PS5"), False),
            "Game (Nintendo Switch)": (("SWITCH",), False),
            "Game (Xbox One / Series X|S Download Code) - EU": (ONE_SERIES, False),
            "Game - PS5 Download Code [EU]": (("PS5",), False),
            "Game (PC / PS5 / Xbox Series X|S) (Global)": (("PS5", "XBOX_SERIES"), True),
            "Game (PC, PS5, PS4, Xbox Series X/S, Xbox One)": (("PS5", "PS4", "XBOX_SERIES", "XBOX_ONE"), True),
        }
        for title, (families, pc) in cases.items():
            with self.subTest(title=title):
                sig = classify_console(title, "https://example.com/x", "Shop")
                self.assertIsNotNone(sig, title)
                self.assertIsNone(sig.skip_reason)
                self.assertEqual((sig.families, sig.pc_declared), (families, pc))
                self.assertEqual(sig.resolve_name, "Game")

    def test_pc_next_to_no_family_is_not_pc_declared(self):
        # "PC Building Simulator" is a game name; PC counts only inside a run WITH a family
        sig = classify_console("PC Building Simulator (Xbox One) - Xbox Live Key - EUROPE",
                               "https://www.g2a.com/pc-building-simulator-xbox-one-xbox-live-key-europe-i1", "G2A")
        self.assertEqual((sig.families, sig.pc_declared, sig.resolve_name), (("XBOX_ONE",), False, "PC Building Simulator"))
        # Xbox + Windows WITHOUT a generation → P4 + P2 (Romain 2026-09-25): One + Series read
        # from the bare "Xbox", PC declared by the SAME run — the Play Anywhere case.
        sig = classify_console("Sokmeal Time Xbox + Windows Pack XBOX LIVE Key EUROPE",
                               "https://example.com/sokmeal-time-xbox-windows-pack-xbox-live-key-europe", "Shop")
        self.assertEqual((sig.families, sig.pc_declared, sig.skip_reason, sig.generation_inferred),
                         (("XBOX_ONE", "XBOX_SERIES"), True, None, True))

    def test_xbox_360_skips_even_next_to_a_valid_family(self):
        sig = classify_console("Rabbids Invasion (Xbox 360 / Xbox One) Xbox Live Key - UNITED STATES",
                               "https://gameseal.com/rabbids-invasion-xbox-360-xbox-one-xbox-live-key-united-states", "GameSeal")
        self.assertEqual(sig.skip_reason, XBOX_360)

    def test_switch_2_is_a_declared_family_since_2026_09_14(self):
        # the Switch 2 skip is retired: the G2A row declares SWITCH2 (region EU)
        sig = classify_console("Sonic Superstars (Nintendo Switch 2) - Nintendo eShop Key - EUROPE",
                               "https://www.g2a.com/sonic-superstars-nintendo-switch-2-nintendo-eshop-key-europe-i1", "G2A")
        self.assertEqual((sig.families, sig.skip_reason, sig.resolve_name), (("SWITCH2",), None, "Sonic Superstars"))
        self.assertEqual((sig.region_base, sig.region_label, sig.region_words), ("eu", None, ("EUROPE",)))
        sig = classify_console("Game (PS5 / Nintendo Switch 2)", "https://example.com/x", "Shop")
        self.assertEqual((sig.families, sig.skip_reason), (("PS5", "SWITCH2"), None))
        self.assertEqual(SKIP_SWITCH_2, SWITCH_2)      # the constant survives for importers only

    def test_non_game_markers(self):
        cases = [
            ("Xbox Game Pass Ultimate 1 Month [EU]", "https://example.com/xbox-game-pass-ultimate-1-month-eu", "Shop", "GAME PASS"),
            ("Xbox Live Gold - 3 month subscription [EU]", "https://example.com/x", "Shop", "XBOX LIVE GOLD"),
            ("Xbox Live Card 25 EUR", "https://example.com/x", "Shop", "XBOX LIVE CARD"),
            ("Xbox Live Gift Card 500 TRY Xbox Live Key TURKEY", "https://example.com/xbox-x", "Shop", "XBOX LIVE GIFT CARD"),
            ("Xbox 500 TRY Gift Card (Turkey) - Digital Key", "https://www.driffle.com/xbox-500-try-gift-card-turkey-digital-key-p10001137", "Driffle", "GIFT CARD"),
            ("PlayStation Network USD 90 Gift Card US", "https://www.kinguin.net/category/1/x", "Kinguin", "GIFT CARD"),
            ("Playstation Network Card 50 Euros [ES]", "https://example.com/x", "Shop", "PLAYSTATION NETWORK CARD"),
            ("PlayStation Plus Premium 14 Days TRIAL Subscription", "https://www.kinguin.net/category/1/x", "Kinguin", "PLAYSTATION PLUS"),
            ("Playstation Plus CARD 365 Days United Arab Emirates PSN CD Key", "https://k4g.com/product/x", "K4G", "PLAYSTATION PLUS"),
            ("PS Plus 12 Months PSN Key", "https://example.com/x", "Shop", "PS PLUS"),
            ("Nintendo eShop Card 25 EUR Luxembourg Nintendo CD Key", "https://k4g.com/product/x", "K4G", "NINTENDO ESHOP CARD"),
            ("eShop Card 15 Euro Nintendo", "https://example.com/x", "Shop", "ESHOP CARD"),
            ("Nintendo Switch Online 12 Months", "https://example.com/x", "Shop", "NINTENDO SWITCH ONLINE"),
            ("Nintendo eShop PLN PL 32zł", "https://example.com/product/nintendo-eshop-pln-pl-32zl-gift-cards", "Shop", "GIFT CARD"),
            ("Blocky Farm XBOX One / Xbox Series X|S Account", "https://www.kinguin.net/category/523387/blocky-farm-xbox-one-xbox-series-x-s-account", "Kinguin", "ACCOUNT"),
            ("Nioh 2 Remastered – The Complete Edition PS4/PS5 Access", "https://www.kinguin.net/category/359969/nioh-2-remastered-the-complete-edition-ps4-ps5-online-account-activation", "Kinguin", "ACCESS"),
            ("Nintendo Switch 2 Game Access", "https://www.kinguin.net/category/1/x-online-account-activation", "Kinguin", "ACCESS"),
        ]
        for title, url, merchant, marker in cases:
            with self.subTest(title=title):
                sig = classify_console(title, url, merchant)
                self.assertIsNotNone(sig)
                self.assertEqual(sig.skip_reason, _not_a_game(marker))
                self.assertEqual(sig.families, ())

    def test_non_game_wins_over_switch_2_and_xbox_360(self):
        # a Game Pass subscription filed under an Xbox-360 slug; Switch 2 "Access" rows
        sig = classify_console("Xbox Game Pass Essential 6 Months [EU]", "https://example.com/xbox-360/xbox-game-pass-essential-6-months-eu", "Shop")
        self.assertEqual(sig.skip_reason, _not_a_game("GAME PASS"))
        sig = classify_console("Game Nintendo Switch 2 Access", "https://www.kinguin.net/category/1/game-nintendo-switch-2-online-account-activation", "Kinguin")
        self.assertEqual(sig.skip_reason, _not_a_game("ACCESS"))

    def test_currencies_stay_with_the_category_skip_upstream(self):
        # a V-Bucks / Points row is a console row with a real family; CATEGORY_SKIP (matcher)
        # still rules it out — classify_console only refuses non-game CONSOLE-STORE items
        sig = classify_console("Madden NFL 27 - 12000 Madden Points XBOX Series X|S CD Key", "https://k4g.com/product/x-xbox-series-x-s-xbox-global-cd-key", "K4G")
        self.assertEqual(sig.families, ("XBOX_SERIES",))
        self.assertIsNone(sig.skip_reason)

    def test_families_order_and_dedup(self):
        sig = classify_console("NHL® 27 Deluxe Edition XBOX Series X|S (Xbox Series X|S) XBOX LIVE Key EUROPE",
                               "https://example.com/nhl-r-27-deluxe-edition-xbox-series-x-s-xbox-series-x-s-xbox-live-key-europe", "Shop")
        self.assertEqual(sig.families, ("XBOX_SERIES",))
        self.assertEqual(sig.resolve_name, "NHL® 27 Deluxe Edition")
        sig = classify_console("Game (PS5 / PS4 / PS5)", "https://example.com/x", "Shop")
        self.assertEqual(sig.families, ("PS5", "PS4"))


class ResolveNameTests(unittest.TestCase):
    def test_design_examples(self):
        cases = {
            "NBA 2K25 (Xbox One / Series X|S Download Code) - EU": "NBA 2K25",
            "FIFA 23 - Ultimate Edition ( Xbox One / Series X|S Download Code ) - EU": "FIFA 23 - Ultimate Edition",
            "Medieval Dynasty - PS5 Download Code [EU]": "Medieval Dynasty",
            "Infected Cowboys Bundle EU XBOX One / Xbox Series X|S CD Key": "Infected Cowboys Bundle",
            "Sniper Ghost Warrior Contracts 1 and 2 Double Pack (Europe) (Xbox One / Xbox Series X|S) - Xbox Live - Digital Key":
                "Sniper Ghost Warrior Contracts 1 and 2 Double Pack",
            "Train Sim World 6 | Deluxe Edition (Xbox Series X/S, PC) - Xbox Live Key - UNITED KINGDOM": "Train Sim World 6 | Deluxe Edition",
            "Overwatch - Legendary Edition (Xbox One Download Code) - EU Key": "Overwatch - Legendary Edition",
            "Toki - Nintendo Switch Download Code": "Toki",
            "Halo 5 Guardians - Xbox One Download Code": "Halo 5 Guardians",
            "Payday 3 - Gold Edition (Xbox Series X|S / Windows) - EU": "Payday 3 - Gold Edition",
            "Kingdom Rush Origins EU (European Union + UK) XBOX One / Xbox Series X|S / PC CD Key": "Kingdom Rush Origins",
            "EA SPORTS Kickoff Bundle (Madden NFL 27 & College Football 27) US Xbox Series X|S CD Key":
                "EA SPORTS Kickoff Bundle (Madden NFL 27 & College Football 27)",
            "LEGO Harry Potter Collection (2018) CA XBOX One / Xbox Series X|S CD Key": "LEGO Harry Potter Collection (2018)",
            "Star Wars Battlefront II (2018) XBOX One/Series X|S CD Key": "Star Wars Battlefront II (2018)",
            "Wrap House Simulator European Union XBOX One / Xbox Series X|S / PC CD Key": "Wrap House Simulator",
            "Madden NFL 27 | Deluxe Edition (Xbox Series X/S) - Xbox Live Key - CANADA": "Madden NFL 27 | Deluxe Edition",
            "Saros - Pre-order Bonus (PS5) - PSN Key - EUROPE": "Saros - Pre-order Bonus",
            "Snipperclips – Cut it out, together! Bundle (United States) (Nintendo Switch) - Nintendo - Digital Key":
                "Snipperclips – Cut it out, together! Bundle",
            "Little Nightmares - Tengu Mask DLC (SIEE) (PS4) - PSN - Digital Key": "Little Nightmares - Tengu Mask DLC (SIEE)",
            "The Last of Us Part I EU PS5 CD Key": "The Last of Us Part I",
            "PC Building Simulator (Xbox One) - Xbox Live Key - EUROPE": "PC Building Simulator",
            "Thomas & Friends™: Wonders of Sodor PC/XBOX LIVE Key UNITED STATES": "Thomas & Friends™: Wonders of Sodor",
            "Zero Escape: The Nonary Games (Xbox One, PC) - Xbox Live Key - EUROPE": "Zero Escape: The Nonary Games",
            "Let's Sing 2025 - International Hits (DLC) (PS4/PS5) PSN Key EUROPE": "Let's Sing 2025 - International Hits (DLC)",
            "Grand Theft Auto VI | Standard Edition (Xbox Series X/S) - Xbox Live Key - GLOBAL": "Grand Theft Auto VI | Standard Edition",
            "Persona 5 Royal United Kingdom XBOX One/PC/XBOX Series X|S CD Key": "Persona 5 Royal",
        }
        for title, expected in cases.items():
            with self.subTest(title=title):
                self.assertEqual(resolve_name_of(title), expected)

    def test_language_tail_is_not_shared_vocabulary(self):
        # 2026-09-14: the "EN <Region>" tail is one merchant's grammar (its console_noise,
        # tests/test_merchants_gamivo.py) — the shared strip removes the region tail only
        self.assertEqual(resolve_name_of("Ravenswatch EN United Kingdom"), "Ravenswatch EN")
        self.assertEqual(resolve_name_and_regions("Ravenswatch EN United Kingdom"), ("Ravenswatch EN", ("United Kingdom",)))

    def test_edition_words_are_kept_and_mid_title_region_codes_survive(self):
        self.assertEqual(resolve_name_of("NHL 27 UK Deluxe Edition Xbox Series X|S CD Key"), "NHL 27 UK Deluxe Edition")
        self.assertEqual(resolve_name_of("Borderlands 3 Ultimate Edition Europe PS4/PS5 CD Key"), "Borderlands 3 Ultimate Edition")

    def test_never_empty(self):
        self.assertEqual(resolve_name_of("Xbox One"), "Xbox One")
        self.assertEqual(resolve_name_of(""), "")

    def test_classify_resolve_name_equals_resolve_name_of(self):
        for title, url, merchant, *_ in ROWS:
            sig = classify_console(title, url, merchant)
            self.assertEqual(sig.resolve_name, resolve_name_of(title, merchant))
            self.assertEqual(sig.resolve_name, resolve_name_of(title))     # no hooks: same text


class UrlMarkerTests(unittest.TestCase):
    def test_marker_in_url(self):
        self.assertTrue(console_marker_in_url("https://www.gamivo.com/product/riders-republic-xbox-xbox-one-series-us-premium"))
        self.assertTrue(console_marker_in_url("https://www.eneba.com/psn-lets-sing-2025-ps4-ps5-psn-key-europe"))
        self.assertTrue(console_marker_in_url("https://www.eneba.com/nintendo-split-fiction-nintendo-switch-2-eshop-key-hong-kong"))
        self.assertTrue(console_marker_in_url("https://www.mmoga.com/Xbox-Live/Xbox-One-Game-Keys/NBA-2K25.html?ref=615"))
        self.assertTrue(console_marker_in_url("https://www.mmoga.com/Nintendo/Switch/Toki-Download-Code.html"))
        self.assertTrue(console_marker_in_url("https://k4g.com/product/x-playstation-5-europe-cd-key-cd-key-UE4Z75H6"))
        self.assertTrue(console_marker_in_url("https://www.gamivo.com/product/fifa-23-ps-ps5-eu-standard"))

    def test_no_marker(self):
        self.assertFalse(console_marker_in_url("https://www.kinguin.net/category/1/switch-galaxy-ultra-steam-cd-key"))
        self.assertFalse(console_marker_in_url("https://www.mmoga.com/Steam-Games/Among-Us.html"))
        self.assertFalse(console_marker_in_url("https://www.eneba.com/steam-elden-ring-steam-key-global"))
        self.assertFalse(console_marker_in_url("https://www.g2a.com/xboxer-steam-key-global-i1"))   # no whole token
        # the query string is never scanned
        self.assertFalse(console_marker_in_url("https://www.mmoga.com/Steam-Games/Among-Us.html?ref=xbox"))
        self.assertFalse(console_marker_in_url(""))


class PageIdentityTests(unittest.TestCase):
    def test_identity(self):
        cases = {
            "Hades PS5": "Hades", "Hades Xbox Series": "Hades", "Hades Xbox One": "Hades",
            "Hades Nintendo Switch": "Hades", "Hades PS4": "Hades", "Hades": "Hades",
            "Elden Ring Tarnished Edition Nintendo Switch 2": "Elden Ring Tarnished Edition",
            "Street Fighter 6 Xbox Series X|S": "Street Fighter 6",
            "Forza Horizon 5 Switch 2": "Forza Horizon 5",
            # the real Switch 2 page names (2026-09-14: ids 188436 / 188441)
            "Street Fighter 6 Nintendo Switch 2": "Street Fighter 6",
            "ELDEN RING Tarnished Edition Nintendo Switch 2": "ELDEN RING Tarnished Edition",
        }
        for name, expected in cases.items():
            with self.subTest(name=name):
                self.assertEqual(console_page_identity(name), expected)

    def test_only_one_suffix_and_never_empty(self):
        self.assertEqual(console_page_identity("PS5"), "PS5")
        self.assertEqual(console_page_identity("Game PS4 PS5"), "Game PS4")


# ── real tab-bar excerpts (whitespace trimmed, markup verbatim) ─────────────────────
def _tab_link(slug_kind: str, title: str, label: str) -> str:
    return (
        f'<li>\n<a href="https://www.allkeyshop.com/blog/buy-{slug_kind}-compare-prices/" class="inactive"  title=" {title}">\n'
        f'<svg class="me-1" width="16" height="16" fill="currentColor">\n'
        f'  <use xlink:href="https://www.allkeyshop.com/blog/wp-content/themes/aks-theme/assets/images/sprites/storesprite.svg#xbox"/>\n'
        f'</svg> <span class="d-none d-md-inline">{label}</span>\n</a>\n</li>\n'
    )


def _tab_active(title: str, platform: str) -> str:
    return (
        f'<li>\n<span class="active"  title=" {title}">\n'
        f'<meta data-itemprop="platform" content="{platform}" />\n'
        f'<svg class="me-1 d-none d-md-block" width="16" height="16" fill="currentColor">\n'
        f'  <use xlink:href="https://www.allkeyshop.com/blog/wp-content/themes/aks-theme/assets/images/sprites/storesprite.svg#laptop"/>\n'
        f'</svg> {title}\n</span>\n</li>\n'
    )


def _page(*tabs: str) -> str:
    return ('<html><body><div class="x">\n<ul class="aks-offer-tabulations">\n' + "".join(tabs)
            + '</ul>\n</div><div>official platforms: Steam</div></body></html>')


# Hades PC page 26712 (5 console tabs; PC active) — verbatim block shape of 2026-09-12
HADES_PC = _page(
    _tab_active("PC", "PC"),
    _tab_link("hades-ps4", "PS4", "PS4"), _tab_link("hades-ps5", "PS5", "PS5"),
    _tab_link("hades-xbox-one", "Xbox One", "Xbox One"), _tab_link("hades-xbox-series", "Xbox Series", "Xbox Series"),
    _tab_link("hades-nintendo-switch", "Switch", "Switch"),
)
# Hades PS5 page 85105 (PC is a LINK, PS5 is the active span)
HADES_PS5 = _page(
    _tab_link("hades-cd-key", "PC", "PC"), _tab_link("hades-ps4", "PS4", "PS4"),
    _tab_active("PS5", "PS5"),
    _tab_link("hades-xbox-one", "Xbox One", "Xbox One"), _tab_link("hades-xbox-series", "Xbox Series", "Xbox Series"),
    _tab_link("hades-nintendo-switch", "Switch", "Switch"),
)
HADES_XBOX_SERIES = _page(
    _tab_link("hades-cd-key", "PC", "PC"), _tab_link("hades-ps4", "PS4", "PS4"), _tab_link("hades-ps5", "PS5", "PS5"),
    _tab_link("hades-xbox-one", "Xbox One", "Xbox One"),
    _tab_active("Xbox Series", "Xbox Series X"),
    _tab_link("hades-nintendo-switch", "Switch", "Switch"),
)
FORZA_HORIZON_5 = _page(
    _tab_active("PC", "PC"),
    _tab_link("forza-horizon-5-ps5", "PS5", "PS5"), _tab_link("forza-horizon-5-xbox-one", "Xbox One", "Xbox One"),
    _tab_link("forza-horizon-5-xbox-series", "Xbox Series", "Xbox Series"),
)
STREET_FIGHTER_6 = _page(
    _tab_active("PC", "PC"),
    _tab_link("street-fighter-6-ps4", "PS4", "PS4"), _tab_link("street-fighter-6-ps5", "PS5", "PS5"),
    _tab_link("street-fighter-6-xbox-series", "Xbox Series", "Xbox Series"),
    _tab_link("street-fighter-6-nintendo-switch-2", "Switch 2", "Switch 2"),
)
# Elden Ring 29109: the Switch 2 tab points to ANOTHER product (Tarnished Edition)
ELDEN_RING = _page(
    _tab_active("PC", "PC"),
    _tab_link("elden-ring-ps4", "PS4", "PS4"), _tab_link("elden-ring-ps5", "PS5", "PS5"),
    _tab_link("elden-ring-xbox-one", "Xbox One", "Xbox One"), _tab_link("elden-ring-xbox-series", "Xbox Series", "Xbox Series"),
    _tab_link("elden-ring-tarnished-edition-nintendo-switch-2", "Switch 2", "Switch 2"),
)
AKS = "https://www.allkeyshop.com/blog/buy-"


class ExtractConsolePagesTests(unittest.TestCase):
    def test_hades_pc_page(self):
        self.assertEqual(extract_console_pages(HADES_PC), {
            "ps4": AKS + "hades-ps4-compare-prices/", "ps5": AKS + "hades-ps5-compare-prices/",
            "xbox-one": AKS + "hades-xbox-one-compare-prices/", "xbox-series": AKS + "hades-xbox-series-compare-prices/",
            "nintendo-switch": AKS + "hades-nintendo-switch-compare-prices/",
        })
        self.assertEqual(extract_page_platform(HADES_PC), "PC")

    def test_console_pages_link_back_to_pc(self):
        pages = extract_console_pages(HADES_PS5)
        self.assertEqual(pages["cd-key"], AKS + "hades-cd-key-compare-prices/")
        self.assertNotIn("ps5", pages)                       # the active span has no href
        self.assertEqual(set(pages), {"cd-key", "ps4", "xbox-one", "xbox-series", "nintendo-switch"})
        self.assertEqual(extract_page_platform(HADES_PS5), "PS5")
        pages = extract_console_pages(HADES_XBOX_SERIES)
        self.assertNotIn("xbox-series", pages)
        self.assertEqual(pages["ps5"], AKS + "hades-ps5-compare-prices/")
        self.assertEqual(extract_page_platform(HADES_XBOX_SERIES), "Xbox Series X")

    def test_forza_and_street_fighter(self):
        self.assertEqual(set(extract_console_pages(FORZA_HORIZON_5)), {"ps5", "xbox-one", "xbox-series"})
        sf6 = extract_console_pages(STREET_FIGHTER_6)
        self.assertEqual(set(sf6), {"ps4", "ps5", "xbox-series", "nintendo-switch-2"})
        self.assertEqual(sf6["nintendo-switch-2"], AKS + "street-fighter-6-nintendo-switch-2-compare-prices/")
        self.assertNotIn("nintendo-switch", sf6)              # "-2" is not "nintendo-switch"

    def test_elden_ring_tab_to_another_product_is_returned_as_is(self):
        pages = extract_console_pages(ELDEN_RING)
        self.assertEqual(pages["nintendo-switch-2"], AKS + "elden-ring-tarnished-edition-nintendo-switch-2-compare-prices/")
        self.assertEqual(len(pages), 5)

    def test_no_tab_bar_or_unknown_kind(self):
        self.assertEqual(extract_console_pages("<html><body>Page not found</body></html>"), {})
        self.assertEqual(extract_console_pages(""), {})
        body = _page(_tab_link("hades-android", "Android", "Android"), _tab_link("hades-ps5", "PS5", "PS5"))
        self.assertEqual(extract_console_pages(body), {"ps5": AKS + "hades-ps5-compare-prices/"})
        # links OUTSIDE the tab bar are ignored
        outside = '<a href="https://www.allkeyshop.com/blog/buy-other-ps4-compare-prices/">x</a>' + HADES_PC
        self.assertNotIn("other", extract_console_pages(outside)["ps4"])

    def test_page_platform_absent(self):
        self.assertEqual(extract_page_platform("<html><body>x</body></html>"), "")
        self.assertEqual(extract_page_platform('<meta data-itemprop="platform" content="Switch" />'), "Switch")
        # the Switch 2 pages' own meta (Street Fighter 6 / ELDEN RING Tarnished Edition, 2026-09-14)
        self.assertEqual(extract_page_platform('<meta data-itemprop="platform" content="Switch 2" />'), "Switch 2")


# ── 2026-09-14 review fixes ──────────────────────────────────────────────────────────
KINGUIN = "https://www.kinguin.net/category/1/x"
K4G = "https://k4g.com/product/x"
DRIFFLE = "https://www.driffle.com/x-p1"
G2A = "https://www.g2a.com/x-i1"


def _slot(sig):
    return sig.region_base, sig.region_label, sig.region_words


class RegionSlotTests(unittest.TestCase):
    """The region the merchant writes NEXT TO the platform phrase (review finders 2/3,
    critical: 456 region-locked rows fell to implicit GLOBAL because resolve_name stripped
    the word the matcher never mapped). Every stripped region word is reported; a sellable
    base maps to eu/us/uk/global, anything else to the matcher's forbidden label. These
    grammars are the SHARED tail / bracket / code reads (no merchant hook)."""

    def test_two_letter_codes_before_the_platform_phrase(self):
        # real rows of the 2026-09-12 Kinguin batch (CA 83 / AU 77 / US 48 / NA 2 / TR 2 / AR 3 / CO 1 / ZA 1)
        cases = [
            ("Hobo: Tough Life US Xbox One / Xbox Series X|S CD Key", ("us", None, ("US",)), ONE_SERIES),
            ("Star Wars Zero Company Deluxe Edition US PS5 CD Key", ("us", None, ("US",)), ("PS5",)),
            ("Onimusha: Way of the Sword EU PS5 CD Key", ("eu", None, ("EU",)), ("PS5",)),
            ("The Quarry Deluxe Edition UK XBOX One / Xbox Series X|S CD Key", ("uk", None, ("UK",)), ONE_SERIES),
            ("Hades UK Xbox Series X|S CD Key", ("uk", None, ("UK",)), ("XBOX_SERIES",)),
            ("Puyo Puyo Tetris 2 CA Xbox One / Xbox Series X|S CD Key", (None, "CANADA", ("CA",)), ONE_SERIES),
            ("Planet Coaster: Console Edition AU Xbox One / Xbox Series X|S CD Key", (None, "AUSTRALIA", ("AU",)), ONE_SERIES),
            ("MotoGP 26 AU Xbox Series X|S / PC CD Key", (None, "AUSTRALIA", ("AU",)), ("XBOX_SERIES",)),
            ("Destiny 2 - The Collection Bundle DLC AU XBOX One / Xbox Series X|S CD Key", (None, "AUSTRALIA", ("AU",)), ONE_SERIES),
            ("Onimusha: Way of the Sword NA PS5 CD Key", (None, "NORTH AMERICA", ("NA",)), ("PS5",)),
            ("Onimusha: Way of the Sword Premium Deluxe Edition NA PS5 CD Key", (None, "NORTH AMERICA", ("NA",)), ("PS5",)),
            ("Fortnite - Witching Wing Quest Pack TR XBOX One / Xbox Series X|S CD Key", (None, "TURKEY", ("TR",)), ONE_SERIES),
            ("Bus Simulator 21 EN Language Only AR XBOX One / Xbox Series X|S CD Key", (None, "ARGENTINA", ("AR",)), ONE_SERIES),
            ("Snufkin: Melody of Moominvalley CO Xbox Series X|S / PC CD Key", (None, "COLOMBIA", ("CO",)), ("XBOX_SERIES",)),
            ("Dynasty Warriors: Origins ZA Xbox Series X|S CD Key", (None, "SOUTH AFRICA", ("ZA",)), ("XBOX_SERIES",)),
            ("EA SPORTS Madden NFL 27 NA Nintendo Switch 2 CD Key", (None, "NORTH AMERICA", ("NA",)), ("SWITCH2",)),
        ]
        for title, slot, families in cases:
            with self.subTest(title=title):
                sig = classify_console(title, KINGUIN, "Kinguin")
                self.assertIsNone(sig.skip_reason)
                self.assertEqual(sig.families, families)
                self.assertEqual(_slot(sig), slot)
                for word in sig.region_words:
                    self.assertNotIn(word, sig.resolve_name.split())

    def test_full_names_before_the_platform_phrase(self):
        sig = classify_console("Wrap House Simulator European Union XBOX One / Xbox Series X|S / PC CD Key", KINGUIN, "Kinguin")
        self.assertEqual((_slot(sig), sig.pc_declared, sig.resolve_name), (("eu", None, ("European Union",)), True, "Wrap House Simulator"))
        # the feed's own "RoW" spelling (2 real rows) — a forbidden lock, "Row" stays a name word
        sig = classify_console("NARUTO SHIPPUDEN: Ultimate Ninja STORM Trilogy RoW Xbox One / Xbox Series X|S CD Key", KINGUIN, "Kinguin")
        self.assertEqual(_slot(sig), (None, "ROW", ("RoW",)))
        self.assertEqual(sig.resolve_name, "NARUTO SHIPPUDEN: Ultimate Ninja STORM Trilogy")
        sig = classify_console("THE GAME OF LIFE 2 RoW Xbox One / Xbox Series X|S CD Key", KINGUIN, "Kinguin")
        self.assertEqual(_slot(sig), (None, "ROW", ("RoW",)))
        self.assertEqual(resolve_name_of("Death Row Xbox One CD Key"), "Death Row")
        for title, slot in {
            "Game Europe PS5 CD Key": ("eu", None, ("Europe",)),
            "Game United States PS5 CD Key": ("us", None, ("United States",)),
            "Game United Kingdom PS5 CD Key": ("uk", None, ("United Kingdom",)),
            "Game Global PS5 CD Key": ("global", None, ("Global",)),
            "Game Worldwide PS5 CD Key": ("global", None, ("Worldwide",)),
            "Game North America PS5 CD Key": (None, "NORTH AMERICA", ("North America",)),
            "Game Canada PS5 CD Key": (None, "CANADA", ("Canada",)),
            "Game Australia PS5 CD Key": (None, "AUSTRALIA", ("Australia",)),
            "Game Mexico PS5 CD Key": (None, "MEXICO", ("Mexico",)),
            "Game United Arab Emirates PS5 CD Key": (None, "UNITED ARAB EMIRATES", ("United Arab Emirates",)),
            "Game Latin America PS5 CD Key": (None, "LATIN AMERICA", ("Latin America",)),
            "Game Netherlands PS5 CD Key": (None, "NETHERLANDS", ("Netherlands",)),
            "Game EU West PS5 CD Key": (None, "EU WEST", ("EU West",)),   # unknown word → its text
        }.items():
            with self.subTest(title=title):
                sig = classify_console(title, KINGUIN, "Kinguin")
                self.assertEqual((_slot(sig), sig.resolve_name, sig.skip_reason), (slot, "Game", None))

    def test_k4g_grammar(self):
        cases = {
            "Icarus Console Edition Europe XBOX Series X|S CD Key": (("eu", None, ("Europe",)), "Icarus Console Edition"),
            "Trepang2 Standard Edition Europe PC/XBOX Series X|S CD Key": (("eu", None, ("Europe",)), "Trepang2 Standard Edition"),
            "Mortal Kombat 11 Ultimate Add-On Bundle United States XBOX Series X|S CD Key": (("us", None, ("United States",)), "Mortal Kombat 11 Ultimate Add-On Bundle"),
            "Persona 5 Royal United Kingdom XBOX One/PC/XBOX Series X|S CD Key": (("uk", None, ("United Kingdom",)), "Persona 5 Royal"),
            "Persona 5 Royal Canada XBOX One/PC/XBOX Series X|S CD Key": ((None, "CANADA", ("Canada",)), "Persona 5 Royal"),
            "Tom Clancy's Ghost Recon Breakpoint Gold Edition Global XBOX One/Series X|S CD Key": (("global", None, ("Global",)), "Tom Clancy's Ghost Recon Breakpoint Gold Edition"),
            "Stardew Valley United States Nintendo Switch 2 CD Key": (("us", None, ("United States",)), "Stardew Valley"),
        }
        for title, (slot, name) in cases.items():
            with self.subTest(title=title):
                sig = classify_console(title, K4G, "K4G")
                self.assertIsNone(sig.skip_reason)
                self.assertEqual((_slot(sig), sig.resolve_name), (slot, name))
        # "SIEE" is NOT a region word of any vocabulary: stays in the name (R16 blocks it, as before)
        sig = classify_console("Far Cry 6 - Jungle Expedition SIEE PS5 CD Key", K4G, "K4G")
        self.assertEqual((_slot(sig), sig.resolve_name), ((None, None, ()), "Far Cry 6 - Jungle Expedition SIEE"))

    def test_driffle_bracket(self):
        cases = {
            "Sniper Ghost Warrior Contracts 1 and 2 Double Pack (Europe) (Xbox One / Xbox Series X|S) - Xbox Live - Digital Key": ("eu", None, ("Europe",)),
            "NBA 2K27 - 15000 VC (Global) (Xbox Series X|S) - Xbox Live - Digital Key": ("global", None, ("Global",)),
            "Fortnite - Fresh Aura Outfits + 1,000 V-Bucks DLC (United States) (Xbox One / Xbox Series X|S) - Xbox Live - Digital Key": ("us", None, ("United States",)),
            "SMITE 2 Ultimate Founder's Edition (United Kingdom) (Xbox Series X|S) - Xbox Live - Digital Key": ("uk", None, ("United Kingdom",)),
            "Mario Kart 8 Deluxe - Booster Course Pass DLC (Hong Kong) (Nintendo Switch) - Nintendo - Digital Key": (None, "HONG KONG", ("Hong Kong",)),
            "Fortnite - Shaka Surfin' Pack DLC (South Africa) (PC / Xbox One / Xbox Series X|S) - Xbox Live - Digital Key": (None, "SOUTH AFRICA", ("South Africa",)),
            "Game (Turkey) (PS5) - PSN - Digital Key": (None, "TURKEY", ("Turkey",)),
            "Game (Romania) (PS5) - PSN - Digital Key": (None, "ROMANIA", ("Romania",)),
            "Everspace 2 Galactic Edition (Europe) (Nintendo Switch 2) - Nintendo - Digital Key": ("eu", None, ("Europe",)),
        }
        for title, slot in cases.items():
            with self.subTest(title=title):
                sig = classify_console(title, DRIFFLE, "Driffle")
                self.assertIsNone(sig.skip_reason)
                self.assertEqual(_slot(sig), slot)
        # the (Turkey) of a gift card is reported too — on a non-game skip
        sig = classify_console("Xbox 500 TRY Gift Card (Turkey) - Digital Key",
                               "https://www.driffle.com/xbox-500-try-gift-card-turkey-digital-key-p10001137", "Driffle")
        self.assertEqual((sig.skip_reason, _slot(sig)), (_not_a_game("GIFT CARD"), (None, "TURKEY", ("Turkey",))))

    def test_g2a_tail(self):
        cases = {
            "Shadowrun Trilogy (Xbox Series X/S) - Xbox Live Key - EUROPE": ("eu", None, ("EUROPE",)),
            "Train Sim World 6 | Deluxe Edition (Xbox Series X/S, PC) - Xbox Live Key - UNITED KINGDOM": ("uk", None, ("UNITED KINGDOM",)),
            "Grand Theft Auto VI | Standard Edition (Xbox Series X/S) - Xbox Live Key - GLOBAL": ("global", None, ("GLOBAL",)),
            "Game (Xbox Series X/S) - Xbox Live Key - UNITED STATES": ("us", None, ("UNITED STATES",)),
            "Madden NFL 27 (Xbox Series X/S) - Xbox Live Key - CANADA": (None, "CANADA", ("CANADA",)),
            "Diablo IV: Lord of Hatred (Xbox Series X/S) - Xbox Live Key - JAPAN": (None, "JAPAN", ("JAPAN",)),
            "Microsoft Flight Simulator 2024 (Xbox Series X/S, PC) - Xbox Live Key - POLAND": (None, "POLAND", ("POLAND",)),
            "Sonic Superstars (Nintendo Switch 2) - Nintendo eShop Key - EUROPE": ("eu", None, ("EUROPE",)),
        }
        for title, slot in cases.items():
            with self.subTest(title=title):
                sig = classify_console(title, G2A, "G2A")
                self.assertIsNone(sig.skip_reason)
                self.assertEqual(_slot(sig), slot)

    def test_shared_key_region_tail_without_a_hook(self):
        # "<STORE> Key <REGION>" read by the shared run grammar (no merchant hook needed)
        cases = {
            "Game (Xbox Series X|S) XBOX LIVE Key EUROPE": ("eu", None, ("EUROPE",)),
            "Game (Xbox Series X|S) XBOX LIVE Key UNITED STATES": ("us", None, ("UNITED STATES",)),
            "Game (Xbox One) Xbox Live Key GERMANY": (None, "GERMANY", ("GERMANY",)),
            "Game (Nintendo Switch 2) eShop Key HONG KONG": (None, "HONG KONG", ("HONG KONG",)),
        }
        for title, slot in cases.items():
            with self.subTest(title=title):
                sig = classify_console(title, "https://example.com/x", "Shop")
                self.assertIsNone(sig.skip_reason)
                self.assertEqual(_slot(sig), slot)
        sig = classify_console("Game XBOX LIVE Key UNITED STATES", "https://example.com/x", "Shop")
        self.assertEqual((sig.skip_reason, sig.generation_inferred, _slot(sig)),
                         (None, True, ("us", None, ("UNITED STATES",))))            # P4, 2026-09-25

    def test_two_letter_codes_are_uppercase_only(self):
        # "Us" / "Uk" / "Ca" in a name are never region words — nothing stripped, nothing read
        for title in ("Hell is Us Xbox Series X|S CD Key", "The Last of Us Part I PS5 CD Key",
                      "After Us (PS5) - PSN Key - EUROPE", "Devil Inside Us Xbox One CD Key"):
            with self.subTest(title=title):
                sig = classify_console(title, KINGUIN, "Kinguin")
                self.assertIn("Us", sig.resolve_name)
                self.assertNotIn("Us", sig.region_words)
        sig = classify_console("The Last of Us Part I EU PS5 CD Key", KINGUIN, "Kinguin")
        self.assertEqual((_slot(sig), sig.resolve_name), (("eu", None, ("EU",)), "The Last of Us Part I"))
        sig = classify_console("After Us (PS5) - PSN Key - EUROPE", G2A, "G2A")
        self.assertEqual(_slot(sig), ("eu", None, ("EUROPE",)))

    def test_no_slot_read_when_the_region_word_is_not_in_the_slot(self):
        # "UK" mid-name (real row): kept in resolve_name, not a slot read — the matcher's
        # generic scan still sees " UK " in the original title
        sig = classify_console("NHL 27 UK Deluxe Edition Xbox Series X|S CD Key", KINGUIN, "Kinguin")
        self.assertEqual((_slot(sig), sig.resolve_name), ((None, None, ()), "NHL 27 UK Deluxe Edition"))
        # no region anywhere
        sig = classify_console("Hoomanz! Xbox Series X|S / PC CD Key", KINGUIN, "Kinguin")
        self.assertEqual(_slot(sig), (None, None, ()))
        sig = classify_console("Assassin's Creed Odyssey - Ultimate Edition (Xbox One Download Code)", "https://example.com/x", "Shop")
        self.assertEqual(_slot(sig), (None, None, ()))

    def test_two_different_sellable_bases_is_not_a_base(self):
        # "EU (European Union + UK)": three words stripped, EU and UK disagree → neither a
        # base nor a forbidden label; region_words tells the matcher the slot was read
        sig = classify_console("Kingdom Rush Origins EU (European Union + UK) XBOX One / Xbox Series X|S / PC CD Key", KINGUIN, "Kinguin")
        self.assertEqual(_slot(sig), (None, None, ("EU", "European Union", "UK")))
        self.assertEqual(sig.resolve_name, "Kingdom Rush Origins")
        # the same base twice is fine
        sig = classify_console("Game EU (Europe) Xbox One CD Key", KINGUIN, "Kinguin")
        self.assertEqual(_slot(sig), ("eu", None, ("EU", "Europe")))
        # a forbidden word wins over a sellable one (a lock is a lock)
        sig = classify_console("Game (EU/NA) Xbox One CD Key", KINGUIN, "Kinguin")
        self.assertEqual(_slot(sig), (None, "EU NA", ("EU/NA",)))

    def test_resolve_name_and_regions_is_the_public_pair(self):
        self.assertEqual(resolve_name_and_regions("Hobo: Tough Life US Xbox One / Xbox Series X|S CD Key"),
                         ("Hobo: Tough Life", ("US",)))
        self.assertEqual(resolve_name_and_regions("Hoomanz! Xbox Series X|S / PC CD Key"), ("Hoomanz!", ()))
        self.assertEqual(resolve_name_and_regions(""), ("", ()))
        for title, url, merchant, *_ in ROWS:
            sig = classify_console(title, url, merchant)
            self.assertEqual((sig.resolve_name, sig.region_words), resolve_name_and_regions(title, merchant))

    def test_signal_defaults_keep_the_four_positional_fields(self):
        sig = ConsoleSignal((), False, "x", None)
        self.assertEqual((sig.region_base, sig.region_label, sig.region_words), (None, None, ()))


class Switch2FamilyTests(unittest.TestCase):
    """2026-09-14: AKS Switch 2 product pages exist (kind nintendo-switch-2) and their offers
    use the Nintendo family bucket — SWITCH2 is a declared family, the old skip is retired."""

    def test_real_switch_2_rows_declare_the_family(self):
        rows = [
            ("CloverPit EU Nintendo Switch 2 CD Key", "https://www.kinguin.net/category/764730/cloverpit-eu-nintendo-switch-2-cd-key", "Kinguin", "eu", "CloverPit"),
            ("Splatoon Raiders US Nintendo Switch 2 CD Key", "https://www.kinguin.net/category/633361/splatoon-raiders-us-nintendo-switch-2-cd-key", "Kinguin", "us", "Splatoon Raiders"),
            ("Fallout 4: Anniversary Edition US Nintendo Switch 2 CD Key", "https://www.kinguin.net/category/803577/fallout-4-anniversary-edition-us-nintendo-switch-2-cd-key", "Kinguin", "us", "Fallout 4: Anniversary Edition"),
            ("Super Mario Odyssey EU Nintendo Switch 2 CD Key", "https://www.kinguin.net/category/797452/super-mario-odyssey-eu-nintendo-switch-2-cd-key", "Kinguin", "eu", "Super Mario Odyssey"),
            ("Pokémon Scarlet Europe Nintendo Switch 2 CD Key", "https://k4g.com/product/pokemon-scarlet-nintendo-switch-2-europe-cd-key-cd-key-3FWB2QK5", "K4G", "eu", "Pokémon Scarlet"),
            ("Sonic Superstars Standard Edition Europe Nintendo Switch 2 CD Key", "https://k4g.com/product/sonic-superstars-nintendo-switch-2-global-cd-key-standard-edition-cd-key-KSBAYQ1V", "K4G", "eu", "Sonic Superstars Standard Edition"),
            ("Stardew Valley United States Nintendo Switch 2 CD Key", "https://k4g.com/product/stardew-valley-nintendo-switch-2-united-states-instant-cd-key-cd-key-A4BN20IC", "K4G", "us", "Stardew Valley"),
            ("Sonic Superstars (Nintendo Switch 2) - Nintendo eShop Key - EUROPE", "https://www.g2a.com/sonic-superstars-nintendo-switch-2-nintendo-eshop-key-europe-i10000500318030", "G2A", "eu", "Sonic Superstars"),
            ("Everspace 2 Galactic Edition (Europe) (Nintendo Switch 2) - Nintendo - Digital Key", "https://www.driffle.com/everspace-2-galactic-edition-europe-nintendo-switch-2-nintendo-digital-key-p9999690", "Driffle", "eu", "Everspace 2 Galactic Edition"),
        ]
        for title, url, merchant, base, name in rows:
            with self.subTest(title=title):
                sig = classify_console(title, url, merchant)
                self.assertEqual((sig.families, sig.skip_reason, sig.region_base, sig.resolve_name),
                                 (("SWITCH2",), None, base, name))
                self.assertEqual(CONSOLE_PAGE_KIND[sig.families[0]], "nintendo-switch-2")

    def test_title_spellings_and_url_runs(self):
        for title in ("Game Nintendo Switch 2", "Game Switch 2", "Game (Nintendo Switch 2)", "Game (Switch 2) - EU",
                      "Game Nintendo Switch 2 CD Key", "Game (Nintendo Switch 2) eShop Key EUROPE"):
            with self.subTest(title=title):
                sig = classify_console(title, "https://example.com/x", "Shop")
                self.assertEqual((sig.families, sig.skip_reason, sig.resolve_name), (("SWITCH2",), None, "Game"))
        # a URL-only declaration (title carries no generation) through the shared slug run
        sig = classify_console("Game eShop Key", "https://example.com/game-nintendo-switch-2-cd-key", "SomeShop")
        self.assertEqual((sig.families, sig.skip_reason), (("SWITCH2",), None))
        # Switch (1) is untouched
        sig = classify_console("Game (Nintendo Switch)", "https://example.com/x", "Shop")
        self.assertEqual(sig.families, ("SWITCH",))
        sig = classify_console("Game", "https://example.com/game-nintendo-switch-cd-key", "Shop")
        self.assertEqual(sig.families, ("SWITCH",))

    def test_switch_2_edition_name_suffix_is_not_a_declaration(self):
        # Instant Gaming: "<Game> - Nintendo Switch 2 Edition" is the product name; no
        # platform phrase, no URL grammar → fail-closed "no declared generation", the
        # name keeps its suffix
        sig = classify_console("Xenoblade Chronicles X: Definitive Edition - Nintendo Switch 2 Edition",
                               "https://www.instant-gaming.com/en/21871-/", "Instant Gaming")
        self.assertEqual((sig.families, sig.skip_reason), ((), NO_GEN))
        self.assertEqual(sig.resolve_name, "Xenoblade Chronicles X: Definitive Edition - Nintendo Switch 2 Edition")
        # K4G: the same suffix AND a platform phrase saying Switch 2 → declared, suffix kept in the name
        sig = classify_console("The Legend of Zelda: Breath of the Wild – Nintendo Switch 2 Edition Upgrade Pack Europe Nintendo Switch 2 CD Key",
                               "https://k4g.com/product/the-legend-of-zelda-breath-of-the-wild-nintendo-switch-2-edition-upgrade-pack-nintendo-switch-2-europe-instant-cd-key-cd-key-WZFPMKTR", "K4G")
        self.assertEqual((sig.families, sig.skip_reason, sig.region_base), (("SWITCH2",), None, "eu"))
        self.assertEqual(sig.resolve_name, "The Legend of Zelda: Breath of the Wild – Nintendo Switch 2 Edition Upgrade Pack")
        # a Switch 2 Edition whose slug files it under Switch (1) → fail-closed contradiction
        sig = classify_console("Some Game - Nintendo Switch 2 Edition (Switch Download Code) - EU",
                               "https://example.com/some-game-nintendo-switch-cd-key", "Shop")
        self.assertEqual(sig.families, ("SWITCH",))
        self.assertEqual(sig.skip_reason, "console: product name suffix 'Nintendo Switch 2 Edition' contradicts "
                                          "the declared platform SWITCH — not entered (R45)")
        sig = classify_console("Game - PS5 Edition (Xbox One) - Xbox Live Key - EUROPE", G2A, "G2A")
        self.assertEqual(sig.skip_reason, "console: product name suffix 'PS5 Edition' contradicts "
                                          "the declared platform XBOX_ONE — not entered (R45)")
        # the same platform in the suffix and the phrase → fine
        sig = classify_console("Game - PS5 Edition (PS5) - PSN Key - EUROPE", G2A, "G2A")
        self.assertEqual((sig.families, sig.skip_reason, sig.resolve_name), (("PS5",), None, "Game - PS5 Edition"))

    def test_switch_2_non_game_rows_still_skip_first(self):
        sig = classify_console("Hello Kitty Island Adventure Nintendo Switch 2 Access",
                               "https://www.kinguin.net/category/450231/hello-kitty-island-adventure-nintendo-switch-2-access", "Kinguin")
        self.assertEqual(sig.skip_reason, _not_a_game("ACCESS"))
        sig = classify_console("Divinity: Original Sin 2 Definitive Edition Nintendo Switch 2 Access",
                               "https://www.kinguin.net/category/447356/divinity-original-sin-2-definitive-edition-nintendo-switch-2-access", "Kinguin")
        self.assertEqual(sig.skip_reason, _not_a_game("ACCESS"))

    def test_retired_skip_is_never_emitted(self):
        titles = ["Game Nintendo Switch 2", "Game (PS5 / Nintendo Switch 2)", "Game Switch 2 Edition",
                  "Xenoblade Chronicles X: Definitive Edition - Nintendo Switch 2 Edition"]
        for title in titles:
            self.assertNotEqual(classify_console(title, "https://example.com/x", "Shop").skip_reason, SWITCH_2)
        for url in ("https://example.com/game-nintendo-switch-2-cd-key",
                    "https://www.gamivo.com/product/game-nintendo-nintendo-switch-2-uk-standard",
                    "https://www.eneba.com/nintendo-game-nintendo-switch-2-eshop-key-europe"):
            self.assertNotEqual(classify_console("Game eShop Key", url, "Shop").skip_reason, SWITCH_2)


class AccountRowsTests(unittest.TestCase):
    """Review finder 3 [high]: Difmark '(Account)' console rows classified as Switch KEYS."""

    def test_difmark_account_row(self):
        sig = classify_console("Madness Beverage (Account) Standard Edition",
                               "https://difmark.com/en/buy-console-account-madness-beverage-nintendo-switch-account-185025?referal=allkeyshop&marketplace_id=9&edition_id=780&region_product_id=1",
                               "Difmark")
        self.assertEqual((sig.families, sig.skip_reason), ((), _not_a_game("ACCOUNT")))

    def test_account_word_anywhere_and_url_forms(self):
        cases = [
            ("Game (Account) Standard Edition", "https://difmark.com/en/buy-console-account-game-nintendo-switch-account-1?x=1"),
            ("Game Account Xbox One", "https://example.com/x"),                       # word mid-title
            ("Game (Account) PS5", "https://example.com/x"),                          # parenthesised
            ("Game Standard Edition", "https://difmark.com/en/buy-console-account-game-ps5-account-185025"),   # URL only
            ("Game PS5", "https://example.com/game-ps5-account-185025"),              # "-account-<digits>" suffix
            ("Game PS5", "https://example.com/game-ps5-account/"),                    # "-account/" suffix
            ("Blocky Farm XBOX One / Xbox Series X|S Account", "https://www.kinguin.net/category/523387/blocky-farm-xbox-one-xbox-series-x-s-account"),
        ]
        for title, url in cases:
            with self.subTest(title=title, url=url):
                sig = classify_console(title, url, "Shop")
                self.assertEqual((sig.families, sig.skip_reason), ((), _not_a_game("ACCOUNT")))

    def test_accounts_is_not_account_and_access_is_unchanged(self):
        # "(ONLY FOR NEW ACCOUNTS)" is not the ACCOUNT word — the PLAYSTATION PLUS marker rules
        sig = classify_console("PlayStation Plus Premium 14 Days TRIAL Subscription US (ONLY FOR NEW ACCOUNTS)",
                               "https://www.kinguin.net/category/299561/playstation-plus-premium-14-days-trial-subscription-us-only-for-new-accounts", "Kinguin")
        self.assertEqual(sig.skip_reason, _not_a_game("PLAYSTATION PLUS"))
        sig = classify_console("The Accountant PS5 CD Key", KINGUIN, "Kinguin")
        self.assertEqual((sig.families, sig.skip_reason), (("PS5",), None))
        sig = classify_console("NHL 22 PS4 Access", "https://www.kinguin.net/category/366235/nhl-22-ps4-access", "Kinguin")
        self.assertEqual(sig.skip_reason, _not_a_game("ACCESS"))
        sig = classify_console("Nioh 2 Remastered – The Complete Edition PS4/PS5 Access",
                               "https://www.kinguin.net/category/359969/nioh-2-remastered-the-complete-edition-ps4-ps5-online-account-activation", "Kinguin")
        self.assertEqual(sig.skip_reason, _not_a_game("ACCESS"))


class BareSeriesTests(unittest.TestCase):
    """Review finder 2 [low]: 'Xbox One/Series' (no X|S) declared XBOX_ONE only with a
    '/Series' residue — a partial console entry path."""

    def test_bare_series_after_xbox_one_is_xbox_series(self):
        cases = {
            "Hades Xbox One/Series Global": ("global", "Hades"),
            "Hades (Xbox One / Series) - EU": ("eu", "Hades"),
            "Hades Xbox One & Series Global": ("global", "Hades"),
            "Hades Xbox One, Series X - EU": ("eu", "Hades"),
            "Hades Xbox One / Series S": (None, "Hades"),
            "Hades (Xbox One / Series X) - Xbox Live Key - EUROPE": ("eu", "Hades"),
            "Hades Xbox One and Series X|S": (None, "Hades"),
        }
        for title, (base, name) in cases.items():
            with self.subTest(title=title):
                sig = classify_console(title, "https://gameseal.com/x", "GameSeal")
                self.assertEqual((sig.families, sig.skip_reason, sig.region_base, sig.resolve_name),
                                 (ONE_SERIES, None, base, name))
        # the real GameSeal row (a POINTS row — CATEGORY_SKIP upstream — but both generations declared)
        sig = classify_console("EA Sports: FC 25 XBOX GLOBAL 1050 FC Points Xbox One/Series Global",
                               "https://gameseal.com/ea-sports-fc-25-xbox-global-1050-fc-points-xbox-one-series-global", "GameSeal")
        self.assertEqual((sig.families, sig.skip_reason), (ONE_SERIES, None))
        self.assertNotIn("Series", sig.resolve_name)

    def test_bare_series_elsewhere_stays_a_name_word(self):
        sig = classify_console("World Series of Poker PS4 CD Key", KINGUIN, "Kinguin")
        self.assertEqual((sig.families, sig.skip_reason, sig.resolve_name), (("PS4",), None, "World Series of Poker"))
        self.assertEqual(resolve_name_of("The Dark Pictures Anthology Series (Xbox One) - EU"), "The Dark Pictures Anthology Series")

    def test_residue_guard(self):
        # an "Xbox One Series" phrase the grammar cannot parse whole leaves "Series)" glued
        # to a bracket → fail-closed skip, never a One-only entry
        sig = classify_console("Hades (Xbox One Series)", "https://example.com/x", "Shop")
        self.assertEqual((sig.families, sig.skip_reason), ((), RESIDUE))
        self.assertEqual(SKIP_RESIDUE, RESIDUE)
        for name in ("Hades /Series", "Hades & Series", "Hades / Series)", "Hades (Series", "Hades, One", "Hades / One"):
            with self.subTest(name=name):
                sig = classify_console(name + " Xbox Live Key", "https://example.com/x", "Shop")
                self.assertEqual(sig.skip_reason, RESIDUE)
        # ordinary names with ONE / SERIES between words or after "-" / ":" are not residue
        for title in ("The Walking Dead: Season One (Xbox One) - Xbox Live Key - EUROPE",
                      "Killer Instinct: Season One - Ultra Edition (Xbox One) - Xbox Live Key - EUROPE",
                      "One Piece: Pirate Warriors 4 EU PS4 CD Key",
                      "Formula One - PS5 Download Code [EU]"):
            with self.subTest(title=title):
                sig = classify_console(title, G2A, "G2A")
                self.assertIsNone(sig.skip_reason)
        # a BALANCED standalone "(Series)" is a name element (2 real rows)
        sig = classify_console("Get Them Out! (Series) (Xbox Series X|S) XBOX LIVE Key EUROPE", "https://example.com/x", "Shop")
        self.assertEqual((sig.families, sig.skip_reason, sig.resolve_name, sig.region_base),
                         (("XBOX_SERIES",), None, "Get Them Out! (Series)", "eu"))


class LeadingNameTokenTests(unittest.TestCase):
    """Review finder 3 [low]: a console run that OPENS the title and is followed by a plain
    word is part of the game name — kept in resolve_name, not a family declaration."""

    def test_real_rows_keep_the_leading_word(self):
        cases = [
            ("Nintendo World Championships: NES Edition US Nintendo Switch CD Key",
             "https://www.kinguin.net/category/1/nintendo-world-championships-nes-edition-us-nintendo-switch-cd-key", "Kinguin",
             ("SWITCH",), "us", "Nintendo World Championships: NES Edition"),
            ("Xbox Fitness (Xbox One Download Code) - EU",
             "https://example.com/xbox-fitness-xbox-one-download-code-eu", "Shop",
             ("XBOX_ONE",), "eu", "Xbox Fitness"),
            ("PlayStation All-Stars Battle Royale EU PS4 CD Key",
             "https://www.kinguin.net/category/1/playstation-all-stars-battle-royale-eu-ps4-cd-key", "Kinguin",
             ("PS4",), "eu", "PlayStation All-Stars Battle Royale"),
            ("Nintendo Switch Sports EU Nintendo Switch CD Key",
             "https://www.kinguin.net/category/1/nintendo-switch-sports-eu-nintendo-switch-cd-key", "Kinguin",
             ("SWITCH",), "eu", "Nintendo Switch Sports"),
        ]
        for title, url, merchant, families, base, name in cases:
            with self.subTest(title=title):
                sig = classify_console(title, url, merchant)
                self.assertEqual((sig.families, sig.skip_reason, sig.region_base, sig.resolve_name),
                                 (families, None, base, name))
                self.assertEqual(resolve_name_of(title), name)

    def test_leading_run_as_the_only_marker_is_no_declaration(self):
        # Instant Gaming (URL carries nothing) / a slug that only mirrors the name
        for url, merchant in (("https://www.instant-gaming.com/en/1-/", "Instant Gaming"),
                              ("https://www.kinguin.net/category/1/nintendo-switch-sports-cd-key", "Kinguin"),
                              ("https://example.com/nintendo-switch-sports-cd-key", "Shop")):
            with self.subTest(url=url):
                sig = classify_console("Nintendo Switch Sports", url, merchant)
                self.assertEqual((sig.families, sig.skip_reason, sig.resolve_name), ((), NO_GEN, "Nintendo Switch Sports"))
        # a real platform slot AFTER the mirrored name still declares
        sig = classify_console("Nintendo Switch Sports", "https://www.kinguin.net/category/1/nintendo-switch-sports-nintendo-switch-cd-key", "Kinguin")
        self.assertEqual((sig.families, sig.skip_reason), (("SWITCH",), None))

    def test_bracketed_or_separated_opening_run_is_a_declaration(self):
        sig = classify_console("(Xbox One) Game - EU", "https://example.com/x", "Shop")
        self.assertEqual((sig.families, sig.resolve_name), (("XBOX_ONE",), "Game"))
        sig = classify_console("PS5 - Game Name [EU]", "https://example.com/x", "Shop")
        self.assertEqual((sig.families, sig.resolve_name), (("PS5",), "Game Name"))
        # the non-game markers still win over a leading name run
        sig = classify_console("Xbox Game Pass Ultimate 1 Month [EU]", "https://example.com/x", "Shop")
        self.assertEqual(sig.skip_reason, _not_a_game("GAME PASS"))
        sig = classify_console("Nintendo Switch Online 12 Months", "https://example.com/x", "Shop")
        self.assertEqual(sig.skip_reason, _not_a_game("NINTENDO SWITCH ONLINE"))


if __name__ == "__main__":
    unittest.main()

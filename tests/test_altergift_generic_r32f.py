"""`[R32f]` — « Steam Altergift = Steam Gift » pour TOUS les marchands, existants et futurs,
et les crochets de livraison MMOGA (proposition 6 de l'audit du 2026-09-28).

Romain, 2026-09-14 : « Steam Altergift = Steam Gift on rentre sous gift tous les altergifts »
(K4G, puis Kinguin) ; 2026-09-29 : « Oui pour etendre Altergift a MMOGA et a tous marchant
existant et futur ».

Les TITRES et les URL sont réels (feeds du 10 au 27/09 : K4G, Kinguin, MMOGA, CJS), sauf ceux
marqués « synthétique ». Le marchand « Nouveau Marchand » n'existe pas : c'est le marchand
FUTUR, sans fichier de config, que la décision couvre. Les PAGES sont celles lues le
2026-09-28 / 2026-09-29 (UA AKS/Staff) : nom, éditions, liste de régions (filtre de page) et
plateformes officielles recopiés tels quels. Le catalogue du formulaire est figé dans
``tests/fixtures/region_catalog_2026-09-26.json``.

Mutations vérifiées à la main (chacune fait tomber au moins un test ci-dessous) : retirer
``or is_altergift(offer.name)`` de ``_detect_region_parts`` (Firewatch → STEAM EU 9) ; retirer
le refus « outside the Steam collocation » de ``precheck_skip`` (Battle.net → BATTLENET GIFT) ;
retirer ``drop_altergift`` du nom de garde (R16 « extra words: ['ALTERGIFT'] ») ou de
``resolution_name`` (slug « …-altergift ») ; retirer la lecture du code dans les crochets MMOGA
(Ghost of Tsushima → GLOBAL 2 implicite) ; retirer le vocabulaire « produit » des crochets
(« Silent Hill 2 [Remake] » → « Silent Hill 2 ») ; faire rendre None au lieu de False par
``k4g.gift_delivery`` sur un Altergift refusé (Trine 5 → GIFT 25).
"""

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.console_keys import classify_console  # noqa: E402
from src.contracts import NormalizedOffer  # noqa: E402
from src.matcher import (  # noqa: E402
    AksResolution, Candidate, SkippedOffer, build_slug_candidates, detect_region, match_offer,
    precheck_skip, resolution_name,
)
from src.merchants import k4g, kinguin, mmoga  # noqa: E402
from src.merchants.common import (  # noqa: E402
    SKIP_ALTERGIFT_NOT_STEAM, drop_altergift, is_altergift, names_steam_alone,
)
from src.submitter import resolve_catalog_id  # noqa: E402

CATALOG = json.loads((ROOT / "tests" / "fixtures" / "region_catalog_2026-09-26.json")
                     .read_text(encoding="utf-8"))["regions"]["master_options"]
FUTURE = "Nouveau Marchand"          # aucun fichier de config : le marchand « futur »


def _offer(merchant, name, url):
    return NormalizedOffer(offer_id="1", name=name, url=url, merchant=merchant, price="9.99", stock="y")


def _page(slug, aks_name, editions, regions, platforms):
    return AksResolution(slug=slug, url=f"https://www.allkeyshop.com/blog/buy-{slug}-compare-prices/",
                         product_id="1", aks_name=aks_name,
                         editions={k: {"name": v} for k, v in editions.items()},
                         regions=dict(regions), official_platforms=tuple(platforms))


# ── pages AKS lues le 2026-09-28 / 2026-09-29 (UA AKS/Staff) ──────────────────────────
FIREWATCH = _page(
    "firewatch-cd-key", "Firewatch", {"1": "Standard"},
    {"6": "GOG GLOBAL", "25": "STEAM GIFT GLOBAL", "259": "STEAM GIFT EU", "2": "STEAM GLOBAL",
     "260": "STEAM GIFT EN LANG.", "9": "STEAM EU"},
    ("EA app", "Steam", "Xbox Play Anywhere", "GoG", "Direct Publisher"))
HIGH_ON_LIFE = _page(
    "high-on-life-cd-key", "High on Life",
    {"1": "Standard", "518": "Standard + DLC", "8": "Bundle", "1377": "DLC Bundle"},
    {"433": "EPIC ACCOUNT", "577": "ROW", "412": "STEAM ACCOUNT", "9": "STEAM EU",
     "259": "STEAM GIFT EU", "25": "STEAM GIFT GLOBAL", "2": "STEAM GLOBAL", "steamrow": "STEAM ROW",
     "477": "WINDOWS ACCOUNT", "306": "XBOX/PC", "241": "XBOX/PC  EUROPE"},
    ("Steam", "Xbox Play Anywhere"))
TETRIS = _page(
    "tetris-effect-connected-cd-key", "Tetris Effect Connected", {"1": "Standard"},
    {"2": "STEAM GLOBAL", "9": "STEAM EU", "259": "STEAM GIFT EU", "steamrow": "STEAM ROW",
     "25": "STEAM GIFT GLOBAL", "241": "XBOX/PC  EUROPE", "306": "XBOX/PC", "412": "STEAM ACCOUNT"},
    ("Steam", "Oculus", "Xbox Play Anywhere", "Epic Store"))
FC_25 = _page(
    "ea-sports-fc-25-cd-key", "EA SPORTS FC 25", {"1": "Standard", "21": "Ultimate"},
    {"466": "EA ACCOUNT", "3efsp": "EA ENG/FRA/SPA ONLY", "31": "EA ENG/POL/RUS ONLY",
     "3eu": "EA EUROPE", "32": "EA GERMANY", "3": "EA GLOBAL", "433": "EPIC ACCOUNT",
     "80": "EPIC GLOBAL", "412": "STEAM ACCOUNT", "9": "STEAM EU", "2": "STEAM GLOBAL"},
    ("Steam", "EA app", "Epic Store"))
GHOST_DC = _page(
    "ghost-of-tsushima-directors-cut-cd-key", "Ghost of Tsushima DIRECTOR’S CUT", {"1": "Standard"},
    {"steamrow": "STEAM ROW", "2": "STEAM GLOBAL", "9": "STEAM EU", "steamemea": "STEAM EMEA",
     "259": "STEAM GIFT EU", "25": "STEAM GIFT GLOBAL", "80": "EPIC GLOBAL", "412": "STEAM ACCOUNT"},
    ("Steam", "Epic Store"))
HORIZON_FW = _page(
    "horizon-forbidden-west-cd-key", "Horizon Forbidden West", {"91": "Complete"},
    {"2": "STEAM GLOBAL", "steamrow": "STEAM ROW", "9": "STEAM EU", "261": "STEAM ENG ONLY",
     "25": "STEAM GIFT GLOBAL", "259": "STEAM GIFT EU", "80": "EPIC GLOBAL", "433": "EPIC ACCOUNT",
     "412": "STEAM ACCOUNT"},
    ("Steam", "Epic Store"))
SPIDERMAN_R = _page(
    "marvels-spider-man-remastered-cd-key", "Marvel’s Spider-Man Remastered", {"1": "Standard"},
    {"2": "STEAM GLOBAL", "9": "STEAM EU", "steamrow": "STEAM ROW", "25": "STEAM GIFT GLOBAL",
     "259": "STEAM GIFT EU", "88us": "USA", "80": "EPIC GLOBAL", "412": "STEAM ACCOUNT",
     "433": "EPIC ACCOUNT"},
    ("Steam", "Playstation Store", "Epic Store"))
LAST_OF_US = _page(
    "the-last-of-us-part-i-cd-key", "The Last of Us Part I", {"1": "Standard", "7": "Deluxe"},
    {"433": "EPIC ACCOUNT", "80": "EPIC GLOBAL", "412": "STEAM ACCOUNT", "steamemea": "STEAM EMEA",
     "9": "STEAM EU", "427": "STEAM EU EN ONLY", "439": "STEAM EU EN/FR/DE", "259": "STEAM GIFT EU",
     "25": "STEAM GIFT GLOBAL", "2": "STEAM GLOBAL", "steamrow": "STEAM ROW", "641": "STEAM US/UK"},
    ("Steam", "Epic Store"))

# ── lignes MMOGA réelles (offres du feed store 12) ────────────────────────────────────
MMOGA_ALTERGIFT = (
    ("Firewatch [EU Steam Altergift]",
     "https://www.mmoga.com/Steam-Games/Firewatch-EU-Steam-Altergift.html?ref=615", FIREWATCH, "Firewatch"),
    ("High On Life [EU Steam Altergift]",
     "https://www.mmoga.com/Steam-Games/High-On-Life-EU-Steam-Altergift.html?ref=615", HIGH_ON_LIFE, "High On Life"),
    ("Tetris Effect Connected [EU Steam Altergift]",
     "https://www.mmoga.com/Steam-Games/Tetris-Effect-Connected-EU-Steam-Altergift.html?ref=615", TETRIS,
     "Tetris Effect Connected"),
    ("EA Sports FC 25 [EU Steam Altergift]",
     "https://www.mmoga.com/Steam-Games/EA-Sports-FC-25-EU-Steam-Altergift.html?ref=615", FC_25, "EA Sports FC 25"),
)
CJS_BATTLENET = (
    ("World of Warcraft - Forever Skyborne Epic Pack Battle.net Altergift (Digital Download)",
     "https://www.cjs-cdkeys.com/products/World-of-Warcraft-%252d-Forever-Skyborne-Epic-Pack-Battle.net-Altergift-%28Digital-Download%29"),
    ("Call of Duty: Black Ops 4 - Battle Royale & Multiplayer Only (Zombies Not Included) Battle.net Altergift",
     "https://www.cjs-cdkeys.com/products/Call-of-Duty%3A-Black-Ops-4-%252d-Battle-Royale-%26-Multiplayer-Only-%28Zombies-Not-Included%29-Battle.net-Altergift"),
)


class VocabularyTests(unittest.TestCase):
    def test_the_word(self):
        for title in ("Firewatch [EU Steam Altergift]", "Seafrog Steam Altergift",
                      "Sons Of The Forest PC Steam Altergift", CJS_BATTLENET[0][0]):
            with self.subTest(title=title):
                self.assertTrue(is_altergift(title))
        for title in ("Thief Simulator Europe Steam CD Key", "Altergifted PC Steam CD Key",
                      "F1 2013 Classic Edition Upgrade Steam Gift"):
            with self.subTest(title=title):
                self.assertFalse(is_altergift(title))

    def test_drop_leaves_everything_else(self):
        self.assertEqual(drop_altergift("Firewatch [EU Steam Altergift]"), "Firewatch [EU Steam]")
        self.assertEqual(drop_altergift("Seafrog Steam Altergift"), "Seafrog Steam")
        self.assertEqual(drop_altergift("Thief Simulator Europe Steam CD Key"), "Thief Simulator Europe Steam CD Key")

    def test_steam_alone(self):
        self.assertTrue(names_steam_alone("Firewatch [EU Steam Altergift]"))
        self.assertTrue(names_steam_alone("Sons Of The Forest PC Steam Altergift"))
        for title in (CJS_BATTLENET[0][0], "Warcraft I: Remastered PC Battle.net Altergift",
                      "Seafrog Steam / Epic Games Altergift", "Some ALTERGIFT Thing"):
            with self.subTest(title=title):
                self.assertFalse(names_steam_alone(title))

    def test_merchant_files_share_one_definition(self):
        # K4G / Kinguin re-export the shared helpers (their tests import them from there)
        self.assertIs(k4g.is_altergift, is_altergift)
        self.assertIs(kinguin.drop_altergift, drop_altergift)


class GenericGateTests(unittest.TestCase):
    """Steam SEULEMENT — la borne de la décision du 14/09, désormais générique."""

    def test_cjs_battlenet_altergift_is_refused_explicitly(self):
        # avant [R32f] : R16 « extra words: [..., 'ALTERGIFT'] » — refusé par effet de bord
        for title, url in CJS_BATTLENET:
            with self.subTest(title=title):
                offer = _offer("CJS-CDKeys", title, url)
                self.assertEqual(precheck_skip(offer), SKIP_ALTERGIFT_NOT_STEAM)
                self.assertEqual(precheck_skip(offer, consoles=True), SKIP_ALTERGIFT_NOT_STEAM)
                r = match_offer(offer, resolver=lambda name, **kw: FIREWATCH)
                self.assertIsInstance(r, SkippedOffer)
                self.assertEqual(r.reason, SKIP_ALTERGIFT_NOT_STEAM)

    def test_future_merchant_non_steam_is_refused(self):
        for title in ("Warcraft I: Remastered PC Battle.net Altergift",       # Kinguin, réel
                      "Seafrog Steam / Epic Games Altergift",                  # synthétique (K4G)
                      "Some ALTERGIFT Thing"):                                 # synthétique
            with self.subTest(title=title):
                self.assertEqual(precheck_skip(_offer(FUTURE, title, "https://shop.example/p/1")),
                                 SKIP_ALTERGIFT_NOT_STEAM)

    def test_merchant_grammar_keeps_its_own_reason(self):
        # K4G / Kinguin decide in their precheck (gift_delivery is not None) — reasons unchanged
        self.assertIn("Kinguin Altergift outside the Steam collocation",
                      precheck_skip(_offer("Kinguin", "Warcraft I: Remastered PC Battle.net Altergift",
                                           "https://www.kinguin.net/category/303669/warcraft-i-remastered-pc-battle-net-altergift")))
        self.assertIn("K4G delivery conflict",
                      precheck_skip(_offer("K4G", "Trine 5: A Clockwork Conspiracy Steam Altergift",
                                           "https://k4g.com/product/trine-5-a-clockwork-conspiracy-steam-global-instant-cd-key-48V2PFDZ")))

    def test_refused_merchant_row_never_reads_gift(self):
        # the K4G slug conflict: k4g.gift_delivery says False (not None) — or the generic read,
        # which knows the word now, would call it GIFT (25)
        trine = _offer("K4G", "Trine 5: A Clockwork Conspiracy Steam Altergift",
                       "https://k4g.com/product/trine-5-a-clockwork-conspiracy-steam-global-instant-cd-key-48V2PFDZ")
        self.assertIs(k4g.gift_delivery(trine.name, trine.url), False)
        self.assertEqual(detect_region(trine, "STEAM"), ("GLOBAL", "2", False))


class GenericGiftTests(unittest.TestCase):
    """Un marchand SANS grammaire de livraison : la lecture générique fait le travail."""

    SEAFROG_URL = "https://k4g.com/product/seafrog-steam-global-altergift-alter-gift-QU67G9P5"

    def test_future_merchant_buckets_are_layered_on_the_base_region(self):
        cases = (
            ("Seafrog Steam Altergift", "https://shop.example/p/seafrog", ("GIFT", "25", True)),
            ("Thief Simulator Europe Steam Altergift", "https://shop.example/p/thief-simulator",
             ("GIFT EU", "259", False)),
            ("Thief Simulator United Kingdom Steam Altergift",
             "https://k4g.com/product/thief-simulator-steam-united-kingdom-altergift-alter-gift-9TL2OHWM",
             ("GIFT UK", "2572", False)),
        )
        for title, url, expected in cases:
            with self.subTest(title=title):
                offer = _offer(FUTURE, title, url)
                self.assertIsNone(precheck_skip(offer))
                self.assertEqual(detect_region(offer, "STEAM"), expected)
        # a locked gift never widens to 25: a platform without the base bucket has no id
        self.assertEqual(detect_region(_offer(FUTURE, "Thief Simulator United Kingdom Steam Altergift",
                                              "https://shop.example/p/thief-simulator-united-kingdom"), "GOG"),
                         ("GIFT UK", None, False))

    def test_forbidden_region_keeps_its_skip(self):
        self.assertEqual(precheck_skip(_offer(FUTURE, "Mato Anomalies North America Steam Altergift",
                                              "https://shop.example/p/mato-anomalies")),
                         "forbidden region: NORTH AMERICA")

    def test_word_never_reaches_the_slug_nor_the_guard(self):
        offer = _offer(FUTURE, "Seafrog Steam Altergift", "https://shop.example/p/seafrog")
        self.assertNotIn("ALTERGIFT", resolution_name(offer).upper())
        self.assertTrue(all("altergift" not in s for s in build_slug_candidates(resolution_name(offer))))
        page = _page("seafrog-cd-key", "Seafrog", {"1": "Standard"}, {"25": "STEAM GIFT GLOBAL"}, ("Steam",))
        r = match_offer(offer, resolver=lambda name, **kw: page)
        self.assertIsInstance(r, Candidate, getattr(r, "reason", None))
        self.assertEqual((r.platform, r.region_label, r.region_id, r.edition_id), ("STEAM", "GIFT", "25", "1"))


class MmogaAltergiftTests(unittest.TestCase):
    """Les 4 lignes MMOGA « [EU Steam Altergift] » des feeds (10 → 27/09) — refusées jusqu'ici
    (slug « …-eu-steam-altergift » en 404 ; et, crochets retirés du seul nom de garde,
    « Firewatch » serait entré en STEAM EU (9), le seau des CLÉS : audit du 28/09, §6.1)."""

    def test_all_four_enter_as_steam_gift_eu(self):
        for title, url, page, asked_name in MMOGA_ALTERGIFT:
            with self.subTest(title=title):
                offer = _offer("MMOGA", title, url)
                self.assertIsNone(precheck_skip(offer, consoles=True))
                self.assertEqual(mmoga.title_region(title), "eu")
                self.assertEqual(mmoga.resolve_name(title), asked_name)
                self.assertEqual(detect_region(offer, "STEAM"), ("GIFT EU", "259", False))
                asked = []

                def resolver(name, **kw):
                    asked.append(name)
                    return page

                r = match_offer(offer, resolver=resolver, consoles=True)
                self.assertIsInstance(r, Candidate, getattr(r, "reason", None))
                self.assertEqual((r.platform, r.region_label, r.region_id, r.edition_label, r.edition_id),
                                 ("STEAM", "GIFT EU", "259", "Standard", "1"))
                self.assertEqual(asked, [asked_name])
                self.assertEqual(resolve_catalog_id(r.region_label, r.region_id, CATALOG)["id"], "259")


class MmogaDeliveryBracketTests(unittest.TestCase):
    """Proposition 6 (audit du 2026-09-28) : les crochets de LIVRAISON sortent du slug — et
    leur code de région est LU, sinon une clé EU entrerait en GLOBAL implicite."""

    def test_which_brackets_are_delivery(self):
        for content in ("EU Steam Altergift", "EU Key", "PC Version - Steam Key EU", "PC - Steam Key EU",
                        "Steam PC Key EU", "PC Version | Steam Key EU", "Steam Game Card", "Steam Game Card EU",
                        "PC", "Steam", "PC Version / EA Gamecard", "PC Version, EA App Key", "Official Key",
                        "Greencode Key", "PC - Origin", "Steam Key"):
            with self.subTest(content=content):
                self.assertTrue(mmoga.is_delivery_bracket(content))
        for content in ("Remake", "VR", "2014", "DLC", "Banjo & Kazooie", "EU", "Austria", "DE",
                        "Xbox One / Series X|S Download Code", "Xbox One/Series X|S",
                        "EN Key - English Only", "PC - Origin EN Key", "EA App Key EN - English Only",
                        "PC Version / EA App EN Key - English only",
                        # synthétiques : un mot de PRODUIT mêlé à la livraison garde le crochet
                        "Deluxe Steam Key", "Remake PC", "Steam Deck"):
            with self.subTest(content=content):
                self.assertFalse(mmoga.is_delivery_bracket(content))

    def test_resolve_name_real_titles(self):
        for title, expected in (
            ("Firewatch [EU Steam Altergift]", "Firewatch"),
            ("Borderlands 2 [EU Key]", "Borderlands 2"),
            ("Ghost of Tsushima - Director's Cut [PC Version - Steam Key EU]", "Ghost of Tsushima - Director's Cut"),
            ("Horizon Zero Dawn Remastered [PC Version | Steam Key EU]", "Horizon Zero Dawn Remastered"),
            ("The Last of Us : Part I [PC] [Steam]", "The Last of Us : Part I"),
            ("EA Sports FC 25 [PC Version / Steam Gamecard] - EU", "EA Sports FC 25"),
            ("Immortals of Aveum [PC Version, EA App Key] - EU", "Immortals of Aveum"),
            ("Days Gone [PC Version]", "Days Gone"),
            # product brackets, console brackets, [R63] brackets: untouched
            ("Silent Hill 2 [Remake]", "Silent Hill 2 [Remake]"),
            ("Metro Awakening [VR] - Deluxe Edition", "Metro Awakening [VR] - Deluxe Edition"),
            ("Lords of the Fallen - Digital Deluxe Edition [2014]", "Lords of the Fallen - Digital Deluxe Edition [2014]"),
            ("TBH: Task Bar Hero - Hunter (Class) [DLC]", "TBH: Task Bar Hero - Hunter (Class) [DLC]"),
            ("Diablo IV - Ultimate Edition [Xbox One / Series X|S Download Code]",
             "Diablo IV - Ultimate Edition [Xbox One / Series X|S Download Code]"),
            ("GRID Legends [EN Key - English Only]", "GRID Legends [EN Key - English Only]"),
            ("FIFA 23 - Ultimate Edition [PC - Origin EN Key] - English Only",
             "FIFA 23 - Ultimate Edition [PC - Origin EN Key] - English Only"),
            # no bracket: byte-identical (the historical "<CODE> Key" peel)
            ("Borderlands 2 EU Key", "Borderlands 2"),
            ("Street Fighter  6 - Year 1 Character Pass", "Street Fighter  6 - Year 1 Character Pass"),
        ):
            with self.subTest(title=title):
                self.assertEqual(mmoga.resolve_name(title), expected)

    def test_region_inside_the_bracket(self):
        for title, code, region in (
            ("Ghost of Tsushima - Director's Cut [PC Version - Steam Key EU]", "EU", "eu"),
            ("Horizon Forbidden West - Complete Edition [Steam PC Key EU]", "EU", "eu"),
            ("Planet Coaster 2 [Steam Game Card EU]", "EU", "eu"),
            ("Borderlands 2 [EU Key]", "EU", "eu"),
            ("Immortals of Aveum [PC Version, EA App Key] - EU", "EU", "eu"),
            ("Returnal [PC - Steam Key]", None, None),
            ("FIFA 23 - Ultimate Edition [PC - Origin EN Key] - English Only", None, None),   # EN ≠ région
            ("A Way Out [EA App Key EN - English Only] - EU", None, None),   # [R63] bracket: generic tail
        ):
            with self.subTest(title=title):
                self.assertEqual(mmoga.region_code(title), code)
                self.assertEqual(mmoga.title_region(title), region)
                self.assertIsNone(mmoga.precheck(title, ""))
        # an unmapped code after a delivery bracket is a lock → fail-closed, never GLOBAL
        self.assertEqual(mmoga.precheck("EA Sports FC 25 [PC Version / EA Gamecard] - DE", ""),
                         "forbidden region: DE")
        # synthétique : two different codes → refused, never one of the two
        self.assertEqual(mmoga.precheck("Game [Steam Key US] - EU", ""),
                         "MMOGA region conflict: US / EU written in the same title — not entered (2026-09-29)")

    def test_eu_keys_never_widen_to_global(self):
        # 101040244 / 101039968 were created STEAM GLOBAL (2) on 2026-09-11: the bracket code was unread
        for title, url, page, edition in (
            ("Ghost of Tsushima - Director's Cut [PC Version - Steam Key EU]",
             "https://www.mmoga.com/Steam-Games/Ghost-of-Tsushima-Directors-Cut-PC-Version-Steam-Key-EU.html?ref=615",
             GHOST_DC, ("Standard", "1")),
            ("Horizon Forbidden West - Complete Edition [Steam PC Key EU]",
             "https://www.mmoga.com/Steam-Games/Horizon-Forbidden-West-Complete-Edition-Steam-PC-Key-EU.html?ref=615",
             HORIZON_FW, ("Complete", "91")),
            ("Marvel's Spider-Man Remastered [PC - Steam Key EU]",
             "https://www.mmoga.com/Steam-Games/Marvels-Spider-Man-Remastered-PC-Steam-Key-EU.html?ref=615",
             SPIDERMAN_R, ("Standard", "1")),
        ):
            with self.subTest(title=title):
                offer = _offer("MMOGA", title, url)
                self.assertEqual(detect_region(offer, "STEAM"), ("EU", "9", False))
                r = match_offer(offer, resolver=lambda name, **kw: page, consoles=True)
                self.assertIsInstance(r, Candidate, getattr(r, "reason", None))
                self.assertEqual((r.platform, r.region_label, r.region_id, r.region_implicit,
                                  r.edition_label, r.edition_id), ("STEAM", "EU", "9", False) + edition)

    def test_region_less_bracket_enters_like_any_region_less_mmoga_row(self):
        offer = _offer("MMOGA", "The Last of Us : Part I [PC] [Steam]",
                       "https://www.mmoga.com/Steam-Games/The-Last-of-Us-Part-I-PC-Steam.html?ref=615")
        r = match_offer(offer, resolver=lambda name, **kw: LAST_OF_US, consoles=True)
        self.assertIsInstance(r, Candidate, getattr(r, "reason", None))
        self.assertEqual((r.platform, r.region_label, r.region_id, r.edition_id), ("STEAM", "GLOBAL", "2", "1"))

    def test_guard_still_reads_the_bracket(self):
        # the bracket leaves the SLUG only: « Card » / « Gamecard » stay extra words
        for title, url in (
            ("SMITE 2 [Steam Game Card]", "https://www.mmoga.com/Steam-Games/SMITE-2-Steam-Game-Card.html?ref=615"),
            ("EA Sports FC 25 [PC Version / Steam Gamecard] - EU",
             "https://www.mmoga.com/Steam-Games/EA-Sports-FC-25-PC-Version-Steam-Gamecard-EU.html?ref=615"),
        ):
            with self.subTest(title=title):
                page = FC_25 if "FC 25" in title else _page("smite-2-cd-key", "SMITE 2", {"1": "Standard"},
                                                            {"2": "STEAM GLOBAL"}, ("Steam",))
                r = match_offer(_offer("MMOGA", title, url), resolver=lambda name, **kw: page, consoles=True)
                self.assertIsInstance(r, SkippedOffer)
                self.assertIn("extra words", r.reason)

    def test_console_rows_unchanged(self):
        sig = classify_console("Ride 4 - Xbox One Download Code [EU Key]",
                               "https://www.mmoga.com/Xbox-Live/Xbox-One-Game-Keys/Ride-4-Xbox-One-Download-Code-EU-Key.html?ref=615",
                               "MMOGA")
        self.assertEqual((sig.families, sig.resolve_name, sig.region_base, sig.skip_reason),
                         (("XBOX_ONE",), "Ride 4", "eu", None))


if __name__ == "__main__":
    unittest.main()

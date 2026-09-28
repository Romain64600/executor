"""`[R63]` — clés EA « English only » : case 31 sans verrou, 3euen sinon 3eu en Europe.

Romain, 2026-09-28 : « go pour les clés EA English only en case 31 », puis « Une clé english
only n'est pas forcément bloquée à la région Europe, si on a une info comme EU english only on
renseignera EU en priorité si pas de région "EU english only" ».

Les TITRES et les URL sont réels (feeds du 10 au 28/09, deux machines), sauf ceux marqués
« synthétique » : aucune clé EA English only verrouillée US / UK ni aucun cadeau n'a été vu,
ces cas (c) sont donc construits. Les PAGES sont celles lues le 2026-09-28 (UA AKS/Staff) :
nom, éditions, liste de régions (filtre de page) et plateformes officielles recopiés tels quels.
Le catalogue du formulaire est figé dans ``tests/fixtures/region_catalog_2026-09-26.json``
(867 options, identiques dans les 32 catalogues sauvegardés du 10 au 26/09).
"""

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import src.matcher as matcher  # noqa: E402
from src.aks_lists import suggest_target_list  # noqa: E402
from src.contracts import NormalizedOffer  # noqa: E402
from src.feed_status import categorize_reason  # noqa: E402
from src.matcher import (  # noqa: E402
    EA_ENGLISH_ONLY_LABELS, REGION_IDS, SKIP_R63_CONSOLE, SKIP_R63_NO_PLATFORM, AksResolution,
    Candidate, SkippedOffer, english_only_bucket, english_only_route, extra_significant_words,
    match_offer, precheck_skip, resolution_name, skip_r63_platform,
)
from src.merchants import g2a, mmoga  # noqa: E402
from src.merchants.common import (  # noqa: E402
    english_only_mark, split_english_only_tail, strip_english_only,
)
from src.merchants.registry import merchant_config  # noqa: E402
from src.sort_plan import build_sort_plan  # noqa: E402
from src.submitter import resolve_catalog_id  # noqa: E402

CATALOG = json.loads((ROOT / "tests" / "fixtures" / "region_catalog_2026-09-26.json")
                     .read_text(encoding="utf-8"))["regions"]["master_options"]


def _page(slug, aks_name, editions, regions, platforms):
    return AksResolution(slug=slug, url=f"https://www.allkeyshop.com/blog/buy-{slug}-compare-prices/",
                         product_id="1", aks_name=aks_name, editions=dict(editions),
                         regions=dict(regions), official_platforms=tuple(platforms))


def _without(page, *ids):
    """La même page, sans certaines régions — pour les cas « la page ne porte pas le seau »
    (toutes les pages EA lues le 28/09 portent 31)."""

    regions = {k: v for k, v in page.regions.items() if k not in ids}
    return _page(page.slug, page.aks_name, page.editions, regions, page.official_platforms)


# ── pages AKS lues le 2026-09-28 (UA AKS/Staff) ───────────────────────────────────────
NFS_HEAT = _page(
    "need-for-speed-heat-cd-key", "Need for Speed Heat", {"7": "Deluxe", "1": "Standard"},
    {"466": "EA ACCOUNT", "431": "EA EN/FR/ES/PT", "3efsp": "EA ENG/FRA/SPA ONLY",
     "31": "EA ENG/POL/RUS ONLY", "3eu": "EA EUROPE", "3": "EA GLOBAL", "3row": "EA ROW",
     "433": "EPIC ACCOUNT", "412": "STEAM ACCOUNT", "259": "STEAM GIFT EU",
     "25": "STEAM GIFT GLOBAL", "2": "STEAM GLOBAL"},
    ("Steam", "EA app", "Xbox"))
FC_25 = _page(
    "ea-sports-fc-25-cd-key", "EA SPORTS FC 25", {"1": "Standard", "21": "Ultimate"},
    {"466": "EA ACCOUNT", "3efsp": "EA ENG/FRA/SPA ONLY", "31": "EA ENG/POL/RUS ONLY",
     "3eu": "EA EUROPE", "32": "EA GERMANY", "3": "EA GLOBAL", "433": "EPIC ACCOUNT",
     "80": "EPIC GLOBAL", "412": "STEAM ACCOUNT", "9": "STEAM EU", "25": "STEAM GIFT GLOBAL",
     "2": "STEAM GLOBAL"},
    ("Steam", "EA app", "Epic Store"))
FIFA_23 = _page(
    "fifa-23-cd-key", "FIFA 23", {"1": "Standard", "21": "Ultimate"},
    {"466": "EA ACCOUNT", "38": "EA EN/FR", "431": "EA EN/FR/ES/PT", "3efsp": "EA ENG/FRA/SPA ONLY",
     "31": "EA ENG/POL/RUS ONLY", "3euen": "EA EU ENG ONLY", "3eu": "EA EUROPE", "3": "EA GLOBAL",
     "433": "EPIC ACCOUNT", "412": "STEAM ACCOUNT", "261": "STEAM ENG ONLY", "9": "STEAM EU",
     "2": "STEAM GLOBAL", "steamrow": "STEAM ROW"},
    ("Steam", "EA app", "Playstation Store"))
GRID_LEGENDS = _page(
    "grid-legends-cd-key", "GRID Legends", {"1": "Standard", "7": "Deluxe"},
    {"3": "EA GLOBAL", "31": "EA ENG/POL/RUS ONLY", "25": "STEAM GIFT GLOBAL", "2": "STEAM GLOBAL",
     "9": "STEAM EU", "259": "STEAM GIFT EU", "261": "STEAM ENG ONLY", "466": "EA ACCOUNT",
     "412": "STEAM ACCOUNT"},
    ("Steam", "EA app"))
A_WAY_OUT = _page(
    "a-way-out-cd-key", "A Way Out", {"1": "Standard"},
    {"466": "EA ACCOUNT", "3emea": "EA EMEA", "3efsp": "EA ENG/FRA/SPA ONLY",
     "31": "EA ENG/POL/RUS ONLY", "3euen": "EA EU ENG ONLY", "3eu": "EA EUROPE", "3": "EA GLOBAL",
     "412": "STEAM ACCOUNT", "259": "STEAM GIFT EU", "25": "STEAM GIFT GLOBAL",
     "steamgiftrow": "STEAM GIFT ROW", "2": "STEAM GLOBAL"},
    ("Steam", "Ubisoft Connect", "EA app"))
PVZ_BFN = _page(
    "plants-vs-zombies-battle-for-neighborville-cd-key", "Plants vs Zombies Battle for Neighborville",
    {"1": "Standard", "7": "Deluxe"},
    {"466": "EA ACCOUNT", "3efsp": "EA ENG/FRA/SPA ONLY", "31": "EA ENG/POL/RUS ONLY",
     "3eu": "EA EUROPE", "3": "EA GLOBAL", "433": "EPIC ACCOUNT", "412": "STEAM ACCOUNT",
     "9": "STEAM EU", "259": "STEAM GIFT EU", "25": "STEAM GIFT GLOBAL", "2": "STEAM GLOBAL"},
    ("Steam", "EA app", "Xbox"))
BURNOUT = _page(
    "burnout-paradise-remastered-cd-key", "Burnout Paradise Remastered", {"1": "Standard"},
    {"2": "STEAM GLOBAL", "25": "STEAM GIFT GLOBAL", "259": "STEAM GIFT EU", "3": "EA GLOBAL",
     "31": "EA ENG/POL/RUS ONLY", "3eu": "EA EUROPE", "466": "EA ACCOUNT", "412": "STEAM ACCOUNT"},
    ("Steam", "EA app"))
NFS_RIVALS = _page(
    "need-for-speed-rivals-cd-key", "Need for Speed Rivals",
    {"1": "Standard", "91": "Complete", "4": "Limited"},
    {"3": "EA GLOBAL", "25": "STEAM GIFT GLOBAL", "259": "STEAM GIFT EU", "2": "STEAM GLOBAL",
     "3eu": "EA EUROPE", "31": "EA ENG/POL/RUS ONLY", "433": "EPIC ACCOUNT", "466": "EA ACCOUNT"},
    ("Steam", "EA app"))
FC_27 = _page(
    "ea-sports-fc-27-key", "EA SPORTS FC 27",
    {"1": "Standard", "6734": "Standard + Bonus", "21": "Ultimate", "15222": "Ultimate Plus"},
    {"31": "EA ENG/POL/RUS ONLY", "3euen": "EA EU ENG ONLY", "3eu": "EA EUROPE", "3": "EA GLOBAL",
     "433": "EPIC ACCOUNT", "80": "EPIC GLOBAL", "412": "STEAM ACCOUNT", "9": "STEAM EU",
     "259": "STEAM GIFT EU", "25": "STEAM GIFT GLOBAL", "2": "STEAM GLOBAL"},
    ("Steam", "EA app", "Epic Store"))

# ── lignes réelles ─────────────────────────────────────────────────────────────────────
MMOGA_NFS_HEAT = ("Need for Speed Heat (English only)",
                  "https://www.mmoga.com/EA-Games/Need-for-Speed-Heat-English-only.html?ref=615", "MMOGA")
MMOGA_FC_25 = ("EA Sports FC 25 [PC Version / EA App EN Key - English only]",
               "https://www.mmoga.com/EA-Games/EA-Sports-FC-25-PC-Version-EA-App-EN-Key-English-only.html?ref=615",
               "MMOGA")
MMOGA_FIFA_23 = ("FIFA 23 - Ultimate Edition [PC - Origin EN Key] - English Only",
                 "https://www.mmoga.com/EA-Games/FIFA-23-Ultimate-Edition-PC-Origin-EN-Key-English-Only.html?ref=615",
                 "MMOGA")
MMOGA_GRID = ("GRID Legends [EN Key - English Only]",
              "https://www.mmoga.com/EA-Games/GRID-Legends-EN-Key-English-Only.html?ref=615", "MMOGA")
MMOGA_A_WAY_OUT = ("A Way Out [EA App Key EN - English Only] - EU",
                   "https://www.mmoga.com/EA-Games/A-Way-Out-EA-App-Key-EN-English-Only-EU.html?ref=615",
                   "MMOGA")
MMOGA_BF_V = ("Battlefield V (English only)",
              "https://www.mmoga.com/EA-Games/Battlefield-V-English-only.html?ref=615", "MMOGA")
MMOGA_FC_24_PS5 = ("EA Sports FC 24 (PS5 Download Code EU) - English Only Key",
                   "https://www.mmoga.com/Playstation-Network/Playstation-5-Game-Keys/"
                   "EA-Sports-FC-24-PS5-Download-Code-EU-English-Only-Key.html?ref=615", "MMOGA")
CJS_PVZ = ("Plants vs. Zombies: Battle for Neighborville (EA App): English Only",
           "https://www.cjs-cdkeys.com/products/Plants-vs.-Zombies%3A-Battle-for-Neighborville-%28EA-App%29.html?variation=443",
           "CJS-CDKeys")
CJS_SIMCITY = ("SimCity Limited Edition (EA App): Standard Edition (English Only)",
               "https://www.cjs-cdkeys.com/products/SimCity-Limited-Edition-%28EA-App%29.html?variation=184",
               "CJS-CDKeys")
CJS_DIVISION = ("Tom Clancy's The Division Gold Edition Ubisoft Connect Key: English Only (Cheaper) "
                "(Day 1 Edition (includes Hazmat Gear Set))",
                "https://www.cjs-cdkeys.com/products/Tom-Clancy%27s-The-Division-Gold-Edition-Ubisoft-Connect-Key.html?variation=435%2C439",
                "CJS-CDKeys")
GAMESEAL_BURNOUT = ("Burnout Paradise Remastered EN Language Only  (PC) EA App Key - GLOBAL",
                    "https://gameseal.com/burnout-paradise-remastered-en-language-only-pc-ea-app-key-global",
                    "GameSeal")
GAMESEAL_TECHNOMANCER = ("The Technomancer EN Only (PC) Steam Key - GLOBAL",
                         "https://gameseal.com/the-technomancer-en-only-pc-steam-key-global", "GameSeal")
KINGUIN_NFS_RIVALS = ("Need for Speed Rivals Complete Edition EN Language Only PC EA App CD Key",
                      "https://www.kinguin.net/en/category/564200/need-for-speed-rivals-complete-edition-en-language-only-pc-ea-app-cd-key?nosalesbooster=1",
                      "Kinguin")
KINGUIN_FC_27 = ("EA SPORTS FC 27 Ultimate Edition EN Language Only EA App CD Key",
                 "https://www.kinguin.net/category/826759/ea-sports-fc-27-ultimate-edition-en-language-only-ea-app-cd-key",
                 "Kinguin")
KINGUIN_DEADLIGHT = ("Deadlight: Director's Cut English Language Only Steam CD Key",
                     "https://www.kinguin.net/category/115714/deadlight-director-s-cut-english-language-only-steam-cd-key",
                     "Kinguin")
KINGUIN_COD_BNET = ("Call of Duty: Modern Warfare II Endowment (C.O.D.E.) - Protector Pack DLC EN Language "
                    "Only Battle.net CD Key",
                    "https://www.kinguin.net/category/139491/call-of-duty-modern-warfare-ii-endowment-c-o-d-e-protector-pack-dlc-en-language-only-battle-net-cd-k",
                    "Kinguin")
KINGUIN_POKEMON = ("Pokemon FireRed Version EN Language Only EU Nintendo Switch CD Key",
                   "https://www.kinguin.net/category/510313/pokemon-firered-version-en-language-only-eu-nintendo-switch-cd-key",
                   "Kinguin")
KINGUIN_BUS_AR = ("Bus Simulator 21 EN Language Only AR XBOX One / Xbox Series X|S CD Key",
                  "https://www.kinguin.net/category/320006/bus-simulator-21-en-language-only-ar-xbox-one-xbox-series-x-s-cd-key",
                  "Kinguin")
KINGUIN_DOW2 = ("Warhammer 40,000: Dawn of War II: Retribution - Complete DLC Collection EN Language Only "
                "Steam CD Key",
                "https://www.kinguin.net/category/146941/warhammer-40-000-dawn-of-war-ii-retribution-complete-dlc-collection-en-language-only-steam-cd-key",
                "Kinguin")
KINGUIN_DRAGON_AGE = ("Dragon Age: The Veilguard EN/ES/FR/PT Languages Only PC EA App CD Key",
                      "https://www.kinguin.net/category/301811/dragon-age-the-veilguard-enesfrpt-languages-only-pc-ea-app-c",
                      "Kinguin")
K4G_AC_UNITY = ("Assassin's Creed Unity (English Only) Ubisoft Connect CD Key",
                "https://k4g.com/product/assassin-s-creed-unity-ubisoft-connect-global-english-only-cd-key-cd-key-CRT7P40S",
                "K4G")
G2A_BF_V = ("Battlefield V | Definitive Edition (PC) - In App Key - EUROPE ENG ONLY",
            "https://www.g2a.com/battlefield-v-definitive-edition-pc-in-app-key-europe-eng-only-i10000155679071?___currency=EUR",
            "G2A")
GAMESEAL_FIFA_EN_PL = ("FIFA 23 EN/PL Languages Only (PC) EA App Key - GLOBAL",
                       "https://gameseal.com/fifa-23-en-pl-languages-only-pc-ea-app-key-global", "GameSeal")
CJS_JEDI_EN_PL = ("Star Wars: Jedi Fallen Order EN/PL Language EA App Key",
                  "https://www.cjs-cdkeys.com/products/Star-Wars%3A-Jedi-Fallen-Order-EN%7B47%7DPL-Language-EA-App-Key.html",
                  "CJS-CDKeys")
DRIFFLE_FC_27_EN = ("EA SPORTS FC 27 Ultimate Edition (EN) (Global) (PC) - EA Play - Digital Key",
                    "https://www.driffle.com/ea-sports-fc-27-ultimate-edition-en-global-pc-ea-play-digital-key-p10000827",
                    "Driffle")

IN_SCOPE = (MMOGA_NFS_HEAT, MMOGA_FC_25, MMOGA_FIFA_23, MMOGA_GRID, MMOGA_A_WAY_OUT, MMOGA_BF_V,
            CJS_PVZ, CJS_SIMCITY, GAMESEAL_BURNOUT, KINGUIN_NFS_RIVALS, KINGUIN_FC_27, G2A_BF_V)


def _offer(row):
    name, url, merchant = row
    return NormalizedOffer(offer_id="1", name=name, url=url, merchant=merchant)


def _match(row, page, consoles=True):
    """Le matcher tel qu'en production ; le résolveur rend ``page`` et garde les noms qu'on
    lui a demandés (le nom de résolution = le slug)."""

    asked = []

    def resolver(name, **kw):
        asked.append(name)
        return None if kw.get("page_kind") not in (None, "cd-key") else page

    res = match_offer(_offer(row), resolver=resolver, account_resolver=resolver,
                      page_resolver=lambda url: None, consoles=consoles)
    return res, asked


# ════════════════════════════════════════════════════════════════════════════════════════
class LaMention(unittest.TestCase):
    """Le détecteur partagé (``merchants.common``) — lu sur le titre BRUT."""

    def test_toutes_les_ecritures_vues_dans_les_feeds(self):
        for row, mark in (
            (MMOGA_NFS_HEAT, "English only"), (MMOGA_FC_25, "English only"),
            (MMOGA_FIFA_23, "English Only"), (MMOGA_GRID, "English Only"),
            (MMOGA_A_WAY_OUT, "English Only"), (CJS_PVZ, "English Only"),
            (CJS_SIMCITY, "English Only"), (GAMESEAL_BURNOUT, "EN Language Only"),
            (GAMESEAL_TECHNOMANCER, "EN Only"), (KINGUIN_DEADLIGHT, "English Language Only"),
            (G2A_BF_V, "ENG ONLY"), (MMOGA_FC_24_PS5, "English Only"),
        ):
            with self.subTest(row[0]):
                self.assertEqual(english_only_mark(row[0]), mark)

    def test_un_nom_de_jeu_qui_contient_english_ou_only_n_est_pas_la_mention(self):
        # Titres RÉELS des feeds : « English » ou « Only » y sont des mots du produit, ou une
        # langue parmi d'autres, jamais la restriction.
        for title in (
            "Little Busters English Edition (PC) Standard Europe",
            "Tomoyo After ~It's a Wonderful Life~ English Edition Steam Gift EUROPE",
            "Learn English Grammar Online Course Standard Other Global",
            "The District English (PC) Steam Key - GLOBAL",
            "Kingdom Come: Deliverance - HD Voice Pack - English",
            "Lost Planet 2 English (all regions and languages) Key (Windows Live)",
            "Tom Clancy's The Division Gold Edition Ubisoft Connect Key: Multi-Language "
            "(English + all other languages) (Standard Edition)",
            "Read Only Memories Neurodiver EN United States",       # Gamivo : EN = créneau langue
            "Read Only Memories: NEURODIVER (PC) Steam Key - GLOBAL",
            "Virus Hunter - Adult Only (PC) Steam Key - GLOBAL",
            "Only DWARVES DIG Proper HOLES PC Steam CD Key",
            "Company of Heroes 2 Multiplayer Access Only Steam CD Key",
            "Mass Effect Legendary Edition (ENG) (PC)  EA App Key  - GLOBAL",
            DRIFFLE_FC_27_EN[0],
            "Battlefield 4 (EA App): Standard Edition + Premium Membership (Base Game + ALL "
            "expansion packs) (English (EN))",
        ):
            with self.subTest(title):
                self.assertIsNone(english_only_mark(title))

    def test_une_liste_de_langues_n_est_pas_la_mention(self):
        for title in (
            "Lonesome Village IT/FR/EN Languages Only Steam CD Key",       # réel
            "Webbed EN/DE Languages Only Steam CD Key",                    # réel
            GAMESEAL_FIFA_EN_PL[0], KINGUIN_DRAGON_AGE[0],                 # réels
            "Polish/English Language Only EA App Key",                     # synthétique
            "Game French & English Only EA App Key",                       # synthétique
            "Game German, English only (EA App)",                          # synthétique
            "Game Polish and English only (EA App)",                       # synthétique
        ):
            with self.subTest(title):
                self.assertIsNone(english_only_mark(title))

    def test_en_et_eng_ne_comptent_qu_en_capitales(self):
        self.assertIsNone(english_only_mark("Some Game En Only"))
        self.assertIsNone(english_only_mark("Some Game Eng Only"))
        self.assertEqual(english_only_mark("Some Game English-only"), "English-only")


class LeRetraitDeLaMention(unittest.TestCase):
    def test_la_phrase_et_ce_qu_elle_vide(self):
        self.assertEqual(strip_english_only(MMOGA_NFS_HEAT[0]), "Need for Speed Heat")
        self.assertEqual(strip_english_only(CJS_PVZ[0]),
                         "Plants vs. Zombies: Battle for Neighborville (EA App)")
        self.assertEqual(strip_english_only(MMOGA_FIFA_23[0]),
                         "FIFA 23 - Ultimate Edition [PC - Origin EN Key]")
        self.assertEqual(strip_english_only(MMOGA_GRID[0]), "GRID Legends [EN Key]")
        self.assertEqual(strip_english_only(GAMESEAL_BURNOUT[0]),
                         "Burnout Paradise Remastered (PC) EA App Key - GLOBAL")
        self.assertEqual(strip_english_only("Some Game"), "Some Game")

    def test_mmoga_retire_le_crochet_de_livraison_entier(self):
        self.assertEqual(mmoga.english_only_name(MMOGA_GRID[0]), "GRID Legends")
        self.assertEqual(mmoga.english_only_name(MMOGA_FC_25[0]), "EA Sports FC 25")
        self.assertEqual(mmoga.english_only_name(MMOGA_A_WAY_OUT[0]), "A Way Out - EU")
        self.assertEqual(mmoga.english_only_name(MMOGA_FIFA_23[0]),
                         "FIFA 23 - Ultimate Edition - English Only")
        self.assertIs(merchant_config("MMOGA").english_only_name, mmoga.english_only_name)

    def test_hors_r63_le_nom_de_resolution_garde_la_mention(self):
        # resolution_name alimente aussi l'export liste 22 : la mention n'en sort JAMAIS ;
        # seul _pc_plan, sur la route [R63], la retire.
        for row in IN_SCOPE:
            with self.subTest(row[0]):
                self.assertIsNotNone(english_only_mark(resolution_name(_offer(row))))
        self.assertEqual(merchant_config("MMOGA").resolve_name(MMOGA_GRID[0]), MMOGA_GRID[0])

    def test_hors_r63_les_gardes_pesent_toujours_english_only(self):
        # ENGLISH / ONLY ne sont PAS des mots de bruit : sans la route, la mention reste un extra.
        self.assertEqual(extra_significant_words("Need for Speed Heat", MMOGA_NFS_HEAT[0]),
                         ["ENGLISH", "ONLY"])
        self.assertEqual(extra_significant_words("GRID Legends", "GRID Legends ENG ONLY"),
                         ["ENG", "ONLY"])

    def test_g2a_la_queue_de_region_perd_la_mention(self):
        self.assertEqual(g2a.region_tail(G2A_BF_V[0]), "EUROPE")
        self.assertIsNone(g2a.precheck(G2A_BF_V[0], G2A_BF_V[1]))
        self.assertEqual(g2a.title_region(G2A_BF_V[0]), "eu")
        self.assertEqual(split_english_only_tail("EUROPE ENG ONLY"), ("EUROPE", True))
        self.assertEqual(split_english_only_tail("NORTH AMERICA"), ("NORTH AMERICA", False))


# ════════════════════════════════════════════════════════════════════════════════════════
class LePrecheck(unittest.TestCase):
    """Les refus que le titre / l'URL décident seuls — explicites, avant toute page AKS."""

    def test_steam_ubisoft_battlenet_sont_refuses_explicitement(self):
        for row, platform in ((KINGUIN_DEADLIGHT, "STEAM"), (GAMESEAL_TECHNOMANCER, "STEAM"),
                              (K4G_AC_UNITY, "UBISOFT"), (CJS_DIVISION, "UBISOFT"),
                              (KINGUIN_COD_BNET, "BATTLENET")):
            for consoles in (False, True):
                with self.subTest(row[0], consoles=consoles):
                    self.assertEqual(precheck_skip(_offer(row), consoles=consoles),
                                     skip_r63_platform(platform))

    def test_g2a_sans_plateforme_declaree(self):
        # « In App Key » ne déclare pas EA ; avant : « forbidden region: EUROPE ENG ONLY ».
        self.assertEqual(precheck_skip(_offer(G2A_BF_V), consoles=True), SKIP_R63_NO_PLATFORM)

    def test_console_r7_seulement_sur_le_chemin_console(self):
        for row in (MMOGA_FC_24_PS5, KINGUIN_POKEMON):
            with self.subTest(row[0]):
                self.assertEqual(precheck_skip(_offer(row), consoles=True), SKIP_R63_CONSOLE)
                self.assertEqual(precheck_skip(_offer(row), consoles=False), "console")
        self.assertEqual(categorize_reason(SKIP_R63_CONSOLE), "console")

    def test_les_raisons_existantes_gardent_la_priorite(self):
        self.assertEqual(precheck_skip(_offer(KINGUIN_BUS_AR), consoles=True),
                         "forbidden region: ARGENTINA")
        self.assertTrue(precheck_skip(_offer(KINGUIN_DOW2)).startswith("skip category: COMPLETE DLC"))
        division_gold = (
            "Tom Clancy's The Division Gold Edition Ubisoft Connect Key: English Only (Cheaper) "
            "(Gold Edition (Game + Season Pass))",
            "https://www.cjs-cdkeys.com/products/Tom-Clancy%27s-The-Division-Gold-Edition-Ubisoft-Connect-Key.html?variation=435%2C440",
            "CJS-CDKeys")
        self.assertEqual(precheck_skip(_offer(division_gold)), "possible multi-game bundle")

    def test_les_listes_de_langues_restent_language_restriction(self):
        for row in (GAMESEAL_FIFA_EN_PL, CJS_JEDI_EN_PL, KINGUIN_DRAGON_AGE,
                    ("Polish/English Language Only EA App Key",                     # synthétique
                     "https://www.kinguin.net/category/1/polish-english-language-only-ea-app-key",
                     "Kinguin")):
            with self.subTest(row[0]):
                self.assertEqual(precheck_skip(_offer(row), consoles=True), "language restriction")

    def test_les_lignes_ea_passent_le_precheck(self):
        for row in (MMOGA_NFS_HEAT, MMOGA_A_WAY_OUT, GAMESEAL_BURNOUT, KINGUIN_FC_27, CJS_PVZ):
            with self.subTest(row[0]):
                self.assertIsNone(precheck_skip(_offer(row), consoles=True))

    def test_aucun_refus_r63_n_est_route_vers_une_liste(self):
        for reason in (skip_r63_platform("STEAM"), SKIP_R63_NO_PLATFORM, SKIP_R63_CONSOLE,
                       english_only_route("EA", "EA", "US")[1],
                       english_only_route("EA", "EA", "GMG GIFT")[1],
                       english_only_bucket("en_only", _without(NFS_HEAT, "31")),
                       english_only_bucket("eu_en_only", GRID_LEGENDS)):
            with self.subTest(reason):
                self.assertIsNone(suggest_target_list(reason))
                self.assertIn("R63", reason)

    def test_le_tri_ne_compte_pas_une_cle_steam_english_only_comme_candidate(self):
        plan = build_sort_plan([_offer(KINGUIN_DEADLIGHT)], run_id="t")
        self.assertEqual(plan["counts"]["candidates"], 0)


# ════════════════════════════════════════════════════════════════════════════════════════
class CasA_SansVerrou_Case31(unittest.TestCase):
    def _enters_31(self, row, page, edition=("Standard", "1"), slug_name=None):
        res, asked = _match(row, page)
        self.assertIsInstance(res, Candidate, getattr(res, "reason", ""))
        self.assertEqual((res.platform, res.region_id), ("EA", "31"))
        self.assertEqual(res.region_label, "Origin English Only -OR- EN/PL -OR- EN/PL/RU")
        self.assertEqual((res.edition_label, res.edition_id), edition)
        if slug_name is not None:
            self.assertEqual(asked[0], slug_name)
        return res

    def test_mmoga_nfs_heat(self):
        self._enters_31(MMOGA_NFS_HEAT, NFS_HEAT, slug_name="Need for Speed Heat")

    def test_mmoga_fc_25(self):
        self._enters_31(MMOGA_FC_25, FC_25, slug_name="EA Sports FC 25")

    def test_mmoga_fifa_23_ultimate(self):
        self._enters_31(MMOGA_FIFA_23, FIFA_23, ("Ultimate", "21"),
                        slug_name="FIFA 23 - Ultimate Edition")

    def test_mmoga_grid_legends(self):
        self._enters_31(MMOGA_GRID, GRID_LEGENDS, slug_name="GRID Legends")

    def test_cjs_pvz(self):
        self._enters_31(CJS_PVZ, PVZ_BFN)

    def test_gameseal_burnout_global_ecrit(self):
        res = self._enters_31(GAMESEAL_BURNOUT, BURNOUT)
        self.assertFalse(res.region_implicit)

    def test_kinguin_nfs_rivals_complete(self):
        self._enters_31(KINGUIN_NFS_RIVALS, NFS_RIVALS, ("Complete", "91"),
                        slug_name="Need for Speed Rivals Complete Edition")

    def test_kinguin_fc_27_ultimate(self):
        self._enters_31(KINGUIN_FC_27, FC_27, ("Ultimate", "21"))

    def test_page_sans_31_refus_explicite(self):
        res, _ = _match(MMOGA_NFS_HEAT, _without(NFS_HEAT, "31"))
        self.assertIsInstance(res, SkippedOffer)
        self.assertIn("ne porte pas la case 31", res.reason)
        self.assertIn("(R63)", res.reason)

    def test_le_plan_garde_la_base_globale_pour_r44(self):
        plan = matcher._pc_plan(_offer(MMOGA_NFS_HEAT), lambda n, **k: NFS_HEAT,
                                lambda url: None, lambda n, **k: None)
        self.assertEqual((plan.region_id, plan.base_label), ("31", "GLOBAL"))


class CasB_Europe_3euen_sinon_3eu(unittest.TestCase):
    def test_a_way_out_eu_entre_en_3euen(self):
        res, asked = _match(MMOGA_A_WAY_OUT, A_WAY_OUT)
        self.assertIsInstance(res, Candidate, getattr(res, "reason", ""))
        self.assertEqual((res.platform, res.region_id, res.region_label),
                         ("EA", "3euen", "Origin EU English Only"))
        self.assertEqual(asked[0], "A Way Out - EU")

    def test_page_sans_3euen_le_verrou_europe_prime_3eu(self):
        res, _ = _match(MMOGA_A_WAY_OUT, _without(A_WAY_OUT, "3euen"))
        self.assertIsInstance(res, Candidate, getattr(res, "reason", ""))
        self.assertEqual((res.region_id, res.region_label), ("3eu", "EU"))

    def test_page_sans_3euen_ni_3eu_refus_jamais_31(self):
        page = _without(A_WAY_OUT, "3euen", "3eu")
        self.assertIn("31", page.regions)
        res, _ = _match(MMOGA_A_WAY_OUT, page)
        self.assertIsInstance(res, SkippedOffer)
        self.assertIn("ne porte ni 3euen", res.reason)

    def test_une_page_reelle_sans_aucun_seau_europe(self):
        # synthétique : la même grammaire MMOGA, verrou Europe, sur la page GRID Legends
        # (31 seul, ni 3euen ni 3eu).
        row = ("GRID Legends [EN Key - English Only] - EU",
               "https://www.mmoga.com/EA-Games/GRID-Legends-EN-Key-English-Only-EU.html?ref=615", "MMOGA")
        res, _ = _match(row, GRID_LEGENDS)
        self.assertIsInstance(res, SkippedOffer)
        self.assertIn("ne porte ni 3euen", res.reason)

    def test_g2a_europe_eng_only_s_arrete_faute_de_plateforme(self):
        res, _ = _match(G2A_BF_V, A_WAY_OUT)
        self.assertEqual(getattr(res, "reason", None), SKIP_R63_NO_PLATFORM)

    def test_le_plan_garde_la_base_eu(self):
        plan = matcher._pc_plan(_offer(MMOGA_A_WAY_OUT), lambda n, **k: A_WAY_OUT,
                                lambda url: None, lambda n, **k: None)
        self.assertEqual((plan.region_id, plan.base_label), ("3euen", "EU"))


class CasC_AutresVerrous(unittest.TestCase):
    """Aucune ligne réelle : aucune clé EA English only verrouillée US / UK n'a été vue."""

    def test_us_refuse_question_ouverte(self):
        row = ("A Way Out [EA App Key EN - English Only] - US",                      # synthétique
               "https://www.mmoga.com/EA-Games/A-Way-Out-EA-App-Key-EN-English-Only-US.html?ref=615", "MMOGA")
        res, asked = _match(row, A_WAY_OUT)
        self.assertIsInstance(res, SkippedOffer)
        self.assertIn("verrouillée US — question ouverte", res.reason)
        self.assertEqual(asked, [])                  # refusé avant toute page AKS

    def test_uk_par_la_grammaire_mmoga(self):
        row = ("Need for Speed Heat (English only) UK Key",                          # synthétique
               "https://www.mmoga.com/EA-Games/Need-for-Speed-Heat-English-only-UK-Key.html?ref=615", "MMOGA")
        res, _ = _match(row, NFS_HEAT)
        self.assertIsInstance(res, SkippedOffer)
        self.assertIn("verrouillée UK", res.reason)

    def test_la_route_elle_meme(self):
        self.assertEqual(english_only_route("EA", "EA", "GLOBAL"), ("en_only", None))
        self.assertEqual(english_only_route("EA", "EA", "EU"), ("eu_en_only", None))
        for label in ("US", "UK"):
            self.assertIsNone(english_only_route("EA", "EA", label)[0])
        self.assertIn("GMG GIFT", english_only_route("EA", "EA", "GMG GIFT")[1])
        self.assertIn("GLOBAL ACCOUNT", english_only_route("EA", "EA", "GLOBAL ACCOUNT")[1])
        self.assertEqual(english_only_route(None, "STEAM", "GLOBAL"), (None, SKIP_R63_NO_PLATFORM))
        self.assertEqual(english_only_route("STEAM", "STEAM", "GLOBAL"),
                         (None, skip_r63_platform("STEAM")))


class PlateformeLueSurLaPageMarchande(unittest.TestCase):
    """Un marchand dont la plateforme vient de SA page (Instant Gaming) : le precheck ne peut
    pas trancher, ``_pc_plan`` refait tous les contrôles une fois la page lue (synthétique :
    aucune ligne Instant Gaming English only n'a été vue)."""

    ROW = ("Need for Speed Heat (English only)",
           "https://www.instant-gaming.com/en/4242-buy-need-for-speed-heat-pc-game-origin/",
           "Instant Gaming")

    def _with_page_platform(self, platform):
        import dataclasses
        from src.merchant_config import MerchantOfferSignals
        from src.merchants.registry import MERCHANT_CONFIGS
        original = MERCHANT_CONFIGS["INSTANT GAMING"]
        MERCHANT_CONFIGS["INSTANT GAMING"] = dataclasses.replace(
            original, offer_page_resolver=lambda url, name="": MerchantOfferSignals(platform=platform))
        try:
            return precheck_skip(_offer(self.ROW), consoles=True), _match(self.ROW, NFS_HEAT)[0]
        finally:
            MERCHANT_CONFIGS["INSTANT GAMING"] = original

    def test_page_steam_refus_dans_le_plan(self):
        pre, res = self._with_page_platform("STEAM")
        self.assertIsNone(pre)
        self.assertEqual(getattr(res, "reason", None), skip_r63_platform("STEAM"))

    def test_page_ea_case_31(self):
        pre, res = self._with_page_platform("EA")
        self.assertIsNone(pre)
        self.assertIsInstance(res, Candidate, getattr(res, "reason", ""))
        self.assertEqual(res.region_id, "31")


class LeFormulaire(unittest.TestCase):
    """Au moment de la saisie : ``resolve_catalog_id`` puis un clic sur ``[data-value=id]``."""

    def test_les_ids(self):
        self.assertEqual(REGION_IDS["EA"]["en_only"], "31")
        self.assertEqual(REGION_IDS["EA"]["eu_en_only"], "3euen")
        self.assertEqual(REGION_IDS["EA"]["eu"], "3eu")
        owners = {fam for fam, ids in REGION_IDS.items() for v in ids.values() if v in ("31", "3euen")}
        self.assertEqual(owners, {"EA"})

    def test_31_et_3euen_se_resolvent_par_libelle_de_facon_unique(self):
        for rid, label in EA_ENGLISH_ONLY_LABELS.items():
            with self.subTest(rid):
                got = resolve_catalog_id(label, rid, CATALOG)
                self.assertEqual((got["id"], got["source"]), (rid, "label"))
                # le libellé l'emporte même si l'id du matcher avait dérivé
                self.assertEqual(resolve_catalog_id(label, "999999", CATALOG)["id"], rid)

    def test_le_repli_3eu_se_resout_par_id_comme_toute_cle_ea_eu(self):
        got = resolve_catalog_id("EU", "3eu", CATALOG)
        self.assertEqual((got["id"], got["source"], got["text"]), ("3eu", "id", "Origin EU (3eu)"))

    def test_le_catalogue_fige(self):
        texts = {o["key"]: o["text"] for o in CATALOG}
        self.assertEqual(len(CATALOG), 867)
        self.assertEqual(texts["31"], "Origin English Only -OR- EN/PL -OR- EN/PL/RU (31)")
        self.assertEqual(texts["3euen"], "Origin EU English Only (3euen)")


class HorsPerimetre(unittest.TestCase):
    def test_driffle_en_nu_inchange(self):
        # « (EN) » n'est pas la mention : la ligne garde le chemin EA ordinaire (question
        # ouverte pour Romain — AKS range l'Ultimate de Driffle en 31).
        res, _ = _match(DRIFFLE_FC_27_EN, FC_27)
        self.assertIsInstance(res, Candidate, getattr(res, "reason", ""))
        self.assertEqual(res.region_id, "3")

    def test_bf_v_mmoga_reste_sans_page(self):
        res, asked = _match(MMOGA_BF_V, None)
        self.assertEqual(getattr(res, "reason", ""), "no AKS product page found (slug not 200)")
        self.assertEqual(asked[0], "Battlefield V")


if __name__ == "__main__":
    unittest.main()

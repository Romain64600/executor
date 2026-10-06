"""[R70] — l'Amérique du Nord est une région vendable (Romain, 2026-10-06 : « go pour NA, PC et
consoles »), après le log K4G « STAR WARS: Galactic Racer Standard Edition North America Steam CD
Key — forbidden region: NORTH AMERICA ». Le menu AKS a STEAM NA (steamna), Steam Gift NA (2571),
Origin NA (643), Ubisoft NA (606), Battle.net NA (625), et les cases consoles NA (582 / 304 / 605 /
610 / 496). 1 260 offres distinctes étaient refusées en production. Ce que ces tests épinglent :
la lecture (nom entier partout, code « NA » seulement dans un créneau), les ids par plateforme
(jamais un élargissement : pas de case → refus), les consoles, les verrous composés qui restent,
R44 et R63 qui connaissent la nouvelle base."""

import unittest

from src.console_keys import CONSOLE_REGION_IDS, CONSOLE_REGION_LABELS, classify_console, region_slot_of
from src.contracts import NormalizedOffer
from src.matcher import (
    FORBIDDEN_REGIONS, REGION_IDS, AksResolution, Candidate, SkippedOffer, detect_region,
    detect_region_base, english_only_unread_lock, match_offer, precheck_skip,
    region_phrase_in_aks_name,
)
from src.merchants.common import compound_region_kind, region_kind, sellable_base

FUTURE = "Nouveau Marchand"          # aucun fichier de config : le scan générique seul


def _offer(name, url, merchant=FUTURE):
    return NormalizedOffer(offer_id="1", name=name, url=url, merchant=merchant, store_id="999",
                           price="9.99", stock="y")


def _page(aks_name, platforms=("Steam",), regions=None, editions=None):
    return AksResolution(slug="x", url="https://www.allkeyshop.com/blog/buy-x-cd-key-compare-prices/",
                         product_id="1", aks_name=aks_name,
                         editions=editions or {"1": "Standard"},
                         regions=regions or {"2": "GLOBAL"}, official_platforms=platforms)


class LaLecture(unittest.TestCase):
    def test_le_cas_de_romain_k4g_lit_na_steam(self):
        o = _offer("STAR WARS: Galactic Racer Standard Edition North America Steam CD Key",
                   "https://k4g.com/product/star-wars-galactic-racer-steam-north-america-instant-cd-key-standard-edition-cd-key-Z13V2KT0",
                   merchant="K4G")
        self.assertIsNone(precheck_skip(o), "plus un verrou")
        self.assertEqual(detect_region(o, "STEAM"), ("NA", "steamna", False))

    def test_le_nom_entier_dans_le_titre_ou_le_slug_le_code_seulement_en_creneau(self):
        cas = (
            ("Quantum Break North America Steam Key", "https://m/quantum-break", "na"),
            ("Quantum Break Steam Key", "https://m/quantum-break-north-america", "na"),
            ("Quantum Break Steam Key", "https://m/quantum-break-steam-key-na", "na"),      # slot d'URL
            ("Quantum Break (NA) Steam Key", "https://m/quantum-break", "na"),             # parenthèse
            ("Quantum Break - Steam Key - NA", "https://m/quantum-break", "na"),           # queue
            ("Sea of NA Thieves Steam Key", "https://m/sea-of-na-thieves", "global"),      # « NA » nu = un mot
            ("Banana Steam Key", "https://m/banana-steam-key", "global"),
        )
        for name, url, base in cas:
            with self.subTest(name):
                self.assertEqual(detect_region_base(_offer(name, url))[0], base)

    def test_les_verrous_composes_restent_des_verrous(self):
        self.assertNotIn("NORTH AMERICA", FORBIDDEN_REGIONS)
        self.assertIn("EU NA", FORBIDDEN_REGIONS)
        self.assertIn("AMERICAS", FORBIDDEN_REGIONS)
        self.assertEqual(precheck_skip(_offer("Game EU/NA Steam Key", "https://m/game")),
                         "forbidden region: EU NA")
        self.assertEqual(precheck_skip(_offer("Game Americas Steam Key", "https://m/game")),
                         "forbidden region: AMERICAS")
        # vocabulaire partagé des grammaires marchandes
        self.assertEqual(region_kind("NORTH AMERICA"), ("base", "na"))
        self.assertEqual(region_kind("NA"), ("base", "na"))
        self.assertIsNone(region_kind("Na"), "un code court en minuscules n'est pas un code")
        self.assertEqual(sellable_base("North America"), "na")
        self.assertEqual(compound_region_kind("EU/NA"), ("forbidden", "EU NA"))
        self.assertEqual(compound_region_kind("EUROPE / NORTH AMERICA"),
                         ("forbidden", "EUROPE / NORTH AMERICA"),
                         "deux bases différentes = un verrou (comme EU/UK), jamais une devinette")


class LesCases(unittest.TestCase):
    def test_une_case_par_plateforme_jamais_un_elargissement(self):
        attendu = {"STEAM": "steamna", "EA": "643", "UBISOFT": "606", "BATTLENET": "625",
                   "GOG": None, "EPIC": None, "PUBLISHER": None, "ROCKSTAR": None, "MICROSOFT": None}
        for plat, rid in attendu.items():
            with self.subTest(plat):
                self.assertEqual(REGION_IDS[plat].get("na"), rid)
                self.assertEqual(detect_region(_offer("Game North America Key", "https://m/game"), plat),
                                 ("NA", rid, False))

    def test_le_cadeau_na_prend_sa_case_jamais_le_cadeau_mondial(self):
        o = _offer("vROVpilot: TITANIC (PC) Steam Gift - NA", "https://m/vrovpilot-titanic")
        self.assertEqual(detect_region(o, "STEAM"), ("GIFT NA", "2571", False))
        self.assertEqual(detect_region(o, "BATTLENET"), ("GIFT NA", None, False))

    def test_sans_case_la_ligne_est_refusee_pas_devinee(self):
        o = _offer("Game North America GOG Key", "https://m/game-gog")
        res = match_offer(o, resolver=lambda n, **k: _page("Game", platforms=("GoG",)))
        self.assertIsInstance(res, SkippedOffer)
        self.assertIn("no region id", res.reason)

    def test_un_candidat_steam_na_de_bout_en_bout(self):
        o = _offer("Quantum Break North America Steam Key", "https://m/quantum-break")
        res = match_offer(o, resolver=lambda n, **k: _page("Quantum Break"))
        self.assertIsInstance(res, Candidate, getattr(res, "reason", ""))
        self.assertEqual((res.platform, res.region_label, res.region_id, res.region_implicit),
                         ("STEAM", "NA", "steamna", False))


class LesConsoles(unittest.TestCase):
    def test_les_cases_na_par_famille_et_leur_texte(self):
        attendu = {"XBOX_ONE": "582", "XBOX_SERIES": "304", "XBOX_PC": "605", "PS4": "610",
                   "PS5": "610", "SWITCH": "496", "SWITCH2": "496"}
        for fam, rid in attendu.items():
            with self.subTest(fam):
                self.assertEqual(CONSOLE_REGION_IDS[fam]["na"], rid)
                self.assertIn(rid, CONSOLE_REGION_LABELS)
        self.assertEqual(CONSOLE_REGION_LABELS["304"], "Xbox Series NA Game Code")
        self.assertEqual(CONSOLE_REGION_LABELS["610"], "playstation game code na")

    def test_une_ligne_console_na_a_sa_base(self):
        self.assertEqual(region_slot_of(["NA"]), ("na", None))
        self.assertEqual(region_slot_of(["North America"]), ("na", None))
        sig = classify_console("Onimusha: Way of the Sword NA PS5 CD Key",
                               "https://www.kinguin.net/category/1/onimusha-way-of-the-sword-na-ps5-cd-key", "Kinguin")
        self.assertIsNotNone(sig)
        self.assertEqual((sig.region_base, sig.region_label), ("na", None))
        self.assertEqual(sig.families, ("PS5",))


class LesGardesConnaissentLaBase(unittest.TestCase):
    def test_r44_north_america_dans_le_nom_de_la_page_est_une_identite(self):
        self.assertEqual(region_phrase_in_aks_name("NA", "Railway Empire North America"), "NORTH AMERICA")
        self.assertIsNone(region_phrase_in_aks_name("NA", "Railway Empire"))

    def test_r63_un_verrou_na_ecrit_n_est_jamais_la_case_31(self):
        o = _offer("Battlefield 2042 (English Only) North America EA App Key", "https://m/battlefield-2042")
        self.assertIsNotNone(english_only_unread_lock(o, "en_only"))
        self.assertIsNotNone(english_only_unread_lock(o, "eu_en_only"))


if __name__ == "__main__":
    unittest.main()

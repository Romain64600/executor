"""eww.gg (store 170) — la seconde boutique de Driffle UAB (Romain, 2026-10-07 : « Store ID 170
stop B et lance le data entry pour ce nouveau shop »). Le fichier est une déclinaison de
`driffle.py` : ces tests épinglent qu'il lit la ligne réelle du 07/10 comme Driffle le ferait,
que l'URL eww (identifiant nu) donne les familles console, et que le registre / la liste
blanche le connaissent sous son nom et son store."""

import unittest

from src.admin.auto_merchants import AUTO_MERCHANTS, rejection_reason
from src.contracts import NormalizedOffer
from src.matcher import detect_region, precheck_skip
from src.merchants import eww
from src.merchants.registry import merchant_config, merchant_for_store

TITRE = "George VS Bonny PP Wars (Global) (PC) - Steam - Digital Key"
URL = "https://eww.gg/george-vs-bonny-pp-wars-global-pc-steam-digital-key-151108"


def _offre(nom=TITRE, url=URL):
    return NormalizedOffer(offer_id="1", name=nom, url=url, merchant="eww.gg", store_id="170")


class LaGrammaireDeDriffle(unittest.TestCase):
    def test_la_ligne_reelle_du_07_10(self):
        self.assertIsNone(precheck_skip(_offre(), consoles=True))
        self.assertEqual(detect_region(_offre(), "STEAM"), ("GLOBAL", "2", False))
        self.assertEqual(eww.title_region(TITRE), "global")
        self.assertEqual(eww.region_bracket(TITRE), "Global")

    def test_les_parentheses_de_region_comme_chez_driffle(self):
        self.assertEqual(eww.title_region("Uncle Billy's Dream Bundle (Europe) (PC) - Steam - Digital Key"), "eu")
        self.assertEqual(eww.precheck("DRAGON BALL Sparking! ZERO (United States / Canada) (PC) - Steam - Digital Key", URL),
                         "forbidden region: CANADA")
        self.assertEqual(eww.precheck("Fortnite - 12500 V-Bucks Card (France) - Epic Games - Digital Key", URL),
                         "forbidden region: FRANCE")
        self.assertIsNone(eww.title_region("Little Nightmares - Tengu Mask DLC (SIEE) (PS4) - PSN - Digital Key"))

    def test_les_familles_console_de_l_url_eww(self):
        self.assertEqual(eww.console_url_families(
            "https://eww.gg/hades-europe-xbox-one-xbox-series-xs-xbox-live-digital-key-151234"), ("XBOX_ONE", "XBOX_SERIES"))
        self.assertEqual(eww.console_url_families("https://eww.gg/hades-global-ps4-ps5-psn-digital-key-9"), ("PS4", "PS5"))
        self.assertEqual(eww.console_url_families("https://eww.gg/hades-eu-nintendo-switch-nintendo-digital-code-p77"), ("SWITCH",))
        self.assertIsNone(eww.console_url_families(URL))

    def test_le_domaine_est_exige(self):
        self.assertIn("merchant-domain mismatch", precheck_skip(_offre(url="https://driffle.com/x-global-pc-steam-digital-key-p1")) or "")


class LeRegistreEtLaListeBlanche(unittest.TestCase):
    def test_nom_store_et_module(self):
        cfg = merchant_config("eww.gg")
        self.assertIs(cfg, eww.CONFIG)
        self.assertEqual(cfg.domain, "eww.gg")
        self.assertEqual(merchant_for_store("170"), "eww.gg")
        self.assertIn(("eww.gg", "170"), AUTO_MERCHANTS)
        self.assertIsNone(rejection_reason("eww.gg", "170"))
        self.assertIsNotNone(rejection_reason("eww.gg", "127"), "le store de Driffle n'est pas celui d'eww")


if __name__ == "__main__":
    unittest.main()

"""CJS-CDKeys — `[R67]` le créneau de région après « Key: » (2026-09-29).

« DYSMANTLE Steam Key: United Kingdom » tombait au GLOBAL implicite : la lecture générique ne
connaît que la queue « - X ». 120 clés Steam « United Kingdom » (plus une EA, une Epic) ont été
écrites en GLOBAL au lieu du seau UK. Titres réels du feed CJS."""

import unittest

from src.contracts import NormalizedOffer
from src.matcher import detect_region, precheck_skip
from src.merchants import cjs


def _o(nom):
    return NormalizedOffer(offer_id="1", name=nom, merchant="CJS-CDKeys", store_id="30",
                           url="https://www.cjs-cdkeys.com/products/X-Steam-Key.html?variation=609")


class LeCreneauDeRegion(unittest.TestCase):
    def test_royaume_uni_n_est_plus_le_monde(self):
        for nom, plateforme, attendu in (
            ("DYSMANTLE Steam Key: United Kingdom", "STEAM", ("UK", "71")),
            ("Persona 3 Reload Deluxe Edition (Steam): United Kingdom", "STEAM", ("UK", "71")),
            ("EA Sports FC 25 EA App Key: United Kingdom", "EA", ("UK", "3uk")),
            ("Just Cause 4 Reloaded Steam Key: United Kingdom", "STEAM", ("UK", "71")),
        ):
            with self.subTest(nom):
                o = _o(nom)
                self.assertIsNone(precheck_skip(o, consoles=True))
                self.assertEqual(detect_region(o, plateforme)[:2], attendu)

    def test_les_creneaux_vendables_gardent_leur_base(self):
        for nom, attendu in (
            ("Ticket to Ride: Classic Edition Steam Key: Europe & UK", ("EU", "9")),
            ("Ticket to Ride: Classic Edition Steam Key: Global", ("GLOBAL", "2")),
            ("Ticket to Ride: Classic Edition Steam Key: USA", ("US", "8")),
            ("Wargame: Red Dragon Steam Key: EU", ("EU", "9")),
            ("Omerta City of Gangsters Steam CD Key: GLOBAL", ("GLOBAL", "2")),
        ):
            with self.subTest(nom):
                self.assertEqual(detect_region(_o(nom), "STEAM")[:2], attendu)

    def test_les_autres_orthographes_vendables_ne_sont_pas_des_pays(self):
        # Audit de Romain (2026-09-29, P2) : « UK » et « Worldwide » étaient refusés comme des
        # pays. « Worldwide est Global, UK est UK. »
        for nom, plateforme, attendu in (
            ("DYSMANTLE Steam Key: UK", "STEAM", ("UK", "71")),
            ("DYSMANTLE Steam Key: GB", "STEAM", ("UK", "71")),
            ("DYSMANTLE Steam Key: Worldwide", "STEAM", ("GLOBAL", "2")),
            ("DYSMANTLE Steam Key: WW", "STEAM", ("GLOBAL", "2")),
            ("DYSMANTLE Steam Key: United States", "STEAM", ("US", "8")),
            ("DYSMANTLE Steam Key: European Union", "STEAM", ("EU", "9")),
        ):
            with self.subTest(nom):
                o = _o(nom)
                self.assertIsNone(precheck_skip(o, consoles=True))
                self.assertEqual(detect_region(o, plateforme)[:2], attendu)
                self.assertFalse(detect_region(o, plateforme)[2], "région lue, pas implicite")

    def test_un_pays_ou_une_zone_est_refuse_jamais_le_monde(self):
        for nom in ("Quantum Break Steam Key: China",
                    "Darksiders Warmastered Edition EN/DE/FR/IT Steam Key: Italy",
                    "Midnight at the Red Light : An Investigation Steam Key: Austria",
                    "Microsoft Flight Simulator Steam Key: Nigeria",
                    "Mortal Shell - The Virtuous Cycle Steam Key: MENA",
                    "Some Game Steam Key: US Region (North America)",
                    "Some Game Steam Key: Latin and North America"):
            with self.subTest(nom):
                self.assertIsNotNone(precheck_skip(_o(nom), consoles=True))

    def test_un_creneau_qui_n_est_pas_un_lieu_laisse_la_main(self):
        # Édition, contenu, nom de jeu avec deux-points : la lecture générique, comme avant.
        for nom in ("Thief Steam Key: Standard Edition",
                    "Call Of Duty Black Ops 2 Steam Key: Include Nuketown 2025 pack",
                    "Some Game Steam Key: Nether - Watcher",
                    "Warhammer 40,000: Space Marine Steam Key"):
            with self.subTest(nom):
                self.assertIsNone(cjs.precheck(nom, ""))
                self.assertIsNone(cjs.title_region(nom))

    def test_le_creneau_lu(self):
        self.assertEqual(cjs.region_slot("DYSMANTLE Steam Key: United Kingdom"), "United Kingdom")
        self.assertEqual(cjs.region_slot("Persona 3 Reload (Steam):  United   Kingdom"), "United Kingdom")
        self.assertIsNone(cjs.region_slot("Dune: Awakening EN Language Steam Key"))


if __name__ == "__main__":
    unittest.main()


class LesAccessSontInverifiables(unittest.TestCase):
    """[R72] (Romain, 2026-10-07) : « <Jeu> <Plateforme> Access (Digital Download) » ne dit pas si
    c'est une clé ou un compte — « Account, on le voit que sur la page, avec un message : attention,
    ce jeu est un account » — et la page CJS ne se lit pas (403). Refus nommé, sans routage : jamais
    une clé (52 l'ont été du 17/09 au 30/09), jamais « un compte » (on ne le sait pas)."""

    URL = "https://www.cjs-cdkeys.com/products/Onimusha%3A-Way-of-the-Sword-PS5-Access-%28Digital-Download%29.html"
    ACCESS = (
        "Onimusha: Way of the Sword PS5 Access (Digital Download)",
        "Persona 5 Royal PS4/PS5 Access (Digital Download)",
        "Slay the Spire Nintendo Switch Access (Digital Download)",
        "The Quarry XBOX One / Xbox Series X|S Access (Digital Download)",
        "Nioh 3 PS5 Access (Digital Download)",
        "Some Game PS5 Access",
    )
    CLES = (
        "Super Fantasy Kingdom (Early Access) PC Steam Key: Global",
        "HITMAN 3 Access Pass: HITMAN 2 Expansion - DLC (Steam)",
        "Path of Exile 2 Early Access Supporter Packs XBOX",
        "Dragon's Dogma 2 Steam Key: Europe",
        "Game Early Access (Digital Download)",
    )

    def test_refus_nomme_sans_routage(self):
        from src.aks_lists import suggest_target_list
        from src.contracts import NormalizedOffer
        from src.matcher import precheck_skip
        from src.merchants import cjs
        for nom in self.ACCESS:
            with self.subTest(nom):
                self.assertTrue(cjs.access_listing(nom))
                self.assertEqual(cjs.precheck(nom, self.URL), cjs.SKIP_ACCESS_UNVERIFIABLE)
                o = NormalizedOffer(offer_id="1", name=nom, url=self.URL, merchant="CJS-CDKeys", store_id="30")
                reason = precheck_skip(o, consoles=True)
                self.assertEqual(reason, cjs.SKIP_ACCESS_UNVERIFIABLE)
                self.assertIsNone(suggest_target_list(reason), "ni liste 30 ni blacklist : on ne sait pas")
                self.assertNotIn("skip category", reason)
        for nom in self.CLES:
            with self.subTest(nom):
                self.assertFalse(cjs.access_listing(nom))
                self.assertNotEqual(cjs.precheck(nom, self.URL), cjs.SKIP_ACCESS_UNVERIFIABLE)

    def test_jamais_un_candidat(self):
        # Le chemin complet : c'est ce créneau qui avait écrit Nioh 3 et Onimusha comme des clés PS5.
        from src.contracts import NormalizedOffer
        from src.matcher import Candidate, match_offer
        o = NormalizedOffer(offer_id="1", name=self.ACCESS[0], url=self.URL, merchant="CJS-CDKeys", store_id="30")
        res = match_offer(o, resolver=lambda n, **k: None, consoles=True)
        self.assertNotIsInstance(res, Candidate)
        self.assertIn("(R72)", res.reason)

    def test_le_generique_ne_lit_pas_access_comme_un_compte(self):
        # Chez un marchand sans grammaire, « … Access (Digital Download) » n'est PAS un signal de
        # compte (Romain : on ne le voit que sur la page) — le classifieur garde son ancre « Access »
        # finale (Kinguin) et rien de plus.
        from src.console_keys import account_signal, classify_console
        url = "https://shop.example/p/onimusha-ps5-access-digital-download"
        self.assertIsNone(account_signal("Onimusha PS5 Access (Digital Download)", url, "Nouveau Marchand"))
        sig = classify_console("Onimusha PS5 Access", url, "Nouveau Marchand")
        self.assertEqual(sig.skip_reason, "console: ACCESS — not a game (R45)")

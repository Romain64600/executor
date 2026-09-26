"""[R18c] « <Jeu> <X> Edition » = le jeu + le DLC X — Romain, 2026-09-26.

« go pour A, et B en attendant » ; « ça sera que pour les jeux + DLC et pas pour les DLC
seuls ». AKS range ces offres sur la page du JEU, dans l'édition « <X> Edition » (lu en direct
le 26/09 : Black Ops 3 « Zombies Chronicles Edition » 22 offres, Blasphemous 2 « Mea Culpa
Edition » 25…), jamais sur la page du DLC seul. R18 les rangeait en DLC(16) sur cette page :
18 écritures fausses. Étape B : refus. Les titres sont ceux des offres réellement écrites."""

import unittest

from src.contracts import NormalizedOffer
from src.matcher import AksResolution, Candidate, SkippedOffer, edition_claim_off_page, match_offer


def _offre(nom):
    return NormalizedOffer(offer_id="1", name=nom, url="https://m.test/x", merchant="Test")


def _page(aks_name, editions=None):
    res = AksResolution(slug="x", url="https://aks/x", product_id="1", aks_name=aks_name,
                        editions=editions if editions is not None else {"16": {"name": "DLC"}},
                        official_platforms=("Steam",))
    return lambda nom, **k: res


class LeJeuPlusDlcNEntrePlusEnDlc(unittest.TestCase):
    def test_mea_culpa_edition_sur_la_page_du_dlc_seul_est_refusee(self):
        res = match_offer(_offre("Blasphemous 2 Mea Culpa Edition - Steam GLOBAL"),
                          _page("Blasphemous 2 Mea Culpa"))
        self.assertIsInstance(res, SkippedOffer)
        self.assertIn("R18c", res.reason)
        self.assertIn("game page", res.reason)

    def test_les_titres_reellement_ecrits_a_tort(self):
        for titre, page in (
            ("Call of Duty: Black Ops III - Zombies Chronicles Edition (Microsoft Store)",
             "Call of Duty Black Ops 3 Zombies Chronicles"),
            ("Conan Exiles Isle of Siptah Edition Digital Download Key (Xbox One/Series X): Europe",
             "Conan Exiles Isle of Siptah Xbox One"),
            ("Lords and Villeins: The Great Houses Edition", "Lords and Villeins The Great Houses"),
            ("Jotunnslayer: Hordes of Hel - Conan Edition", "Jotunnslayer Hordes of Hel Conan"),
            ("Kingdom Two Crowns Norse Lands Edition EU", "Kingdom Two Crowns Norse Lands"),
        ):
            with self.subTest(titre):
                self.assertTrue(edition_claim_off_page(titre, None, page))


class LesDlcSeulsNeBougentPas(unittest.TestCase):
    """« pas pour les DLC seuls » : un DLC dont le NOM porte « Edition » — la page AKS le
    porte aussi —, un « Standard Edition », un titre marqué DLC entrent comme avant."""

    def test_un_dlc_dont_le_nom_porte_edition_entre_en_dlc(self):
        res = match_offer(_offre("Chivalry 2 - Special Edition Content - Steam GLOBAL"),
                          _page("Chivalry 2 Special Edition Content"))
        self.assertIsInstance(res, Candidate, getattr(res, "reason", ""))
        self.assertEqual((res.edition_label, res.edition_id), ("DLC", "16"))

    def test_les_dlc_seuls_reellement_ecrits(self):
        for titre, page in (
            ("Prison Architect - Psych Ward: Warden's Edition Steam Key: Europe & UK",
             "Prison Architect Psych Ward Warden's Edition"),
            ("PC Building Simulator - Overclocked Edition Content",
             "PC Building Simulator Overclocked Edition Content"),
            ("Port Royale 4 Extended Edition Bonus Content (PC) Standard Global",
             "Port Royale 4 Extended Edition Bonus Content"),
            ("Assassins Creed Valhalla Wrath of the Druids Standard Edition",
             "Assassin’s Creed Valhalla Wrath of the Druids"),
            ("FINAL FANTASY XV: EPISODE ARDYN Standard Edition Europe Steam CD Key",
             "FINAL FANTASY XV EPISODE ARDYN"),
        ):
            with self.subTest(titre):
                self.assertFalse(edition_claim_off_page(titre, None, page))

    def test_un_titre_marque_dlc_reste_a_r43(self):
        self.assertFalse(edition_claim_off_page("Neon Beats Moon Edition (DLC)", "DLC", "Neon Beats Moon"))

    def test_un_dlc_cache_sans_edition_entre_toujours(self):
        res = match_offer(_offre("Neon Beats Exoplanets Pack - Steam GLOBAL"),
                          _page("Neon Beats Exoplanets Pack"))
        self.assertIsInstance(res, Candidate, getattr(res, "reason", ""))
        self.assertEqual(res.edition_id, "16")

    def test_hors_page_mono_seau_dlc_rien_ne_change(self):
        # R18 ne s'appliquait pas (Standard à côté) : la règle ne touche que ce que R18 prenait.
        res = match_offer(_offre("Neon Beats Moon Edition - Steam GLOBAL"),
                          _page("Neon Beats", {"1": {"name": "Standard"}, "16": {"name": "DLC"}}))
        self.assertNotIn("R18c", getattr(res, "reason", ""))


if __name__ == "__main__":
    unittest.main()

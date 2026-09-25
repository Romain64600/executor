"""Discover.games (feed store 168) — `[R60]`, 2026-09-25, src/merchants/discover.py.

Romain : « go pour Discover.games », puis « il faut vraiment lire la région sur la page !!! ».
La région vient de la fiche : les pays où chaque déclinaison est vendue
(``sellableProductDetail.skus[].availableCountries``, ``WW`` = monde), selon la règle de Romain
`[R59]`. Les fiches de ``tests/fixtures/discover/`` sont des extraits RÉELS (25/09)."""

import pathlib
import unittest
from unittest import mock

from src.contracts import NormalizedOffer
from src.merchants import discover as d
from src.merchants.registry import merchant_config, merchant_for_store

FIX = pathlib.Path(__file__).resolve().parent / "fixtures" / "discover"
URL = "https://discover.games/games/potion-permit"


def _fiche(nom):
    return (FIX / f"{nom}.html").read_text(encoding="utf-8")


class LaFicheDitPlateformeEtRegion(unittest.TestCase):
    def test_fiches_reelles(self):
        for nom, pays_min in (("ww_otxo", 1), ("monde_potion_permit", 200),
                              ("prix_par_pays_mad_metal", 200)):
            with self.subTest(nom):
                plateforme, pays = d.parse_product(_fiche(nom))
                self.assertEqual(plateforme, "STEAM")
                self.assertGreaterEqual(len(pays), pays_min)
                self.assertEqual(d.region_from_countries(pays), ("global", ""))

    def test_un_produit_sans_declinaison_en_vente_est_refuse(self):
        with self.assertRaises(d.DiscoverProductUnavailable):
            d.parse_product(_fiche("sans_declinaison_automachef"))

    def test_une_page_sans_donnees_produit_est_refusee(self):
        with self.assertRaises(d.DiscoverProductUnavailable):
            d.parse_product("<html><title>Discover.games</title></html>")

    def test_une_fiche_404_est_un_product_not_found(self):
        class R:
            ok, status, body, error = False, 404, "", None
        with self.assertRaises(d.DiscoverProductUnavailable) as ctx:
            d.fetch_product(URL, http_get_fn=lambda *a, **k: R())
        self.assertIn("not found", str(ctx.exception))


class LaRegleDeRomain(unittest.TestCase):
    UE = frozenset(d.EU_MEMBERS)

    def test_table(self):
        for pays, attendu in (
            (frozenset({"WW"}), "global"),
            (self.UE | {"GB", "US", "CA"}, "global"),
            (self.UE | {"GB", "NO"}, "eu"),                         # USA non couverts
            (frozenset({"US", "CA", "GB"}), "us"),                  # UE non couverte
            (frozenset({"JP", "KR"}), None),
            (self.UE | {"US"}, None),                               # UK seul exclu : non tranché
        ):
            with self.subTest(n=len(pays)):
                self.assertEqual(d.region_from_countries(pays)[0], attendu)


class DeBoutEnBout(unittest.TestCase):
    def _match(self, fiche, plateformes=("Steam",)):
        from src.matcher import AksResolution, match_offer
        page = AksResolution(slug="potion-permit", url="https://aks/x", product_id="1",
                             aks_name="Potion Permit", editions={"1": "Standard"},
                             regions={"2": "GLOBAL"}, official_platforms=plateformes)
        offre = NormalizedOffer(offer_id="1", name="Potion Permit", merchant="Discover.games",
                                url=URL, store_id="168")
        with mock.patch.object(d, "fetch_product", side_effect=fiche):
            return match_offer(offre, resolver=lambda n, **k: page)

    def test_steam_global(self):
        from src.matcher import Candidate
        res = self._match(lambda *a, **k: ("STEAM", frozenset({"WW"})))
        self.assertIsInstance(res, Candidate, getattr(res, "reason", ""))
        self.assertEqual((res.platform, res.region_id), ("STEAM", "2"))

    def test_steam_europe(self):
        from src.matcher import Candidate
        res = self._match(lambda *a, **k: ("STEAM", frozenset(d.EU_MEMBERS | {"GB"})))
        self.assertIsInstance(res, Candidate, getattr(res, "reason", ""))
        self.assertEqual(res.region_id, "9")

    def test_produit_introuvable(self):
        from src.matcher import SkippedOffer

        def introuvable(*a, **k):
            raise d.DiscoverProductUnavailable("product not found (404)")
        res = self._match(introuvable)
        self.assertIsInstance(res, SkippedOffer)
        self.assertIn("not found", res.reason)

    def test_plateforme_inconnue(self):
        from src.matcher import SkippedOffer
        res = self._match(lambda *a, **k: ("PLAYSTATION_PLUS", frozenset({"WW"})))
        self.assertIsInstance(res, SkippedOffer)
        self.assertIn("R32", res.reason)


class Registre(unittest.TestCase):
    def test_le_store_168_est_discover(self):
        self.assertEqual(merchant_for_store("168"), "Discover.games")
        self.assertIs(merchant_config("Discover.games"), d.CONFIG)

    def test_pas_encore_en_liste_blanche(self):
        from src.admin.auto_merchants import AUTO_MERCHANTS
        self.assertNotIn("168", {s for _, s in AUTO_MERCHANTS})


if __name__ == "__main__":
    unittest.main()

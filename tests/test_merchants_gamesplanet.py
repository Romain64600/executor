"""Gamesplanet FR (feed store 55) — `[R59]`, 2026-09-25, src/merchants/gamesplanet.py.

Romain : « go pour Gamesplanet FR avec ta règle + un pays UE exclu mais États-Unis autorisés →
US ». Les fiches de ``tests/fixtures/gamesplanet/`` sont des extraits RÉELS de
fr.gamesplanet.com (relevés le 2026-09-25), coupés aux parties utiles."""

import pathlib
import unittest
from unittest import mock

from src.contracts import NormalizedOffer
from src.merchants import gamesplanet as g
from src.merchants.registry import merchant_config, merchant_for_store

FIX = pathlib.Path(__file__).resolve().parent / "fixtures" / "gamesplanet"
URL = "https://fr.gamesplanet.com/game/regulators-steam-key--7963-1"


def _fiche(nom):
    return (FIX / f"{nom}.html").read_text(encoding="utf-8")


class LaPlateformeVientDeLUrl(unittest.TestCase):
    def test_les_livraisons_mappees(self):
        for url, plateforme in (
            (URL, "STEAM"),
            ("https://fr.gamesplanet.com/game/x-gog-key--1-1", "GOG"),
            ("https://fr.gamesplanet.com/game/x-epic-games-key--2-3", "EPIC"),
            ("https://fr.gamesplanet.com/game/minecraft-dungeons-ultimate-dlc-bundle-microsoft-store-download--6883-3",
             "MICROSOFT"),
            ("https://fr.gamesplanet.com/game/x-rockstar-key--9-1", "ROCKSTAR"),
        ):
            self.assertEqual(g.url_platform(url), plateforme, url)
            self.assertIsNone(g.precheck("X", url), url)

    def test_une_livraison_inconnue_est_refusee_par_son_nom(self):
        raison = g.precheck("Guild Wars 2", "https://fr.gamesplanet.com/game/gw2-arenanet-key--5-1")
        self.assertIn("arenanet-key", raison)
        self.assertIn("R59", raison)
        self.assertIn("aucune livraison lisible",
                      g.precheck("X", "https://fr.gamesplanet.com/game/some-game--5-1"))


class LaRegionVientDeLaFiche(unittest.TestCase):
    """Les cinq formes réelles relevées le 2026-09-25 sur 30 fiches."""

    def test_fiches_reelles(self):
        for nom, attendu in (
            ("sans_bloc", ("global", "")),                 # pas de bloc : clé non bridée
            ("not_en_ligne_japon", ("global", "")),        # « NOT activate in: Japan »
            ("not_liste_complete", ("global", "")),        # 83 pays exclus, ni UE ni UK ni US
            ("only_europe", ("eu", "")),                   # liste « ONLY » sans les USA
            ("only_microsoft_europe", ("eu", "")),
        ):
            with self.subTest(nom):
                self.assertEqual(g.region_from_lock(g.parse_region_lock(_fiche(nom))), attendu)

    def test_la_liste_complete_est_lue_dans_la_fenetre_pas_dans_le_texte_voisin(self):
        mode, pays = g.parse_region_lock(_fiche("not_liste_complete"))
        self.assertEqual((mode, len(pays)), ("NOT", 83))
        self.assertIn("afghanistan", pays)

    def test_une_page_qui_nest_pas_une_fiche_leve(self):
        with self.assertRaises(g.GamesplanetPageUnreadable):
            g.parse_region_lock("<html><body>Maintenance</body></html>")

    def test_un_bloc_present_mais_illisible_leve_au_lieu_de_donner_global(self):
        casse = _fiche("not_en_ligne_japon").replace("</strong>", "")
        with self.assertRaises(g.GamesplanetPageUnreadable):
            g.parse_region_lock(casse)


class LaRegleDeRomain(unittest.TestCase):
    """Les pays EXCLUS décident ; pour une liste ONLY, les exclus sont les absents."""

    UE = sorted(g.EU_MEMBERS)

    def test_table(self):
        for lock, attendu in (
            (("NOT", frozenset({"china"})), "global"),
            (("NOT", frozenset({"united states"})), "eu"),
            (("NOT", frozenset({"france"})), "us"),              # ajout de Romain
            (("NOT", frozenset({"france", "united states"})), None),
            (("NOT", frozenset({"united kingdom"})), None),        # cas non tranché → refus
            (("ONLY", frozenset(self.UE + ["united kingdom", "united states"])), "global"),
            (("ONLY", frozenset(self.UE + ["united kingdom", "norway"])), "eu"),
            (("ONLY", frozenset({"united states", "canada"})), "us"),
            (("ONLY", frozenset({"japan"})), None),
        ):
            with self.subTest(lock=lock[0], n=len(lock[1])):
                self.assertEqual(g.region_from_lock(lock)[0], attendu)

    def test_un_refus_porte_un_libelle(self):
        base, libelle = g.region_from_lock(("NOT", frozenset({"germany", "united states"})))
        self.assertIsNone(base)
        self.assertIn("GAMESPLANET", libelle)

    def test_les_orthographes_du_site_sont_reconnues(self):
        self.assertEqual(g._country("United Kingdom of Great Britain and Northern Ireland"),
                         "united kingdom")
        self.assertEqual(g._country("United States of America"), "united states")
        self.assertEqual(g._country(" Czech Republic "), "czechia")


class DeBoutEnBout(unittest.TestCase):
    def _match(self, region, plateformes=("Steam",), url=URL):
        from src.matcher import AksResolution, match_offer
        page = AksResolution(slug="regulators", url="https://aks/x", product_id="1",
                             aks_name="Regulators", editions={"1": "Standard"},
                             regions={"2": "GLOBAL"}, official_platforms=plateformes)
        offre = NormalizedOffer(offer_id="1", name="Regulators", merchant="Gamesplanet FR",
                                url=url, store_id="55")
        with mock.patch.object(g, "fetch_region", return_value=region):
            return match_offer(offre, resolver=lambda n, **k: page)

    def test_global_eu_us(self):
        from src.matcher import Candidate
        for region, attendu in ((("global", ""), "2"), (("eu", ""), "9"), (("us", ""), "8")):
            res = self._match(region)
            self.assertIsInstance(res, Candidate, getattr(res, "reason", ""))
            self.assertEqual((res.platform, res.region_id), ("STEAM", attendu))

    def test_un_verrou_devient_un_refus_de_region(self):
        from src.matcher import SkippedOffer
        res = self._match((None, "GAMESPLANET LOCK (EU + US)"))
        self.assertIsInstance(res, SkippedOffer)
        self.assertIn("forbidden region", res.reason)

    def test_une_page_illisible_est_un_refus(self):
        from src.matcher import AksResolution, SkippedOffer, match_offer
        page = AksResolution(slug="regulators", url="https://aks/x", product_id="1",
                             aks_name="Regulators", editions={"1": "Standard"},
                             regions={"2": "GLOBAL"}, official_platforms=("Steam",))
        offre = NormalizedOffer(offer_id="1", name="Regulators", merchant="Gamesplanet FR",
                                url=URL, store_id="55")
        with mock.patch.object(g, "fetch_region",
                               side_effect=g.GamesplanetPageUnreadable("503")):
            res = match_offer(offre, resolver=lambda n, **k: page)
        self.assertIsInstance(res, SkippedOffer)
        self.assertIn("R32", res.reason)

    def test_la_page_aks_doit_vendre_la_plateforme_de_lurl(self):
        from src.matcher import SkippedOffer
        res = self._match(("global", ""), plateformes=("Epic Store",))
        self.assertIsInstance(res, SkippedOffer)
        self.assertIn("R20", res.reason)


class Registre(unittest.TestCase):
    def test_le_store_55_est_gamesplanet_fr(self):
        self.assertEqual(merchant_for_store("55"), "Gamesplanet FR")
        self.assertIs(merchant_config("Gamesplanet FR"), g.CONFIG)

    def test_en_liste_blanche_dans_le_groupe_a(self):
        """Romain, 2026-09-25 : « go liste blanche, groupe A »."""

        from src.admin.auto_merchants import AUTO_MERCHANTS
        from src.merchant_groups import GROUPS
        self.assertIn(("Gamesplanet FR", "55"), AUTO_MERCHANTS)
        self.assertEqual([k for k, noms in GROUPS.items() if "Gamesplanet FR" in noms], ["A"])


if __name__ == "__main__":
    unittest.main()

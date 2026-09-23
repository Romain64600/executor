"""Deux règles DLC du 2026-09-23, et l'audit qui a fixé leur portée.

Romain : « expansion veut dire DLC, non ? » puis « tu peux pas faire comme pour les autres
marchands, et si on a déjà des offres DLC on ajoute en DLC ? » — et avant d'écrire quoi que
ce soit : « audit pour voir si on ferait pas mieux d'ajouter ces comportements à tous les
marchands ».

L'audit a tranché dans les deux sens, et ces tests épinglent ce partage :

* `[R55b]` « Expansion - … » = DLC reste **à GOG**. Sur 88 titres « Expansion » de 13
  marchands, AKS vend certaines extensions en ÉDITIONS (Diablo IV Vessel of Hatred {DLC,
  Deluxe, Ultimate}) ; un marqueur générique les forcerait en DLC(16).
* `[R57]` le DLC reconnu par sa page ET celle de son jeu parent est **générique**. Sur
  ~17 000 offres de tous les marchands, 19 récupérées (GOG 15, K4G 4), toutes des DLC.
"""

import datetime
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import src.matcher as M  # noqa: E402
from src.aks_sitemap import SitemapIndex  # noqa: E402
from src.contracts import NormalizedOffer  # noqa: E402
from src.matcher import AksResolution, Candidate, SkippedOffer, match_offer, own_page_slugs  # noqa: E402


def _index(entries):
    return SitemapIndex(entries=frozenset(entries), incomplete=False,
                        fetched_at=datetime.datetime.now(datetime.timezone.utc)
                        .strftime("%Y-%m-%dT%H:%M:%SZ"))


def _page(slug, aks_name, editions, regions=None):
    return AksResolution(
        slug=slug, url=f"https://www.allkeyshop.com/blog/buy-{slug}-cd-key-compare-prices/",
        product_id="1", aks_name=aks_name, editions=editions,
        regions=regions or {"6": "GOG GLOBAL", "2": "STEAM GLOBAL", "9": "STEAM EU"},
        official_platforms=("Steam", "GoG"))


def _match(offer, page, vus=None):
    def resolver(nom, **k):
        if vus is not None:
            vus.append(nom)
        return page
    return match_offer(offer, resolver=resolver, page_resolver=lambda u: page, consoles=True)


def _gog(nom, slug="x"):
    return NormalizedOffer(offer_id="1", name=nom, url=f"https://www.gog.com/en/game/{slug}",
                           merchant="GOG", store_id="34")


class ExpansionEstUnDLCChezGOG(unittest.TestCase):
    """`[R55b]` — mesuré le 2026-09-23 : 14 des 16 titres « Expansion - » de GOG ont leur page,
    13 de ces pages portent un autre seau que le DLC, et deux un Standard."""

    def setUp(self):
        M.set_sitemap_index(None)
        self.addCleanup(M._SITEMAP_CACHE.clear)

    def test_le_prefixe_est_retire_avant_de_chercher_la_page(self):
        vus = []
        page = _page("crusader-kings-2-holy-fury", "Crusader Kings II: Holy Fury",
                     {"16": "DLC", "501": "Royal Collection", "502": "Imperial Collection"})
        res = _match(_gog("Expansion - Crusader Kings II: Holy Fury"), page, vus)
        self.assertTrue(vus and "Expansion" not in vus[0], f"nom cherché : {vus}")
        self.assertIsInstance(res, Candidate, getattr(res, "reason", ""))
        self.assertEqual((res.edition_label, res.edition_id), ("DLC", "16"))

    def test_meme_avec_un_Standard_egare_sur_la_page_cest_un_DLC(self):
        """Jade Dragon et The Old Gods : leur page porte un Standard. Sans marqueur, la ligne
        y serait rangée en Standard — c'est tout l'intérêt de lire « Expansion » comme un
        marqueur plutôt que de retirer le préfixe."""

        page = _page("crusader-kings-2-jade-dragon", "Crusader Kings II: Jade Dragon",
                     {"16": "DLC", "1": "Standard", "501": "Royal Collection"})
        res = _match(_gog("Expansion - Crusader Kings II: Jade Dragon"), page)
        self.assertIsInstance(res, Candidate, getattr(res, "reason", ""))
        self.assertEqual(res.edition_id, "16")

    def test_une_page_sans_seau_DLC_reste_un_refus(self):
        page = _page("crusader-kings-2-holy-fury", "Crusader Kings II: Holy Fury",
                     {"1": "Standard", "7": "Deluxe"})
        res = _match(_gog("Expansion - Crusader Kings II: Holy Fury"), page)
        self.assertIsInstance(res, SkippedOffer)
        self.assertIn("R43", res.reason)

    def test_la_page_du_jeu_de_base_nest_pas_celle_du_DLC(self):
        page = _page("crusader-kings-2", "Crusader Kings II",
                     {"16": "DLC", "1": "Standard"})
        res = _match(_gog("Expansion - Crusader Kings II: Holy Fury"), page)
        self.assertIsInstance(res, SkippedOffer)

    def test_le_mot_au_milieu_du_nom_nest_pas_le_prefixe(self):
        from src.merchants import gog
        self.assertIsNone(gog.dlc_marker("Talisman - The City Expansion"))
        self.assertEqual(gog.dlc_marker("Expansion - Europa Universalis IV: Emperor"),
                         "EXPANSION")
        self.assertEqual(gog.guard_name("Expansion - Europa Universalis IV: Emperor"),
                         "Europa Universalis IV: Emperor")

    def test_le_marqueur_nest_PAS_generique(self):
        """L'audit : Diablo IV Vessel of Hatred est vendu {DLC, Deluxe, Ultimate}. Chez un
        autre marchand, « Expansion » ne change rien au chemin d'avant."""

        self.assertIsNone(M.dlc_title_marker("Diablo IV: Vessel of Hatred Expansion"))
        autre = NormalizedOffer(offer_id="1", name="Expansion - Crusader Kings II: Holy Fury",
                                url="https://www.kinguin.net/x", merchant="Kinguin")
        self.assertIsNone(M.title_dlc_marker(autre, M.merchant_config("Kinguin")))


class LeDLCSeReconnaitASaPageEtACelleDeSonJeu(unittest.TestCase):
    """`[R57]` — générique, et gardé par quatre conditions réunies."""

    TITRE = "Talisman - The Cataclysm Expansion Europe Steam CD Key"

    def setUp(self):
        self.propre = own_page_slugs(self.TITRE)[0]
        M.set_sitemap_index(_index([f"{self.propre}-cd-key", "talisman-cd-key"]))
        self.addCleanup(M._SITEMAP_CACHE.clear)

    def _k4g(self, titre=None):
        return NormalizedOffer(offer_id="1", name=titre or self.TITRE,
                               url="https://k4g.com/fr/produit/talisman-cataclysm",
                               merchant="K4G", store_id="92")

    def test_un_DLC_sans_marqueur_entre_en_DLC(self):
        page = _page(self.propre, "Talisman - The Cataclysm Expansion", {"16": "DLC", "8": "Bundle"})
        res = _match(self._k4g(), page)
        self.assertIsInstance(res, Candidate, getattr(res, "reason", ""))
        self.assertEqual((res.edition_label, res.edition_id), ("DLC", "16"))

    def test_un_Standard_sur_la_page_garde_le_cas_Vice_City(self):
        """La page du jeu de base « Grand Theft Auto Vice City » portait un seau DLC à côté
        du Standard ; le jeu est entré en DLC le 17/09. Là où un Standard existe, un titre
        qui se lit « Standard » y est rangé, comme avant."""

        page = _page(self.propre, "Talisman - The Cataclysm Expansion",
                     {"16": "DLC", "1": "Standard", "8": "Bundle"})
        res = _match(self._k4g(), page)
        self.assertIsInstance(res, Candidate)
        self.assertEqual(res.edition_id, "1")

    def test_sans_page_parent_la_ligne_reste_refusee(self):
        M.set_sitemap_index(_index([f"{self.propre}-cd-key"]))
        page = _page(self.propre, "Talisman - The Cataclysm Expansion", {"16": "DLC", "8": "Bundle"})
        res = _match(self._k4g(), page)
        self.assertIsInstance(res, SkippedOffer)

    def test_sans_index_sitemap_la_branche_reste_fermee(self):
        M.set_sitemap_index(None)
        page = _page(self.propre, "Talisman - The Cataclysm Expansion", {"16": "DLC", "8": "Bundle"})
        res = _match(self._k4g(), page)
        self.assertIsInstance(res, SkippedOffer)

    def test_un_jeu_sans_sous_titre_nest_jamais_un_derive(self):
        """« Chernobylite » : pas de tête de titre, donc pas de jeu parent — un jeu de base
        dont la page vendrait {DLC, Deluxe} n'est pas rangé en DLC."""

        titre = "Chernobylite Europe Steam CD Key"
        propre = own_page_slugs(titre)[0]
        M.set_sitemap_index(_index([f"{propre}-cd-key"]))
        page = _page(propre, "Chernobylite", {"16": "DLC", "7": "Deluxe"})
        res = _match(self._k4g(titre), page)
        self.assertFalse(isinstance(res, Candidate) and res.edition_id == "16",
                         getattr(res, "reason", ""))

    def test_un_titre_qui_annonce_une_edition_nest_pas_concerne(self):
        self.assertFalse(M.derived_dlc_page(
            "Talisman - The Cataclysm Deluxe Edition", "7", None,
            _page(self.propre, "Talisman - The Cataclysm Expansion", {"16": "DLC", "8": "Bundle"})))

    def test_une_page_qui_nest_pas_la_sienne_nest_pas_concernee(self):
        self.assertFalse(M.derived_dlc_page(
            self.TITRE, "1", None,
            _page("talisman", "Talisman", {"16": "DLC", "8": "Bundle"})))


class LesQuatreConditionsTiennentChacuneSeule(unittest.TestCase):
    """Chaque condition de `[R57]` doit refuser SEULE, toutes les autres étant réunies. Sans
    ça, une condition masquée par sa voisine peut disparaître sans qu'aucun test ne rougisse
    — c'est ce que la vérification par mutation a montré sur les premiers tests."""

    def setUp(self):
        self.addCleanup(M._SITEMAP_CACHE.clear)

    def test_page_propre_une_page_soeur_nest_pas_la_sienne(self):
        """Résolue sur la page d'un AUTRE DLC du même jeu, avec un parent qui existe : seule
        la condition « page propre » peut refuser."""

        M.set_sitemap_index(_index(["talisman-the-dragon-cd-key", "talisman-cd-key"]))
        soeur = _page("talisman-the-dragon", "Talisman - The Dragon", {"16": "DLC", "8": "Bundle"})
        self.assertFalse(M.derived_dlc_page("Talisman - The Cataclysm", "1", None, soeur))

    def test_mot_dedition_tout_le_reste_etant_reuni(self):
        titre = "Talisman - The Cataclysm Deluxe Edition"
        propre = own_page_slugs(titre)[0]
        M.set_sitemap_index(_index([f"{propre}-cd-key", "talisman-cd-key"]))
        page = _page(propre, titre, {"16": "DLC", "8": "Bundle"})
        self.assertTrue(M.derived_dlc_page(titre, "1", None, page),
                        "témoin : lu Standard, la règle s'applique")
        self.assertFalse(M.derived_dlc_page(titre, "7", None, page),
                         "lu Deluxe, la règle ne s'applique pas")

    def test_sans_sous_titre_aucune_variante_du_nom_ne_tient_lieu_de_parent(self):
        """« Crusader Kings II » n'a pas de sous-titre. Si AKS publiait aussi une page à la
        variante numérique `crusader-kings-2`, elle ne doit pas passer pour un jeu parent."""

        M.set_sitemap_index(_index(["crusader-kings-ii-cd-key", "crusader-kings-2-cd-key"]))
        page = _page("crusader-kings-ii", "Crusader Kings II", {"16": "DLC", "8": "Bundle"})
        self.assertFalse(M.derived_dlc_page("Crusader Kings II", "1", None, page))


if __name__ == "__main__":
    unittest.main()

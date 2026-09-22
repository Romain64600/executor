"""GOG.com — la boutique de premier rang (`[R55]`, 2026-09-22).

Romain : « pour GOG, on peut prendre le titre en complément d'information. »

Ce que ces tests protègent, c'est exactement cette nuance. Le titre GOG sert à l'ÉDITION, aux
marqueurs DLC et au refus des démos. Il ne sert JAMAIS à la plateforme ni à la région — parce
que les mots qui y ressemblent sont des noms de jeux : « Two Worlds **Epic** Edition »,
« Strategic Command WWII: War in **Europe** », « Tiny Troopers: **Global** Ops ». Mesuré sur
les 3 473 lignes de l'audit : lire la plateforme dans le titre donne 3 472 erreurs sur 3 473.
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.contracts import NormalizedOffer  # noqa: E402
from src.matcher import AksResolution, Candidate, SkippedOffer, match_offer  # noqa: E402
from src.merchants import gog  # noqa: E402
from src.merchants.registry import merchant_config, merchant_for_store  # noqa: E402


def _page(aks_name, editions=None, regions=None, platforms=("Steam", "GOG"), slug="x"):
    return AksResolution(
        slug=slug,
        url=f"https://www.allkeyshop.com/blog/buy-{slug}-cd-key-compare-prices/",
        product_id="1", aks_name=aks_name,
        editions=editions or {"1": "Standard"},
        regions=regions or {"6": "GOG GLOBAL", "2": "GLOBAL", "9": "STEAM EU"},
        official_platforms=platforms)


def _match(nom, slug, page):
    offre = NormalizedOffer(offer_id="1", name=nom,
                            url=f"https://www.gog.com/en/game/{slug}",
                            merchant="GOG", store_id="34")
    return match_offer(offre, resolver=lambda n, **k: page,
                       page_resolver=lambda u: page, consoles=True)


class LeMarchandEstEnregistre(unittest.TestCase):
    def test_la_config_et_le_store_se_retrouvent(self):
        cfg = merchant_config("GOG")
        self.assertIsNotNone(cfg, "GOG doit avoir son fichier marchand")
        self.assertEqual(cfg.domain, "gog.com")
        self.assertEqual(merchant_for_store("34"), "GOG")

    def test_il_est_sur_la_liste_blanche_avec_son_store(self):
        from src.admin.auto_merchants import is_allowed
        self.assertTrue(is_allowed("GOG", "34"))
        self.assertFalse(is_allowed("GOG", "58"), "un store qui ne colle pas est refusé")


class LaPlateformeVientDuDomaineJamaisDuTitre(unittest.TestCase):
    """Le cœur de `[R55]`. `[R51]` refuse d'INFÉRER la plateforme d'un titre nu depuis la
    page AKS — cette porte reste fermée. Ici la plateforme est DÉCLARÉE par le vendeur :
    gog.com ne vend que du GOG. Ce n'est pas le même mécanisme."""

    def test_un_titre_nu_entre_en_GOG_au_lieu_detre_refuse_par_R51(self):
        res = _match("The Mummy Demastered", "the_mummy_demastered",
                     _page("The Mummy Demastered"))
        self.assertIsInstance(res, Candidate)
        self.assertEqual(res.platform, "GOG")

    def test_Epic_dans_le_NOM_du_jeu_ne_fait_pas_une_cle_Epic(self):
        """« Two Worlds Epic Edition », « Epic Map Pack », « Epic Pinball » : six lignes du
        corpus. Sans `title_is_platform_source=False` elles partiraient en EPIC.

        On n'exige pas que chaque ligne ENTRE — les règles générales (R43 sur les DLC, les
        bundles) continuent de s'appliquer et c'est très bien. On exige que la PLATEFORME ne
        soit jamais lue dans le nom du jeu : entrée, elle est GOG ; refusée, ce n'est jamais
        pour une histoire de plateforme."""

        for nom, seaux in (
                ("Two Worlds Epic Edition Complete", {"1": "Standard", "91": "Complete"}),
                ("Ashes of the Singularity: Escalation - Epic Map Pack DLC",
                 {"1": "Standard", "16": "DLC"}),
                ("Epic Pinball: The Complete Collection", {"1": "Standard"})):
            with self.subTest(titre=nom):
                res = _match(nom, "x", _page(nom, seaux))
                if isinstance(res, Candidate):
                    self.assertEqual(res.platform, "GOG")
                else:
                    # Refusée par une règle générale (R43 sur les DLC) — jamais par la
                    # plateforme, qui est le seul point que ce test surveille.
                    self.assertNotIn("platform", res.reason.lower(),
                                     "le refus ne doit pas venir d'une plateforme devinée")

    def test_Steam_dans_le_NOM_du_jeu_non_plus(self):
        nom = "Detective Girl of the Steam City UNRATED"
        res = _match(nom, "detective_girl_of_the_steam_city_unrated", _page(nom))
        self.assertIsInstance(res, Candidate, getattr(res, "reason", ""))
        self.assertEqual(res.platform, "GOG")

    def test_une_URL_qui_nest_pas_gog_ne_declare_rien(self):
        self.assertIsNone(gog.url_platform("https://www.kinguin.net/x"))
        self.assertEqual(gog.url_platform("https://www.gog.com/en/game/hades"), "GOG")


class LaRegionEstUnFaitSurLaBoutique(unittest.TestCase):
    """Un jeu sans DRM n'a pas de verrou régional : AKS le range en seau 6 (GOG GLOBAL), dix
    fois sur dix sur les pages observées le 2026-09-22."""

    def test_le_seau_est_toujours_GOG_GLOBAL(self):
        res = _match("Hades", "hades", _page("Hades"))
        self.assertIsInstance(res, Candidate)
        self.assertEqual(res.region_id, "6")

    def test_Europe_dans_le_NOM_du_jeu_ne_fait_pas_une_region_Europe(self):
        """Douze titres du corpus contiennent Europe / US / UK / Global. Douze sont des noms
        de jeux. Le crochet répond « global » AVANT que le scan générique ne les voie."""

        for nom in ("Strategic Command WWII: War in Europe",
                    "Construction Simulator 2 US - Pocket Edition",
                    "Medieval Lords: Soldier Kings of Europe",
                    "Tiny Troopers: Global Ops"):
            with self.subTest(titre=nom):
                res = _match(nom, "x", _page(nom, {"1": "Standard", "7": "Deluxe"}))
                self.assertIsInstance(res, Candidate, getattr(res, "reason", ""))
                self.assertEqual(res.region_id, "6", f"{nom} ne doit pas partir en EU/US")

    def test_un_BUNDLE_reste_refuse_comme_partout_ailleurs(self):
        """« Tiny Troopers: Global Ops - Digital Deluxe **Bundle** » : la règle générale ne
        bouge pas pour GOG. On n'entre jamais de bundle, et « Global » n'y change rien."""

        res = _match("Tiny Troopers: Global Ops - Digital Deluxe Bundle", "x",
                     _page("Tiny Troopers: Global Ops", {"1": "Standard", "7": "Deluxe"}))
        self.assertIsInstance(res, SkippedOffer)
        self.assertIn("BUNDLE", res.reason)

    def test_le_crochet_repond_toujours_global(self):
        self.assertEqual(gog.title_region("n'importe quoi"), "global")


class LeTitreSertVraimentAQuelqueChose(unittest.TestCase):
    """« Complément d'information », ce sont ces trois usages — et eux seuls."""

    def test_ledition_est_lue_dans_le_titre(self):
        res = _match("Two Worlds Epic Edition Complete", "x",
                     _page("Two Worlds Epic Edition Complete",
                           {"1": "Standard", "91": "Complete"}))
        self.assertIsInstance(res, Candidate)
        self.assertEqual(res.edition_id, "91", "l'édition du titre doit être retenue")

    def test_une_demo_est_refusee_par_le_titre_ou_par_lURL(self):
        """142 lignes sur 3 473. Un produit gratuit n'a pas de prix à comparer."""

        for nom, slug in (("Dex Demo", "dex_demo"),
                          ("Gently Packed Demo", "gently_packed_demo"),
                          ("Defend the Rook", "defend_the_rook_tactical_tower_defense_demo")):
            with self.subTest(titre=nom):
                res = _match(nom, slug, _page(nom))
                self.assertIsInstance(res, SkippedOffer)
                self.assertIn("demo", res.reason.lower())

    def test_un_jeu_dont_le_nom_contient_demo_nest_PAS_une_demo(self):
        """Le mot est ancré sur ses frontières : « Demolition Company » et « Democracy 3 »
        ne doivent pas partir avec les démos."""

        for nom in ("Demolition Company", "Democracy 3", "Demonologist"):
            with self.subTest(titre=nom):
                self.assertIsNone(gog.precheck(nom, "https://www.gog.com/en/game/x"), nom)


if __name__ == "__main__":
    unittest.main()

"""[R18c] étape A — « <Jeu> <X> Edition » entre sur la page du JEU, dans l'édition « <X> Edition ».

Romain, 2026-09-26 : « go pour A, et B en attendant » ; « ça sera que pour les jeux + DLC et pas
pour les DLC seuls » ; « faut pas se fier au prix. Si t'as des doutes, faut pouvoir ouvrir la
page. Si tu trouves les infos sur la page, OK. Si t'arrives pas à ouvrir la page, tu ne trouves
pas les infos sur la page, tu skip. »

Les titres sont ceux des offres réellement écrites à tort en DLC(16) ; les éditions des pages du
jeu sont celles relevées en lecture seule le 26/09 (Blasphemous 2 « Mea Culpa Edition » 5738,
Call of Duty Black Ops 3 « Zombies Chronicles Edition » 329, Conan Exiles « Isle of Siptah
Edition » 629). La page parente est trouvée par l'index sitemap (préfixe publié le plus long),
lue par le résolveur de page : rien n'est deviné, aucun prix n'est lu."""

import unittest

import src.matcher as M
from src.aks_sitemap import SitemapIndex
from src.contracts import NormalizedOffer
from src.matcher import AksProbeUnreliable, AksResolution, Candidate, SkippedOffer, match_offer

AKS = "https://www.allkeyshop.com/blog/"


def _url(slug, kind="cd-key"):
    return f"{AKS}buy-{slug}-{kind}-compare-prices/"


def _page(name, pid, slug, editions, kind="cd-key", platforms=("Steam",), tabs=()):
    return AksResolution(slug=slug, url=_url(slug, kind), product_id=pid, aks_name=name,
                         editions=editions, official_platforms=tuple(platforms),
                         console_pages={k: _url(slug, k) for k in tabs})


DLC = {"16": {"name": "DLC"}}
BLASPHEMOUS_2 = {"1": {"name": "Standard"}, "5738": {"name": "Mea Culpa Edition"},
                 "7": {"name": "Deluxe"}, "91": {"name": "Complete"}, "8": {"name": "Bundle"}}
BLACK_OPS_3 = {"329": {"name": "Zombies Chronicles Edition"}, "4": {"name": "Limited"},
               "1": {"name": "Standard"}, "32": {"name": "Uncut"},
               "3369": {"name": "Zombie Chronicles Deluxe"}, "7": {"name": "Deluxe"},
               "2394": {"name": "Zombie Deluxe Edition"}}


class _Base(unittest.TestCase):
    def setUp(self):
        self._saved = list(M._SITEMAP_CACHE)
        self.addCleanup(lambda: (M._SITEMAP_CACHE.clear(), M._SITEMAP_CACHE.extend(self._saved)))

    def _sitemap(self, entries):
        M.set_sitemap_index(SitemapIndex(entries=frozenset(entries),
                                         fetched_at="2099-01-01T00:00:00Z", incomplete=False))

    def _match(self, title, dlc_page, pages, merchant="Test", url="https://m.test/x", consoles=False,
               anchors=None):
        by_url = {p.url: p for p in pages}
        anchors = anchors or {}
        self.fetched = []

        def page_resolver(u):
            self.fetched.append(u)
            got = by_url.get(u)
            if isinstance(got, _Raise):
                raise got.exc
            return got

        def resolver(name, **kw):
            return anchors.get(kw["page_kind"]) if "page_kind" in kw else dlc_page

        offre = NormalizedOffer(offer_id="1", name=title, url=url, merchant=merchant)
        return match_offer(offre, resolver, page_resolver=page_resolver, consoles=consoles)


class LEditionEntreSurLaPageDuJeu(_Base):
    def test_mea_culpa_edition_entre_sur_blasphemous_2_edition_5738(self):
        self._sitemap({"blasphemous-2-cd-key", "blasphemous-2-mea-culpa-cd-key"})
        res = self._match("Blasphemous 2 Mea Culpa Edition PC Steam CD Key",
                          _page("Blasphemous 2 Mea Culpa", "900", "blasphemous-2-mea-culpa", DLC),
                          [_page("Blasphemous 2", "100", "blasphemous-2", BLASPHEMOUS_2)])
        self.assertIsInstance(res, Candidate, getattr(res, "reason", ""))
        self.assertEqual((res.aks_product_id, res.aks_name), ("100", "Blasphemous 2"))
        self.assertEqual((res.edition_id, res.edition_label), ("5738", "Mea Culpa Edition"))
        self.assertEqual((res.platform, res.region_id), ("STEAM", "2"))

    def test_zombies_chronicles_edition_entre_en_329_jamais_dans_le_palier_deluxe(self):
        self._sitemap({"call-of-duty-black-ops-3-cd-key",
                       "call-of-duty-black-ops-3-zombies-chronicles-cd-key"})
        res = self._match("Call of Duty: Black Ops III - Zombies Chronicles Edition (PC) Steam Key GLOBAL",
                          _page("Call of Duty Black Ops 3 Zombies Chronicles", "48908",
                                "call-of-duty-black-ops-3-zombies-chronicles", DLC),
                          [_page("Call of Duty Black Ops 3", "6064", "call-of-duty-black-ops-3", BLACK_OPS_3)])
        self.assertIsInstance(res, Candidate, getattr(res, "reason", ""))
        self.assertEqual((res.aks_product_id, res.edition_id), ("6064", "329"))

    def test_la_page_parente_est_le_plus_long_prefixe_publie(self):
        self._sitemap({"blasphemous-cd-key", "blasphemous-2-cd-key", "blasphemous-2-mea-culpa-cd-key"})
        self._match("Blasphemous 2 Mea Culpa Edition PC Steam CD Key",
                    _page("Blasphemous 2 Mea Culpa", "900", "blasphemous-2-mea-culpa", DLC),
                    [_page("Blasphemous 2", "100", "blasphemous-2", BLASPHEMOUS_2)])
        self.assertEqual(self.fetched, [_url("blasphemous-2")])


class LeDouteSeRefuse(_Base):
    """« si tu ne trouves pas les infos sur la page, tu skip » — jamais Standard, jamais DLC."""

    TITRE = "Blasphemous 2 Mea Culpa Edition PC Steam CD Key"
    DLC_PAGE = _page("Blasphemous 2 Mea Culpa", "900", "blasphemous-2-mea-culpa", DLC)

    def _refus(self, res):
        self.assertIsInstance(res, SkippedOffer)
        self.assertIn("R18c", res.reason)
        return res.reason

    def test_la_page_du_jeu_sans_edition_de_ce_nom(self):
        self._sitemap({"blasphemous-2-cd-key"})
        sans = {"1": {"name": "Standard"}, "7": {"name": "Deluxe"}}
        raison = self._refus(self._match(self.TITRE, self.DLC_PAGE,
                                         [_page("Blasphemous 2", "100", "blasphemous-2", sans)]))
        self.assertIn("different/expanded product", raison)

    def test_une_page_du_jeu_qui_ne_vend_que_le_dlc(self):
        self._sitemap({"blasphemous-2-cd-key"})
        raison = self._refus(self._match(self.TITRE, self.DLC_PAGE,
                                         [_page("Blasphemous 2", "100", "blasphemous-2", DLC)]))
        self.assertNotIn("Candidate", raison)

    def test_pas_de_page_parente_publiee(self):
        self._sitemap({"blasphemous-2-mea-culpa-cd-key"})
        raison = self._refus(self._match(self.TITRE, self.DLC_PAGE, []))
        self.assertIn("no AKS product page", raison)
        self.assertEqual(self.fetched, [])

    def test_sans_index_sitemap_rien_n_est_devine(self):
        M.set_sitemap_index(None)
        raison = self._refus(self._match(self.TITRE, self.DLC_PAGE,
                                         [_page("Blasphemous 2", "100", "blasphemous-2", BLASPHEMOUS_2)]))
        self.assertIn("no fresh sitemap index", raison)
        self.assertEqual(self.fetched, [])

    def test_une_page_du_jeu_illisible(self):
        self._sitemap({"blasphemous-2-cd-key"})
        page = _page("Blasphemous 2", "100", "blasphemous-2", BLASPHEMOUS_2)
        by_url = [page]
        res = self._match(self.TITRE, self.DLC_PAGE, by_url)
        self.assertIsInstance(res, Candidate)              # témoin : lisible → entre
        cassee = AksProbeUnreliable("blasphemous-2 -> 503", status=503, slug="blasphemous-2")
        self.assertIn("unreliable", self._refus(self._match(
            self.TITRE, self.DLC_PAGE, [_Raise(page.url, cassee)])))

    def test_jamais_standard_par_defaut_sur_la_page_du_jeu(self):
        # Une page parente dont le nom contient déjà tous les mots du titre : aucun mot ne
        # nomme une édition. Sans la garde de l'étape A, `detect_edition` rendrait Standard.
        self._sitemap({"blasphemous-2-cd-key"})
        raison = self._refus(self._match(self.TITRE, self.DLC_PAGE, [_page(
            "Blasphemous 2 Mea Culpa", "100", "blasphemous-2", {"1": {"name": "Standard"}})]))
        self.assertIn("never Standard or DLC", raison)

    def test_jamais_dlc_sur_la_page_du_jeu(self):
        self._sitemap({"blasphemous-2-cd-key"})
        raison = self._refus(self._match(self.TITRE, self.DLC_PAGE, [_page(
            "Blasphemous 2 Mea Culpa", "100", "blasphemous-2", DLC)]))
        self.assertIn("never Standard or DLC", raison)

    def test_un_palier_du_titre_absent_de_l_edition_nommee(self):
        # « … Zombies Chronicles Deluxe Edition » : les mots nomment 329 mais le titre ajoute
        # DELUXE — jamais une édition plus petite que ce que le marchand vend (R39).
        self._sitemap({"call-of-duty-black-ops-3-cd-key"})
        titre = "Call of Duty: Black Ops III - Zombies Chronicles Deluxe Edition (PC) Steam Key GLOBAL"
        dlc = _page("Call of Duty Black Ops 3 Zombies Chronicles Deluxe", "48908",
                    "call-of-duty-black-ops-3-zombies-chronicles", DLC)
        res = self._match(titre, dlc, [_page("Call of Duty Black Ops 3", "6064",
                                               "call-of-duty-black-ops-3", BLACK_OPS_3)])
        self.assertNotIsInstance(res, Candidate)


class _Raise:
    """Une « page » qui lève à la lecture (réponse AKS douteuse)."""

    def __init__(self, url, exc):
        self.url, self.exc = url, exc


class LesDlcSeulsNeSontPasRoutes(_Base):
    def test_un_dlc_dont_le_nom_porte_edition_reste_sur_sa_page_en_dlc(self):
        self._sitemap({"chivalry-2-cd-key", "chivalry-2-special-edition-content-cd-key"})
        res = self._match("Chivalry 2 - Special Edition Content - Steam GLOBAL",
                          _page("Chivalry 2 Special Edition Content", "700",
                                "chivalry-2-special-edition-content", DLC),
                          [_page("Chivalry 2", "70", "chivalry-2", {"1": {"name": "Standard"},
                                                                     "99": {"name": "Special"}})])
        self.assertIsInstance(res, Candidate, getattr(res, "reason", ""))
        self.assertEqual((res.aks_product_id, res.edition_id), ("700", "16"))
        self.assertEqual(self.fetched, [])


ALASKAN_URL = "https://www.mmoga.com/Steam-Games/Alaskan-Road-Truckers-Mother-Truckers-Edition.html?ref=615"


class LesPagesDlcAPlusieursSeaux(_Base):
    """Romain, 2026-09-26 : « Route-les aussi vers la page du jeu si le jeu est inclus (jeu +
    DLC) ». La page DLC résolue a PLUSIEURS seaux mais aucun Standard, et l'édition du titre n'y
    est pas vendue : on route. Éditions relevées en lecture seule le 26/09."""

    def test_alaskan_road_truckers_mother_truckers_edition(self):
        self._sitemap({"alaskan-road-truckers-cd-key", "alaskan-road-truckers-mother-truckers-cd-key"})
        res = self._match("Alaskan Road Truckers - Mother Truckers Edition",
                          _page("Alaskan Road Truckers Mother Truckers", "900",
                                "alaskan-road-truckers-mother-truckers",
                                {"16": {"name": "DLC"}, "8": {"name": "Bundle"}}),
                          [_page("Alaskan Road Truckers", "100", "alaskan-road-truckers",
                                 {"1": {"name": "Standard"}, "3760": {"name": "Mother Truckers Edition"},
                                  "3761": {"name": "Highway Edition"}})],
                          merchant="MMOGA", url=ALASKAN_URL)
        self.assertIsInstance(res, Candidate, getattr(res, "reason", ""))
        self.assertEqual((res.aks_product_id, res.edition_id), ("100", "3760"))

    def test_deceive_inc_black_tie_edition_steam_et_epic(self):
        self._sitemap({"deceive-inc-cd-key", "deceive-inc-black-tie-cd-key"})
        plats = ("Steam", "Epic Store")
        dlc = _page("Deceive Inc. Black Tie", "900", "deceive-inc-black-tie",
                    {"16": {"name": "DLC"}, "99": {"name": "Special"}}, platforms=plats)
        jeu = _page("Deceive Inc.", "100", "deceive-inc",
                    {"1": {"name": "Standard"}, "2690": {"name": "Black Tie Edition"},
                     "10": {"name": "Ultimate"}}, platforms=plats)
        for titre, url, plateforme in (
                ("Deceive Inc. - Black Tie Edition (Steam Key)",
                 "https://www.mmoga.com/Steam-Games/Deceive-Inc-Black-Tie-Edition-Steam-Key.html?ref=615",
                 "STEAM"),
                ("Deceive Inc. - Black Tie Edition (Epic Games Store Key)",
                 "https://www.mmoga.com/Epic-Store-Games/Deceive-Inc-Black-Tie-Edition-Epic-Games-Store-Key"
                 ".html?ref=615", "EPIC")):
            with self.subTest(titre):
                res = self._match(titre, dlc, [jeu], merchant="MMOGA", url=url)
                self.assertIsInstance(res, Candidate, getattr(res, "reason", ""))
                self.assertEqual((res.aks_product_id, res.edition_id, res.platform),
                                 ("100", "2690", plateforme))

    def test_kingdom_two_crowns_norse_lands_edition(self):
        # La page DLC porte elle-même un seau « Norse Lands Edition » ; le titre ne le NOMME
        # pas (tous ses mots sont dans le nom de la page) : on route vers le jeu, 1558.
        self._sitemap({"kingdom-two-crowns-cd-key", "kingdom-two-crowns-norse-lands-cd-key"})
        res = self._match("Kingdom Two Crowns Norse Lands Edition EU",
                          _page("Kingdom Two Crowns Norse Lands", "900", "kingdom-two-crowns-norse-lands",
                                {"16": {"name": "DLC"}, "1559": {"name": "Norse Lands Edition"}}),
                          [_page("Kingdom Two Crowns", "100", "kingdom-two-crowns",
                                 {"1": {"name": "Standard"}, "1558": {"name": "Norse Lands Edition"},
                                  "1560": {"name": "Jarl Edition"}})],
                          merchant="Gamivo", url="https://www.gamivo.com/product/kingdom-two-crowns-pc-steam-eu-norse-lands")
        self.assertIsInstance(res, Candidate, getattr(res, "reason", ""))
        self.assertEqual((res.aks_product_id, res.edition_id, res.region_id), ("100", "1558", "9"))

    def test_une_page_dlc_qui_vend_le_palier_du_titre_garde_le_chemin_normal(self):
        # « EPISODE ARDYN Complete Edition » sur la page de l'épisode {DLC, Complete} : c'est le
        # palier de CE produit, vendu là. Aucune page du jeu n'est lue.
        self._sitemap({"final-fantasy-xv-cd-key", "final-fantasy-xv-episode-ardyn-cd-key"})
        res = self._match("FINAL FANTASY XV: EPISODE ARDYN Complete Edition Europe Steam CD Key",
                          _page("FINAL FANTASY XV EPISODE ARDYN", "900", "final-fantasy-xv-episode-ardyn",
                                {"16": {"name": "DLC"}, "91": {"name": "Complete"}}),
                          [_page("Final Fantasy XV", "100", "final-fantasy-xv", {"1": {"name": "Standard"}})],
                          merchant="K4G",
                          url="https://k4g.com/product/final-fantasy-xv-episode-ardyn-steam-europe-instant-cd-key-"
                              "complete-edition-cd-key-RQIZ5JH1")
        self.assertIsInstance(res, Candidate, getattr(res, "reason", ""))
        self.assertEqual((res.aks_product_id, res.edition_id), ("900", "91"))
        self.assertEqual(self.fetched, [])

    def test_une_page_qui_vend_standard_n_est_jamais_routee(self):
        self._sitemap({"blasphemous-2-cd-key", "blasphemous-2-mea-culpa-cd-key"})
        res = self._match("Blasphemous 2 Mea Culpa Edition PC Steam CD Key",
                          _page("Blasphemous 2 Mea Culpa", "900", "blasphemous-2-mea-culpa",
                                {"1": {"name": "Standard"}, "16": {"name": "DLC"}}),
                          [_page("Blasphemous 2", "100", "blasphemous-2", BLASPHEMOUS_2)])
        self.assertNotIn("R18c", getattr(res, "reason", ""))
        self.assertEqual(self.fetched, [])

    def test_sans_edition_de_ce_nom_sur_la_page_du_jeu_refus(self):
        self._sitemap({"alaskan-road-truckers-cd-key"})
        res = self._match("Alaskan Road Truckers - Mother Truckers Edition",
                          _page("Alaskan Road Truckers Mother Truckers", "900",
                                "alaskan-road-truckers-mother-truckers",
                                {"16": {"name": "DLC"}, "8": {"name": "Bundle"}}),
                          [_page("Alaskan Road Truckers", "100", "alaskan-road-truckers",
                                 {"1": {"name": "Standard"}, "3761": {"name": "Highway Edition"}})],
                          merchant="MMOGA", url=ALASKAN_URL)
        self.assertIsInstance(res, SkippedOffer)
        self.assertIn("R18c", res.reason)


class LesMotsDuNomDuJeuSurLaPageDuJeu(_Base):
    """« Mother Truckers Edition » : TRUCKERS est un mot du NOM DU JEU (« Alaskan Road
    Truckers »), pas un palier. Toléré en résidu sur la page du jeu, dans la route R18c
    SEULEMENT — ailleurs rien ne change."""

    EDITIONS = {"1": {"name": "Standard"}, "3760": {"name": "Mother Truckers Edition"},
                "3761": {"name": "Highway Edition"}}

    def test_la_fonction_sans_identite_est_inchangee(self):
        self.assertIsNone(M.match_extras_to_page_edition(["MOTHER"], self.EDITIONS))
        self.assertEqual(M.match_extras_to_page_edition(["MOTHER"], self.EDITIONS, "Alaskan Road Truckers"),
                         ("3760", "Mother Truckers Edition"))

    def test_un_palier_du_nom_du_jeu_n_est_jamais_tolere(self):
        # « Ultimate Admiral » : ULTIMATE est dans le nom du jeu, mais c'est un mot de palier —
        # il ne devient pas du bruit, l'édition « Ultimate Dreadnought » n'est pas adoptée.
        eds = {"1": {"name": "Standard"}, "77": {"name": "Ultimate Dreadnought"}}
        self.assertIsNone(M.match_extras_to_page_edition(["DREADNOUGHT"], eds, "Ultimate Admiral"))

    def test_hors_de_la_route_r18c_le_titre_reste_refuse_sur_la_page_du_jeu(self):
        self._sitemap({"alaskan-road-truckers-cd-key"})
        res = self._match("Alaskan Road Truckers - Mother Truckers Edition",
                          _page("Alaskan Road Truckers", "100", "alaskan-road-truckers", self.EDITIONS),
                          [], merchant="MMOGA", url=ALASKAN_URL)
        self.assertIsInstance(res, SkippedOffer)
        self.assertIn("extra words", res.reason)


class LeCheminConsole(_Base):
    """Conan Exiles « Isle of Siptah Edition » — trois écritures CJS fausses la nuit du 25-26/09."""

    def test_isle_of_siptah_edition_entre_sur_les_pages_xbox_du_jeu_en_629(self):
        self._sitemap({"conan-exiles-cd-key", "conan-exiles-xbox-one", "conan-exiles-xbox-series",
                       "conan-exiles-isle-of-siptah-cd-key", "conan-exiles-isle-of-siptah-xbox-one"})
        siptah = {"1": {"name": "Standard"}, "629": {"name": "Isle of Siptah Edition"},
                  "91": {"name": "Complete"}}
        dlc_pc = _page("Conan Exiles Isle of Siptah", "900", "conan-exiles-isle-of-siptah", DLC,
                       tabs=("xbox-one",))
        pages = [
            _page("Conan Exiles Isle of Siptah Xbox One", "901", "conan-exiles-isle-of-siptah", DLC,
                  kind="xbox-one", platforms=()),
            _page("Conan Exiles", "100", "conan-exiles", {"1": {"name": "Standard"}},
                  tabs=("xbox-one",)),
            _page("Conan Exiles Xbox One", "629100", "conan-exiles", siptah, kind="xbox-one",
                  platforms=()),
        ]
        res = self._match("Conan Exiles Isle of Siptah Edition Digital Download Key (Xbox One): Europe",
                          dlc_pc, pages, merchant="CJS-CDKeys",
                          url="https://www.cjs-cdkeys.com/products/Conan-Exiles-Isle-of-Siptah-Edition-"
                              "Digital-Download-Key-%28Xbox-One%29-Europe.html",
                          consoles=True)
        self.assertIsInstance(res, Candidate, getattr(res, "reason", ""))
        self.assertEqual([(t.platform, t.aks_product_id, t.edition_id) for t in res.targets],
                         [("XBOX_ONE", "629100", "629")])


if __name__ == "__main__":
    unittest.main()

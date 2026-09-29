"""[R66] La recherche catalogue AKS en dernier recours du résolveur — Romain, 2026-09-29 :
« La recherche AKS en dernier recours me semble indispensable » (audit « pas de page produit »
du 28/09, proposition 11).

Tout passe par le VRAI chemin (`resolve_aks`, `match_offer`, `match_feed`, `03_match`) avec un
faux GET qui ne sert que :
  * des réponses RÉELLES de l'API catalogue (`tests/fixtures/aks_search_r66/api_*.json`, lues
    en AKS/Staff le 2026-09-29 sur `v2-1-250304`) ;
  * des pages AKS RÉELLES réduites aux blocs que le matcher lit (même dossier, et
    `pages_r64_r65/` pour Marvel's Midnight Suns).
Toute autre URL répond 404. Les titres sont ceux de la population de l'audit (refus « no AKS
product page found »). Les cas où une réponse est FABRIQUÉE (API cassée, 5xx, 429, version
retirée, produit « account » à lien de clé) le disent dans leur docstring. Aucune requête réseau.
"""

import functools
import importlib.util
import json
import socket
import sys
import tempfile
import time
import unittest
import unittest.mock
from pathlib import Path
from urllib.parse import unquote

import src.matcher as M
from src import aks_env, aks_search
from src.aks_env import HttpProbeResult
from src.aks_search import AksCatalogSearch, CatalogProduct
from src.aks_sitemap import SitemapIndex
from src.contracts import NormalizedFeed, NormalizedOffer
from src.matcher import (
    AksNameUnreadable, AksProbeUnreliable, AksThrottled, Candidate, SkippedOffer, match_feed,
    match_offer, resolve_aks, resolve_aks_url,
)

FIX = Path(__file__).resolve().parent / "fixtures" / "aks_search_r66"
FIX64 = Path(__file__).resolve().parent / "fixtures" / "pages_r64_r65"
AKS = "https://www.allkeyshop.com/blog/"


def _url(slug_kind):
    return f"{AKS}buy-{slug_kind}-compare-prices/"


def _api(name):
    raw = json.loads((FIX / f"api_{name}.json").read_text(encoding="utf-8"))
    return raw["query"], raw["body"]


def _pages():
    pages = {_url(p.stem): p.read_text(encoding="utf-8") for p in FIX.glob("*.html")}
    for p in FIX64.glob("*.html"):
        pages.setdefault(_url(p.stem), p.read_text(encoding="utf-8"))
    return pages


def _products(name):
    return aks_search.parse_response(_api(name)[1])


class _Base(unittest.TestCase):
    """Un faux AKS : l'API répond avec la réponse réelle enregistrée pour la requête EXACTE,
    sinon « aucun produit » ; les pages réelles des fixtures ; tout le reste 404."""

    def setUp(self):
        def _no_network(*_a, **_kw):
            raise AssertionError("requête réseau pendant un test [R66]")
        for target in (unittest.mock.patch.object(socket.socket, "connect", _no_network),
                       unittest.mock.patch.object(socket, "create_connection", _no_network)):
            target.start()
            self.addCleanup(target.stop)
        saved = list(M._SITEMAP_CACHE)
        self.addCleanup(lambda: (M._SITEMAP_CACHE.clear(), M._SITEMAP_CACHE.extend(saved)))
        M.set_sitemap_index(None)
        self.addCleanup(M.set_aks_search, None)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cache_path = str(Path(self.tmp.name) / "state" / "aks_search_cache.json")
        self.pages = _pages()
        self.api = {}                  # requête → corps JSON réel
        for f in FIX.glob("api_*.json"):
            q, body = _api(f.stem[4:])
            self.api[q] = body
        self.api_override = None       # (status, body) fabriqué pour un test d'échec
        self.asked = []
        self.api_asked = []
        self.uas = []
        self.now = [1_800_000_000.0]

    def session(self, **kw):
        kw.setdefault("cache_path", self.cache_path)
        kw.setdefault("now", lambda: self.now[0])
        kw.setdefault("sleep", lambda s: None)
        s = AksCatalogSearch(**kw)
        M.set_aks_search(s)
        return s

    def get(self, url, timeout=8, user_agent=None, **_kw):
        self.uas.append(user_agent)
        if "vakrs_catalogv2.php" in url:
            self.api_asked.append(url)
            if self.api_override is not None:
                status, body = self.api_override
                return HttpProbeResult(url=url, ok=status == 200, status=status, body=body)
            if f"/api/{aks_search.API_VERSION}/" not in url:
                return HttpProbeResult(url=url, ok=False, status=404, body="")
            q = unquote(url.split("search_name=", 1)[1].split("&", 1)[0])
            body = self.api.get(q, '{"products":[],"pagination":{"total":0,"per_page":24,'
                                   '"pagenum":1,"total_pages":0,"took":1},"facets":{}}')
            return HttpProbeResult(url=url, ok=True, status=200, body=body)
        self.asked.append(url)
        body = self.pages.get(url)
        if body:
            return HttpProbeResult(url=url, ok=True, status=200, body=body)
        return HttpProbeResult(url=url, ok=False, status=404, body="")

    def match(self, merchant, title, url="https://merchant.example/offer", store_id=None):
        resolver = functools.partial(resolve_aks, http_get_fn=self.get)
        page_resolver = functools.partial(resolve_aks_url, http_get_fn=self.get)
        offer = NormalizedOffer(offer_id="1", name=title, url=url, merchant=merchant,
                                store_id=store_id)
        return match_offer(offer, resolver, M.resolve_difmark_offer, resolver,
                           page_resolver=page_resolver, consoles=True)


# ─────────────────────────── l'adresse et la version ─────────────────────────────────────
class LAdresseEstCelleDuSite(unittest.TestCase):
    def test_la_constante_est_l_apiurl_que_le_site_embarque(self):
        """Preuve : la page de recherche du site (/blog/products/, relue le 29/09) embarque
        cette adresse pour son propre front. Changer la constante sans relire → rouge."""

        extrait = (FIX / "products_page_apiurl_excerpt.txt").read_text(encoding="utf-8")
        self.assertIn(f'"apiUrl":"{aks_search.API_URL.format(version=aks_search.API_VERSION)}"',
                      extrait)
        self.assertIn(f"/api/{aks_search.API_VERSION}/vakrs_catalogv2.php?action=CatalogV2"
                      "&locale=en&currency=EUR&price_mode=price_card&search_name=", extrait)

    def test_la_requete_est_celle_du_front_reduite_a_quatre_champs(self):
        url = aks_search.api_url("Heroes of Might and Magic: Olden Era")
        self.assertTrue(url.startswith("https://www.allkeyshop.com/api/v2-1-250304/"))
        self.assertIn("search_name=Heroes%20of%20Might%20and%20Magic%3A%20Olden%20Era", url)
        self.assertTrue(url.endswith("&fields=id,name,link,type"))

    def test_une_reponse_reelle_se_lit(self):
        prods = _products("olden_era")
        self.assertEqual([(p.id, p.type) for p in prods], [(176433, "game"), (211500, "account")])


# ─────────────────────────── le filtre des candidats ─────────────────────────────────────
class LesCandidats(unittest.TestCase):
    def test_grammaire_seules_les_pages_cle_pc(self):
        """Réponse réelle « Grand Theft Auto V » (24 produits : consoles, comptes, pages
        -key, ancienne forme) : seules les pages clé PC sont des candidats possibles."""

        verdicts = {p.link: M.catalog_page(p.link) for p in _products("gta_v")}
        self.assertEqual(verdicts[_url("gta-5-cd-key")], ("gta-5", _url("gta-5-cd-key")))
        for link, parsed in verdicts.items():
            if parsed is None:
                continue
            self.assertRegex(link, r"-(cd-key|key|game-code|download-code)-compare-prices/$|"
                                   r"compare-and-buy-cd-key-for-digital-download-")
        refuses = [link for link, parsed in verdicts.items() if parsed is None]
        self.assertTrue(any("-ps5-compare-prices" in l for l in refuses))
        self.assertTrue(any("-account-compare-prices" in l for l in refuses))

    def test_grammaire_le_plus_long_gabarit_gagne(self):
        for link in (_url("ea-sports-madden-nfl-27-xbox-series-key"), _url("destiny-2-ps4-game-code"),
                     _url("destiny-2-xbox-one-code"), _url("nhl-27-xbox-key"),
                     _url("heroes-of-might-magic-olden-era-steam-account"),
                     _url("wwe-2k26-nintendo-switch-2-key")):
            with self.subTest(link):
                self.assertIsNone(M.catalog_page(link), "une page console / compte n'est jamais "
                                                        "un candidat clé PC")
        self.assertEqual(M.catalog_page(_url("the-green-light-key")),
                         ("the-green-light", _url("the-green-light-key")))
        legacy = f"{AKS}compare-and-buy-cd-key-for-digital-download-guild-wars-2/"
        self.assertEqual(M.catalog_page(legacy), ("guild-wars-2", legacy))

    def test_grammaire_formes_inconnues_jamais_lues(self):
        """Formes vivantes hors grammaire relevées par l'audit (§4.4) : jamais lues."""

        for link in (f"{AKS}buy-sims-3-cd-key-digital-download-best-price/",
                     f"{AKS}buy-jurassic-world-evolution-2-dominion-biosyn-cd-key-compare-prices-2/",
                     _url("gta-5-cd-key") + "?x=1", "https://evil.example/blog/buy-gta-5-cd-key-compare-prices/",
                     _url("GTA-5-cd-key"), f"{AKS}buy-sonic-the-hedgehog-4-episode-i-xbox-360/",
                     f"{AKS}buy--cd-key-compare-prices/"):
            with self.subTest(link):
                self.assertIsNone(M.catalog_page(link))

    def test_le_remplissage_de_popularite_tombe(self):
        """Réponse réelle pour « WinZip 12 for Mac Pro Version » : Windows 11 Pro, Minecraft,
        Baldur's Gate 3… — le remplissage de popularité. Aucun n'est un candidat."""

        self.assertEqual(M.catalog_candidates(_products("winzip_filler"),
                                              "WinZip 12 for Mac Pro Version"), [])

    def test_le_compte_n_est_jamais_candidat(self):
        """Réponse réelle Olden Era : la page clé est candidate, le compte Steam non."""

        self.assertEqual(
            M.catalog_candidates(_products("olden_era"), "Heroes of Might and Magic: Olden Era"),
            [("heroes-of-might-magic-olden-era", _url("heroes-of-might-magic-olden-era-cd-key"),
              "Heroes of Might & Magic Olden Era")])

    def test_un_nom_fait_de_bruit_n_est_pas_candidat(self):
        """Titre réel GOG « Two Worlds Epic Edition Complete » ; produit FABRIQUÉ « Complete
        Edition » (que des mots de bruit) : il passerait le côté requis de R01 sans rien dire
        du produit — jamais un candidat."""

        prod = CatalogProduct(id=1, name="Complete Edition", type="game",
                              link=_url("complete-edition-cd-key"))
        self.assertEqual(M.catalog_candidates([prod], "Two Worlds Epic Edition Complete"), [])

    def test_le_type_account_suffit_a_ecarter(self):
        """Produit FABRIQUÉ : un type « account » dont le lien aurait la forme d'une page clé."""

        prod = CatalogProduct(id=1, name="Olden Era", type="account",
                              link=_url("olden-era-cd-key"))
        self.assertEqual(M.catalog_candidates([prod], "Olden Era"), [])

    def test_le_plus_precis_d_abord(self):
        """Réponse réelle (Wyrel, « LEGO STAR WARS The Force Awakens Jabba's Palace Character
        Pack ») : l'API range « Jabba's Palace Character Pack » d'abord ; le nom le plus long
        passe devant."""

        cands = M.catalog_candidates(
            _products("lego_jabba"), "LEGO STAR WARS The Force Awakens Jabba's Palace Character Pack")
        self.assertEqual([c[0] for c in cands],
                         ["lego-star-wars-the-force-awakens-jabbas-palace", "jabbas-palace-character-pack"])

    def test_au_plus_trois(self):
        prods = [CatalogProduct(id=i, name="Guild Wars 2", type="game",
                                link=_url(f"guild-wars-2-{i}-cd-key")) for i in range(6)]
        self.assertEqual(len(M.catalog_candidates(prods, "Guild Wars 2 Complete Collection")), 3)

    def test_mots_restants(self):
        self.assertEqual(M.catalog_leftover("The Elder Scrolls Online Collection Necrom",
                                            "The Elder Scrolls Online Necrom"), "COLLECTION")
        self.assertEqual(M.catalog_leftover("Heroes of Might and Magic: Olden Era",
                                            "Heroes of Might & Magic Olden Era"), "",
                         "les mots-outils absents du nom AKS ne comptent pas")
        self.assertEqual(M.catalog_leftover("Marvel's Midnight Suns Digital+ Edition",
                                            "Marvel’s Midnight Suns"), "DIGITAL EDITION")


# ─────────────────────────── le résolveur ─────────────────────────────────────────────────
class LeResolveur(_Base):
    def test_trouve_la_page_que_les_slugs_ratent_et_la_marque(self):
        s = self.session()
        res = resolve_aks("The Elder Scrolls Online Collection Necrom", self.get)
        self.assertEqual(res.url, _url("the-elder-scrolls-online-necrom-cd-key"))
        self.assertEqual((res.found_by, res.catalog_leftover), ("catalogue", "COLLECTION"))
        self.assertEqual(len(self.api_asked), 1)
        self.assertEqual((s.stats["requests"], s.stats["hits"], s.stats["resolved"]), (1, 1, 1))

    def test_avec_un_index_frais_la_recherche_part_quand_meme(self):
        """Avant [R66] : index frais → None avant toute recherche (audit §4.4, « R30 n'est
        jamais appelée en production »). L'index n'est pas exhaustif : la recherche part."""

        M.set_sitemap_index(SitemapIndex(entries=frozenset({"un-autre-jeu-cd-key"}),
                                         fetched_at="2099-01-01T00:00:00Z", incomplete=False,
                                         legacy=frozenset(), legacy_indexed=True))
        self.session()
        res = resolve_aks("The Elder Scrolls Online Collection Necrom", self.get)
        self.assertIsNotNone(res)
        self.assertEqual(len(self.api_asked), 1)

    def test_sans_session_le_comportement_d_avant(self):
        M.set_sitemap_index(SitemapIndex(entries=frozenset({"un-autre-jeu-cd-key"}),
                                         fetched_at="2099-01-01T00:00:00Z", incomplete=False,
                                         legacy=frozenset(), legacy_indexed=True))
        self.assertIsNone(resolve_aks("The Elder Scrolls Online Collection Necrom", self.get))
        self.assertEqual(self.api_asked, [])

    def test_agent_aks_staff_toujours(self):
        self.session()
        resolve_aks("The Elder Scrolls Online Collection Necrom", self.get)
        self.assertTrue(self.uas)
        self.assertEqual(set(self.uas), {aks_env.AKS_STAFF_UA})

    def test_aucun_resultat(self):
        s = self.session()
        self.assertIsNone(resolve_aks("Aura Farming", self.get))
        self.assertEqual((s.stats["queries"], s.stats["empty"]), (1, 1))

    def test_pas_de_recherche_pour_une_page_compte(self):
        self.session()
        self.assertIsNone(resolve_aks("Aura Farming", self.get, page_kind="steam-account"))
        self.assertEqual(self.api_asked, [])

    def test_une_url_deja_demandee_n_est_pas_relue(self):
        """La page du jeu, déjà sondée par le rang 1 (404 simulé ici), n'est pas redemandée
        quand la recherche la propose : même question, même réponse."""

        self.session()
        del self.pages[_url("the-elder-scrolls-online-necrom-cd-key")]
        self.api["The Elder Scrolls Online Necrom"] = self.api[
            "The Elder Scrolls Online Collection Necrom"]
        self.assertIsNone(resolve_aks("The Elder Scrolls Online Necrom", self.get))
        self.assertEqual(self.asked.count(_url("the-elder-scrolls-online-necrom-cd-key")), 1)

    def test_ma1_une_page_candidate_douteuse_leve(self):
        """Page candidate en 503 (FABRIQUÉ) : lève tout de suite, jamais le candidat suivant."""

        self.session()
        page = _url("the-elder-scrolls-online-necrom-cd-key")
        base_get = self.get

        def get(url, **kw):
            if url == page:
                self.asked.append(url)
                return HttpProbeResult(url=url, ok=False, status=503, body="")
            return base_get(url, **kw)
        with self.assertRaises(AksProbeUnreliable) as ctx:
            resolve_aks("The Elder Scrolls Online Collection Necrom", get)
        self.assertEqual(ctx.exception.slug, "the-elder-scrolls-online-necrom")

    def test_nom_illisible_leve(self):
        self.session()
        self.pages[_url("the-elder-scrolls-online-necrom-cd-key")] = (
            '<html><div data-product-id="123"></div></html>')
        with self.assertRaises(AksNameUnreadable):
            resolve_aks("The Elder Scrolls Online Collection Necrom", self.get)


# ─────────────────────────── budget, cache, durée de vie ──────────────────────────────────
class BudgetEtCache(_Base):
    def test_budget_epuise_plus_aucune_requete(self):
        s = self.session(budget=1)
        self.assertIsNotNone(resolve_aks("The Elder Scrolls Online Collection Necrom", self.get))
        self.assertIsNone(resolve_aks("Aura Farming", self.get))
        self.assertEqual(len(self.api_asked), 1)
        self.assertEqual((s.used, s.stats["budget_exhausted_offers"]), (1, 1))

    def test_budget_du_balayage_deja_depense(self):
        s = self.session(budget=10, used=10)
        self.assertIsNone(resolve_aks("Aura Farming", self.get))
        self.assertEqual(self.api_asked, [])
        self.assertEqual(s.meta()["used_before"], 10)

    def test_le_cache_evite_la_seconde_requete_et_survit_au_processus(self):
        s = self.session()
        resolve_aks("The Elder Scrolls Online Collection Necrom", self.get)
        resolve_aks("The Elder Scrolls Online Collection Necrom", self.get)
        self.assertEqual(len(self.api_asked), 1)
        self.assertEqual(s.stats["cache_hits"], 1)
        self.assertEqual(s.flush(), 1)
        s2 = self.session()                       # un autre processus : relit le fichier
        res = resolve_aks("The Elder Scrolls Online Collection Necrom", self.get)
        self.assertIsNotNone(res)
        self.assertEqual(len(self.api_asked), 1, "servi par le cache persistant")
        self.assertEqual(s2.stats["cache_hits"], 1)

    def test_les_reponses_vides_sont_gardees(self):
        s = self.session()
        resolve_aks("Aura Farming", self.get)
        s.flush()
        self.session()
        resolve_aks("Aura Farming", self.get)
        self.assertEqual(len(self.api_asked), 1)

    def test_duree_de_vie(self):
        s = self.session()
        resolve_aks("Aura Farming", self.get)
        s.flush()
        self.now[0] += aks_search.CACHE_TTL_S - 1
        self.session()
        resolve_aks("Aura Farming", self.get)
        self.assertEqual(len(self.api_asked), 1, "encore frais")
        self.now[0] += 2
        self.session()
        resolve_aks("Aura Farming", self.get)
        self.assertEqual(len(self.api_asked), 2, "périmé : ré-interrogé")

    def test_une_erreur_n_est_jamais_gardee(self):
        """503 FABRIQUÉ (l'audit en a vu deux : « Backend fetch failed ») : une reprise, puis
        une erreur qui ne se cache pas — la ligne suivante re-demande."""

        s = self.session()
        self.api_override = (503, "Backend fetch failed")
        with self.assertRaises(AksProbeUnreliable):
            resolve_aks("Aura Farming", self.get)
        self.assertEqual(len(self.api_asked), 2, "une seule reprise")
        self.api_override = None
        self.assertIsNone(resolve_aks("Aura Farming", self.get))
        self.assertEqual(len(self.api_asked), 3)
        self.assertEqual(s.stats["failures"], 1)

    def test_la_cle_porte_la_version_et_le_filtre(self):
        k = aks_search.cache_key("cd-key", "  Aura   Farming ", 1)
        self.assertEqual(k, f"{aks_search.API_VERSION}|f1|cd-key|aura farming")
        self.assertNotEqual(k, aks_search.cache_key("cd-key", "Aura Farming", 2))
        self.assertNotEqual(k, aks_search.cache_key("steam-account", "Aura Farming", 1))

    def test_fusion_avec_un_autre_ecrivain(self):
        s1 = self.session()
        resolve_aks("Aura Farming", self.get)
        s2 = AksCatalogSearch(cache_path=self.cache_path, now=lambda: self.now[0])
        M.set_aks_search(s2)
        resolve_aks("The Elder Scrolls Online Collection Necrom", self.get)
        s2.flush()
        s1.flush()
        raw = json.loads(Path(self.cache_path).read_text())
        self.assertEqual(len(raw["entries"]), 2, "aucun écrivain n'efface l'autre")

    def test_cache_illisible_cache_vide(self):
        Path(self.cache_path).parent.mkdir(parents=True)
        Path(self.cache_path).write_text("{pas du json")
        self.session()
        self.assertIsNone(resolve_aks("Aura Farming", self.get))
        self.assertEqual(len(self.api_asked), 1)

    def test_etat_du_balayage(self):
        path = Path(self.tmp.name) / "aks_search.json"
        self.assertEqual(aks_search.load_sweep_state(str(path), 1000), (0, ""))
        path.write_text("garbage")
        self.assertEqual(aks_search.load_sweep_state(str(path), 1000), (1000, ""),
                         "un compteur illisible = budget épuisé, jamais 1 000 requêtes de plus")
        s = self.session(budget=1000, used=7)
        resolve_aks("Aura Farming", self.get)
        aks_search.save_sweep_state(str(path), s)
        self.assertEqual(aks_search.load_sweep_state(str(path), 1000), (8, ""))


# ─────────────────────────── API changée, disjoncteur, throttle ──────────────────────────
class APIChangeeEtDisjoncteur(_Base):
    def test_version_retiree_refus_nomme_et_coupure(self):
        """Ce qu'une version retirée répond VRAIMENT (vérifié le 29/09 sur v2-1-000000) :
        404, corps vide. Refus nommé, recherche coupée pour la suite — jamais devinée."""

        s = self.session()
        self.api_override = (404, "")
        with self.assertRaises(AksProbeUnreliable) as ctx:
            resolve_aks("Aura Farming", self.get)
        self.assertIn("API changed", str(ctx.exception))
        self.assertIn("never guessed (R66)", str(ctx.exception))
        self.assertEqual(ctx.exception.slug, M.SEARCH_SLUG_KEY)
        self.assertIn("v2-1-250304", s.disabled_reason)
        self.assertIsNone(resolve_aks("Heroes of Might and Magic: Olden Era", self.get))
        self.assertEqual(len(self.api_asked), 1, "coupée : plus aucune requête")
        self.assertEqual(s.stats["disabled_offers"], 1)

    def test_reponse_qui_n_est_plus_du_json(self):
        """Corps HTML en 200 (FABRIQUÉ) : l'API ne répond plus comme on la lit → coupure."""

        s = self.session()
        self.api_override = (200, "<!doctype html><html>maintenance</html>")
        with self.assertRaises(AksProbeUnreliable):
            resolve_aks("Aura Farming", self.get)
        self.assertTrue(s.disabled_reason)

    def test_forme_json_inattendue(self):
        for body in ('{"items":[]}', '{"products":{},"pagination":{"total":0}}',
                     '{"products":[]}', '{"products":[],"pagination":[]}',
                     '{"products":[{"name":"x"}],"pagination":{"total":1}}', "[]",
                     '{"products":[],"pagination":{"total":"0"}}'):
            with self.subTest(body):
                with self.assertRaises(aks_search.AksSearchChanged):
                    aks_search.parse_response(body)

    def test_la_coupure_suit_le_balayage(self):
        s = self.session(disabled_reason="v2-1-250304 : HTTP 404, version d'API introuvable")
        self.assertIsNone(resolve_aks("The Elder Scrolls Online Collection Necrom", self.get))
        self.assertEqual(self.api_asked, [])
        s.flush()

    def test_la_coupure_sert_encore_le_cache(self):
        s = self.session()
        resolve_aks("The Elder Scrolls Online Collection Necrom", self.get)
        s.flush()
        self.session(disabled_reason="v2-1-250304 : HTTP 404")
        self.assertIsNotNone(resolve_aks("The Elder Scrolls Online Collection Necrom", self.get))
        self.assertEqual(len(self.api_asked), 1)

    def test_disjoncteur_ouvert_cache_seulement(self):
        s = self.session()
        self.assertIsNone(resolve_aks("Aura Farming", self.get, search=False))
        self.assertEqual(self.api_asked, [])
        self.assertEqual(s.stats["search_off_offers"], 1)

    def test_trois_echecs_ouvrent_le_disjoncteur_r30(self):
        """503 FABRIQUÉS : le disjoncteur R30 compte les échecs de la recherche catalogue ;
        après trois, plus aucune requête vers l'API pour le reste du match."""

        self.session()
        self.api_override = (503, "")
        feed = NormalizedFeed(run_id="r", merchant="Test", fetched_at="t", offers=tuple(
            NormalizedOffer(offer_id=str(i), name=f"Obscure Title {i} - Steam GLOBAL",
                            url="https://merchant.example/x", merchant="Test")
            for i in range(M.SEARCH_CIRCUIT_BREAKER_FAILURES + 3)))
        stats = {}
        _c, skipped = match_feed(feed, lambda name, **kw: resolve_aks(name, self.get, **kw),
                                 stats=stats)
        self.assertEqual(stats["search_failures"], M.SEARCH_CIRCUIT_BREAKER_FAILURES)
        self.assertEqual(len(self.api_asked), 2 * M.SEARCH_CIRCUIT_BREAKER_FAILURES,
                         "une reprise par titre, puis le disjoncteur")
        self.assertEqual(stats["search_circuit_open_offers"], 3)
        self.assertEqual(sum(1 for s in skipped if s.reason.startswith("AKS probe unreliable")),
                         M.SEARCH_CIRCUIT_BREAKER_FAILURES)

    def test_un_429_arrete_le_match(self):
        """429 FABRIQUÉ sur l'API : AKS pousse — AksThrottled, le match s'arrête."""

        self.session()
        self.api_override = (429, "")
        feed = NormalizedFeed(run_id="r", merchant="Test", fetched_at="t", offers=(
            NormalizedOffer(offer_id="1", name="Aura Farming PC Steam CD Key",
                            url="https://www.kinguin.net/category/555404/aura-farming-pc-steam-cd-key",
                            merchant="Kinguin", store_id="58"),))
        with self.assertRaises(AksThrottled):
            match_feed(feed, lambda name, **kw: resolve_aks(name, self.get, **kw))
        self.assertEqual(len(self.api_asked), 1, "jamais de reprise sur un 429")


# ─────────────────────────── les gardes décident ─────────────────────────────────────────
class LesGardesDecident(_Base):
    def test_driffle_eso_collection_necrom_entre_sous_le_seau_nomme(self):
        """Rejeu du 29/09 : la seule ligne « nom non dérivable » qui entre. Le titre nomme
        « Collection », la page le vend (98) : les mots restants sont NOMMÉS."""

        self.session()
        res = self.match("Driffle", "The Elder Scrolls Online Collection Necrom (Europe) (PC / Mac) - Steam - Digital Key",
                         "https://www.driffle.com/the-elder-scrolls-online-collection-necrom-europe-pc-mac-steam-digital-key-p9996521",
                         store_id="127")
        self.assertIsInstance(res, Candidate, getattr(res, "reason", None))
        self.assertEqual((res.aks_url, res.region_id, res.edition_id),
                         (_url("the-elder-scrolls-online-necrom-cd-key"), "9", "98"))

    def test_cjs_flight_simulator_40th_garde_r01(self):
        """La page est trouvée ; les mots en trop (40TH) refusent — garde inchangée."""

        self.session()
        res = self.match("CJS-CDKeys", "Microsoft Flight Simulator 40th Anniversary Steam Key: United Kingdom",
                         "https://www.cjs-cdkeys.com/products/Microsoft-Flight-Simulator-40th-Anniversary-Steam-Key.html?variation=886",
                         store_id="30")
        self.assertIsInstance(res, SkippedOffer)
        self.assertIn("extra words: ['40TH']", res.reason)

    def test_wyrel_lego_jabba_garde_r01(self):
        self.session()
        res = self.match("Wyrel", "LEGO STAR WARS The Force Awakens Jabba's Palace Character Pack (PC) Standard Global",
                         "https://wyrel.com/en/buy-cheap-lego-star-wars-the-force-awakens-jabbas-palace-character-pack-67060?referal=allkeyshop&marketplace_id=2&edition_id=780&region=1&coupon=allkeyshop",
                         store_id="162")
        self.assertIsInstance(res, SkippedOffer)
        self.assertIn("extra words: ['CHARACTER']", res.reason)

    def test_kinguin_aura_farming_page_vraiment_absente(self):
        self.session()
        res = self.match("Kinguin", "Aura Farming PC Steam CD Key",
                         "https://www.kinguin.net/category/555404/aura-farming-pc-steam-cd-key",
                         store_id="58")
        self.assertIsInstance(res, SkippedOffer)
        self.assertIn("no AKS product page found", res.reason)

    def test_r66_jamais_standard_marvels_midnight_suns_digital_plus(self):
        """Réponse catalogue FABRIQUÉE à partir du vrai produit (page réelle
        `marvels-midnight-suns-cd-key`, sans index : la page n'est trouvée que par la
        recherche). La page vend « Digital+ Edition », mais DIGITAL et EDITION sont du bruit :
        rien ne NOMME ce seau, le bloc édition sortirait Standard(1) — le défaut que la revue
        de [R64] a mesuré. Refus (R66)."""

        from src.merchants import gamesplanet
        self.api["Marvel's Midnight Suns Digital+ Edition"] = json.dumps({
            "products": [{"id": 1, "name": "Marvel's Midnight Suns", "type": "game",
                          "link": _url("marvels-midnight-suns-cd-key")}],
            "pagination": {"total": 1, "per_page": 24, "pagenum": 1, "total_pages": 1}})
        self.session()
        with unittest.mock.patch.object(gamesplanet, "fetch_region", return_value=("global", "")):
            res = self.match("Gamesplanet FR", "Marvel's Midnight Suns Digital+ Edition",
                             "https://fr.gamesplanet.com/game/marvel-s-midnight-suns-digital-edition-steam-key--5306-2")
        self.assertIsInstance(res, SkippedOffer, "jamais Standard(1) par la recherche catalogue")
        self.assertIn("(R66)", res.reason)
        self.assertIn("'DIGITAL EDITION'", res.reason)
        self.assertIn("Digital+ Edition", res.reason, "le motif dit ce que la page vend")

    def test_r66_le_palier_nomme_entre(self):
        """Même page, titre réel CJS « … Legendary Edition Epic Games Key … : Europe & UK » :
        LEGENDARY nomme le seau « Legendary » — il entre, jamais refusé par [R66]."""

        self.api["Marvel's Midnight Suns Legendary Edition"] = json.dumps({
            "products": [{"id": 1, "name": "Marvel's Midnight Suns", "type": "game",
                          "link": _url("marvels-midnight-suns-cd-key")}],
            "pagination": {"total": 1, "per_page": 24, "pagenum": 1, "total_pages": 1}})
        self.session()
        res = self.match("CJS-CDKeys",
                         "Marvel's Midnight Suns Legendary Edition Epic Games Key (Digital Download): Europe & UK",
                         "https://www.cjs-cdkeys.com/products/Marvels-Midnight-Suns-Legendary-Edition-Epic-Games-Key.html",
                         store_id="30")
        self.assertIsInstance(res, Candidate, getattr(res, "reason", None))
        self.assertEqual((res.aks_url, res.region_id, res.edition_id),
                         (_url("marvels-midnight-suns-cd-key"), "80eu", "legendary"))

    def test_r66_logiciel_avec_mots_restants_refuse(self):
        """Page réelle Office Home & Business 2019. Titre : le libellé MMOGA réel
        « Microsoft Office 2019 Home & Business PC (1 User) » décliné « for Mac » comme ses
        lignes 2021 / 2024 (« … MAC (1 User) ») — ADAPTÉ. Le chemin logiciel saute la garde
        des mots en trop : une page au nom plus court que le titre est refusée (R66)."""

        self.api["Microsoft Office 2019 Home & Business for Mac"] = self.api[
            "Microsoft Office 2019 Home & Business"]
        self.session()
        res = self.match("MMOGA", "Microsoft Office 2019 Home & Business for Mac (1 User)",
                         "https://www.mmoga.com/Software/Office/Microsoft-Office-2019-Home-Business-Mac.html?ref=615",
                         store_id="12")
        self.assertIsInstance(res, SkippedOffer)
        self.assertIn("software is not entered through the catalogue search (R66)", res.reason)

    def test_r66_logiciel_sans_mots_restants_suit_r31(self):
        """Titre MMOGA réel : aucun mot restant — [R66] se tait, R31 décide (rejeu du 29/09)."""

        self.session()
        res = self.match("MMOGA", "Microsoft Office 2019 Home & Business PC (1 User)",
                         "https://www.mmoga.com/Software/Office/Microsoft-Office-2019-Home-Business-PC-1-User.html?ref=615",
                         store_id="12")
        self.assertIsInstance(res, SkippedOffer)
        self.assertIn("(R31)", res.reason)
        self.assertNotIn("(R66)", res.reason)


# ─────────────────────────── 03_match : état du balayage, méta, session ──────────────────
def _load_03():
    spec = importlib.util.spec_from_file_location(
        "m03_r66", str(Path(__file__).resolve().parents[1] / "scripts" / "03_match.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class Match03(unittest.TestCase):
    def setUp(self):
        self.MOD = _load_03()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.MOD.ROOT = self.root
        self.run = self.root / "runs" / "r1"
        self.run.mkdir(parents=True)
        (self.run / "offers.json").write_text(json.dumps({
            "run_id": "r1", "merchant": "Kinguin", "fetched_at": "t",
            "offers": [{"offer_id": "1", "name": "Aura Farming PC Steam CD Key",
                        "url": "https://www.kinguin.net/category/555404/aura-farming-pc-steam-cd-key",
                        "merchant": "Kinguin", "store_id": "58"}]}))
        gate_ok = HttpProbeResult(url="u", ok=True, status=200, body="x")
        p = unittest.mock.patch.object(self.MOD, "http_get", return_value=gate_ok)
        p.start()
        self.addCleanup(p.stop)
        self.addCleanup(M.set_aks_search, None)
        self.state = self.root / "sweep" / "aks_search.json"
        self.state.parent.mkdir()
        self.seen = []

    def _stub(self, requests):
        def stub(feed, resolver, **kw):
            session = M.aks_search_session()
            self.seen.append(session)
            if session is not None:
                session.used += requests
                session.stats["requests"] += requests
            return [], []
        return stub

    def _main(self, *extra, requests=0):
        argv = ["03_match.py", str(self.run / "offers.json"), *extra]
        with unittest.mock.patch.object(self.MOD, "match_feed", side_effect=self._stub(requests)), \
                unittest.mock.patch.object(sys, "argv", argv):
            return self.MOD.main()

    def test_le_budget_traverse_les_pages_du_balayage(self):
        self.assertEqual(self._main("--aks-search-state", str(self.state), requests=4), 0)
        self.assertEqual(json.loads(self.state.read_text())["requests_used"], 4)
        self.assertEqual(self._main("--aks-search-state", str(self.state), requests=3), 0)
        self.assertEqual(json.loads(self.state.read_text())["requests_used"], 7)
        meta = json.loads((self.run / "match_meta.json").read_text())["aks_search"]
        self.assertEqual((meta["active"], meta["used_before"], meta["used_after"], meta["budget"]),
                         (True, 4, 7, aks_search.DEFAULT_BUDGET))
        self.assertEqual(meta["api_version"], aks_search.API_VERSION)

    def test_la_coupure_traverse_les_pages_du_balayage(self):
        self.state.write_text(json.dumps({"requests_used": 2, "disabled_reason": "v2-1-250304 : HTTP 404"}))
        self._main("--aks-search-state", str(self.state))
        self.assertEqual(self.seen[0].disabled_reason, "v2-1-250304 : HTTP 404")
        self.assertEqual(json.loads(self.state.read_text())["disabled_reason"], "v2-1-250304 : HTTP 404")

    def test_session_posee_pendant_le_match_puis_retiree(self):
        self._main("--aks-search-budget", "25")
        self.assertIsNotNone(self.seen[0])
        self.assertEqual(self.seen[0].budget, 25)
        self.assertEqual(self.seen[0].cache_path, str(self.root / aks_search.DEFAULT_CACHE_PATH))
        self.assertIsNone(M.aks_search_session(), "la session ne survit pas au match")

    def test_sans_recherche(self):
        self._main("--no-aks-search")
        self.assertIsNone(self.seen[0])
        meta = json.loads((self.run / "match_meta.json").read_text())
        self.assertEqual(meta["aks_search"], {"active": False})

    def test_un_abandon_garde_le_compte(self):
        def stub(feed, resolver, **kw):
            M.aks_search_session().used += 5
            raise AksThrottled("AKS answered 429 (rate limited)")
        argv = ["03_match.py", str(self.run / "offers.json"), "--aks-search-state", str(self.state)]
        with unittest.mock.patch.object(self.MOD, "match_feed", side_effect=stub), \
                unittest.mock.patch.object(sys, "argv", argv):
            self.assertEqual(self.MOD.main(), 2)
        self.assertEqual(json.loads(self.state.read_text())["requests_used"], 5)
        self.assertIsNone(M.aks_search_session())

    def test_le_balayage_passe_son_fichier_d_etat(self):
        src = (Path(__file__).resolve().parents[1] / "scripts" / "10_data_entry_auto.py").read_text()
        self.assertIn('argv += ["--aks-search-state", str(sweep_dir / "aks_search.json")]', src)


if __name__ == "__main__":
    unittest.main()

"""[R66] revue adverse du 2026-09-29 — la recherche catalogue AKS dans la configuration de
PRODUCTION : session posée (03_match en pose une par défaut) ET index sitemap frais.

Les deux revues (« écritures fausses », « robustesse ») l'ont montré : les tests [R64] / [R65]
tournaient SANS session, la configuration de 03_match n'était testée nulle part, et les défauts
ci-dessous n'apparaissaient qu'avec elle.

  P1-1  R01 / R16 / le filtre du catalogue comparaient des ENSEMBLES de mots : « Nope Nope Nope
        Nope Nurses » entrait sur « Nope Nope Nurses », « Legacy of Ancestors » sur « Ancestor's
        Legacy » (`catalog_name_mismatch`) ;
  P1-2  la recherche passait AVANT les gabarits console : « Destiny 2: The Collection » (génération
        déduite) entrait sur la page Xbox One du JEU DE BASE, en Collection(98) ;
  P2-3  …et « Priest Simulator: Vampire Show » / « Worms Armageddon: Anniversary Edition » étaient
        refusés, leur page propre jamais essayée ;
  P2-4  le filtre lisait le titre NETTOYÉ : « The Tartarus Key » tombait pour « The Tartarus » ;
  P2-5  l'article de tête était un mot-outil : « The Fire » pouvait entrer sur « Fire ».

Données : réponses RÉELLES de l'API (`tests/fixtures/aks_search_r66/api_*.json`, lues en AKS/Staff
le 29/09 par les deux revues et par cette correction), pages AKS RÉELLES réduites aux blocs que le
matcher lit (même dossier + `pages_r64_r65/`), entrées RÉELLES de l'index sitemap du 28/09, titres
et URL RÉELS de la population de l'audit. Toute réponse FABRIQUÉE le dit. Aucune requête réseau.
"""

import functools
import json
import socket
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
    Candidate, SkippedOffer, catalog_candidates, catalog_leftover, catalog_name_mismatch,
    catalog_page, match_feed, match_offer, resolve_aks, resolve_aks_url,
)

HERE = Path(__file__).resolve().parent
FIX = HERE / "fixtures" / "aks_search_r66"
FIX64 = HERE / "fixtures" / "pages_r64_r65"
AKS = "https://www.allkeyshop.com/blog/"


def _url(slug_kind):
    return f"{AKS}buy-{slug_kind}-compare-prices/"


# Entrées RÉELLES du relevé sitemap du 2026-09-28 pour ces cas (extraits par préfixe de slug).
INDEX_28_09 = {
    "the-tartarus-key-cd-key", "the-tartarus-key-nintendo-switch", "the-tartarus-key-ps4",
    "the-tartarus-key-xbox-one", "the-tartarus-key-xbox-series",
    "nope-nope-nurses-cd-key",
    "ancestors-legacy-cd-key", "ancestors-legacy-nintendo-switch", "ancestors-legacy-ps4",
    "ancestors-legacy-steam-account", "ancestors-legacy-xbox-one", "ancestors-legacy-xbox-series",
    "priest-simulator-cd-key", "priest-simulator-nintendo-switch", "priest-simulator-ps4",
    "priest-simulator-ps5", "priest-simulator-steam-account", "priest-simulator-xbox-one",
    "priest-simulator-xbox-series", "priest-simulator-vampire-show-epic-account",
    "priest-simulator-vampire-show-ps5-key", "priest-simulator-vampire-show-xbox-series-key",
    "destiny-2-cd-key", "destiny-2-xbox-one-code", "destiny-2-ps4-game-code",
    "destiny-2-the-collection-ps4-key", "destiny-2-the-collection-ps5-key",
    "destiny-2-the-collection-xbox-key", "destiny-2-the-collection-xbox-one-key",
    "worms-armageddon-cd-key", "worms-armageddon-ps4", "worms-armageddon-ps5",
    "worms-armageddon-steam-account", "worms-armageddon-anniversary-edition-nintendo-switch",
    "worms-armageddon-anniversary-edition-ps4", "worms-armageddon-anniversary-edition-ps5",
    "worms-armageddon-anniversary-edition-xbox-one",
    "worms-armageddon-anniversary-edition-xbox-series",
    "fire-cd-key", "emergency-call-112-the-fire-fighting-simulation-cd-key",
    "the-elder-scrolls-online-necrom-cd-key",
}


def _pages():
    pages = {}
    for d in (FIX, FIX64):
        for p in d.glob("*.html"):
            pages.setdefault(_url(p.stem), p.read_text(encoding="utf-8"))
    return pages


def _api_bodies():
    out = {}
    for f in FIX.glob("api_*.json"):
        raw = json.loads(f.read_text(encoding="utf-8"))
        out[raw["query"]] = raw["body"]
    return out


def _products(query):
    return aks_search.parse_response(_api_bodies()[query])


_EMPTY = ('{"products":[],"pagination":{"total":0,"per_page":24,"pagenum":1,"total_pages":0,'
          '"took":1},"facets":{}}')


class _Prod(unittest.TestCase):
    """La configuration de PRODUCTION : index sitemap frais + session de recherche posée.
    L'API répond la réponse RÉELLE enregistrée pour la requête exacte, sinon « aucun produit »."""

    def setUp(self):
        def _no_network(*_a, **_kw):
            raise AssertionError("requête réseau pendant un test [R66]")
        for target in (unittest.mock.patch.object(socket.socket, "connect", _no_network),
                       unittest.mock.patch.object(socket, "create_connection", _no_network)):
            target.start()
            self.addCleanup(target.stop)
        saved = list(M._SITEMAP_CACHE)
        self.addCleanup(lambda: (M._SITEMAP_CACHE.clear(), M._SITEMAP_CACHE.extend(saved)))
        M.set_sitemap_index(SitemapIndex(
            entries=frozenset(INDEX_28_09), fetched_at="2099-01-01T00:00:00Z", incomplete=False,
            legacy=frozenset(), legacy_indexed=True))
        self.addCleanup(M.set_aks_search, None)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.pages = _pages()
        self.api = _api_bodies()
        self.api_override = None
        self.asked, self.api_asked = [], []
        self.now = [1_800_000_000.0]
        self.search = self.session()

    def session(self, **kw):
        kw.setdefault("cache_path", str(Path(self.tmp.name) / "state" / "aks_search_cache.json"))
        kw.setdefault("now", lambda: self.now[0])
        kw.setdefault("sleep", lambda s: None)
        s = AksCatalogSearch(**kw)
        M.set_aks_search(s)
        return s

    def get(self, url, timeout=8, user_agent=None, **_kw):
        if "vakrs_catalogv2.php" in url:
            self.api_asked.append(url)
            if self.api_override is not None:
                status, body = self.api_override
                return HttpProbeResult(url=url, ok=status == 200, status=status, body=body)
            q = unquote(url.split("search_name=", 1)[1].split("&", 1)[0])
            return HttpProbeResult(url=url, ok=True, status=200, body=self.api.get(q, _EMPTY))
        self.asked.append(url)
        body = self.pages.get(url)
        if body:
            return HttpProbeResult(url=url, ok=True, status=200, body=body)
        return HttpProbeResult(url=url, ok=False, status=404, body="")

    def match(self, merchant, title, url, store_id=None):
        resolver = functools.partial(resolve_aks, http_get_fn=self.get)
        page_resolver = functools.partial(resolve_aks_url, http_get_fn=self.get)
        offer = NormalizedOffer(offer_id="1", name=title, url=url, merchant=merchant,
                                store_id=store_id)
        return match_offer(offer, resolver, M.resolve_difmark_offer, resolver,
                           page_resolver=page_resolver, consoles=True)

    def targets(self, res):
        self.assertIsInstance(res, Candidate, getattr(res, "reason", None))
        return sorted((t.aks_url, t.region_id, t.edition_id) for t in res.all_targets)


# ─────────────────────── P1-1 / P2-5 : le nom, compté et ordonné ─────────────────────────
class LaCoherenceDuNom(unittest.TestCase):
    def test_un_mot_repete_moins_souvent_n_est_pas_le_meme_nom(self):
        self.assertIn("NOPE 4 fois", catalog_name_mismatch(
            "Nope Nope Nope Nope Nurses (PC) Steam Key - GLOBAL", "Nope Nope Nope Nope Nurses",
            "Nope Nope Nurses"))
        self.assertIn("NOPE 3 fois", catalog_name_mismatch(
            "Nope Nope Nope Nurses", "Nope Nope Nope Nurses", "Nope Nope Nurses"))
        # …ni plus souvent : le côté requis, compté.
        self.assertIn("absents", catalog_name_mismatch("Nope Nurses", "Nope Nurses",
                                                       "Nope Nope Nurses"))
        self.assertEqual(catalog_name_mismatch("Nope Nope Nurses UNRATED",
                                               "Nope Nope Nurses UNRATED", "Nope Nope Nurses"), "")

    def test_le_bruit_n_est_ni_compte_ni_ordonne(self):
        """Titre Gamerall réel (offre 101111972) : MICROSOFT deux fois, dont une en mobilier de
        boutique — pas un mot du nom répété. Nom réel de la page `flight-simulator-cd-key`."""

        self.assertEqual(catalog_name_mismatch(
            "Microsoft Flight Simulator (Microsoft Store)", "Microsoft Flight Simulator (Microsoft Store)",
            "Microsoft Flight Simulator"), "")

    def test_l_ordre_des_mots(self):
        self.assertIn("ordre", catalog_name_mismatch(
            "Legacy of Ancestors PC Steam CD Key", "Legacy of Ancestors", "Ancestor's Legacy"))
        # Les chiffres ne comptent pas dans l'ordre (le nom AKS les place où il veut).
        self.assertEqual(catalog_name_mismatch(
            "Microsoft Office 2019 Home & Business PC (1 User)",
            "Microsoft Office 2019 Home & Business", "Microsoft Office Home & Business 2019"), "")

    def test_l_article_de_tete(self):
        self.assertIn("article", catalog_name_mismatch(
            "The Fire (PC) Steam Gift - GLOBAL", "The Fire", "Fire"))
        self.assertIn("article", catalog_name_mismatch(
            "A Tiny Life PC Steam CD Key", "A Tiny Life", "Tiny Life"))
        # Ailleurs que EN TÊTE, un mot-outil reste un mot-outil (« & » / AND, THE interne).
        self.assertEqual(catalog_name_mismatch(
            "The Elder Scrolls Online Collection Necrom (Europe) (PC / Mac) - Steam - Digital Key",
            "The Elder Scrolls Online Collection Necrom", "The Elder Scrolls Online Necrom"), "")
        self.assertEqual(catalog_name_mismatch(
            "Heroes of Might and Magic: Olden Era", "Heroes of Might and Magic: Olden Era",
            "Heroes of Might & Magic Olden Era"), "")

    def test_le_titre_brut_pas_la_requete(self):
        """P2-4 : `cleaned_title` retire KEY en fin de titre — le nom « The Tartarus Key » est
        pourtant tout entier dans le titre BRUT."""

        raw = "The Tartarus Key (PC) Steam Gift - GLOBAL"
        self.assertEqual(M.cleaned_title(raw), "The Tartarus")
        self.assertEqual(catalog_name_mismatch(raw, "The Tartarus", "The Tartarus Key"), "")

    def test_les_mots_restants_sont_comptes(self):
        self.assertEqual(catalog_leftover("Nope Nope Nope Nope Nurses", "Nope Nope Nurses"),
                         "NOPE NOPE")
        self.assertEqual(catalog_leftover("The Elder Scrolls Online Collection Necrom",
                                          "The Elder Scrolls Online Necrom"), "COLLECTION")


class LeFiltreSurLesReponsesReelles(unittest.TestCase):
    def test_nope_x4_aucun_candidat(self):
        """Réponse RÉELLE de l'API pour « Nope Nope Nope Nope Nurses » : un seul produit,
        « Nope Nope Nurses » — un AUTRE jeu (GOG vend quatre fiches, GameSeal deux)."""

        self.assertEqual(catalog_candidates(
            _products("Nope Nope Nope Nope Nurses"), "Nope Nope Nope Nope Nurses",
            raw="Nope Nope Nope Nope Nurses (PC) Steam Key - GLOBAL"), [])

    def test_legacy_of_ancestors_aucun_candidat(self):
        """Réponse RÉELLE : « Ancestors Legacy » (page « Ancestor's Legacy »), mêmes mots,
        autre ordre. AKS n'a aucun « Legacy of Ancestors » ; Kinguin le vend sous sa propre
        fiche (478453)."""

        self.assertEqual(catalog_candidates(
            _products("Legacy of Ancestors"), "Legacy of Ancestors",
            raw="Legacy of Ancestors PC Steam CD Key"), [])

    def test_the_tartarus_key_candidat(self):
        """Réponse RÉELLE pour la requête « The Tartarus » : la page clé PC « The Tartarus Key »
        y est. Elle tombait parce que KEY n'est pas dans la requête nettoyée."""

        got = catalog_candidates(_products("The Tartarus"), "The Tartarus",
                                 raw="The Tartarus Key (PC) Steam Gift - GLOBAL")
        self.assertEqual([u for _s, u, _n in got], [_url("the-tartarus-key-cd-key")])

    def test_the_fire_article_de_tete(self):
        """Réponse RÉELLE pour « The Fire » : aucun candidat, avant comme après (l'API ne
        propose pas « Fire »). La même réponse AUGMENTÉE d'un produit FABRIQUÉ « Fire » (page
        réelle `fire-cd-key`, index du 28/09) : il tombe sur l'article de tête."""

        products = _products("The Fire")
        raw = "The Fire (PC) Steam Gift - GLOBAL"
        self.assertEqual(catalog_candidates(products, "The Fire", raw=raw), [])
        fabricated = products + [CatalogProduct(id=1, name="Fire", link=_url("fire-cd-key"),
                                                type="game")]
        self.assertEqual(catalog_candidates(fabricated, "The Fire", raw=raw), [])

    def test_le_bon_candidat_reste(self):
        got = catalog_candidates(
            _products("The Elder Scrolls Online Collection Necrom"),
            "The Elder Scrolls Online Collection Necrom",
            raw="The Elder Scrolls Online Collection Necrom (Europe) (PC / Mac) - Steam - Digital Key")
        self.assertEqual(got[0][1], _url("the-elder-scrolls-online-necrom-cd-key"))


class LesPagesQuiNeSontPasDesClesPC(unittest.TestCase):
    def test_ps3_3ds_wii_u_oculus_jamais_candidats(self):
        """Liens RÉELS de l'index du 28/09 : ces gabarits de « clé » ne vendent pas une clé PC."""

        for slug_kind in ("007-legends-ps3-game-code", "fire-emblem-fates-nintendo-3ds-download-code",
                          "ace-attorney-6-3ds-download-code",
                          "007-legends-nintendo-wii-u-download-code",
                          "1-2-switch-wii-u-download-code", "merry-snowballs-oculus-cd-key"):
            with self.subTest(slug_kind):
                self.assertIsNone(catalog_page(_url(slug_kind)))

    def test_mac_reste_lue(self):
        """`-mac-cd-key` : le nom porte « for Mac », que R01 exige du titre — lue."""

        self.assertEqual(catalog_page(_url("abbyy-finereader-pro-for-mac-cd-key")),
                         ("abbyy-finereader-pro-for-mac", _url("abbyy-finereader-pro-for-mac-cd-key")))


# ─────────────────────── P1-1 / P2-4 de bout en bout ─────────────────────────────────────
class PCDeBoutEnBout(_Prod):
    def test_gameseal_nope_x4_jamais_sur_nope_nope_nurses(self):
        """Offre 100698305. Avant : ENTRE sur `nope-nope-nurses` STEAM GLOBAL(2) Standard(1)."""

        res = self.match("GameSeal", "Nope Nope Nope Nope Nurses (PC) Steam Key - GLOBAL",
                         "https://gameseal.com/nope-nope-nope-nope-nurses-pc-steam-key-global",
                         store_id="126")
        self.assertIsInstance(res, SkippedOffer, "un autre jeu, jamais saisi")
        self.assertIn("no AKS product page found", res.reason)
        self.assertNotIn(_url("nope-nope-nurses-cd-key"), self.asked, "jamais même lue")

    def test_gog_nope_x3_jamais_sur_nope_nope_nurses(self):
        """Offre GOG 100461290. Réponse API de la requête ×4 réutilisée pour ×3 (ADAPTÉ : la même
        fiche AKS est la seule proche). Avant : ENTRE en GOG GLOBAL(6) Standard(1)."""

        self.api["Nope Nope Nope Nurses"] = self.api["Nope Nope Nope Nope Nurses"]
        res = self.match("GOG", "Nope Nope Nope Nurses",
                         "https://www.gog.com/en/game/nope_nope_nope_nurses", store_id="34")
        self.assertIsInstance(res, SkippedOffer)
        self.assertIn("no AKS product page found", res.reason)

    def test_kinguin_legacy_of_ancestors_jamais_sur_ancestors_legacy(self):
        """Offre 100997924. Avant : ENTRE sur `ancestors-legacy` STEAM GLOBAL(2) Standard(1)."""

        res = self.match("Kinguin", "Legacy of Ancestors PC Steam CD Key",
                         "https://www.kinguin.net/category/478453/legacy-of-ancestors-pc-steam-cd-key",
                         store_id="58")
        self.assertIsInstance(res, SkippedOffer)
        self.assertIn("no AKS product page found", res.reason)

    def test_un_nom_lu_incoherent_est_ecarte_apres_lecture(self):
        """Réponse catalogue FABRIQUÉE : le produit s'appelle « Legacy Ancestors » (ordre du
        titre) mais la page lue — la vraie `ancestors-legacy` — s'appelle « Ancestor's Legacy ».
        Le nom LU repasse le contrôle : candidat écarté, compté."""

        self.api["Legacy of Ancestors"] = json.dumps({
            "products": [{"id": 20257, "name": "Legacy Ancestors", "type": "game",
                          "link": _url("ancestors-legacy-cd-key")}],
            "pagination": {"total": 1, "per_page": 24, "pagenum": 1, "total_pages": 1}})
        res = self.match("Kinguin", "Legacy of Ancestors PC Steam CD Key",
                         "https://www.kinguin.net/category/478453/legacy-of-ancestors-pc-steam-cd-key",
                         store_id="58")
        self.assertIsInstance(res, SkippedOffer)
        self.assertIn(_url("ancestors-legacy-cd-key"), self.asked)
        self.assertEqual(self.search.stats["rejected_after_read"], 1)
        self.assertEqual(self.search.stats["resolved"], 0)

    def test_gameseal_the_tartarus_key_entre_en_cadeau(self):
        """Offre 100700947. Avant : refus « no AKS product page found » (le filtre écartait la
        page). Page réelle : seau Standard seul, cadeau Steam mondial (25)."""

        res = self.match("GameSeal", "The Tartarus Key (PC) Steam Gift - GLOBAL",
                         "https://gameseal.com/the-tartarus-key-pc-steam-gift-global",
                         store_id="126")
        self.assertEqual(self.targets(res), [(_url("the-tartarus-key-cd-key"), "25", "1")])

    def test_cjs_eso_deluxe_collection_jamais_le_palier_moins_precis(self):
        """Rejeu final du 29/09 : CJS « The Elder Scrolls Online Deluxe Collection: Necrom Steam Key:
        Europe & UK » (offre 100385971) sur la page réelle `the-elder-scrolls-online-necrom`, qui
        vend Deluxe(7) ET « Deluxe Collection Edition » (2497). `detect_edition` rendait Deluxe(7).
        Réponse API RÉELLE de « The Elder Scrolls Online Collection Necrom » rejouée pour la
        requête Deluxe (ADAPTÉ). Refus ; la ligne Driffle « … Collection Necrom » entre toujours en
        Collection(98) (`test_aks_search_r66`)."""

        self.api["The Elder Scrolls Online Deluxe Collection: Necrom"] = self.api[
            "The Elder Scrolls Online Collection Necrom"]
        res = self.match("CJS-CDKeys", "The Elder Scrolls Online Deluxe Collection: Necrom Steam Key: Europe & UK",
                         "https://www.cjs-cdkeys.com/products/The-Elder-Scrolls-Online-Deluxe-Collection-Necrom-Steam-Key.html?variation=608",
                         store_id="30")
        self.assertIsInstance(res, SkippedOffer, "jamais Deluxe(7) quand la page vend « Deluxe Collection »")
        self.assertIn("not the most precise tier", res.reason)
        self.assertIn("Deluxe Collection Edition", res.reason)
        res = self.match("Driffle", "The Elder Scrolls Online Collection Necrom (Europe) (PC / Mac) - Steam - Digital Key",
                         "https://www.driffle.com/the-elder-scrolls-online-collection-necrom-europe-pc-mac-steam-digital-key-p9996521",
                         store_id="127")
        self.assertEqual(self.targets(res), [(_url("the-elder-scrolls-online-necrom-cd-key"), "9", "98")])

    def test_mmoga_destiny_2_collection_nom_complet_publie_ailleurs(self):
        """MMOGA « Destiny 2: The Collection » (offre 101040050, clé PC). Réponse API RÉELLE :
        « Destiny 2 » (`destiny-2-cd-key`, qui vend Collection, Legacy Collection, Legacy
        Collection 2023). Le nom complet est publié en `-xbox-key` / `-ps4-key` : AKS en fait un
        produit distinct, la condition 3 de [R64] vaut aussi pour la recherche. Avant : ENTRE sur
        `destiny-2` en Collection(98)."""

        res = self.match("MMOGA", "Destiny 2: The Collection",
                         "https://www.mmoga.com/Steam-Games/Destiny-2-The-Collection.html?ref=615",
                         store_id="12")
        self.assertIsInstance(res, SkippedOffer)
        self.assertIn("no AKS product page found", res.reason)
        self.assertNotIn(_url("destiny-2-cd-key"), self.asked, "jamais même lue")

    def test_la_recherche_seule_ne_sonde_aucun_slug(self):
        """``catalog="only"`` : les passes 1-4 ont déjà répondu dans l'appel « off » — aucune
        sonde devinée ne repart, seule la page candidate est lue."""

        res = resolve_aks("The Tartarus Key (PC) Steam Gift - GLOBAL", self.get, catalog="only")
        self.assertEqual(res.url, _url("the-tartarus-key-cd-key"))
        self.assertEqual(self.asked, [_url("the-tartarus-key-cd-key")])
        self.assertIsNone(resolve_aks("The Tartarus Key (PC) Steam Gift - GLOBAL", self.get,
                                      catalog="off"))
        self.assertEqual(len(self.api_asked), 1, "« off » : jamais de question au catalogue")

    def test_la_mention_ne_suit_pas_l_offre_suivante(self):
        """Une offre entrée par le catalogue, puis une offre sans page : la seconde ne porte pas
        la mention (la liste est remise à zéro à chaque offre)."""

        self.assertIsInstance(self.match(
            "GameSeal", "The Tartarus Key (PC) Steam Gift - GLOBAL",
            "https://gameseal.com/the-tartarus-key-pc-steam-gift-global", store_id="126"), Candidate)
        res = self.match("Kinguin", "Aura Farming PC Steam CD Key",
                         "https://www.kinguin.net/category/555404/aura-farming-pc-steam-cd-key",
                         store_id="58")
        self.assertEqual(res.reason, "no AKS product page found (slug not 200)")

    def test_deux_titres_meme_requete_deux_filtres(self):
        """Le filtre dépend du titre BRUT : la clé du cache aussi. Deuxième titre FABRIQUÉ (même
        requête « The Tartarus », sans KEY) : nouvelle question, aucun candidat."""

        resolve_aks("The Tartarus Key (PC) Steam Gift - GLOBAL", self.get)
        self.assertIsNone(resolve_aks("The Tartarus (PC) Steam Gift - GLOBAL", self.get))
        self.assertEqual(len(self.api_asked), 2)


# ─────────────────────── P1-2 / P2-3 : la recherche après les gabarits console ───────────
class ConsoleDeBoutEnBout(_Prod):
    def test_eneba_destiny_2_collection_generation_deduite_2b(self):
        """Offre 100392601 (génération DÉDUITE). Avant, en production : ENTRE sur
        `destiny-2-xbox-one-code` — la page Xbox One du JEU DE BASE — en XBOX_ONE 24us,
        Collection(98). Attendu : le refus « 2b, non tranché » (AGENTS, [R65] (c)), que la
        branche donnait sans session."""

        res = self.match("Eneba", "Destiny 2: The Collection XBOX LIVE Key UNITED STATES",
                         "https://www.eneba.com/xbox-destiny-2-legacy-collection-xbox-live-key-united-states",
                         store_id="19")
        self.assertIsInstance(res, SkippedOffer, "jamais sur la page du jeu de base")
        self.assertIn("2b, non tranché (R65)", res.reason)
        self.assertNotIn(_url("destiny-2-xbox-one-code"), self.asked)
        self.assertEqual(self.api_asked, [], "aucune question au catalogue : un gabarit a répondu")

    def test_kinguin_destiny_2_collection_generations_declarees(self):
        """Offre Kinguin 101047954 (714079), One + Series DÉCLARÉES. Avant, en production : refus
        « AKS has no XBOX_SERIES page for 'Destiny 2' » (ancre = le jeu de base)."""

        res = self.match("Kinguin", "Destiny 2: The Collection EU XBOX One / Xbox Series X|S CD Key",
                         "https://www.kinguin.net/category/714079/destiny-2-the-collection-eu-xbox-one-xbox-series-x-s-cd-key",
                         store_id="58")
        self.assertEqual(self.targets(res), [
            (_url("destiny-2-the-collection-xbox-key"), "302", "1"),
            (_url("destiny-2-the-collection-xbox-one-key"), "24eu", "1")])

    def test_eneba_priest_simulator_vampire_show_page_propre(self):
        """Offre 101046249. Réponse API réelle : « Priest Simulator » (`cd-key`) d'abord. Avant, en
        production : l'ancre devenait le jeu de base, puis refus (page Xbox Series sans éditions).
        Attendu : la page `-xbox-series-key` du DLC lui-même, 302, Standard(1)."""

        res = self.match("Eneba", "Priest Simulator: Vampire Show (Xbox Series X|S) XBOX LIVE Key EUROPE",
                         "https://www.eneba.com/xbox-priest-simulator-vampire-show-xbox-series-x-s-xbox-live-key-europe",
                         store_id="19")
        self.assertEqual(self.targets(res), [
            (_url("priest-simulator-vampire-show-xbox-series-key"), "302", "1")])
        self.assertNotIn(_url("priest-simulator-cd-key"), self.asked)

    def test_eneba_worms_anniversary_generation_deduite(self):
        """Ligne Eneba réelle « … XBOX LIVE Key EUROPE » (entrée en septembre sans session). Réponse
        API réelle : `worms-armageddon-cd-key`. Avant, en production : refus « no AKS product page
        found (console) » — motif faux, une ancre avait été trouvée. Attendu : les deux pages
        Anniversary, 24eu et 302."""

        res = self.match("Eneba", "Worms Armageddon: Anniversary Edition XBOX LIVE Key EUROPE",
                         "https://www.eneba.com/xbox-worms-armageddon-anniversary-edition-xbox-live-key-europe",
                         store_id="19")
        self.assertEqual(self.targets(res), [
            (_url("worms-armageddon-anniversary-edition-xbox-one"), "24eu", "1"),
            (_url("worms-armageddon-anniversary-edition-xbox-series"), "302", "1")])

    def _catalog_only_anchor(self):
        """Montage : ligne Eneba FABRIQUÉE « Ancestors Legacy XBOX LIVE Key EUROPE » (génération
        déduite) ; aucune page devinée ne répond (résolveur FABRIQUÉ : tout appel autre que la
        recherche seule rend None) ; la réponse RÉELLE de l'API pour « Legacy of Ancestors »,
        rejouée pour la requête « Ancestors Legacy » (ADAPTÉ) ; page réelle `ancestors-legacy`."""

        self.api["Ancestors Legacy"] = self.api["Legacy of Ancestors"]
        calls = []
        real = functools.partial(resolve_aks, http_get_fn=self.get)

        def resolver(name, **kw):
            calls.append((kw.get("page_kind", "cd-key"), kw.get("catalog", "last")))
            return real(name, **kw) if kw.get("catalog") == "only" else None

        offer = NormalizedOffer(offer_id="1", name="Ancestors Legacy XBOX LIVE Key EUROPE",
                                url="https://www.eneba.com/xbox-ancestors-legacy-xbox-live-key-europe",
                                merchant="Eneba", store_id="19")
        res = match_offer(offer, resolver, M.resolve_difmark_offer, resolver,
                          page_resolver=functools.partial(resolve_aks_url, http_get_fn=self.get),
                          consoles=True)
        return res, calls

    def test_la_recherche_part_quand_meme_en_dernier(self):
        """Aucune page console d'aucun gabarit : la recherche catalogue part, en DERNIER."""

        _res, calls = self._catalog_only_anchor()
        self.assertEqual(calls[0], ("cd-key", "off"), "l'ancre PC d'abord, SANS la recherche")
        self.assertEqual(calls[-1], ("cd-key", "only"), "la recherche en tout dernier")
        middle = calls[1:-1]
        self.assertTrue(middle and all(k != "cd-key" for k, _c in middle), calls)
        self.assertIn(("xbox-one", "last"), middle)
        self.assertIn(("xbox-series-key", "last"), middle, "[R65] essayé avant la recherche")
        self.assertEqual(len(self.api_asked), 1)

    def test_la_cle_windows_garde_la_recherche_dans_son_appel_pc(self):
        """Clé Windows / appli Xbox (titre Eneba réel, `test_merchants_eneba`) : l'ancre ne peut
        être que la page PC — un seul appel, la recherche en dernier recours comme pour une clé
        PC. URL construite sur la grammaire Eneba."""

        calls = []

        def resolver(name, **kw):
            calls.append(kw)
            return None

        offer = NormalizedOffer(offer_id="1", name="Manor Lords (Windows) XBOX LIVE Key EUROPE",
                                url="https://www.eneba.com/xbox-manor-lords-windows-xbox-live-key-europe",
                                merchant="Eneba", store_id="19")
        res = match_offer(offer, resolver, M.resolve_difmark_offer, resolver,
                          page_resolver=lambda url: None, consoles=True)
        self.assertIsInstance(res, SkippedOffer)
        self.assertEqual(calls, [{}], "un seul appel, catalogue au défaut (« last »)")

    def test_un_refus_apres_une_ancre_du_catalogue_le_dit(self):
        """Même montage : l'ancre PC vient de la recherche, ses onglets Xbox n'ont pas de page
        lisible (404) — génération déduite, rien ne reste. Le refus nomme la recherche, sans
        le mot « console » dans la mention (le tri de la liste 22 le lit)."""

        res, _calls = self._catalog_only_anchor()
        self.assertIsInstance(res, SkippedOffer)
        self.assertIn("no AKS product page found (console) (R45)", res.reason)
        self.assertTrue(res.reason.endswith(M.CATALOG_REFUSAL_NOTE), res.reason)
        self.assertNotIn("console", M.CATALOG_REFUSAL_NOTE)

    def test_sans_page_du_catalogue_pas_de_mention(self):
        res = self.match("Kinguin", "Legacy of Ancestors PC Steam CD Key",
                         "https://www.kinguin.net/category/478453/legacy-of-ancestors-pc-steam-cd-key",
                         store_id="58")
        self.assertNotIn("(R66)", res.reason)


class GamivoLEditionEstLaVariante(unittest.TestCase):
    """Trouvé au rejeu final (29/09) : [R65] fait trouver `gotham-knights-xbox-series-x`, et la
    ligne Gamivo « Gotham Knights EN United States » (offre 100394637) y ENTRAIT en Deluxe(7) —
    `detect_edition` lit « deluxe » dans le slug de PRODUIT, alors que la variante (dernier
    segment) dit « standard » et le titre ne nomme aucun palier. Refus (fichier marchand)."""

    def _pre(self, title, url):
        return M.precheck_skip(NormalizedOffer(offer_id="1", name=title, url=url,
                                               merchant="Gamivo", store_id="51"), consoles=True)

    def test_deux_editions_dans_l_url_refus(self):
        reason = self._pre("Gotham Knights EN United States",
                           "https://www.gamivo.com/product/gotham-knights-deluxe-edition-xbox-xboxseries-us-en-standard")
        self.assertIn("Gamivo edition contradiction", reason)
        self.assertIn("DELUXE", reason)
        from src import aks_lists
        self.assertIsNone(aks_lists.suggest_target_list(reason), "reste en attente, jamais déplacée")

    def test_la_soeur_deluxe_et_le_standard_ordinaire_passent(self):
        self.assertIsNone(self._pre(
            "Gotham Knights Deluxe Edition EN United States",
            "https://www.gamivo.com/product/gotham-knights-deluxe-edition-xbox-xboxseries-us-en-deluxe"))
        self.assertIsNone(self._pre(
            "WWE 2K26 EN United Kingdom", "https://www.gamivo.com/product/wwe-2k26-xbox-xbox-series-uk-standard"))
        self.assertIsNone(self._pre(
            "Tiny Tina's Wonderlands United States",
            "https://www.gamivo.com/product/tiny-tinas-wonderlands-pc-steam-us-standard"))


class LaGardeTransmetLaQuestion(unittest.TestCase):
    """`match_feed` enveloppe TOUJOURS le résolveur dans la garde de throttle, qui prend
    ``**kwargs`` : « accepte-t-il keep_country / catalog ? » doit valoir pour le résolveur gardé.
    Avant : oui pour tout résolveur → `TypeError` sur un résolveur qui ne les connaît pas."""

    def setUp(self):
        self.addCleanup(M.set_aks_search, None)

    def test_accepts_kwarg_regarde_sous_la_garde(self):
        guard = M._ThrottleGuard(lambda name: None)
        self.assertFalse(M._accepts_kwarg(guard, "catalog"))
        self.assertFalse(M._accepts_kwarg(guard, "keep_country"))
        self.assertTrue(M._accepts_kwarg(M._ThrottleGuard(resolve_aks), "catalog"))

    def test_match_feed_avec_un_resolveur_simple_ne_plante_pas(self):
        """Ligne Driffle RÉELLE (pays dans le nom : `keep_country`) et ligne Eneba réelle
        (génération déduite : `catalog`), résolveur qui ne connaît ni l'un ni l'autre."""

        feed = NormalizedFeed(run_id="r", merchant="Driffle", fetched_at="t", offers=(
            NormalizedOffer(offer_id="1", merchant="Driffle", store_id="127",
                            name="Assassin's Creed Chronicles China (Europe) (Xbox One / Xbox Series X|S) - Xbox Live - Digital Key",
                            url="https://www.driffle.com/assassins-creed-chronicles-china-europe-xbox-one-xbox-series-xs-xbox-live-digital-key-p9933983"),
            NormalizedOffer(offer_id="2", merchant="Eneba", store_id="19",
                            name="Worms Armageddon: Anniversary Edition XBOX LIVE Key EUROPE",
                            url="https://www.eneba.com/xbox-worms-armageddon-anniversary-edition-xbox-live-key-europe")))
        _c, skipped = match_feed(feed, lambda name, page_kind="cd-key": None, consoles=True,
                                 page_resolver=lambda url: None)
        reasons = [s.reason for s in skipped]
        self.assertIn("cannot keep it", reasons[0])
        self.assertIn("no AKS product page found", reasons[1])

    def test_mode_inconnu(self):
        with self.assertRaises(ValueError):
            resolve_aks("Aura Farming", lambda *a, **k: None, catalog="toujours")


# ─────────────────────── aks_search : rythme, reprise, budget, coupure ────────────────────
class _Api(unittest.TestCase):
    """Le faux GET EST `aks_env.http_get` (patché) : le rythme et l'attente de reprise ne
    s'appliquent qu'au vrai GET, c'est donc ce chemin-là qu'on regarde."""

    def setUp(self):
        self.sleeps = []
        self.status = [(200, _api_bodies()["The Tartarus"])]
        self.calls = []

        def fake(url, timeout=8, user_agent=None, **_kw):
            self.calls.append(url)
            st, body = self.status[min(len(self.calls), len(self.status)) - 1]
            return HttpProbeResult(url=url, ok=st == 200, status=st, body=body)

        self.fake = fake
        patcher = unittest.mock.patch.object(aks_env, "http_get", fake)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.now = [1_800_000_000.0]

    def session(self, **kw):
        return AksCatalogSearch(sleep=self.sleeps.append, now=lambda: self.now[0], **kw)

    def lookup(self, s, query):
        return s.lookup("cd-key", query, aks_env.http_get, lambda p: [], filter_version=2)


class RythmeRepriseBudget(_Api):
    def test_une_seconde_au_moins_entre_deux_requetes(self):
        s = self.session()
        self.lookup(s, "The Tartarus")
        self.lookup(s, "Other Title")
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(len(self.sleeps), 1)
        self.assertTrue(0.5 < self.sleeps[0] <= aks_search.MIN_INTERVAL_S, self.sleeps)
        self.assertGreaterEqual(aks_search.MIN_INTERVAL_S, 1.0)

    def test_une_reprise_apres_deux_secondes_et_comptee(self):
        self.status = [(503, ""), (503, "")]
        s = self.session()
        with self.assertRaises(aks_search.AksSearchUnavailable):
            self.lookup(s, "The Tartarus")
        self.assertEqual(len(self.calls), 2)
        self.assertIn(aks_search.RETRY_WAIT_S, self.sleeps)
        self.assertGreaterEqual(aks_search.RETRY_WAIT_S, 2.0)
        self.assertEqual((s.used, s.stats["requests"]), (2, 2), "la reprise est comptée")

    def test_la_reprise_respecte_le_budget(self):
        self.status = [(503, "")]
        s = self.session(budget=1)
        with self.assertRaises(aks_search.AksSearchUnavailable):
            self.lookup(s, "The Tartarus")
        self.assertEqual((len(self.calls), s.used), (1, 1), "budget 1 : jamais de reprise")

    def test_la_portee_du_budget_est_dite(self):
        self.assertEqual(self.session().meta()["budget_scope"], aks_search.BUDGET_SCOPE)
        self.assertIn("partagé par les marchands", aks_search.BUDGET_SCOPE)


class LaCoupureExpireSaufVersionRetiree(_Api):
    def test_corps_illisible_coupe_une_demi_heure(self):
        self.status = [(200, "<!doctype html><html>maintenance</html>"),
                       (200, _api_bodies()["The Tartarus"])]
        s = self.session()
        with self.assertRaises(aks_search.AksSearchChanged):
            self.lookup(s, "The Tartarus")
        self.assertEqual(s.disabled_until, self.now[0] + aks_search.UNREADABLE_DISABLE_S)
        self.now[0] += aks_search.UNREADABLE_DISABLE_S - 1
        self.assertIsNone(self.lookup(s, "The Tartarus"), "encore coupée")
        self.assertEqual(len(self.calls), 1)
        self.now[0] += 2
        self.assertEqual(self.lookup(s, "The Tartarus"), [], "l'échéance est passée : elle reprend")
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(s.disabled_reason, "")
        self.assertEqual(aks_search.UNREADABLE_DISABLE_S, 30 * 60, "la demi-heure de R30")

    def test_version_retiree_coupe_tout_le_balayage(self):
        self.status = [(404, "")]
        s = self.session()
        with self.assertRaises(aks_search.AksSearchChanged):
            self.lookup(s, "The Tartarus")
        self.now[0] += 10 * aks_search.UNREADABLE_DISABLE_S
        self.assertIsNone(self.lookup(s, "The Tartarus"))
        self.assertEqual((len(self.calls), s.disabled_until), (1, 0.0))

    def test_l_echeance_traverse_les_pages_du_balayage(self):
        self.status = [(200, '{"items":[]}')]
        s = self.session()
        with self.assertRaises(aks_search.AksSearchChanged):
            self.lookup(s, "The Tartarus")
        with tempfile.TemporaryDirectory() as d:
            path = str(Path(d) / "aks_search.json")
            aks_search.save_sweep_state(path, s)
            used, reason, until = aks_search.load_sweep_state(path, 1000, now=lambda: self.now[0])
            self.assertEqual((used, until), (1, self.now[0] + aks_search.UNREADABLE_DISABLE_S))
            self.assertTrue(reason)
            later = self.now[0] + aks_search.UNREADABLE_DISABLE_S
            self.assertEqual(aks_search.load_sweep_state(path, 1000, now=lambda: later), (1, "", 0.0))


if __name__ == "__main__":
    unittest.main()

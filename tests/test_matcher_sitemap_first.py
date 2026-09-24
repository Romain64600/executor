"""Sitemap d'abord : les passes 1-2 ne sondent que ce que l'index confirme (2026-09-24).

Romain : « go pour le matching sitemap d'abord », après l'audit du parallélisme du 23/09. Une
offre sans page AKS coûtait ~4,7 sondes aveugles qui répondaient toutes 404 — slug complet,
slug sans édition, tête de titre, variantes année, forme ancienne. Avec un index frais, on sait
sans requête lesquelles existent.

Trois choses à tenir, et ce fichier les épingle une par une :

* sans index frais, RIEN ne change (le fail-closed d'AGENTS.md : « je ne sais pas » n'est
  jamais « la page n'existe pas ») ;
* la SOUPAPE : la toute première sonde part toujours — le sitemap a des trous
  (``buy-the-front-cd-key`` répondait 200 le 24/09 sans être dans l'index du 23) ;
* la forme ANCIENNE ``compare-and-buy-…`` se juge sur la liste à part de l'index, et un
  index qui ne l'a pas cherchée ne peut pas l'écarter.
"""

import datetime
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import src.matcher as M  # noqa: E402
from src.aks_env import HttpProbeResult  # noqa: E402
from src.aks_sitemap import SitemapIndex, refresh  # noqa: E402
from src.matcher import AksProbeUnreliable, resolve_aks  # noqa: E402

PAGE = (
    '<html><head>'
    '<meta property="og:title" content="Buy Far Cry 3 CD Key Compare Prices">'
    '</head><body>'
    '<div data-product-id="555"></div>'
    '<script>var x={"editions":{"1":{"name":"Standard"}}};</script>'
    '</body></html>'
)
BUY = "https://www.allkeyshop.com/blog/buy-{}-compare-prices/"
LEGACY = "https://www.allkeyshop.com/blog/compare-and-buy-cd-key-for-digital-download-{}/"


def _maintenant():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _index(entries, legacy=(), legacy_indexed=True):
    return SitemapIndex(entries=frozenset(entries), fetched_at=_maintenant(),
                        incomplete=False, legacy=frozenset(legacy),
                        legacy_indexed=legacy_indexed)


def _get(repond=()):
    """Un faux GET qui note chaque URL et ne répond 200 qu'à celles de ``repond``."""

    vus = []

    def faux_get(url, **kw):
        vus.append(url)
        if url in repond:
            return HttpProbeResult(url=url, ok=True, status=200, body=PAGE)
        return HttpProbeResult(url=url, ok=False, status=404, body="")
    return faux_get, vus


class SitemapDabord(unittest.TestCase):
    def setUp(self):
        M.set_sitemap_index(None)
        M.reset_sitemap_first_stats()
        self.addCleanup(M._SITEMAP_CACHE.clear)
        self.addCleanup(M.reset_sitemap_first_stats)

    # -- sans index frais : le matcher d'hier -----------------------------------------
    def test_sans_index_toutes_les_sondes_partent_comme_avant(self):
        faux_get, vus = _get()
        with mock.patch.object(M, "search_aks_slugs", return_value=[]):
            self.assertIsNone(resolve_aks("Far Cry 3 Deluxe Edition", faux_get))
        attendues = [u for _, u in M.sitemap_first_probes(
            [(s, M.aks_url(s)) for s in M.build_slug_candidates("Far Cry 3 Deluxe Edition")])]
        self.assertTrue(set(attendues) <= set(vus))
        self.assertTrue(any("compare-and-buy" in u for u in vus),
                        "sans index, la forme ancienne est sondée comme avant")
        self.assertTrue(any(re.search(r"-20\d\d-cd-key-", u) for u in vus),
                        "sans index, les variantes année sont sondées comme avant")
        self.assertEqual(M.SITEMAP_FIRST_STATS["probes_skipped"], 0)

    # -- avec index : seulement ce qu'AKS publie, plus la soupape ----------------------
    def test_seules_les_formes_confirmees_partent_apres_la_soupape(self):
        M.set_sitemap_index(_index(["far-cry-3-cd-key"]))
        faux_get, vus = _get({BUY.format("far-cry-3-cd-key")})
        res = resolve_aks("Far Cry 3 Deluxe Edition", faux_get)
        self.assertIsNotNone(res)
        self.assertEqual(vus, [BUY.format("far-cry-3-deluxe-edition-cd-key"),   # soupape
                               BUY.format("far-cry-3-cd-key")],                  # confirmée
                         "aucune sonde aveugle entre la soupape et la page confirmée")
        self.assertEqual(M.SITEMAP_FIRST_STATS["valve_unconfirmed"], 1)
        self.assertGreater(M.SITEMAP_FIRST_STATS["probes_skipped"], 0)

    def test_une_offre_sans_page_ne_coute_plus_quune_requete(self):
        M.set_sitemap_index(_index(["un-autre-jeu-cd-key"]))
        faux_get, vus = _get()
        with mock.patch.object(M, "search_aks_slugs", return_value=[]) as recherche:
            self.assertIsNone(resolve_aks("Far Cry 3 Deluxe Edition", faux_get))
        self.assertEqual(vus, [BUY.format("far-cry-3-deluxe-edition-cd-key")],
                         "la soupape seule — ni tiers, ni années, ni forme ancienne")
        self.assertFalse(recherche.called)

    def test_la_soupape_trouve_une_page_absente_du_sitemap(self):
        """Le cas mesuré le 24/09 : `buy-the-front-cd-key` répond 200, l'index l'ignore."""

        M.set_sitemap_index(_index(["un-autre-jeu-cd-key"]))
        faux_get, vus = _get({BUY.format("the-front-cd-key")})
        res = resolve_aks("The Front", faux_get)
        self.assertIsNotNone(res, "la page neuve doit être trouvée par la soupape")
        self.assertEqual(vus, [BUY.format("the-front-cd-key")])

    def test_la_soupape_ne_vaut_que_pour_la_PREMIERE_sonde(self):
        M.set_sitemap_index(_index([]))
        sondes = [("a", BUY.format("a-cd-key")), ("b", BUY.format("b-cd-key")),
                  ("c", BUY.format("c-cd-key"))]
        self.assertEqual(M.sitemap_first_probes(sondes), sondes[:1])

    def test_une_variante_annee_se_confirme_par_son_propre_segment(self):
        M.set_sitemap_index(_index(["fable-2026-cd-key"]))
        sondes = M.aks_page_urls("fable", years=(2026, 2027))
        gardees = [v for v, _ in M.sitemap_first_probes(sondes)]
        self.assertEqual(gardees, ["fable", "fable-2026"],
                         "soupape + la seule année publiée ; ni 2027, ni la forme ancienne")

    def test_un_gabarit_compte_se_confirme_avec_son_gabarit(self):
        M.set_sitemap_index(_index(["ignoble-steam-account"]))
        sondes = [("zzz", BUY.format("zzz-steam-account")),
                  ("ignoble", BUY.format("ignoble-steam-account")),
                  ("ignoble-2", BUY.format("ignoble-2-steam-account"))]
        self.assertEqual([v for v, _ in M.sitemap_first_probes(sondes, "steam-account")],
                         ["zzz", "ignoble"])

    # -- la forme ancienne ---------------------------------------------------------------
    def test_la_forme_ancienne_publiee_est_sondee_et_resout(self):
        M.set_sitemap_index(_index(["un-autre-jeu-cd-key"], legacy=["far-cry-3"]))
        faux_get, vus = _get({LEGACY.format("far-cry-3")})
        res = resolve_aks("Far Cry 3", faux_get)
        self.assertIsNotNone(res, "Far Cry 3 vit sur une page ancienne : elle doit être trouvée")
        self.assertEqual(vus, [BUY.format("far-cry-3-cd-key"), LEGACY.format("far-cry-3")])

    def test_la_forme_ancienne_absente_dun_index_qui_la_cherchee_nest_pas_sondee(self):
        M.set_sitemap_index(_index(["un-autre-jeu-cd-key"], legacy=["borderlands-2"]))
        faux_get, vus = _get()
        with mock.patch.object(M, "search_aks_slugs", return_value=[]):
            resolve_aks("Far Cry 3", faux_get)
        self.assertFalse([u for u in vus if "compare-and-buy" in u])

    def test_un_index_qui_na_pas_cherche_les_pages_anciennes_ne_les_ecarte_pas(self):
        """Un fichier d'avant le 24/09 : son silence sur la forme ancienne ne prouve rien."""

        M.set_sitemap_index(_index(["un-autre-jeu-cd-key"], legacy_indexed=False))
        faux_get, vus = _get()
        with mock.patch.object(M, "search_aks_slugs", return_value=[]):
            resolve_aks("Far Cry 3", faux_get)
        self.assertIn(LEGACY.format("far-cry-3"), vus)

    # -- MA1 et la passe 3 -------------------------------------------------------------
    def test_un_429_sur_une_sonde_gardee_leve_toujours_immediatement(self):
        M.set_sitemap_index(_index(["far-cry-3-cd-key", "far-cry-3-key"]))

        def faux_get(url, **kw):
            if url == BUY.format("far-cry-3-cd-key"):
                return HttpProbeResult(url=url, ok=False, status=429, body="")
            return HttpProbeResult(url=url, ok=False, status=404, body="")

        with self.assertRaises(AksProbeUnreliable) as ctx:
            resolve_aks("Far Cry 3", faux_get)
        self.assertEqual(ctx.exception.status, 429)

    def test_la_passe_3_ne_resonde_pas_une_url_deja_sondee(self):
        """Le slug exact indexé : l'aplatissement de la passe 3 retombait sur la même URL."""

        M.set_sitemap_index(_index(["far-cry-3-cd-key"]))
        faux_get, vus = _get()
        with mock.patch.object(M, "search_aks_slugs", return_value=[]):
            self.assertIsNone(resolve_aks("Far Cry 3", faux_get))
        self.assertEqual(vus.count(BUY.format("far-cry-3-cd-key")), 1,
                         f"une URL, une requête : {vus}")


class LIndexGardeLesPagesAnciennesAPart(unittest.TestCase):
    NS = b'<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'

    def _refresh(self, tmp):
        index = (b'<?xml version="1.0"?><sitemapindex xmlns="http://www.sitemaps.org/'
                 b'schemas/sitemap/0.9"><sitemap><loc>https://www.allkeyshop.com/blog/'
                 b'page-sitemap.xml</loc></sitemap></sitemapindex>')
        pages = (self.NS
                 + b"<url><loc>https://www.allkeyshop.com/blog/buy-hades-cd-key-compare-prices/"
                   b"</loc></url>"
                 + b"<url><loc>https://www.allkeyshop.com/blog/compare-and-buy-cd-key-for-"
                   b"digital-download-far-cry-3/</loc></url></urlset>")
        corps = {"https://www.allkeyshop.com/blog/sitemap_index.xml": index,
                 "https://www.allkeyshop.com/blog/page-sitemap.xml": pages}
        dest = Path(tmp) / "idx.json"
        resume = refresh(dest, fetch=corps.__getitem__, sleep=lambda s: None)
        return dest, resume

    def test_le_releve_capture_les_pages_anciennes_sans_les_melanger(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest, resume = self._refresh(tmp)
            self.assertEqual(resume["legacy_pages"], 1)
            idx = SitemapIndex.load(dest)
            self.assertTrue(idx.legacy_indexed)
            self.assertTrue(idx.has_legacy("far-cry-3"))
            self.assertFalse(idx.has_legacy("hades"))
            self.assertEqual(idx.entries, frozenset({"hades-cd-key"}),
                             "une page ancienne n'a pas de gabarit : jamais dans `entries`")

    def test_un_fichier_davant_le_24_09_repond_je_ne_sais_pas(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "vieux.json"
            p.write_text(json.dumps({"entries": ["hades-cd-key"],
                                     "fetched_at": _maintenant(), "incomplete": False}))
            idx = SitemapIndex.load(p)
            self.assertFalse(idx.legacy_indexed)
            self.assertIsNone(idx.has_legacy("far-cry-3"))


if __name__ == "__main__":
    unittest.main()

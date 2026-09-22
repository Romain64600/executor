"""La passe 3 du résolveur : l'index sitemap (2026-09-22).

Romain : « n'oublie pas le gabarit -key et l'index sitemap ».

Le contexte, qui explique pourquoi cette passe existe. La recherche interne d'AKS (R30) était
notre seul recours quand aucun slug deviné ne répondait. Mesurée le 2026-09-22 depuis les DEUX
VPS, elle rend ``HTTP 200`` avec ``Content-Length: 0`` : un corps vide. Son disjoncteur était
ouvert sur 253 des 259 pages du balayage de nuit, et 9 719 lignes en sont ressorties « no AKS
product page found » — soit 4 152 offres DISTINCTES (la même offre est refusée à plusieurs
pages). Confrontées au sitemap d'AKS, 546 d'entre elles ont POURTANT une page.

La passe 3 en rattrape **226** : celles dont la page est une autre façon d'écrire « une clé »
(le gabarit ``-key``). Les autres — 246 pages compte Steam, des pages console — ne sont PAS
rattrapées ici, et c'est délibéré : un compte n'est pas une clé, une page console a sa propre
branche. Elles restent « pas de page » pour le matcher, et l'export de tri les RETIENT au lieu
de les déplacer en 22.

Le coût est nul quand l'index ne connaît rien : c'est une lecture locale qui DIT quelles URL
sonder, au lieu d'en deviner d'autres à l'aveugle (la leçon du 2026-09-10 : sonder plus de
formes poussait ~300 req/min et AKS répondait 503).
"""

import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import src.matcher as M  # noqa: E402
from src.aks_env import HttpProbeResult  # noqa: E402
from src.aks_sitemap import SitemapIndex  # noqa: E402
from src.matcher import AksProbeUnreliable, resolve_aks  # noqa: E402

PAGE = (
    '<html><head>'
    '<meta property="og:title" content="Buy Ignoble CD Key Compare Prices">'
    '</head><body>'
    '<div data-product-id="424242"></div>'
    '<script>var x={"editions":{"1":{"name":"Standard"}}};</script>'
    '</body></html>'
)


def _index(entries, fetched_at=None, incomplete=False):
    import datetime
    fetched_at = fetched_at or datetime.datetime.now(
        datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return SitemapIndex(entries=frozenset(entries), fetched_at=fetched_at,
                        incomplete=incomplete)


class LaPasse3(unittest.TestCase):
    def setUp(self):
        M.set_sitemap_index(None)
        self.addCleanup(M._SITEMAP_CACHE.clear)

    # -- le comportement d'avant, intact --------------------------------------------
    def test_sans_index_rien_ne_change(self):
        """Fail-closed par défaut : pas d'index = exactement le matcher d'hier, recherche
        comprise. Un index absent ne doit jamais devenir « AKS n'a pas la page »."""

        vus = []

        def faux_get(url, **kw):
            vus.append(url)
            return HttpProbeResult(url=url, ok=False, status=404, body="")

        with mock.patch.object(M, "search_aks_slugs", return_value=[]) as recherche:
            self.assertIsNone(resolve_aks("Ignoble", faux_get))
        self.assertTrue(recherche.called, "sans index, la recherche R30 reste le recours")
        self.assertTrue(all("-cd-key-" in u or "compare-and-buy" in u for u in vus),
                        f"aucune forme nouvelle ne doit être sondée : {vus[:6]}")

    def test_un_index_incomplet_ou_perime_ne_fait_pas_autorite(self):
        for nom, index in (("incomplet", _index(["ignoble-key"], incomplete=True)),
                           ("périmé", _index(["ignoble-key"], fetched_at="2020-01-01T00:00:00Z"))):
            with self.subTest(index=nom):
                import tempfile, json as j
                with tempfile.TemporaryDirectory() as tmp:
                    p = Path(tmp) / "idx.json"
                    p.write_text(j.dumps({"entries": sorted(index.entries),
                                          "fetched_at": index.fetched_at,
                                          "incomplete": index.incomplete}))
                    self.assertIsNone(M.sitemap_index(str(p)),
                                      "un catalogue troué ou vieux ne fait pas autorité")

    # -- ce que la passe 3 apporte ---------------------------------------------------
    def test_le_gabarit_key_est_rattrape_grace_a_lindex(self):
        """Le cas de Romain, mesuré : 226 offres du balayage vivent sur `buy-<slug>-key-`."""

        M.set_sitemap_index(_index(["ignoble-key"]))
        vus = []

        def faux_get(url, **kw):
            vus.append(url)
            if url.endswith("buy-ignoble-key-compare-prices/"):
                return HttpProbeResult(url=url, ok=True, status=200, body=PAGE)
            return HttpProbeResult(url=url, ok=False, status=404, body="")

        res = resolve_aks("Ignoble", faux_get)
        self.assertIsNotNone(res, "la page existe : elle doit être résolue")
        self.assertEqual(res.product_id, "424242")
        self.assertIn("buy-ignoble-key-compare-prices/", vus[-1])

    def test_lindex_ne_fait_sonder_QUE_ce_quil_confirme(self):
        """Le coût de la passe 3 est nul quand l'index ne connaît rien — pas une requête."""

        M.set_sitemap_index(_index(["un-autre-jeu-key"]))
        vus = []

        def faux_get(url, **kw):
            vus.append(url)
            return HttpProbeResult(url=url, ok=False, status=404, body="")

        with mock.patch.object(M, "search_aks_slugs", return_value=[]):
            self.assertIsNone(resolve_aks("Ignoble", faux_get))
        self.assertFalse([u for u in vus if u.endswith("-key-compare-prices/")
                          and "-cd-key-" not in u],
                         f"aucune forme non confirmée ne doit être sondée : {vus}")

    def test_la_recherche_MORTE_nest_plus_appelee_quand_lindex_fait_autorite(self):
        """R30 n'est pas retirée : elle est court-circuitée tant que l'index est frais.
        Elle répond `Content-Length: 0` — 3 × 8 s pour rien, à chaque offre irrésolue."""

        M.set_sitemap_index(_index(["un-autre-jeu-key"]))
        with mock.patch.object(M, "search_aks_slugs", return_value=[]) as recherche:
            resolve_aks("Ignoble", lambda url, **kw: HttpProbeResult(
                url=url, ok=False, status=404, body=""))
        self.assertFalse(recherche.called)

    def test_la_ponctuation_ne_doit_pas_cacher_une_page_qui_existe(self):
        """Trouvé par la vérification du 22/09 : « MotoGP24 » cherche `motogp24` quand AKS
        écrit `motogp-24`, « House of 1,000 Doors » cherche `1-000-doors` contre
        `1000-doors`. Le produit est le même. Le slug rendu doit être celui d'AKS, NU —
        c'est lui que R43 compare au titre (`own_page_slugs`)."""

        M.set_sitemap_index(_index(["motogp-24-cd-key"]))
        formes = M.sitemap_shapes(["motogp24"])
        self.assertEqual(formes, [("motogp-24",
                                   "https://www.allkeyshop.com/blog/"
                                   "buy-motogp-24-cd-key-compare-prices/")])

    def test_laplatissement_ne_rapproche_pas_deux_jeux_differents(self):
        M.set_sitemap_index(_index(["hades-2-cd-key"]))
        self.assertEqual(M.sitemap_shapes(["hades"]), [],
                         "« hades » et « hades-2 » ne s'aplatissent pas pareil")

    # -- les gardes de la passe 3 ----------------------------------------------------
    def test_un_503_sur_une_page_annoncee_remonte_a_la_garde_de_throttle(self):
        """AKS qui pousse doit arrêter le stage, pas devenir un skip silencieux — MA1."""

        M.set_sitemap_index(_index(["ignoble-key"]))

        def faux_get(url, **kw):
            if url.endswith("buy-ignoble-key-compare-prices/"):
                return HttpProbeResult(url=url, ok=False, status=503, body="")
            return HttpProbeResult(url=url, ok=False, status=404, body="")

        with self.assertRaises(AksProbeUnreliable) as ctx:
            resolve_aks("Ignoble", faux_get)
        self.assertEqual(ctx.exception.status, 503)

    def test_un_404_propre_sur_une_page_annoncee_nest_PAS_une_anomalie(self):
        """Le sitemap est une PHOTO : une page publiée hier peut avoir été retirée. On
        continue, on ne lève pas — sinon toute page supprimée ferait tomber le stage."""

        M.set_sitemap_index(_index(["ignoble-key", "ignoble-game-code"]))
        vus = []

        def faux_get(url, **kw):
            vus.append(url)
            if url.endswith("buy-ignoble-game-code-compare-prices/"):
                return HttpProbeResult(url=url, ok=True, status=200, body=PAGE)
            return HttpProbeResult(url=url, ok=False, status=404, body="")

        res = resolve_aks("Ignoble", faux_get)
        self.assertIsNotNone(res, "la seconde page annoncée doit être essayée")
        self.assertTrue(any("ignoble-key" in u for u in vus),
                        "la première a bien été essayée avant")

    def test_une_page_compte_nouvre_pas_la_passe_3_sur_les_cles(self):
        """`page_kind` non cd-key : la passe 3 ne doit pas rouvrir la porte des clés."""

        M.set_sitemap_index(_index(["ignoble-cd-key", "ignoble-key"]))
        vus = []

        def faux_get(url, **kw):
            vus.append(url)
            return HttpProbeResult(url=url, ok=False, status=404, body="")

        self.assertIsNone(resolve_aks("Ignoble", faux_get, page_kind="steam-account"))
        self.assertEqual(vus, ["https://www.allkeyshop.com/blog/"
                               "buy-ignoble-steam-account-compare-prices/"],
                         "une page compte ne sonde que la sienne")

    def test_une_page_COMPTE_nest_jamais_un_substitut_a_une_cle(self):
        """Mesure du 22/09 : des offres « sans page » ont en fait une page `-steam-account`. Les
        rattraper ici les entrerait sous un AUTRE produit — un compte n'est pas une clé.
        Elles restent « pas de page », et l'export de tri les RETIENT au lieu de les
        déplacer en 22. C'est le partage voulu entre les deux mécanismes."""

        M.set_sitemap_index(_index(["ignoble-steam-account"]))
        vus = []

        def faux_get(url, **kw):
            vus.append(url)
            # la page compte RÉPOND — si la passe 3 la sondait, elle résoudrait dessus
            if "steam-account" in url:
                return HttpProbeResult(url=url, ok=True, status=200, body=PAGE)
            return HttpProbeResult(url=url, ok=False, status=404, body="")

        with mock.patch.object(M, "search_aks_slugs", return_value=[]):
            res = resolve_aks("Ignoble", faux_get)
        self.assertFalse([u for u in vus if "steam-account" in u],
                         f"la page compte ne doit jamais être sondée pour une clé : {vus}")
        self.assertIsNone(res, "et surtout : aucune résolution ne doit en sortir")


if __name__ == "__main__":
    unittest.main()

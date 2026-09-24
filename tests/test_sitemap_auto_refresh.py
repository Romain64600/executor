"""Relevé automatique de l'index sitemap au lancement d'un balayage (2026-09-24).

Romain : « oui pour le refresh auto ». Sans relevé, l'index expire au bout de sept jours et le
matching « sitemap d'abord » se coupe tout seul ; une page publiée entre deux relevés reste
invisible jusqu'au suivant. Aucun test ne touche le réseau : `fetch` est bouchonné.
"""

import importlib.util
import json
import pathlib
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.aks_sitemap import SITEMAP_INDEX_URL, SitemapIndex, ensure_fresh  # noqa: E402

_NS_INDEX = (b'<?xml version="1.0" encoding="UTF-8"?>'
             b'<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">')
_NS_URLSET = (b'<?xml version="1.0" encoding="UTF-8"?>'
              b'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">')
_INDEX = (_NS_INDEX
          + b"<sitemap><loc>https://www.allkeyshop.com/blog/page-sitemap.xml</loc></sitemap>"
          + b"</sitemapindex>")
_PAGE = (_NS_URLSET
         + b"<url><loc>https://www.allkeyshop.com/blog/buy-hades-cd-key-compare-prices/</loc></url>"
         + b"<url><loc>https://www.allkeyshop.com/blog/"
         + b"compare-and-buy-cd-key-for-digital-download-far-cry-3/</loc></url>"
         + b"</urlset>")

MAINTENANT = datetime(2026, 9, 24, 18, 0, tzinfo=timezone.utc).timestamp()


def _ecrire(chemin, *, fetched_at, incomplete=False, legacy_indexed=True):
    chemin.write_text(json.dumps({
        "fetched_at": fetched_at, "incomplete": incomplete, "legacy_indexed": legacy_indexed,
        "legacy": ["ancienne"] if legacy_indexed else [], "entries": ["ancien-cd-key"],
    }), encoding="utf-8")


class _Fetch:
    def __init__(self, pages=None, boom=None):
        self.appels = []
        self.pages = pages if pages is not None else {
            SITEMAP_INDEX_URL: _INDEX,
            "https://www.allkeyshop.com/blog/page-sitemap.xml": _PAGE,
        }
        self.boom = boom

    def __call__(self, url):
        self.appels.append(url)
        if self.boom:
            raise self.boom
        return self.pages[url]


def _assurer(chemin, fetch):
    return ensure_fresh(chemin, fetch=fetch, sleep=lambda s: None, now=lambda: MAINTENANT)


class LeReleveNePartQueSiLIndexEnABesoin(unittest.TestCase):
    def setUp(self):
        self.dossier = pathlib.Path(tempfile.mkdtemp())
        self.chemin = self.dossier / "aks_sitemap.json"

    def test_un_index_du_jour_nest_pas_releve(self):
        _ecrire(self.chemin, fetched_at="2026-09-24T08:00:00Z")          # 10 h
        fetch = _Fetch()
        resume = _assurer(self.chemin, fetch)
        self.assertEqual(fetch.appels, [], "aucune requête quand l'index a moins de 20 h")
        self.assertFalse(resume["refreshed"])

    def test_un_index_de_la_veille_est_releve_et_remplace(self):
        _ecrire(self.chemin, fetched_at="2026-09-23T14:00:00Z")          # 28 h
        resume = _assurer(self.chemin, _Fetch())
        self.assertTrue(resume["refreshed"], resume)
        index = SitemapIndex.load(self.chemin)
        self.assertTrue(index.has_page("hades-cd-key"))
        self.assertTrue(index.has_legacy("far-cry-3"))
        self.assertEqual(sorted(p.name for p in self.dossier.iterdir()), ["aks_sitemap.json"],
                         "aucun fichier temporaire ne doit traîner")

    def test_absent_troue_ou_sans_pages_anciennes_declenche_le_releve(self):
        for prepare in (lambda: None,
                        lambda: _ecrire(self.chemin, fetched_at="2026-09-24T17:00:00Z",
                                        incomplete=True),
                        lambda: _ecrire(self.chemin, fetched_at="2026-09-24T17:00:00Z",
                                        legacy_indexed=False)):
            self.chemin.unlink(missing_ok=True)
            prepare()
            fetch = _Fetch()
            resume = _assurer(self.chemin, fetch)
            self.assertTrue(resume["refreshed"], resume)
            self.assertIn(SITEMAP_INDEX_URL, fetch.appels)


class UnReleveRateNeCasseRien(unittest.TestCase):
    def setUp(self):
        self.chemin = pathlib.Path(tempfile.mkdtemp()) / "aks_sitemap.json"

    def test_le_reseau_en_panne_ne_leve_pas_et_garde_lancien(self):
        _ecrire(self.chemin, fetched_at="2026-09-22T18:00:00Z")          # 2 jours
        avant = self.chemin.read_text()
        resume = _assurer(self.chemin, _Fetch(boom=OSError("ERR_CONNECTION_REFUSED")))
        self.assertFalse(resume["refreshed"])
        self.assertIn("ERR_CONNECTION_REFUSED", resume["error"])
        self.assertEqual(self.chemin.read_text(), avant, "l'ancien index reste en place")

    def test_un_releve_troue_ne_remplace_pas_un_index_complet_encore_valable(self):
        _ecrire(self.chemin, fetched_at="2026-09-22T18:00:00Z")
        avant = self.chemin.read_text()
        fetch = _Fetch(pages={SITEMAP_INDEX_URL: _INDEX,
                              "https://www.allkeyshop.com/blog/page-sitemap.xml": b"<html>503</html>"})
        resume = _assurer(self.chemin, fetch)
        self.assertFalse(resume["refreshed"])
        self.assertIn("troué", resume["error"])
        self.assertEqual(self.chemin.read_text(), avant)
        self.assertEqual(sorted(p.name for p in self.chemin.parent.iterdir()), ["aks_sitemap.json"])

    def test_un_releve_troue_remplace_un_index_perime(self):
        """Un index de plus de sept jours ne fait plus autorité : un relevé troué, qui le DIT,
        ne vaut pas moins que lui."""

        _ecrire(self.chemin, fetched_at="2026-09-10T18:00:00Z")
        deux = (_NS_INDEX
                + b"<sitemap><loc>https://www.allkeyshop.com/blog/page-sitemap.xml</loc></sitemap>"
                + b"<sitemap><loc>https://www.allkeyshop.com/blog/page-sitemap2.xml</loc></sitemap>"
                + b"</sitemapindex>")
        fetch = _Fetch(pages={SITEMAP_INDEX_URL: deux,
                              "https://www.allkeyshop.com/blog/page-sitemap.xml": _PAGE,
                              "https://www.allkeyshop.com/blog/page-sitemap2.xml": b"<html>503</html>"})
        resume = _assurer(self.chemin, fetch)
        self.assertTrue(resume["refreshed"])
        self.assertTrue(SitemapIndex.load(self.chemin).incomplete)


class LeBalayageLeDemandeEtLeDit(unittest.TestCase):
    """`scripts/10_data_entry_auto.py --sitemap-refresh`, et la console qui le passe toujours."""

    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location(
            "sweep10_refresh", ROOT / "scripts" / "10_data_entry_auto.py")
        cls.MOD = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.MOD)

    def _main(self, argv, run_id):
        recap = {"merchant": "Kinguin", "store_id": "58", "pages": [], "total_created": 0,
                 "halted": None}
        releve = mock.Mock(return_value={"refreshed": True, "reason": "absent", "pages": 3})
        with mock.patch.object(self.MOD, "run_sweep", return_value=recap), \
                mock.patch.object(self.MOD, "refresh_sitemap_if_stale", releve), \
                mock.patch.object(sys, "argv", ["10_data_entry_auto.py", "--targets", "Kinguin:58",
                                                "--run-id", run_id] + argv):
            code = self.MOD.main()
        saved = json.loads((self.MOD.ROOT / "runs" / run_id / "recap.json").read_text())
        return code, releve, saved

    def tearDown(self):
        import shutil
        for rid in ("t-sitemap-oui", "t-sitemap-non"):
            shutil.rmtree(self.MOD.ROOT / "runs" / rid, ignore_errors=True)

    def test_avec_le_drapeau_le_releve_part_une_fois_et_entre_au_recap(self):
        code, releve, saved = self._main(["--sitemap-refresh"], "t-sitemap-oui")
        self.assertEqual(code, 0)
        releve.assert_called_once_with()
        self.assertEqual(saved["sitemap_refresh"]["reason"], "absent")

    def test_sans_le_drapeau_aucun_releve(self):
        code, releve, saved = self._main([], "t-sitemap-non")
        self.assertEqual(code, 0)
        releve.assert_not_called()
        self.assertNotIn("sitemap_refresh", saved)

    def test_la_console_le_passe_toujours(self):
        src = (ROOT / "src" / "admin" / "submit_manager.py").read_text(encoding="utf-8")
        bloc = src[src.index("def start_data_entry_auto"):]
        bloc = bloc[:bloc.index("return self._spawn(")]
        self.assertIn('"--sitemap-refresh"', bloc)


if __name__ == "__main__":
    unittest.main()

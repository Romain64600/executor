"""Le catalogue des pages AKS (Romain, 2026-09-21 : « on peut créer une DB partagée sur nos
VPS, non ? »).

Ce que ces tests verrouillent, dans l'ordre d'importance :
1. **jamais un échec en cache** — une page « pas trouvée » ne doit PAS devenir un souvenir ;
2. **jamais une raison d'échouer** — base illisible, hôte injoignable : le match continue ;
3. la nature de page telle que Romain l'a définie, et les deux axes (contenu / gabarit) ;
4. la durée de vie : un vieux relevé n'est plus une réponse, sans être effacé.
"""

from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import time
import unittest
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.page_catalog import (  # noqa: E402
    NATURE_DLC,
    NATURE_EARLY_ACCESS,
    NATURE_STANDARD,
    NATURE_UNKNOWN,
    CatalogRecorder,
    PageCatalog,
    PageRecord,
    catalog_from_spec,
    describe,
    page_nature,
)


@dataclass
class _Res:
    slug: str
    url: str
    product_id: str = "1"
    aks_name: str = "Jeu"
    editions: dict | None = None
    regions: dict | None = None
    official_platforms: tuple = ()
    console_pages: dict | None = None
    page_platform: str = ""


class LaNatureDeLaPage(unittest.TestCase):
    """« C'est une page standard, une page DLC, une page early access… »"""

    def test_les_natures_de_romain(self):
        self.assertEqual(page_nature({"1": {"name": "Standard"}}), NATURE_STANDARD)
        self.assertEqual(page_nature({"16": {"name": "DLC"}}), NATURE_DLC)
        self.assertEqual(page_nature({"5": {"name": "Early Access"}}), NATURE_EARLY_ACCESS)
        self.assertEqual(page_nature({}), NATURE_UNKNOWN)

    def test_une_page_sans_standard_mais_avec_du_dlc_est_une_page_dlc(self):
        # Le cas « Diablo IV Lord of Hatred » : {DLC, Deluxe, Ultimate}, pas de Standard.
        self.assertEqual(page_nature({"16": "DLC", "7": "Deluxe", "21": "Ultimate"}), NATURE_DLC)

    def test_standard_prime_quand_il_coexiste(self):
        # Un seau DLC À CÔTÉ de Standard ne fait pas une page DLC — c'est la même prudence
        # que [R18] depuis le durcissement du 2026-09-17.
        self.assertEqual(page_nature({"1": "Standard", "16": "DLC"}), NATURE_STANDARD)
        self.assertEqual(page_nature({"1": "Standard", "5": "Early Access"}), NATURE_STANDARD)

    def test_le_gabarit_est_un_AUTRE_axe(self):
        """La page compte de « Subnautica 2 » est À LA FOIS une page de compte Steam et une
        page d'accès anticipé — c'est le second axe qui a fait entrer 4 offres en Standard."""

        nature = page_nature({"5": {"name": "Early Access"}}, "steam-account")
        self.assertEqual(nature, NATURE_EARLY_ACCESS)
        self.assertEqual(describe({"page_kind": "steam-account", "nature": nature}),
                         "page compte Steam, accès anticipé (sans date de sortie connue)")
        self.assertEqual(describe({"page_kind": "xbox-series", "nature": NATURE_STANDARD}),
                         "page console Xbox Series, standard")
        self.assertEqual(describe({"page_kind": "cd-key", "nature": NATURE_DLC}),
                         "page de clé, DLC")

    def test_la_date_de_sortie_est_dite_quand_on_la_connait(self):
        self.assertIn("jusqu'au 2026-11-12", describe(
            {"page_kind": "cd-key", "nature": NATURE_EARLY_ACCESS,
             "early_access_until": "2026-11-12"}))


class LeCatalogueLocal(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = str(Path(self.tmp.name) / "cat.db")
        self.cat = PageCatalog(self.db, source="test")

    def _rec(self, slug="jeu", kind="cd-key", editions=None, read_at=""):
        return PageRecord.from_resolution(
            _Res(slug=slug, url=f"https://aks/{slug}", aks_name="Jeu",
                 editions=editions or {"1": {"name": "Standard"}}, regions={"2": "GLOBAL"}),
            page_kind=kind, source="test")

    def test_ecrire_puis_relire(self):
        self.assertEqual(self.cat.put_many([self._rec()]), 1)
        row = self.cat.get("jeu")
        self.assertEqual(row["slug"], "jeu")
        self.assertEqual(row["nature"], NATURE_STANDARD)
        self.assertEqual(row["editions"], {"1": {"name": "Standard"}})
        self.assertEqual(row["regions"], {"2": "GLOBAL"})

    def test_le_meme_slug_sous_deux_gabarits_sont_deux_pages(self):
        self.cat.put_many([self._rec(kind="cd-key"),
                           self._rec(kind="steam-account", editions={"5": "Early Access"})])
        self.assertEqual(self.cat.get("jeu", "cd-key")["nature"], NATURE_STANDARD)
        self.assertEqual(self.cat.get("jeu", "steam-account")["nature"], NATURE_EARLY_ACCESS)

    def test_une_relecture_met_a_jour(self):
        self.cat.put_many([self._rec(editions={"5": "Early Access"})])
        self.cat.put_many([self._rec(editions={"1": "Standard"})])   # le jeu est sorti
        self.assertEqual(self.cat.get("jeu")["nature"], NATURE_STANDARD)

    def test_la_duree_de_vie_ecarte_un_vieux_releve_sans_l_effacer(self):
        self.cat.put_many([self._rec()])
        with sqlite3.connect(self.db) as conn:
            conn.execute("UPDATE pages SET read_at = ?", ("2020-01-01T00:00:00Z",))
        self.assertIsNone(self.cat.get("jeu"))                       # périmé
        self.assertIsNotNone(self.cat.get("jeu", fresh_only=False))  # toujours là

    def test_les_statistiques_repondent_combien_de_pages_dlc(self):
        self.cat.put_many([self._rec("a", editions={"16": "DLC"}),
                           self._rec("b", editions={"5": "Early Access"}),
                           self._rec("c")])
        stats = self.cat.stats()
        self.assertEqual(stats["total"], 3)
        self.assertEqual(stats["par_nature"][NATURE_DLC], 1)
        self.assertEqual([r["slug"] for r in self.cat.by_nature(NATURE_EARLY_ACCESS)], ["b"])


class LeCatalogueNeFaitJamaisEchouerUnBalayage(unittest.TestCase):
    """Garde-fou n°3 : « c'est un accélérateur, pas une dépendance »."""

    def test_un_chemin_impossible_ne_leve_pas(self):
        cat = PageCatalog("/proc/interdit/cat.db")
        rec = PageRecord(slug="x", page_kind="cd-key", url="https://aks/x", editions={})
        self.assertEqual(cat.put_many([rec]), 0)
        self.assertIsNone(cat.get("x"))
        self.assertEqual(cat.stats()["total"], 0)
        self.assertTrue(cat.last_error)

    def test_une_base_corrompue_ne_leve_pas(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        p = Path(tmp.name) / "cat.db"
        p.write_text("ceci n'est pas une base sqlite", encoding="utf-8")
        cat = PageCatalog(str(p))
        self.assertEqual(cat.put_many([PageRecord(slug="x", page_kind="cd-key",
                                                  url="https://aks/x", editions={})]), 0)
        self.assertIsNone(cat.get("x"))

    def test_le_disjoncteur_coupe_apres_deux_echecs(self):
        """Mesuré le 2026-09-21 : un hôte injoignable coûtait 120 s par lot. Deux échecs
        coupent le catalogue pour le reste du processus."""

        cat = PageCatalog("/tmp/x.db", ssh="debian@203.0.113.1")   # TEST-NET-3, injoignable
        cat._note_failure("premier")
        self.assertFalse(cat.disabled)
        cat._note_failure("second")
        self.assertTrue(cat.disabled)
        t0 = time.time()
        self.assertEqual(cat.put_many([PageRecord(slug="x", page_kind="cd-key",
                                                  url="https://aks/x", editions={})]), 0)
        self.assertLess(time.time() - t0, 1.0, "coupé = instantané, aucune tentative")


class LeSeauDuMatch(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cat = PageCatalog(str(Path(self.tmp.name) / "cat.db"))

    def test_jamais_un_echec_en_cache(self):
        """Garde-fou n°1 — celui qui a coûté 434 offres au balayage du 19/09 : une page
        introuvable ne doit pas devenir un souvenir."""

        rec = CatalogRecorder(self.cat, source="t")
        rec.note(None, {})
        self.assertEqual(rec.pending, 0)
        self.assertEqual(rec.flush(), 0)
        self.assertEqual(self.cat.stats()["total"], 0)

    def test_une_resolution_reussie_est_retenue_puis_ecrite_en_un_lot(self):
        rec = CatalogRecorder(self.cat, source="t")
        for nom in ("a", "b", "c", "a"):          # « a » deux fois : une seule ligne
            rec.note(_Res(slug=nom, url="https://aks/blog/buy-%s-cd-key-compare-prices/" % nom,
                          editions={"1": "Standard"}, regions={}), {})
        self.assertEqual(rec.pending, 3)
        self.assertEqual(rec.flush(), 3)
        self.assertEqual(rec.pending, 0)          # le seau est vidé
        self.assertEqual(self.cat.stats()["total"], 3)

    def test_le_gabarit_voyage_avec_la_resolution(self):
        rec = CatalogRecorder(self.cat, source="t")
        rec.note(_Res(slug="subnautica-2", url="https://aks/x",
                      editions={"5": "Early Access"}, regions={}),
                 {"page_kind": "steam-account"})
        rec.flush()
        row = self.cat.get("subnautica-2", "steam-account")
        self.assertEqual(row["nature"], NATURE_EARLY_ACCESS)

    def test_une_page_console_nécrase_pas_la_page_PC(self):
        """Revue de Romain (2026-09-22) : « après lecture des pages PC puis PS5 du même jeu,
        l'entrée PC contient l'URL PS5 et aucune entrée PS5 n'existe ». Le gabarit se lit
        sur l'URL quand l'appelant ne le donne pas — c'est le cas des lectures de page
        console, qui passent par le résolveur d'URL."""

        rec = CatalogRecorder(self.cat, source="t")
        base = "https://www.allkeyshop.com/blog/buy-hades-%s-compare-prices/"
        rec.note(_Res(slug="hades", url=base % "cd-key", editions={"1": "Standard"}, regions={}), {})
        rec.note(_Res(slug="hades", url=base % "ps5", editions={"1": "Standard"}, regions={}), {})
        self.assertEqual(rec.flush(), 2)
        pc = self.cat.get("hades", "cd-key")
        ps5 = self.cat.get("hades", "ps5")
        self.assertIsNotNone(ps5, "la page PS5 doit exister en propre")
        self.assertIn("cd-key", pc["url"])
        self.assertIn("ps5", ps5["url"])

    def test_sans_catalogue_le_seau_ne_fait_rien(self):
        rec = CatalogRecorder(None, source="t")
        rec.note(_Res(slug="a", url="u", editions={}, regions={}), {})
        self.assertEqual(rec.flush(), 0)

    def test_le_matcher_ignore_tout_du_catalogue(self):
        """Le seau enveloppe le résolveur : `src/matcher.py` ne l'importe pas."""

        src = (ROOT / "src" / "matcher.py").read_text(encoding="utf-8")
        self.assertNotIn("page_catalog", src)


class LaSpecificationDeBase(unittest.TestCase):
    def test_chemin_local_hote_distant_et_vide(self):
        self.assertIsNone(catalog_from_spec(""))
        local = catalog_from_spec("/tmp/cat.db")
        self.assertEqual((local.path, local.ssh), ("/tmp/cat.db", ""))
        distant = catalog_from_spec("debian@51.38.37.254:/home/debian/executor/state/cat.db")
        self.assertEqual(distant.ssh, "debian@51.38.37.254")
        self.assertEqual(distant.path, "/home/debian/executor/state/cat.db")

    def test_le_cli_de_match_expose_l_option_sans_l_imposer(self):
        src = (ROOT / "scripts" / "03_match.py").read_text(encoding="utf-8")
        self.assertIn('"--page-catalog"', src)
        self.assertIn('default=""', src)          # vide = comportement d'avant
        # Le catalogue ÉCOUTE, il n'enveloppe plus : envelopper changeait l'identité du
        # résolveur, dont `match_feed` se sert pour armer la garde de throttle des pages
        # console (revue de Romain, 2026-09-22).
        self.assertIn("on_resolution=recorder.note", src)
        self.assertNotIn("recorder.wrap(", src)
        self.assertIn("recorder.flush()", src)

    def test_le_resolveur_passe_au_matcher_reste_LE_resolveur(self):
        """La revue du 22/09, vérifiée sur le CLI réel et pas sur son texte.

        `match_feed` n'arme la garde de throttle des pages console que si le résolveur
        qu'on lui donne EST `resolve_aks` (test d'identité). Le catalogue enveloppait ce
        résolveur : l'identité tombait, la garde n'était plus armée — et ce, même sans
        `--page-catalog`, donc pendant le balayage GameSeal de la nuit. On lance ici le
        vrai CLI, catalogue activé, et on regarde ce qui arrive au matcher."""

        import importlib.util
        import pathlib
        import sys
        import tempfile
        from unittest import mock
        from src.aks_env import HttpProbeResult
        import src.matcher as M

        spec = importlib.util.spec_from_file_location(
            "m03_identite", str(ROOT / "scripts" / "03_match.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        with tempfile.TemporaryDirectory() as tmp:
            racine = pathlib.Path(tmp)
            mod.ROOT = racine
            run = racine / "runs" / "r1"
            run.mkdir(parents=True)
            (run / "offers.json").write_text(json.dumps({
                "run_id": "r1", "merchant": "GameSeal", "fetched_at": "t",
                "offers": [{"offer_id": "1", "name": "Neon Beats - Steam GLOBAL",
                            "url": "https://gameseal.com/x", "merchant": "GameSeal",
                            "store_id": "999"}]}), encoding="utf-8")
            vus = {}

            def faux_match_feed(feed, resolver, **kw):
                vus["resolver"] = resolver
                vus["page_resolver"] = kw.get("page_resolver")
                vus["on_resolution"] = kw.get("on_resolution")
                return [], []

            argv = ["03_match.py", str(run / "offers.json"),
                    "--page-catalog", str(racine / "cat.db")]
            with mock.patch.object(mod, "match_feed", faux_match_feed), \
                    mock.patch.object(mod, "http_get", return_value=HttpProbeResult(
                        url="u", ok=True, status=200, body="x")), \
                    mock.patch.object(sys, "argv", argv):
                mod.main()

        self.assertIs(vus["resolver"], M.resolve_aks,
                      "le catalogue ne doit pas changer l'identité du résolveur principal")
        self.assertIs(vus["page_resolver"], M.resolve_aks_url,
                      "ni celle du résolveur de pages — c'est lui que la garde surveille")
        self.assertIsNotNone(vus["on_resolution"],
                             "le catalogue écoute : il reçoit les résolutions autrement")

    def test_lecoute_recoit_la_page_PC_ET_la_page_console(self):
        """L'écoute doit REMPLACER l'enveloppe, pas la supprimer.

        Une enveloppe voyait tout ce que les deux résolveurs rendaient. Si l'écoute ne
        remonte qu'une partie — ou rien — le catalogue se vide en silence et personne ne le
        voit : aucune exception, aucun log. On lance donc `match_feed` sur une clé Switch,
        dont la branche console lit une SECONDE page, et on vérifie que les deux lectures
        arrivent au catalogue, chacune sous son propre gabarit."""

        from unittest import mock
        import src.matcher as M
        from src.contracts import NormalizedFeed, NormalizedOffer
        from src.matcher import AksResolution

        AKS = "https://www.allkeyshop.com/blog/"
        url_pc = AKS + "buy-hades-cd-key-compare-prices/"
        url_switch = AKS + "buy-hades-nintendo-switch-compare-prices/"
        page_pc = AksResolution(
            slug="hades", url=url_pc, product_id="1", aks_name="Hades",
            editions={"1": "Standard"}, regions={"99eu": "EU"},
            official_platforms=("Nintendo",),
            console_pages={"nintendo-switch": url_switch})
        page_switch = AksResolution(
            slug="hades", url=url_switch, product_id="1", aks_name="Hades",
            editions={"1": "Standard"}, regions={"99eu": "EU"},
            official_platforms=("Nintendo",),
            console_pages={"nintendo-switch": url_switch})
        offre = NormalizedOffer(offer_id="1", name="Hades (Nintendo Switch) Nintendo Key - EU",
                                url="https://gameseal.com/hades-nintendo-switch-nintendo-key-eu",
                                merchant="GameSeal")
        feed = NormalizedFeed(run_id="r", merchant="GameSeal",
                              fetched_at="2026-09-22T00:00:00Z", offers=(offre,))
        recorder = CatalogRecorder(None, source="test")

        with mock.patch.object(M, "resolve_aks", lambda n, **k: page_pc), \
                mock.patch.object(M, "resolve_aks_url", lambda u: page_switch):
            M.match_feed(feed, M.resolve_aks, page_resolver=M.resolve_aks_url,
                         consoles=True, on_resolution=recorder.note)

        gabarits = sorted(k for _, k in recorder._seen)
        self.assertIn("cd-key", gabarits, "la résolution principale n'arrive plus au catalogue")
        self.assertIn("nintendo-switch", gabarits,
                      "la lecture de page CONSOLE n'arrive plus au catalogue")


if __name__ == "__main__":
    unittest.main()

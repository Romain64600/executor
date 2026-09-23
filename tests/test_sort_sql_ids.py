"""Le tri SQL par identifiants et l'index sitemap (2026-09-22, « liste 22, go »).

Ce qui est en jeu : un ``UPDATE`` collé à la main dans phpMyAdmin sur des milliers de lignes,
sans preuve après coup. Ces tests portent donc sur les GARDES — ce qui est retenu, ce qui est
compté, et ce qui refuse de s'écrire — plus que sur la mise en forme.
"""

import json
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.aks_sitemap import SitemapIndex, refresh, SitemapUnavailable  # noqa: E402
from src.sort_sql_ids import (  # noqa: E402
    ExportRefused,
    PAGE_KINDS,
    collect,
    collect_from_sort_scan,
    domain_of,
    non_game_reason,
    partition,
    render_sql,
)


# Des sitemaps de la FORME réelle d'AKS (Yoast) : racine `sitemapindex` pour l'index,
# `urlset` pour une page, espace de noms sitemaps.org. Vérifié contre le vrai site.
_NS_INDEX = (b'<?xml version="1.0" encoding="UTF-8"?>'
             b'<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">')
_NS_URLSET = (b'<?xml version="1.0" encoding="UTF-8"?>'
              b'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">')
_INDEX_2 = (_NS_INDEX
            + b"<sitemap><loc>https://www.allkeyshop.com/blog/page-sitemap1.xml</loc></sitemap>"
            + b"<sitemap><loc>https://www.allkeyshop.com/blog/page-sitemap2.xml</loc></sitemap>"
            + b"</sitemapindex>")
_URLSET_HADES = (_NS_URLSET + b"<url><loc>https://www.allkeyshop.com/blog/"
                 b"buy-hades-cd-key-compare-prices/</loc></url></urlset>")


def _index(entries, fetched_at="2026-09-22T12:00:00Z", incomplete=False):
    return SitemapIndex(entries=frozenset(entries), fetched_at=fetched_at,
                        incomplete=incomplete)


def _run(tmp, nom, entrees):
    d = pathlib.Path(tmp) / nom
    d.mkdir(parents=True)
    (d / "skipped.json").write_text(json.dumps(entrees), encoding="utf-8")
    return d


def _skip(oid, nom, raison="no AKS product page found (slug not 200)", url="https://m/x"):
    return {"offer": {"offer_id": oid, "name": nom, "url": url, "merchant": "GameSeal"},
            "reason": raison}


class LIndexSitemap(unittest.TestCase):
    def test_un_index_absent_ou_vide_repond_je_ne_sais_pas(self):
        """La distinction qui compte : « AKS n'a aucune page » et « je n'ai pas l'index »
        se ressemblent à l'usage et disent le contraire. On ne rend que le second."""

        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(SitemapIndex.load(pathlib.Path(tmp) / "absent.json"))
            vide = pathlib.Path(tmp) / "vide.json"
            vide.write_text(json.dumps({"entries": [], "fetched_at": "2026-09-22T00:00:00Z"}))
            self.assertIsNone(SitemapIndex.load(vide))
            casse = pathlib.Path(tmp) / "casse.json"
            casse.write_text("{pas du json")
            self.assertIsNone(SitemapIndex.load(casse))

    def test_la_page_se_cherche_par_son_segment_entier(self):
        idx = _index(["hades-cd-key", "hades-2-cd-key", "ignoble-key"])
        self.assertTrue(idx.has_page("hades-cd-key"))
        self.assertFalse(idx.has_page("hades"), "le slug nu n'est pas une page")
        self.assertEqual(idx.kinds_for("ignoble", PAGE_KINDS), ["key"])
        self.assertEqual(idx.kinds_for("hades", ("cd-key", "ps5")), ["cd-key"])

    def test_la_recherche_par_prefixe_attrape_les_gabarits_non_enumeres(self):
        """96 % de l'index tombe dans nos gabarits nommés, pas 100 % : xbox-360-code,
        wii-u, download-code… existent. Le préfixe rattrape ce qu'on n'a pas listé."""

        idx = _index(["007-legends-playstation-vita-code", "zzz-cd-key"])
        self.assertEqual(idx.kinds_for("007-legends", PAGE_KINDS), [],
                         "ce gabarit n'est pas dans notre liste — c'est le point du test")
        self.assertEqual(idx.any_page_starting_with("007-legends"),
                         "007-legends-playstation-vita-code")
        self.assertIsNone(idx.any_page_starting_with("jamais-vu"))

    def test_la_fraicheur_se_mesure_et_un_horodatage_illisible_nest_pas_frais(self):
        import calendar, time
        t = calendar.timegm(time.strptime("2026-09-22T12:00:00Z", "%Y-%m-%dT%H:%M:%SZ"))
        idx = _index(["a-cd-key"], fetched_at="2026-09-22T12:00:00Z")
        self.assertTrue(idx.fresh(7, now=t + 3 * 86400))
        self.assertFalse(idx.fresh(7, now=t + 8 * 86400))
        self.assertFalse(_index(["a-cd-key"], fetched_at="n'importe quoi").fresh(7))

    def test_un_sous_sitemap_en_echec_rend_lindex_INCOMPLET(self):
        """Un index troué qui ne le dit pas ferait déplacer des lignes dont la page existe
        dans le morceau manquant. Il le dit, et l'export refuse."""

        def faux_fetch(url):
            if url.endswith("sitemap_index.xml"):
                return _INDEX_2
            if url.endswith("page-sitemap1.xml"):
                return _URLSET_HADES
            raise OSError("502")
        with tempfile.TemporaryDirectory() as tmp:
            dest = pathlib.Path(tmp) / "idx.json"
            resume = refresh(dest, fetch=faux_fetch, sleep=lambda s: None,
                             now=lambda: 1758542400.0)
            self.assertTrue(resume["incomplete"])
            self.assertEqual(resume["pages"], 1)
            self.assertEqual(len(resume["sitemaps_failed"]), 1)
            self.assertTrue(SitemapIndex.load(dest).incomplete)

    def test_un_index_sans_page_sitemap_leve_au_lieu_de_rendre_un_index_vide(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(SitemapUnavailable):
                refresh(pathlib.Path(tmp) / "x.json",
                        fetch=lambda u: (_NS_INDEX + b"<sitemap><loc>https://ailleurs/rien.xml"
                                         b"</loc></sitemap></sitemapindex>"),
                        sleep=lambda s: None, now=lambda: 0.0)

    def test_un_sous_sitemap_qui_nest_pas_un_sitemap_rend_lindex_INCOMPLET(self):
        """REVUE DE ROMAIN (2026-09-23) : « un sous-sitemap renvoyant du HTML ou un corps
        vide ne déclenche aucune erreur — deux fichiers, dont un invalide, donnent
        incomplete=False. » Une page d'erreur ne contient aucun <loc> : lue à l'expression
        régulière, elle passait pour un sitemap vide et l'index se disait complet, alors
        qu'il lui manquait des milliers de pages. C'est le cas où l'export déplacerait en
        22 des lignes dont la page existe."""

        for nom, corps in (("page HTML", b"<html><body>503 Service Unavailable</body></html>"),
                           ("corps vide", b""),
                           ("XML tronqué", b"<urlset><url><loc>https://x"),
                           ("urlset sans URL", _NS_URLSET + b"</urlset>"),
                           # l'INDEX renvoyé à la place d'une page : du XML valide, avec des
                           # <loc>, mais la mauvaise racine — seule la racine le trahit.
                           ("index au lieu d'une page", _INDEX_2)):
            with self.subTest(cas=nom):
                def faux_fetch(url, c=corps):
                    if url.endswith("sitemap_index.xml"):
                        return _INDEX_2
                    return _URLSET_HADES if url.endswith("page-sitemap1.xml") else c
                with tempfile.TemporaryDirectory() as tmp:
                    resume = refresh(pathlib.Path(tmp) / "i.json", fetch=faux_fetch,
                                     sleep=lambda s: None, now=lambda: 0.0)
                self.assertTrue(resume["incomplete"], f"{nom} accepté comme sitemap")
                self.assertEqual(len(resume["sitemaps_failed"]), 1)

    def test_un_index_qui_nest_pas_un_index_leve(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(SitemapUnavailable):
                refresh(pathlib.Path(tmp) / "x.json",
                        fetch=lambda u: b"<html><a>page-sitemap1.xml</a></html>",
                        sleep=lambda s: None, now=lambda: 0.0)


class LaRecolteDesVerdicts(unittest.TestCase):
    def test_la_variante_console_nest_PAS_la_meme_famille(self):
        """« no AKS product page found (console) (R45) » veut dire : le jeu A une page PC,
        c'est celle de la console qui manque. La déplacer en 22 demanderait la création
        d'une page qui existe déjà pour une autre plateforme."""

        with tempfile.TemporaryDirectory() as tmp:
            _run(tmp, "r-gameseal-s126-p1", [
                _skip("1", "Jeu A"),
                _skip("2", "Jeu B", "no AKS product page found (console) (R45)"),
                _skip("3", "Jeu C", "skip category: GIFT CARD"),
            ])
            got = collect(tmp, "r", "no_aks_page")
        self.assertEqual([o["offer_id"] for o in got], ["1"])

    def test_les_pages_du_balayage_sont_toutes_lues_et_dedoublonnees(self):
        with tempfile.TemporaryDirectory() as tmp:
            _run(tmp, "r-gameseal-s126-p1", [_skip("10", "Jeu"), _skip("11", "Autre")])
            _run(tmp, "r-kinguin-s58-p4", [_skip("10", "Jeu"), _skip("12", "Encore")])
            _run(tmp, "AUTRE-run-p1", [_skip("99", "Hors sujet")])
            got = collect(tmp, "r", "no_aks_page")
        self.assertEqual([o["offer_id"] for o in got], ["10", "11", "12"])

    def test_un_identifiant_non_numerique_nentre_pas_en_SQL(self):
        with tempfile.TemporaryDirectory() as tmp:
            _run(tmp, "r-x-s1-p1", [_skip("42", "Bon"), _skip("4; DROP TABLE", "Mauvais")])
            got = collect(tmp, "r", "no_aks_page")
        self.assertEqual([o["offer_id"] for o in got], ["42"])

    def test_une_famille_inconnue_est_refusee(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ExportRefused):
                collect(tmp, "r", "ce-que-je-veux")


class LeFiltreDuSitemap(unittest.TestCase):
    """LE test de ce lot : une offre dont la page EXISTE ne doit jamais partir en 22."""

    def _cands(self, nom):
        return {"Ignoble": ["ignoble"], "Hades": ["hades"],
                "Jeu Fantome": ["jeu-fantome"], "Legends": ["007-legends"]}[nom]

    def test_une_offre_dont_la_page_existe_sous_un_autre_gabarit_est_RETENUE(self):
        idx = _index(["ignoble-key", "hades-cd-key"])
        offres = [{"offer_id": "1", "name": "Ignoble", "url": "u"},
                  {"offer_id": "2", "name": "Jeu Fantome", "url": "u"}]
        part = partition(offres, idx, self._cands)
        self.assertEqual([o["offer_id"] for o in part.to_move], ["2"])
        self.assertEqual([o["offer_id"] for o in part.page_exists], ["1"])
        self.assertEqual(part.page_exists[0]["pages_aks"], ["ignoble-key"])

    def test_un_voisin_par_prefixe_met_la_ligne_en_doute_pas_en_mouvement(self):
        idx = _index(["007-legends-playstation-vita-code"])
        part = partition([{"offer_id": "3", "name": "Legends", "url": "u"}],
                         idx, self._cands)
        self.assertEqual(part.to_move, [])
        self.assertEqual([o["offer_id"] for o in part.doubtful], ["3"])

    def test_les_comptes_couvrent_toutes_les_lignes(self):
        idx = _index(["ignoble-key", "007-legends-playstation-vita-code"])
        offres = [{"offer_id": str(i), "name": n, "url": "u"} for i, n in
                  enumerate(["Ignoble", "Legends", "Jeu Fantome"], 1)]
        part = partition(offres, idx, self._cands)
        self.assertEqual(sum(part.counts().values()), len(offres))


class LeFiltreDesNonJeux(unittest.TestCase):
    """Mesuré sur l'export réel du 2026-09-22 par une vérification boutique par boutique :
    394 lignes sur 4 811 n'étaient pas des jeux. Demander la création d'une page AKS pour
    une bande dessinée, c'est fabriquer du travail inutile pour un humain."""

    def _cands(self, nom):
        return ["x"]

    def test_une_BD_ou_un_livre_derriere_un_redirecteur_daffiliation(self):
        """`awin1.com` n'est pas une boutique : c'est un redirecteur. Sans déplier l'URL,
        le chemin qui type le produit est invisible — et « Halo: Collateral Damage », un
        ROMAN, part en 22 comme un jeu."""

        roman = {"offer_id": "1", "name": "Halo: Collateral Damage",
                 "url": "https://www.awin1.com/cread.php?ued=https%3A%2F%2F"
                        "www.fanatical.com%2Fen%2Fbook%2Fhalo-collateral-damage"}
        self.assertIn("/book/", non_game_reason(roman) or "")
        bd = dict(roman, offer_id="2", url="https://fanatical.com/en/comic/the-midnite-show")
        self.assertIn("/comic/", non_game_reason(bd) or "")

    def test_une_demo_nest_pas_un_produit_a_comparer(self):
        self.assertIn("démo", non_game_reason(
            {"offer_id": "3", "name": "Dice Crawler Demo", "url": "https://gog.com/x"}) or "")
        self.assertIsNone(non_game_reason(
            {"offer_id": "4", "name": "Demolition Company", "url": "https://gog.com/x"}),
            "« Demolition » contient « demo » sans être une démo — le mot est isolé")

    def test_un_titre_de_remplacement_ne_prouve_rien(self):
        for nom in ("product_title_1294777125", "2367709"):
            self.assertIsNotNone(non_game_reason(
                {"offer_id": "5", "name": nom, "url": "https://muve.games/x"}), nom)

    def test_un_vrai_jeu_passe(self):
        self.assertIsNone(non_game_reason(
            {"offer_id": "6", "name": "Hades", "url": "https://gog.com/en/game/hades"}))

    def test_la_partition_les_range_a_part_et_les_compte(self):
        idx = _index(["x-cd-key"])
        offres = [{"offer_id": "1", "name": "Dice Crawler Demo", "url": "u"},
                  {"offer_id": "2", "name": "Vrai Jeu", "url": "u"}]
        part = partition(offres, idx, lambda n: ["jamais-vu"])
        self.assertEqual([o["offer_id"] for o in part.not_a_game], ["1"])
        self.assertEqual([o["offer_id"] for o in part.to_move], ["2"])
        self.assertEqual(sum(part.counts().values()), len(offres))


class LaComparaisonAplatie(unittest.TestCase):
    """La ponctuation et le groupement des chiffres divergent entre le titre marchand et le
    slug d'AKS, pas le produit : « Re;Birth3 » contre « rebirth3 », « 1,000 Doors » contre
    « 1000-doors », « MotoGP24 » contre « motogp-24 ». 140 lignes de l'export (2,9 %)
    retrouvent leur page ainsi — et ne doivent donc PAS partir en création."""

    def test_une_page_trouvee_a_la_ponctuation_pres_retient_la_ligne(self):
        idx = _index(["motogp-24-cd-key"])
        part = partition([{"offer_id": "1", "name": "MotoGP24", "url": "u"}],
                         idx, lambda n: ["motogp24"])
        self.assertEqual(part.to_move, [], "la page existe : on ne demande pas de la créer")
        self.assertEqual(part.page_exists[0]["pages_aks"], ["motogp-24-cd-key"])

    def test_elle_ne_rapproche_pas_deux_produits_differents(self):
        idx = _index(["hades-2-cd-key"])
        part = partition([{"offer_id": "1", "name": "Hades", "url": "u"}],
                         idx, lambda n: ["hades"])
        self.assertEqual([o["offer_id"] for o in part.page_exists], [],
                         "« hades » et « hades-2 » ne s'aplatissent pas pareil")


class LExportLitLeNomCommeLeMatcher(unittest.TestCase):
    """REVUE DE ROMAIN (2026-09-23) : « Zombies Invasion (PC) Steam Gift- EU part en page à
    créer alors que le nettoyage GameSeal retrouve la page. Il faut réutiliser les règles de
    résolution du marchand. » Mesuré sur les deux fichiers livrés la veille : 204 lignes dont
    la page existe une fois le nom nettoyé — elles seraient parties en 22."""

    def _cli(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "s17noms", str(ROOT / "scripts" / "17_sort_sql_ids.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_le_nom_GameSeal_nettoye_est_cherche_aussi(self):
        mod = self._cli()
        noms = mod.noms_a_chercher({"offer_id": "1", "merchant": "GameSeal",
                                    "name": "Zombies Invasion (PC) Steam Gift- EU",
                                    "url": "https://gameseal.com/x"})
        self.assertEqual(noms[0], "Zombies Invasion (PC) Steam Gift- EU", "le brut reste essayé")
        self.assertEqual(len(noms), 2)
        self.assertNotIn("Steam Gift", noms[1], f"nettoyage GameSeal non appliqué : {noms}")

    def test_la_page_trouvee_sous_le_nom_nettoye_RETIENT_la_ligne(self):
        from src.matcher import build_slug_candidates
        mod = self._cli()
        idx = _index(["zombies-invasion-cd-key"])
        offre = {"offer_id": "1", "merchant": "GameSeal", "url": "https://gameseal.com/x",
                 "name": "Zombies Invasion (PC) Steam Gift- EU"}
        sans = partition([offre], idx, build_slug_candidates)
        avec = partition([offre], idx, build_slug_candidates, name_variants=mod.noms_a_chercher)
        self.assertEqual([o["offer_id"] for o in sans.to_move], ["1"],
                         "témoin : sur le seul titre brut, la ligne partait en 22")
        self.assertEqual(avec.to_move, [], "la page existe : on ne demande pas de la créer")
        self.assertEqual([o["offer_id"] for o in avec.page_exists], ["1"])

    def test_un_nom_de_plus_ne_peut_quempecher_un_deplacement(self):
        """Le sens prudent : chaque variante de nom est une chance de PLUS de trouver la
        page. Une variante qui ne trouve rien ne fait pas partir une ligne retenue."""

        idx = _index(["hades-cd-key"])
        offre = {"offer_id": "1", "name": "Hades", "url": "u"}
        part = partition([offre], idx, lambda n: [n.lower().replace(" ", "-")],
                         name_variants=lambda o: ["Hades", "Rien Du Tout"])
        self.assertEqual(part.to_move, [])

    def test_le_scan_de_tri_retrouve_le_marchand_canonique_par_son_store(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = pathlib.Path(tmp) / "tri"; d.mkdir()
            (d / "offers.json").write_text(json.dumps({"offers": [
                {"offer_id": "1", "name": "Jeu", "url": "https://www.gog.com/en/game/jeu",
                 "store_id": "34"},
                {"offer_id": "2", "name": "Autre", "url": "https://inconnu.test/a",
                 "store_id": "99999"}]}), encoding="utf-8")
            (d / "sort_plan.json").write_text(json.dumps(
                {"source_list": 9, "by_list": {}, "unrouted": []}), encoding="utf-8")
            got = {o["offer_id"]: o for o in collect_from_sort_scan(d)}
        self.assertEqual(got["1"]["merchant"], "GOG", "store 34 -> la grammaire GOG")
        self.assertEqual(got["2"]["merchant"], "inconnu.test", "inconnu -> le domaine")


class LeFichierSQL(unittest.TestCase):
    OFFRES = [{"offer_id": str(1000 + i), "name": f"Jeu {i}",
               "url": f"https://m.test/jeu-{i}"} for i in range(5)]

    def test_letape_0_verifie_la_colonne_avec_des_URL_quon_connait(self):
        """Nous n'avons jamais vu le schéma : `id` est une hypothèse. Le fichier doit
        donner à Romain de quoi l'infirmer AVANT le premier UPDATE."""

        sql = render_sql(self.OFFRES, 22, chunk=2, sample=3)
        avant_update = sql.split("UPDATE")[0]
        self.assertIn("ÉTAPE 0", avant_update)
        self.assertIn("SELECT `id`, `url`", avant_update)
        for o in self.OFFRES[:3]:
            self.assertIn(o["url"], avant_update,
                          "les URL attendues doivent précéder le premier UPDATE")

    def test_chaque_lot_est_compte_avant_decrire(self):
        sql = render_sql(self.OFFRES, 22, chunk=2)
        lots = [b for b in sql.split("-- ---- lot ")[1:]]
        self.assertEqual(len(lots), 3)
        for b in lots:
            self.assertLess(b.index("SELECT COUNT(*)"), b.index("UPDATE"),
                            "le compte doit précéder l'écriture")

    def test_toute_requete_porte_la_restriction_a_la_file_pending(self):
        sql = render_sql(self.OFFRES, 22, chunk=2)
        requetes = [l for l in sql.splitlines() if l.startswith("UPDATE")]
        self.assertTrue(requetes)
        for req in requetes:
            self.assertIn("`listId`=9", req,
                          "une ligne déjà triée ailleurs ne doit pas rebouger")
            self.assertIn("SET `listId`=22", req)

    def test_le_compte_annonce_est_un_MAXIMUM_pas_une_egalite(self):
        """Romain, 2026-09-22 : « j'ai fait un tri où l'on a envoyé certaines lignes vers la
        liste old games / no page ». Ces lignes ont quitté la file 9 : le COUNT de leur lot
        rendra moins que le nombre annoncé. Si le fichier disait « un écart = arrêter », il
        bloquerait sur du tri DÉJÀ FAIT — la garde deviendrait une fausse alerte."""

        sql = render_sql(self.OFFRES, 22, chunk=2)
        self.assertIn("au plus", sql)
        self.assertNotIn("Un écart = arrêter", sql)
        self.assertIn("ne sont plus dans la liste 9", sql)

    def test_le_retour_en_arriere_de_la_22_vers_la_9(self):
        """Revue du 2026-09-23 : 255 lignes des fichiers du 22/09 avaient une page. S'ils ont
        été collés, il faut les rendre — avec les mêmes gardes qu'à l'aller, et SANS toucher
        une ligne qui n'est pas dans la 22."""

        sql = render_sql(self.OFFRES, 9, chunk=2, from_list=22)
        requetes = [l for l in sql.splitlines() if l.startswith("UPDATE")]
        self.assertTrue(requetes)
        for req in requetes:
            self.assertIn("SET `listId`=9", req)
            self.assertIn("AND `listId`=22", req, "seules les lignes encore en 22 bougent")
        self.assertIn("tous les comptes valent 0", sql,
                      "si l'ancien fichier n'a pas été collé, le dire : 0 est normal")
        with self.assertRaises(ExportRefused):
            render_sql(self.OFFRES, 22, from_list=22)

    def test_letape_0_montre_la_liste_actuelle_sans_filtrer_dessus(self):
        """Une ligne déjà déplacée ailleurs doit s'afficher à l'étape 0 : filtrée sur la
        liste d'origine, elle disparaîtrait, et une étape 0 vide ferait croire que la
        colonne d'identifiant est fausse."""

        etape0 = render_sql(self.OFFRES, 22, chunk=2).split("-- Les URL attendues")[0]
        select = etape0[etape0.index("SELECT"):]
        self.assertIn("`listId`", select.splitlines()[0])
        self.assertNotIn("AND `listId`", select)

    def test_la_file_pending_ne_peut_pas_etre_sa_propre_cible(self):
        with self.assertRaises(ExportRefused):
            render_sql(self.OFFRES, 9)

    def test_un_export_vide_refuse_au_lieu_de_rendre_un_fichier_sans_ligne(self):
        with self.assertRaises(ExportRefused):
            render_sql([], 22)

    def test_un_identifiant_non_numerique_fait_echouer_le_rendu(self):
        with self.assertRaises(ExportRefused):
            render_sql([{"offer_id": "1 OR 1=1", "name": "x", "url": "u"}], 22)

    def test_tous_les_identifiants_sont_bien_dans_les_lots(self):
        sql = render_sql(self.OFFRES, 22, chunk=2)
        for o in self.OFFRES:
            self.assertIn(o["offer_id"], sql)


class LeScanDeTriCommeSource(unittest.TestCase):
    """Romain, 2026-09-22 : « lance le même export sur les autres marchands ». Les 44
    boutiques hors liste blanche n'ont jamais été balayées : aucun `skipped.json` n'existe
    pour elles. Le scan de tri tous-magasins est la seule source — il a déjà fait passer
    toute la file par notre routeur."""

    def _scan(self, tmp):
        d = pathlib.Path(tmp) / "tri"
        d.mkdir(parents=True)
        rows = [
            {"offer_id": "1", "name": "Jeu Libre", "url": "https://gog.com/a", "store_id": "999"},
            {"offer_id": "2", "name": "Carte", "url": "https://gog.com/carte", "store_id": "999"},
            {"offer_id": "3", "name": "Console", "url": "https://wyrel.com/c", "store_id": "998"},
            # Un de NOS marchands, dont le domaine ne se devine pas : GamersOutlet vit sur
            # « gamers-outlet.net » avec un tiret. C'est le store_id qui doit l'exclure.
            {"offer_id": "4", "name": "Notre Jeu",
             "url": "https://www.gamers-outlet.net/x", "store_id": "31"},
        ]
        (d / "offers.json").write_text(json.dumps({"offers": rows}), encoding="utf-8")
        (d / "sort_plan.json").write_text(json.dumps({
            "source_list": 9,
            "by_list": {"21": {"offers": [rows[1]]}},          # réclamée : carte cadeau
            "unrouted": [dict(rows[2], reason="console")],      # gardée avec une raison
            "coverage": {"truncated": False, "pages_fetched": 1, "feed_last_page": 1},
        }), encoding="utf-8")
        return d

    def test_seules_les_lignes_que_le_routeur_tient_pour_des_jeux_sortent(self):
        """Une ligne déjà réclamée par une autre liste (carte cadeau) ou gardée avec une
        raison (console) n'a rien à faire en 22 : on ne demanderait pas la création d'une
        page pour une carte cadeau."""

        with tempfile.TemporaryDirectory() as tmp:
            got = collect_from_sort_scan(self._scan(tmp))
        self.assertEqual(sorted(o["offer_id"] for o in got), ["1", "4"])

    def test_nos_marchands_sont_ecartes_par_STORE_ID_pas_par_domaine(self):
        """Le défaut que ce test épingle, trouvé sur les vraies données : filtrer par
        domaine ratait GamersOutlet (« gamers-outlet.net », avec un tiret) et Allyouplay
        (pas de domaine propre du tout — ses liens passent par « anandadigitalbv.sjv.io »).
        Leurs lignes partaient dans l'export « des autres », donc en double."""

        with tempfile.TemporaryDirectory() as tmp:
            d = self._scan(tmp)
            autres = collect_from_sort_scan(d, exclude_stores={"31"})
            self.assertEqual([o["offer_id"] for o in autres], ["1"],
                             "le store_id 31 doit écarter la ligne, quel que soit son domaine")
            gog = collect_from_sort_scan(d, only_domains={"gog.com"})
            self.assertEqual([o["offer_id"] for o in gog], ["1"])
            self.assertEqual(domain_of("https://www.gamers-outlet.net/x"), "gamers-outlet.net")

    def test_le_CLI_ecarte_exactement_les_store_id_de_la_liste_blanche(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "s17dom", str(ROOT / "scripts" / "17_sort_sql_ids.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        from src.admin.auto_merchants import AUTO_MERCHANTS
        self.assertEqual(mod.NOS_STORES, {s for _, s in AUTO_MERCHANTS})


class LeCliRefuseUnIndexQuilNePeutPasJustifier(unittest.TestCase):
    """Le script refuse d'exporter sans index frais et complet : un catalogue troué ou
    vieux ferait déplacer des lignes dont la page existe."""

    def _cli(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "s17", str(ROOT / "scripts" / "17_sort_sql_ids.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def _lance(self, index_path, extra=()):
        mod = self._cli()
        argv = ["17", "--run", "r", "--list", "22", "--sitemap", str(index_path)] + list(extra)
        with mock.patch.object(sys, "argv", argv):
            return mod.main()

    def test_index_absent_incomplet_ou_perime(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = pathlib.Path(tmp)
            self.assertEqual(self._lance(t / "rien.json"), 2)
            (t / "troue.json").write_text(json.dumps(
                {"entries": ["a-cd-key"], "fetched_at": "2026-09-22T00:00:00Z",
                 "incomplete": True}))
            self.assertEqual(self._lance(t / "troue.json"), 2)
            (t / "vieux.json").write_text(json.dumps(
                {"entries": ["a-cd-key"], "fetched_at": "2020-01-01T00:00:00Z"}))
            self.assertEqual(self._lance(t / "vieux.json"), 2)


if __name__ == "__main__":
    unittest.main()

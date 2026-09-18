"""La voie SQL remplace l'exécution d'un déplacement (2026-09-18).

Romain : « je veux que la voie SQL remplace l'exécution d'un déplacement, tu me donneras les
requêtes dans l'admin en liste et [elles seront] prêtes à copier coller, les requêtes seront
collées à la main dans phpMyAdmin par mes soins ».

Ce que ce changement COÛTE, et que ces tests rendent explicite : le déplacement par navigateur
avait une preuve — la ligne avait quitté la liste source au rafraîchissement, exactement comme
la preuve « gone from feed » du submit. Un ``UPDATE`` collé à la main n'a ni preuve, ni garde
fail-closed, ni retour arrière. On ne peut donc plus vérifier APRÈS : tout se joue sur la
mesure AVANT, et c'est pourquoi chaque requête est affichée avec ce qu'elle toucherait
réellement sur le dernier scan.
"""

import json
import pathlib
import re
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
import sys
sys.path.insert(0, str(ROOT))

from src.admin.sort_sql_view import sort_sql_payload
from src.sort_sql_rules import FLAGGED, RULES

APP = (ROOT / "src" / "admin" / "app.py").read_text(encoding="utf-8")
HTML = (ROOT / "src" / "admin" / "static" / "sql.html").read_text(encoding="utf-8")
JS = (ROOT / "src" / "admin" / "static" / "sql.js").read_text(encoding="utf-8")
VIEW = (ROOT / "src" / "admin" / "sort_sql_view.py").read_text(encoding="utf-8")


def _run(tmp, rows, by_list, unrouted=()):
    d = pathlib.Path(tmp) / "scan"
    d.mkdir(parents=True)
    (d / "offers.json").write_text(json.dumps({"offers": rows}), encoding="utf-8")
    (d / "sort_plan.json").write_text(
        json.dumps({"by_list": by_list, "unrouted": list(unrouted)}), encoding="utf-8")
    return pathlib.Path(tmp)


class NothingHereTouchesADatabaseTests(unittest.TestCase):
    """Le seul chemin d'écriture est le copier-coller de Romain dans phpMyAdmin."""

    def test_no_database_driver_anywhere_on_this_path(self):
        for drv in ("pymysql", "MySQLdb", "mysql.connector", "sqlalchemy", "psycopg"):
            with self.subTest(drv=drv):
                self.assertNotIn(drv, VIEW)
                self.assertNotIn(drv, JS)

    def test_the_only_posts_MEASURE_or_PROMOTE_a_rule(self):
        """La page a gagné deux POST le 2026-09-18 : mesurer un motif édité (lecture seule)
        et promouvoir une proposition (édition d'une LISTE). Aucun ne touche une base ;
        aucune requête n'est exécutée d'ici, et le déplacement par navigateur n'est pas
        rappelé."""

        posts = sorted(set(re.findall(r'post\("([^"]+)"', JS)))
        self.assertEqual(posts, ["api/sort/sql/measure", "api/sort/sql/promote"], posts)
        self.assertNotIn("api/sort/move", JS)
        self.assertNotIn("UPDATE `aksfeeds_offer`", JS,
                         "le SQL vient du serveur, la page ne le fabrique pas")


class PromotingAProposalTests(unittest.TestCase):
    """« go pour les propositions avec promotion manuelle » — le mineur propose, Romain décide."""

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())

    def test_a_promoted_rule_persists_and_joins_the_list(self):
        from src import sort_sql_promoted
        sort_sql_promoted.promote(self.tmp, pattern="%philippines%", target="8",
                                  by="Romain", run_id="scan", hits=76)
        rows = sort_sql_promoted.load(self.tmp)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["pattern"], "%philippines%")
        self.assertEqual(rows[0]["promoted_by"], "Romain")
        self.assertTrue(rows[0]["promoted_at"].endswith("Z"))

    def test_a_duplicate_is_refused(self):
        from src import sort_sql_promoted
        sort_sql_promoted.promote(self.tmp, pattern="%philippines%", target="8", by="R")
        with self.assertRaises(ValueError):
            sort_sql_promoted.promote(self.tmp, pattern="%philippines%", target="8", by="R")

    def test_a_rule_already_in_romains_list_cannot_be_promoted_again(self):
        from src import sort_sql_promoted
        with self.assertRaises(ValueError):
            sort_sql_promoted.promote(self.tmp, pattern="%gift-card%", target="21", by="R")

    def test_an_injectable_pattern_is_refused_not_escaped(self):
        from src import sort_sql_promoted
        for bad in ("%o'brien%", "%a b%", "x%", "%x%; DROP", "%café%"):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    sort_sql_promoted.promote(self.tmp, pattern=bad, target="8", by="R")

    def test_an_unknown_list_is_refused(self):
        from src import sort_sql_promoted
        with self.assertRaises(ValueError):
            sort_sql_promoted.promote(self.tmp, pattern="%x-y%", target="999", by="R")

    def test_a_corrupt_store_does_not_break_the_page(self):
        from src import sort_sql_promoted
        (self.tmp / "data").mkdir(parents=True)
        (self.tmp / "data" / "sort_sql_promoted.json").write_text("{pas du json", encoding="utf-8")
        self.assertEqual(sort_sql_promoted.load(self.tmp), [])

    def test_the_endpoint_exists_and_answers_400_on_a_bad_promotion(self):
        self.assertIn('if self.path.split("?")[0] == "/api/sort/sql/promote":', APP)
        self.assertIn('raise ApiError(400, "bad_promotion", str(exc))', APP)


class EditingBeforePromotingTests(unittest.TestCase):
    """Romain 2026-09-18 : « faudrait qu'on puisse éditer avant de promouvoir, dans le cas où
    on a besoin d'hésiter, rajoutez un tiret ». Resserrer %puzzle% en %-puzzle-% doit être
    possible — mais une édition rend la mesure affichée PÉRIMÉE, et la mesure est la seule
    garde de cette voie. Elle est donc refaite des deux côtés."""

    def test_the_pattern_and_the_list_are_editable(self):
        self.assertIn('el("input", { type: "text", value: p.pattern', JS)
        self.assertIn('value: String(p.target)', JS)

    def test_an_edit_invalidates_the_displayed_measurement(self):
        self.assertIn('pat.addEventListener("input", stale)', JS)
        self.assertIn('tgt.addEventListener("input", stale)', JS)
        self.assertIn('msg.textContent = "édité — mesure à refaire"', JS)

    def test_promoting_a_stale_edit_is_refused_client_side(self):
        self.assertIn('if (!fresh) { msg.textContent = "mesure d\'abord', JS)

    def test_the_server_re_measures_before_accepting(self):
        """La garde côté client ne suffit pas : éditer ne doit pas être le moyen de la
        contourner. Le serveur refait la mesure et refuse le collatéral."""

        self.assertIn('check = measure_pattern(', APP)
        self.assertIn('"promotion_collateral"', APP)
        block = APP[APP.index("check = measure_pattern("):]
        self.assertLess(block.index("promotion_collateral"),
                        block.index("sort_sql_promoted.promote("),
                        "la vérification doit précéder l'écriture")

    def test_the_measure_endpoint_is_read_only(self):
        self.assertIn('if self.path.split("?")[0] == "/api/sort/sql/measure":', APP)
        block = APP[APP.index('"/api/sort/sql/measure"'):]
        block = block[:block.index('"/api/sort/sql/promote"')]
        self.assertNotIn("promote(", block)
        self.assertNotIn("write_text", block)

    def test_a_narrowed_pattern_measures_differently(self):
        """Le cas d'usage exact : le tiret resserre, et le compte le montre."""

        with tempfile.TemporaryDirectory() as tmp:
            rows = [{"offer_id": "1", "name": "Vrai Jeu Puzzle", "url": "https://m.test/a-puzzle-game"},
                    {"offer_id": "2", "name": "Pack", "url": "https://m.test/jigsaw-puzzles-pack"}]
            runs = _run(tmp, rows, {"8": {"offers": [dict(rows[1], reason="skip category: SKIN")]}})
            from src.admin.sort_sql_view import measure_pattern
            large = measure_pattern(runs, "%puzzle%", "8", "scan")
            tight = measure_pattern(runs, "%-puzzles-%", "8", "scan")
        self.assertEqual(large["hits"], 2)
        self.assertEqual(large["collateral"], 1, "le motif large attrape le vrai jeu")
        self.assertEqual(tight["hits"], 1)
        self.assertEqual(tight["collateral"], 0, "le motif resserré ne l'attrape plus")


class ProposalsAreMinedNotInventedTests(unittest.TestCase):
    """Le mineur ne propose que du VOCABULAIRE de routage, et rien qui vise un vrai jeu."""

    def test_a_game_name_is_never_proposed(self):
        with tempfile.TemporaryDirectory() as tmp:
            rows = [{"offer_id": str(i), "name": f"Modern Warfare {i}",
                     "url": f"https://m.test/modern-warfare-{i}-philippines"} for i in range(3)]
            runs = _run(tmp, rows, {"8": {"offers": [dict(r, reason="forbidden region: PHILIPPINES")
                                                     for r in rows]}})
            payload = sort_sql_payload(runs, "scan", repo_root=pathlib.Path(tmp))
        got = {p["pattern"] for p in payload["proposals"]}
        self.assertIn("%philippines%", got)
        self.assertNotIn("%modern-warfare%", got)

    def test_a_proposal_that_would_hit_a_real_game_is_not_offered(self):
        with tempfile.TemporaryDirectory() as tmp:
            rows = [{"offer_id": "1", "name": "Razer PH", "url": "https://m.test/razer-philippines"},
                    {"offer_id": "2", "name": "Razer PH 2", "url": "https://m.test/razer2-philippines"},
                    {"offer_id": "3", "name": "Vrai Jeu", "url": "https://m.test/jeu-philippines"}]
            runs = _run(tmp, rows, {"8": {"offers": [dict(r, reason="forbidden region: PHILIPPINES")
                                                     for r in rows[:2]]}})
            payload = sort_sql_payload(runs, "scan", repo_root=pathlib.Path(tmp))
        self.assertEqual([p["pattern"] for p in payload["proposals"]], [])

    def test_a_rule_already_in_the_list_is_not_proposed_again(self):
        with tempfile.TemporaryDirectory() as tmp:
            rows = [{"offer_id": str(i), "name": f"Carte {i}",
                     "url": f"https://m.test/a-{i}-gift-card"} for i in range(3)]
            runs = _run(tmp, rows, {"21": {"offers": [dict(r, reason="skip category: GIFT CARD")
                                                      for r in rows]}})
            payload = sort_sql_payload(runs, "scan", repo_root=pathlib.Path(tmp))
        self.assertNotIn("%gift-card%", [p["pattern"] for p in payload["proposals"]])

    def test_every_statement_is_bounded_to_the_pending_list(self):
        payload = sort_sql_payload(pathlib.Path("/nonexistent"))
        self.assertEqual(len(payload["rules"]), len(RULES))
        for r in payload["rules"]:
            with self.subTest(sql=r["sql"]):
                self.assertTrue(r["sql"].startswith("UPDATE `aksfeeds_offer` SET `listId`="))
                self.assertTrue(r["sql"].endswith("AND `listId`=9;"))


class TheMeasurementIsShownNextToEachQueryTests(unittest.TestCase):
    """Sans preuve d'après, la mesure d'avant est tout ce qui protège."""

    def test_a_rule_that_would_hit_a_real_game_reports_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            rows = [{"offer_id": "1", "name": "Carte cadeau 20", "url": "https://m.test/a-gift-card-20"},
                    {"offer_id": "2", "name": "Vrai Jeu", "url": "https://m.test/vrai-jeu-gift-card-ed"}]
            runs = _run(tmp, rows, {"21": {"offers": [dict(rows[0], reason="skip category: GIFT CARD")]}})
            payload = sort_sql_payload(runs, "scan")
        rule = next(r for r in payload["rules"] if r["pattern"] == "%gift-card%")
        self.assertEqual(rule["hits"], 2)
        self.assertEqual(rule["agree"], 1)
        self.assertEqual(rule["collateral"], 1)
        self.assertEqual(rule["collateral_sample"], ["Vrai Jeu"])

    def test_without_a_scan_the_rules_are_served_UNMEASURED_and_say_so(self):
        payload = sort_sql_payload(pathlib.Path("/nonexistent"))
        self.assertFalse(payload["measured"])
        self.assertIn("sans mesure", payload["note"])
        self.assertTrue(all(r["measured"] is False for r in payload["rules"]))

    def test_the_page_says_the_counts_come_from_a_scan_that_ages(self):
        self.assertIn("vieillissent", JS)

    def test_the_page_says_it_executes_nothing(self):
        self.assertIn("pas exécutées ici", HTML)
        self.assertIn("phpMyAdmin", HTML)


class KnownContradictionsAreSurfacedNotSilentTests(unittest.TestCase):
    """Une règle qui contredit une décision écrite s'affiche, elle n'est pas retirée en douce."""

    def test_the_kinguin_valid_until_rule_is_RETIRED_and_says_why(self):
        """Romain a tranché le 2026-09-18 : « retire la règle, on respecte la décision de
        septembre ». La règle envoyait en Blacklist des clés que la décision du 2026-09-14
        fait ENTRER — les deux ne pouvaient pas coexister. Elle n'est pas juste absente :
        sa raison est écrite, pour qu'un audit relisant l'ancienne liste ne la remette pas."""

        from src.sort_sql_rules import RETIRED
        self.assertNotIn("%valid-until%", [p for p, _ in RULES])
        self.assertIn("%valid-until%", RETIRED)
        self.assertIn("2026-09-14", RETIRED["%valid-until%"])
        self.assertIn("ENTRÉES", RETIRED["%valid-until%"])

    def test_no_rule_blacklists_an_activation_deadline(self):
        """Le fond de la décision : la mention est une date limite, pas un produit."""

        for pattern, target in RULES:
            if target == "8":
                with self.subTest(pattern=pattern):
                    self.assertNotIn("valid", pattern)

    def test_the_flag_reaches_the_payload_and_the_page(self):
        payload = sort_sql_payload(pathlib.Path("/nonexistent"))
        flagged = [r for r in payload["rules"] if r["flag"]]
        self.assertTrue(flagged)
        self.assertIn("r.flag", JS)

    def test_a_retired_rule_stays_VISIBLE_with_its_reason(self):
        """Un retrait silencieux se fait recoller depuis une vieille liste."""

        payload = sort_sql_payload(pathlib.Path("/nonexistent"))
        retired = {r["pattern"]: r["why"] for r in payload.get("retired", [])}
        self.assertIn("%valid-until%", retired)
        self.assertIn("ne pas les recoller", JS.replace("Ne pas", "ne pas"))

    def test_a_flagged_rule_is_still_served(self):
        """C'est SA liste : on l'affiche avec son avertissement, on ne la censure pas."""

        payload = sort_sql_payload(pathlib.Path("/nonexistent"))
        patterns = {r["pattern"] for r in payload["rules"]}
        for flagged in FLAGGED:
            with self.subTest(flagged=flagged):
                self.assertIn(flagged, patterns)


class RomainsListIsKeptVERBATIMTests(unittest.TestCase):
    """Romain : « j'avais 54 requêtes, pourquoi /executor/sql me donne que les 52 ? ».

    J'avais replié les paires qui ne diffèrent que par la casse — ``%Month-Subscription%`` et
    ``%month-subscription%``, idem pour Year — en me fiant aux collations ``_ci`` de MySQL, où
    les deux visent les mêmes lignes. Mais cette équivalence dépend d'un réglage de la base que
    je ne peux pas vérifier d'ici, et sa liste contient des motifs écrits UNIQUEMENT en
    capitales (``%-Pass-PSN-%``…) : sur une collation sensible à la casse, mon repli les aurait
    fait échouer en silence. Deux requêtes redondantes ne coûtent rien ; une requête qui ne
    matche plus rien coûte un tri perdu. Ses motifs sont donc gardés tels quels."""

    def test_the_capitalised_patterns_survive(self):
        patterns = [p for p, _ in RULES]
        for verbatim in ("%-Pass-PSN-%", "%-Ancient-Coins-%", "%-Clothing-Set-%"):
            with self.subTest(verbatim=verbatim):
                self.assertIn(verbatim, patterns)

    def test_both_case_variants_are_kept(self):
        patterns = [p for p, _ in RULES]
        for pair in (("%Month-Subscription%", "%month-subscription%"),
                     ("%Year-Subscription%", "%year-subscription%")):
            with self.subTest(pair=pair):
                self.assertIn(pair[0], patterns)
                self.assertIn(pair[1], patterns)

    def test_the_count_adds_up(self):
        """54 lignes données, 1 retirée sur arbitrage — 53 servies, rien d'autre perdu."""

        from src.sort_sql_rules import RETIRED
        self.assertEqual(len(RULES) + len(RETIRED), 54)


class TheConsoleServesItTests(unittest.TestCase):
    def test_the_route_and_assets_are_declared(self):
        self.assertIn('"sql.html": "text/html; charset=utf-8"', APP)
        self.assertIn('"sql.js": "application/javascript; charset=utf-8"', APP)
        self.assertIn('if path in ("/sql", "/tri-sql"):', APP)
        self.assertIn('if path == "/api/sort/sql":', APP)

    def test_the_page_offers_a_copy_of_everything_and_of_the_clean_subset(self):
        self.assertIn('id="copy-all"', HTML)
        self.assertIn('id="copy-safe"', HTML)
        self.assertIn("const clean = (r) =>", JS)

    def test_the_clean_subset_excludes_collateral_and_conflict(self):
        self.assertIn("!r.collateral && !r.conflict", JS)

    def test_every_console_page_links_to_it(self):
        """Romain 2026-09-18 : « je voudrais pouvoir y accéder par le menu/top bar »."""

        static = ROOT / "src" / "admin" / "static"
        for page in ("index.html", "sort.html", "auto.html", "urls.html"):
            with self.subTest(page=page):
                self.assertIn('href="sql"', (static / page).read_text(encoding="utf-8"))

    def test_its_own_tab_is_marked_current(self):
        self.assertIn('<a href="sql" class="tab active" aria-current="page">', HTML)

    def test_the_whole_list_is_also_offered_as_ONE_selectable_block(self):
        """« l'option de copier toutes les requêtes d'un bloc » — bouton ET zone de texte :
        le presse-papiers du navigateur peut être refusé sans HTTPS ou sans geste direct,
        une sélection à la main marche toujours."""

        self.assertIn('id="all-sql"', HTML)
        self.assertIn("readonly", HTML)
        self.assertIn('$("#all-sql").value = RULES.map((r) => r.sql).join', JS)


if __name__ == "__main__":
    unittest.main()

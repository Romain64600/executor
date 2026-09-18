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

    def test_the_page_never_posts_anything(self):
        self.assertNotIn('method: "POST"', JS)
        self.assertNotIn("api/sort/move", JS)

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

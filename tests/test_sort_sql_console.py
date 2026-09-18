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

    def test_the_kinguin_valid_until_conflict_is_flagged(self):
        self.assertIn("%valid-until%", FLAGGED)
        self.assertIn("valid until", FLAGGED["%valid-until%"])
        self.assertIn("2026-09-14", FLAGGED["%valid-until%"])

    def test_the_flag_reaches_the_payload_and_the_page(self):
        payload = sort_sql_payload(pathlib.Path("/nonexistent"))
        flagged = [r for r in payload["rules"] if r["flag"]]
        self.assertTrue(flagged)
        self.assertIn("r.flag", JS)

    def test_a_flagged_rule_is_still_served(self):
        """C'est SA liste : on l'affiche avec son avertissement, on ne la censure pas."""

        payload = sort_sql_payload(pathlib.Path("/nonexistent"))
        patterns = {r["pattern"] for r in payload["rules"]}
        for flagged in FLAGGED:
            with self.subTest(flagged=flagged):
                self.assertIn(flagged, patterns)


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


if __name__ == "__main__":
    unittest.main()

"""Stage 13 — le SQL de tri, généré mais jamais exécuté (2026-09-17).

Romain veut coller des `UPDATE` dans phpMyAdmin et les lancer lui-même. Le danger est
asymétrique : un `UPDATE` parti à la main n'a ni garde fail-closed, ni preuve, ni retour
arrière. Le script ne touche donc AUCUNE base — il produit du texte — et chaque motif est
mesuré sur le feed avant d'être proposé.

La régression que ces tests verrouillent vraiment : ma PREMIÈRE version minait tous les jetons
« purs » des URL de l'échantillon et proposait `%modern-warfare%` → Blacklist, `%agatha-christie%`,
`%marvel-tokon%`. Purs sur 10 % du feed, catastrophiques sur 100 % : ce sont des NOMS DE JEUX.
Les motifs ne viennent plus que du VOCABULAIRE de routage (« forbidden region: X », « skip
category: Y »), c'est-à-dire du mot qui a fait décider notre routeur.
"""

import json
import pathlib
import re
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

SCRIPT = ROOT / "scripts" / "13_sort_sql.py"
SRC = SCRIPT.read_text(encoding="utf-8")

sys.path.insert(0, str(ROOT / "scripts"))
import importlib.util
_spec = importlib.util.spec_from_file_location("sort_sql", SCRIPT)
sort_sql = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sort_sql)


def _row(offer_id, name, url, reason=""):
    return {"offer_id": offer_id, "name": name, "url": url, "reason": reason,
            "store_id": "1"}


class GeneratedSqlIsNarrowTests(unittest.TestCase):
    def test_the_statement_shape_is_the_only_one_we_emit(self):
        stmt = sort_sql.sql({"pattern": "%philippines%", "target": "8"})
        self.assertEqual(
            stmt,
            "UPDATE `aksfeeds_offer` SET `listId`=8 "
            "WHERE `url` LIKE '%philippines%' AND `listId`=9;")

    def test_it_is_always_bounded_to_the_pending_list(self):
        self.assertIn("AND `listId`={PENDING_LIST}", SRC)
        self.assertEqual(sort_sql.PENDING_LIST, 9)
        stmt = sort_sql.sql({"pattern": "%x-y%", "target": "21"})
        self.assertTrue(stmt.endswith("AND `listId`=9;"), stmt)

    def test_the_emitted_statement_can_only_ever_be_this_one(self):
        """Une seule forme sort d'ici, et elle est vérifiée par expression régulière —
        pas par une chasse aux mots-clés dans le source, qui attraperait `path.insert`."""

        shape = re.compile(
            r"^UPDATE `aksfeeds_offer` SET `listId`=\d+ "
            r"WHERE `url` LIKE '[%A-Za-z0-9._/+-]+' AND `listId`=9;$")
        for target, pat in (("8", "%philippines%"), ("21", "%gift-card%"), ("30", "%account%")):
            with self.subTest(target=target):
                self.assertRegex(sort_sql.sql({"pattern": pat, "target": target}), shape)

    def test_the_source_builds_no_other_statement(self):
        """Le seul gabarit de requête du fichier est celui-là : rien qui construise un
        DELETE, un DROP ou un INSERT SQL."""

        import ast
        strings = [n.value for n in ast.walk(ast.parse(SRC))
                   if isinstance(n, ast.Constant) and isinstance(n.value, str)]
        sqlish = [s for s in strings
                  if re.search(r"\b(DELETE|DROP|INSERT|TRUNCATE|ALTER)\b\s+", s.upper())]
        self.assertEqual(sqlish, [], sqlish)

    def test_the_target_must_be_an_integer(self):
        with self.assertRaises(ValueError):
            sort_sql.sql({"pattern": "%x%", "target": "8; DROP TABLE x"})

    def test_a_pattern_with_quotes_or_spaces_is_refused(self):
        for bad in ("%o'brien%", "%a b%", "%x%'; --", "%café%"):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    sort_sql.sql({"pattern": bad, "target": "8"})

    def test_no_database_driver_is_imported(self):
        for drv in ("pymysql", "MySQLdb", "mysql.connector", "sqlalchemy", "psycopg"):
            with self.subTest(drv=drv):
                self.assertNotIn(drv, SRC)


class MeasurementDecidesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.run = self.tmp / "runs" / "scan"
        self.run.mkdir(parents=True)

    def _write(self, rows, by_list, unrouted=()):
        (self.run / "offers.json").write_text(json.dumps({"offers": rows}), encoding="utf-8")
        (self.run / "sort_plan.json").write_text(
            json.dumps({"by_list": by_list, "unrouted": list(unrouted)}), encoding="utf-8")
        return sort_sql._classify(self.run)

    def test_a_pattern_that_would_hit_a_real_game_is_refused(self):
        """Une seule ligne « candidat création » suffit : ce serait blacklister un jeu."""

        rows = [_row("1", "Razer Gold PHILIPPINES", "https://m.test/razer-gold-philippines"),
                _row("2", "Some Game", "https://m.test/some-game-philippines-edition")]
        dest, by_url = self._write(
            rows, {"8": {"offers": [dict(rows[0], reason="forbidden region: PHILIPPINES")]}})
        m = sort_sql.measure("%philippines%", "8", dest, by_url)
        self.assertEqual(m["hits"], 2)
        self.assertEqual(m["collateral"], 1)
        why = sort_sql.verdict(m)
        self.assertIsNotNone(why)
        self.assertIn("vrai", why)

    def test_a_pattern_that_crosses_two_lists_is_refused(self):
        rows = [_row("1", "A", "https://m.test/gift-card-a"),
                _row("2", "B", "https://m.test/gift-card-b")]
        dest, by_url = self._write(rows, {
            "21": {"offers": [dict(rows[0], reason="skip category: GIFT CARD")]},
            "30": {"offers": [dict(rows[1], reason="skip category: ACCOUNT")]}})
        m = sort_sql.measure("%gift-card%", "21", dest, by_url)
        self.assertEqual(m["conflict"], 1)
        self.assertIsNotNone(sort_sql.verdict(m))

    def test_a_single_hit_never_generalises(self):
        rows = [_row("1", "A", "https://m.test/only-one-philippines")]
        dest, by_url = self._write(
            rows, {"8": {"offers": [dict(rows[0], reason="forbidden region: PHILIPPINES")]}})
        self.assertIsNotNone(sort_sql.verdict(sort_sql.measure("%philippines%", "8", dest, by_url)))

    def test_a_clean_pattern_passes_and_reports_its_count(self):
        rows = [_row(str(i), f"Razer {i} PHILIPPINES",
                     f"https://m.test/razer-{i}-philippines") for i in range(3)]
        dest, by_url = self._write(
            rows, {"8": {"offers": [dict(r, reason="forbidden region: PHILIPPINES")
                                    for r in rows]}})
        m = sort_sql.measure("%philippines%", "8", dest, by_url)
        self.assertIsNone(sort_sql.verdict(m))
        self.assertEqual((m["hits"], m["agree"], m["collateral"]), (3, 3, 0))


class PatternsComeFromTheRoutingVocabularyTests(unittest.TestCase):
    """La régression qui compte : plus jamais un nom de jeu comme motif."""

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.run = self.tmp / "runs" / "scan"
        self.run.mkdir(parents=True)

    def test_a_game_name_shared_by_routed_rows_is_NOT_proposed(self):
        rows = [_row("1", "Modern Warfare A", "https://m.test/modern-warfare-a-philippines"),
                _row("2", "Modern Warfare B", "https://m.test/modern-warfare-b-philippines")]
        plan = {"by_list": {"8": {"offers": [dict(r, reason="forbidden region: PHILIPPINES")
                                             for r in rows]}}, "unrouted": []}
        (self.run / "offers.json").write_text(json.dumps({"offers": rows}), encoding="utf-8")
        (self.run / "sort_plan.json").write_text(json.dumps(plan), encoding="utf-8")
        dest, by_url = sort_sql._classify(self.run)
        pats = {m["pattern"] for m in sort_sql.propose(dest, by_url, plan)}
        self.assertIn("%philippines%", pats, "le mot du motif de routage, lui, est proposé")
        self.assertNotIn("%modern-warfare%", pats,
                         "un nom de jeu pur dans l'échantillon reste un nom de jeu")

    def test_the_vocabulary_term_is_read_from_the_reason(self):
        self.assertEqual(sort_sql._vocab_term("forbidden region: PHILIPPINES"), "PHILIPPINES")
        self.assertEqual(sort_sql._vocab_term("skip category: GIFT CARD"), "GIFT CARD")
        self.assertEqual(sort_sql._vocab_term("skip category: SOFTWARE (software/app — x)"),
                         "SOFTWARE")
        self.assertIsNone(sort_sql._vocab_term("quelque chose d'autre"))
        self.assertIsNone(sort_sql._vocab_term(""))


class TheCliAuditsAPatternTests(unittest.TestCase):
    def test_check_mode_prints_the_breakdown_without_emitting_sql(self):
        tmp = pathlib.Path(tempfile.mkdtemp())
        run = ROOT / "runs" / "___sqltest"
        run.mkdir(parents=True, exist_ok=True)
        try:
            rows = [_row("1", "Razer PHILIPPINES", "https://m.test/razer-philippines"),
                    _row("2", "Vrai Jeu", "https://m.test/vrai-jeu-philippines")]
            (run / "offers.json").write_text(json.dumps({"offers": rows}), encoding="utf-8")
            (run / "sort_plan.json").write_text(json.dumps(
                {"by_list": {"8": {"offers": [dict(rows[0],
                                                   reason="forbidden region: PHILIPPINES")]}},
                 "unrouted": []}), encoding="utf-8")
            proc = subprocess.run(
                [sys.executable, str(SCRIPT), "--run-id", "___sqltest",
                 "--check", "%philippines%:8"],
                capture_output=True, text=True, timeout=60, cwd=ROOT)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertIn("collatéral 1", proc.stdout)
            self.assertNotIn("UPDATE", proc.stdout, "un motif audité n'est pas du SQL à copier")
        finally:
            for f in run.glob("*"):
                f.unlink()
            run.rmdir()


if __name__ == "__main__":
    unittest.main()

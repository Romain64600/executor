"""Audit de Romain sur les 14 commits 0f2c871..36c83fc — trois défauts, trois corrections.

Ses mots : « la mesure SQL peut manquer des lignes réellement visées, un scan privé de
offers.json est tout de même déclaré mesuré, et le premier submit enfant efface le suivi du
sweep CLI ». Les trois sont réels, et les deux premiers touchent la SEULE garde de la voie
SQL : il n'y a pas de preuve après coup, Romain exécutant lui-même les requêtes.
"""

import json
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.admin.sort_sql_view import IncompleteScan, _like, sort_sql_payload


def _scan(tmp, rows, by_list, drop_offers=False, corrupt=False):
    d = pathlib.Path(tmp) / "runs" / "scan"
    d.mkdir(parents=True)
    if corrupt:
        (d / "offers.json").write_text("{pas du json", encoding="utf-8")
    elif not drop_offers:
        (d / "offers.json").write_text(json.dumps({"offers": rows}), encoding="utf-8")
    (d / "sort_plan.json").write_text(
        json.dumps({"by_list": by_list, "unrouted": []}), encoding="utf-8")
    return pathlib.Path(tmp)


class LikeSemanticsTests(unittest.TestCase):
    """`[P1]` « Elle cherche une sous-chaîne littérale et retire les paramètres d'URL,
    contrairement au LIKE généré. »"""

    def test_underscore_is_a_WILDCARD_as_in_sql(self):
        """L'exemple exact de Romain : %digital_extras% sélectionne « digital-extras »."""

        self.assertTrue(_like("%digital_extras%", "https://m.test/a-digital-extras-pack"))
        self.assertTrue(_like("%digital_extras%", "https://m.test/a-digital_extras-pack"))
        self.assertTrue(_like("%digital_extras%", "https://m.test/a-digitalXextras-pack"))

    def test_percent_matches_anything(self):
        self.assertTrue(_like("%gift-card%", "https://m.test/x/a-gift-card-20?x=1"))
        self.assertFalse(_like("%gift-card%", "https://m.test/x/a-giftcard-20"))

    def test_the_query_string_is_NOT_stripped(self):
        """La colonne `url` contient les paramètres : un motif qui les vise compte."""

        self.assertTrue(_like("%currency=EUR%", "https://m.test/x?currency=EUR&utm=a"))

    def test_matching_ignores_case_like_a_ci_collation(self):
        self.assertTrue(_like("%GIFT-CARD%", "https://m.test/a-gift-card"))

    def test_a_dot_in_the_pattern_is_not_a_regex_dot(self):
        """Le motif est du SQL, pas une expression régulière : `.` reste littéral."""

        self.assertTrue(_like("%gog.com%", "https://m.test/a-gog.com-key"))
        self.assertFalse(_like("%gog.com%", "https://m.test/a-gogXcom-key"))

    def test_the_measurement_counts_what_sql_would_move(self):
        """Le cas qui rendait la garde muette : collatéral annoncé nul, offres déplacées."""

        with tempfile.TemporaryDirectory() as tmp:
            rows = [{"offer_id": "1", "name": "Vrai Jeu",
                     "url": "https://m.test/some-game-digital-extras"}]
            root = _scan(tmp, rows, {})           # aucune ligne routée → le jeu est candidat
            payload = sort_sql_payload(root / "runs", "scan", repo_root=root)
        rule = next(r for r in payload["rules"] if r["pattern"] == "%digital_extras%")
        self.assertEqual(rule["hits"], 1, "la ligne est bien visée par le LIKE")
        self.assertEqual(rule["collateral"], 1, "et c'est un vrai jeu")


class AnUnusableScanIsNotMeasuredTests(unittest.TestCase):
    """`[P2]` « Si offers.json manque ou est corrompu, le code poursuit avec une liste vide et
    renvoie measured: true. » Le collatéral devenait nul par ABSENCE de données."""

    def _payload(self, **kw):
        with tempfile.TemporaryDirectory() as tmp:
            root = _scan(tmp, [], {}, **kw)
            return sort_sql_payload(root / "runs", "scan", repo_root=root)

    def test_a_missing_offers_file_is_reported_unmeasured(self):
        payload = self._payload(drop_offers=True)
        self.assertFalse(payload["measured"])
        self.assertIn("inexploitable", payload["note"])

    def test_a_corrupt_offers_file_is_reported_unmeasured(self):
        payload = self._payload(corrupt=True)
        self.assertFalse(payload["measured"])

    def test_nothing_is_proposed_from_an_unusable_scan(self):
        """Sans mesure, aucune promotion ne doit pouvoir s'appuyer sur un chiffre."""

        for kw in ({"drop_offers": True}, {"corrupt": True}):
            with self.subTest(kw=kw):
                payload = self._payload(**kw)
                self.assertEqual(payload["proposals"], [])
                self.assertEqual(payload["conflicted"], [])
                self.assertTrue(all(r["measured"] is False for r in payload["rules"]))

    def test_the_rules_are_still_SERVED_just_not_measured(self):
        """On n'ampute pas la liste : on dit seulement qu'on ne sait pas ce qu'elle toucherait."""

        from src.sort_sql_rules import RULES
        payload = self._payload(drop_offers=True)
        self.assertEqual(len(payload["rules"]), len(RULES))


class AChildSubmitDoesNotEraseItsParentTests(unittest.TestCase):
    """`[P2]` « Chaque submit enfant écrase le marqueur du sweep, puis le supprime en sortant.
    Le parent continue, mais la console ne le détecte plus. »"""

    def test_the_child_only_announces_itself_when_nobody_else_has(self):
        src = (ROOT / "scripts" / "05_submit.py").read_text(encoding="utf-8")
        self.assertIn("if run_marker.read_marker(ROOT) is None:", src)
        block = src[src.index("if run_marker.read_marker(ROOT) is None:"):]
        block = block[:block.index("\n\n")]
        self.assertIn("write_marker", block)
        self.assertIn("atexit.register", block,
                      "le nettoyage doit être DANS la branche : sinon l'enfant efface le parent")

    def test_a_live_parent_marker_survives_a_child(self):
        from src import run_marker
        with tempfile.TemporaryDirectory() as tmp:
            run_marker.write_marker(tmp, run_id="sweep-parent", kind="data_entry_auto")
            # ce que fait l'enfant depuis la correction : il regarde d'abord
            self.assertIsNotNone(run_marker.read_marker(tmp))
            # et ne clôt que SON run — jamais celui d'un autre
            self.assertFalse(run_marker.clear_marker(tmp, "enfant-submit"))
            still = run_marker.read_marker(tmp)
        self.assertIsNotNone(still)
        self.assertEqual(still["run_id"], "sweep-parent")


if __name__ == "__main__":
    unittest.main()

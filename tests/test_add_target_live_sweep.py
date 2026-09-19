"""Ajouter un marchand à un sweep EN COURS (Romain, 2026-09-19).

« On a l'option pour ajouter un marchand à un sweep en cours ? » — non, il n'y en avait
aucune : `scripts/10_data_entry_auto.py` lisait `--targets` une fois au démarrage et itérait
une liste figée. Couper un sweep de plusieurs heures pour y ajouter un marchand, c'était
perdre le balayage en cours.

Le canal est un fichier du dossier de run, avec UN SEUL écrivain (la console) et UN SEUL
lecteur (le sweep). Pas de lecture-modification-écriture des deux côtés, donc pas de course à
arbitrer. Le sweep le relit à chaque FRONTIÈRE de marchand, jamais au milieu d'une page.
"""

import importlib.util
import json
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src import run_marker                                       # noqa: E402
from src.admin.submit_manager import SubmitManager, SubmitStartError   # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "sweep_cli", ROOT / "scripts" / "10_data_entry_auto.py")
SWEEP = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(SWEEP)

RUN = "20260919-082932-auto"


class TheQueueIsWrittenByTheConsoleOnly(unittest.TestCase):
    def setUp(self):
        self.root = pathlib.Path(tempfile.mkdtemp())
        (self.root / "state").mkdir(parents=True)
        self.run_dir = self.root / "runs" / RUN
        self.run_dir.mkdir(parents=True)
        self.manager = SubmitManager(self.root)

    def _sweep_is_running(self):
        run_marker.write_marker(self.root, run_id=RUN, kind="data_entry_auto", source="admin")

    def test_no_sweep_running_is_refused(self):
        """Sans run actif l'ajout partirait dans le vide : on refuse au lieu d'écrire un
        fichier que personne ne lira."""

        with self.assertRaises(SubmitStartError) as ctx:
            self.manager.add_sweep_target("Gamerall", "13", by="romain")
        self.assertEqual(ctx.exception.code, "no_sweep_running")
        self.assertEqual(ctx.exception.http_status, 409)

    def test_a_target_is_queued_and_the_sweep_reads_it(self):
        self._sweep_is_running()
        out = self.manager.add_sweep_target("Gamerall", "13", by="romain")
        self.assertTrue(out["queued"])
        self.assertEqual(out["position"], 1)
        self.assertEqual(SWEEP.read_targets_queue(self.run_dir), [("Gamerall", "13")])

    def test_a_double_click_does_not_queue_twice(self):
        self._sweep_is_running()
        self.manager.add_sweep_target("Gamerall", "13", by="romain")
        again = self.manager.add_sweep_target("Gamerall", "13", by="romain")
        self.assertFalse(again["queued"])
        self.assertEqual(SWEEP.read_targets_queue(self.run_dir), [("Gamerall", "13")])

    def test_the_order_of_addition_is_kept(self):
        self._sweep_is_running()
        self.manager.add_sweep_target("Gamerall", "13", by="romain")
        self.manager.add_sweep_target("MMOGA", "12", by="romain")
        self.assertEqual(SWEEP.read_targets_queue(self.run_dir),
                         [("Gamerall", "13"), ("MMOGA", "12")])

    def test_a_non_numeric_store_is_refused(self):
        self._sweep_is_running()
        with self.assertRaises(SubmitStartError) as ctx:
            self.manager.add_sweep_target("Gamerall", "treize", by="romain")
        self.assertEqual(ctx.exception.code, "bad_store_id")

    def test_the_write_is_atomic(self):
        """Le sweep lit ce fichier pendant qu'il tourne : jamais de troncature visible."""

        self._sweep_is_running()
        self.manager.add_sweep_target("Gamerall", "13", by="romain")
        self.assertFalse(list(self.run_dir.glob("*.tmp")), "aucun temporaire ne doit rester")
        self.assertIsInstance(
            json.loads((self.run_dir / "targets_queue.json").read_text(encoding="utf-8")), list)


class TheSweepNeverChokesOnTheQueue(unittest.TestCase):
    """Un fichier illisible ne doit pas tuer un run de 30 h. Le pire cas acceptable est
    « le marchand ajouté n'est pas pris », visible tout de suite dans la console — jamais
    une écriture fausse sur AKS, jamais un run mort."""

    def setUp(self):
        self.run_dir = pathlib.Path(tempfile.mkdtemp())

    def test_absent_file_reads_as_empty(self):
        self.assertEqual(SWEEP.read_targets_queue(self.run_dir), [])

    def test_corrupt_file_reads_as_empty(self):
        (self.run_dir / "targets_queue.json").write_text("{ pas du json", encoding="utf-8")
        self.assertEqual(SWEEP.read_targets_queue(self.run_dir), [])

    def test_entries_without_a_store_are_dropped(self):
        (self.run_dir / "targets_queue.json").write_text(json.dumps(
            [{"merchant": "Gamerall"}, {"store_id": "13"}, "texte",
             {"merchant": "MMOGA", "store_id": "12"}]), encoding="utf-8")
        self.assertEqual(SWEEP.read_targets_queue(self.run_dir), [("MMOGA", "12")])

    def test_no_sweep_dir_reads_as_empty(self):
        self.assertEqual(SWEEP.read_targets_queue(None), [])


class TheLoopIsExtensible(unittest.TestCase):
    """La boucle des cibles était un `for … in targets` sur une liste figée. Elle est
    maintenant indexée, et relit la file AVANT le test de fin — sans quoi une cible ajoutée
    pendant le DERNIER marchand serait perdue."""

    SOURCE = (ROOT / "scripts" / "10_data_entry_auto.py").read_text(encoding="utf-8")

    def test_the_loop_is_no_longer_a_frozen_for(self):
        self.assertNotIn("for merchant, store_id in targets:", self.SOURCE)
        self.assertIn("while True:", self.SOURCE)

    def test_the_queue_is_read_before_the_exit_test(self):
        body = self.SOURCE[self.SOURCE.index("    planned = {"):]
        read_at = body.index("read_targets_queue(sweep_dir)")
        exit_at = body.index("if index >= len(targets):")
        self.assertLess(read_at, exit_at,
                        "relire la file APRÈS le test de fin perdrait la dernière cible ajoutée")


class TheConsoleControlIsWired(unittest.TestCase):
    HTML = (ROOT / "src" / "admin" / "static" / "auto.html").read_text(encoding="utf-8")
    JS = (ROOT / "src" / "admin" / "static" / "auto.js").read_text(encoding="utf-8")
    APP = (ROOT / "src" / "admin" / "app.py").read_text(encoding="utf-8")

    def test_the_control_lives_in_the_running_sweep_indicator(self):
        head = self.HTML[self.HTML.index('id="busy-ind"'):self.HTML.index('class="topbar-right"')]
        self.assertIn('id="add-live-merchant"', head)
        self.assertIn('id="add-live-btn"', head)

    def test_the_client_types_GO_like_every_real_write_path(self):
        self.assertIn('id="add-live-go"', self.HTML)
        self.assertIn('confirm: "GO"', self.JS)

    def test_the_route_re_checks_the_allowlist_server_side(self):
        handler = self.APP[self.APP.index("_post_data_entry_auto_add_target"):]
        handler = handler[:handler.index("def _post_data_entry_by_urls")]
        self.assertIn("rejection_reason(merchant, store_id)", handler)
        self.assertIn("confirm_required", handler)


if __name__ == "__main__":
    unittest.main()

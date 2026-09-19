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
    maintenant indexée, relit la file à chaque frontière de marchand, et — revue de Romain
    du 2026-09-19 — FERME la file avant sa toute dernière relecture."""

    SOURCE = (ROOT / "scripts" / "10_data_entry_auto.py").read_text(encoding="utf-8")

    def test_the_loop_is_no_longer_a_frozen_for(self):
        self.assertNotIn("for merchant, store_id in targets:", self.SOURCE)
        self.assertIn("while True:", self.SOURCE)

    def test_the_queue_is_drained_first_then_closed_then_drained_once_more(self):
        """L'ORDRE est la correction : fermer AVANT la dernière relecture. Un ajout que la
        console a accepté sans voir le marqueur a été écrit avant lui, donc la relecture qui
        suit la fermeture le voit. Relire puis fermer laisserait la fenêtre ouverte."""

        body = self.SOURCE[self.SOURCE.index("    queue_closed = False"):]
        body = body[:body.index("        merchant, store_id = targets[index]")]
        drain = body.index("drain_queue()")
        exit_test = body.index("if index >= len(targets):")
        close = body.index("close_targets_queue(sweep_dir)")
        flag = body.index("queue_closed = True")
        again = body.index("continue", close)
        self.assertLess(drain, exit_test, "la file se relit avant le test de fin")
        self.assertLess(exit_test, close, "on ne ferme qu'au moment de sortir")
        self.assertLess(close, flag)
        self.assertLess(flag, again, "après la fermeture on REPASSE par la relecture, on ne sort pas")
        self.assertIn("if queue_closed:\n                break", body)


class TheReaderEnforcesTheAllowlist(unittest.TestCase):
    """P1 (revue de Romain, 2026-09-19) — la route HTTP filtrait la liste blanche, pas le
    lecteur : `Difmark:167`, interdit au lancement, écrit directement dans le fichier,
    rejoignait l'exécution. Le point qui DÉCLENCHE les écritures vérifie lui-même."""

    def setUp(self):
        self.run_dir = pathlib.Path(tempfile.mkdtemp())

    def _queue(self, *entries):
        (self.run_dir / "targets_queue.json").write_text(json.dumps(
            [{"merchant": m, "store_id": s} for m, s in entries]), encoding="utf-8")

    def test_a_parked_merchant_written_by_hand_is_refused_not_swept(self):
        self._queue(("Difmark", "167"))
        recap, planned, refused = {}, set(), set()
        taken = SWEEP.take_from_queue(self.run_dir, planned, refused, recap, lambda: "t")
        self.assertEqual(taken, [], "Difmark ne doit JAMAIS rejoindre l'exécution")
        self.assertEqual([r["merchant"] for r in recap["targets_refused"]], ["Difmark"])
        self.assertIn("Difmark", recap["targets_refused"][0]["reason"])
        self.assertNotIn("targets_added", recap)

    def test_a_wrong_store_for_a_vetted_merchant_is_refused_too(self):
        self._queue(("Gamerall", "999"))
        recap = {}
        self.assertEqual(SWEEP.take_from_queue(self.run_dir, set(), set(), recap, lambda: "t"), [])
        self.assertIn("13", recap["targets_refused"][0]["reason"])

    def test_a_vetted_merchant_is_taken_once(self):
        self._queue(("Gamerall", "13"))
        recap, planned, refused = {}, set(), set()
        first = SWEEP.take_from_queue(self.run_dir, planned, refused, recap, lambda: "t")
        second = SWEEP.take_from_queue(self.run_dir, planned, refused, recap, lambda: "t")
        self.assertEqual(first, [("Gamerall", "13")])
        self.assertEqual(second, [], "déjà pris : la relecture suivante ne le reprend pas")
        self.assertEqual(len(recap["targets_added"]), 1)

    def test_a_refused_entry_is_recorded_once_not_at_every_reread(self):
        self._queue(("Difmark", "167"))
        recap, planned, refused = {}, set(), set()
        for _ in range(3):
            SWEEP.take_from_queue(self.run_dir, planned, refused, recap, lambda: "t")
        self.assertEqual(len(recap["targets_refused"]), 1)


class AnAddIsNeverAcceptedThenLost(unittest.TestCase):
    """P2 (revue de Romain, 2026-09-19) — un ajout arrivé APRÈS la dernière relecture
    répondait `queued: true`, puis le sweep se terminait sans le traiter : succès annoncé,
    marchand perdu, sortie 0. Le sweep écrit un marqueur de fermeture AVANT sa dernière
    relecture ; la console refuse dès qu'elle le voit, et re-vérifie APRÈS avoir écrit."""

    def setUp(self):
        self.root = pathlib.Path(tempfile.mkdtemp())
        (self.root / "state").mkdir(parents=True)
        self.run_dir = self.root / "runs" / RUN
        self.run_dir.mkdir(parents=True)
        self.manager = SubmitManager(self.root)
        run_marker.write_marker(self.root, run_id=RUN, kind="data_entry_auto", source="admin")

    def test_the_sweep_writes_the_closed_marker(self):
        SWEEP.close_targets_queue(self.run_dir)
        self.assertTrue((self.run_dir / "targets_queue.closed").is_file())

    def test_an_add_after_closing_is_refused_before_anything_is_written(self):
        SWEEP.close_targets_queue(self.run_dir)
        with self.assertRaises(SubmitStartError) as ctx:
            self.manager.add_sweep_target("Gamerall", "13", by="romain")
        self.assertEqual(ctx.exception.code, "sweep_finishing")
        self.assertFalse((self.run_dir / "targets_queue.json").exists(),
                         "rien n'est écrit : pas de fausse promesse, pas de fichier orphelin")

    def test_a_closing_that_lands_between_write_and_recheck_is_reported_not_promised(self):
        """La fenêtre exacte : le marqueur apparaît juste après l'écriture de l'entrée. On ne
        sait pas de quel côté de la dernière relecture l'écriture est tombée — on le DIT."""

        import src.admin.submit_manager as sm
        real_replace = sm.os.replace
        marker = self.run_dir / "targets_queue.closed"

        def replace_then_close(src, dst):
            real_replace(src, dst)
            marker.write_text("t", encoding="utf-8")       # le sweep ferme à cet instant

        sm.os.replace = replace_then_close
        try:
            out = self.manager.add_sweep_target("Gamerall", "13", by="romain")
        finally:
            sm.os.replace = real_replace
        self.assertFalse(out["queued"])
        self.assertIn("NON garantie", out["reason"])

    def test_the_protocol_end_to_end(self):
        """Le protocole de fin de boucle, joué avec les vraies fonctions des deux côtés :
        un ajout AVANT la fermeture est pris par la relecture qui la suit ; un ajout APRÈS
        est refusé. Aucun ajout accepté n'est perdu."""

        planned, refused, recap = set(), set(), {}
        targets = []
        # 1. le sweep a fini ses cibles : relecture → rien
        targets.extend(SWEEP.take_from_queue(self.run_dir, planned, refused, recap, lambda: "t"))
        self.assertEqual(targets, [])
        # 2. la console ajoute Gamerall — AVANT la fermeture : accepté
        self.assertTrue(self.manager.add_sweep_target("Gamerall", "13", by="romain")["queued"])
        # 3. le sweep ferme, PUIS relit une dernière fois : Gamerall est pris
        SWEEP.close_targets_queue(self.run_dir)
        targets.extend(SWEEP.take_from_queue(self.run_dir, planned, refused, recap, lambda: "t"))
        self.assertEqual(targets, [("Gamerall", "13")], "l'ajout accepté est traité")
        # 4. un ajout APRÈS la fermeture : refusé, jamais promis
        with self.assertRaises(SubmitStartError) as ctx:
            self.manager.add_sweep_target("MMOGA", "12", by="romain")
        self.assertEqual(ctx.exception.code, "sweep_finishing")


class AnAddIsBoundToTheDisplayedRun(unittest.TestCase):
    """P2 (revue de Romain, 2026-09-19) — la requête ne transmettait aucun run_id : si le
    sweep A finissait et que B démarrait entre l'affichage et le clic, le marchand rejoignait
    B, avec les paramètres de B."""

    def setUp(self):
        self.root = pathlib.Path(tempfile.mkdtemp())
        (self.root / "state").mkdir(parents=True)
        (self.root / "runs" / RUN).mkdir(parents=True)
        self.manager = SubmitManager(self.root)
        run_marker.write_marker(self.root, run_id=RUN, kind="data_entry_auto", source="admin")

    def test_a_stale_run_id_is_refused(self):
        with self.assertRaises(SubmitStartError) as ctx:
            self.manager.add_sweep_target("Gamerall", "13", by="romain",
                                          run_id="20260919-071948-auto")
        self.assertEqual(ctx.exception.code, "run_mismatch")
        self.assertEqual(ctx.exception.http_status, 409)
        self.assertEqual(ctx.exception.detail["active_run"], RUN)

    def test_the_matching_run_id_is_accepted(self):
        out = self.manager.add_sweep_target("Gamerall", "13", by="romain", run_id=RUN)
        self.assertTrue(out["queued"])
        self.assertEqual(out["run_id"], RUN)

    def test_the_client_sends_the_displayed_run_and_forgets_it_when_the_sweep_ends(self):
        js = (ROOT / "src" / "admin" / "static" / "auto.js").read_text(encoding="utf-8")
        self.assertIn("run_id: LIVE_RUN_ID", js)
        self.assertIn("LIVE_RUN_ID = runId || null;", js)
        end = js[js.index("function endSweepUi"):]
        end = end[:end.index("\n}")]
        self.assertIn("LIVE_RUN_ID = null;", end)

    def test_the_route_forwards_the_run_id(self):
        app = (ROOT / "src" / "admin" / "app.py").read_text(encoding="utf-8")
        handler = app[app.index("_post_data_entry_auto_add_target"):]
        handler = handler[:handler.index("def _post_data_entry_by_urls")]
        self.assertIn('run_id=str(body.get("run_id") or "") or None', handler)


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

"""Ajouter un marchand à un sweep EN COURS (Romain, 2026-09-19).

« On a l'option pour ajouter un marchand à un sweep en cours ? » — non, il n'y en avait
aucune : `scripts/10_data_entry_auto.py` lisait `--targets` une fois au démarrage et itérait
une liste figée. Couper un sweep de plusieurs heures pour y ajouter un marchand, c'était
perdre le balayage en cours.

Le canal est un fichier du dossier de run, avec UN SEUL écrivain (la console) et UN SEUL
lecteur (le sweep). Pas de lecture-modification-écriture des deux côtés, donc pas de course à
arbitrer. Le sweep le relit à chaque FRONTIÈRE de marchand, jamais au milieu d'une page.
"""

import json
import pathlib
import sys
import tempfile
import types
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src import run_marker                                       # noqa: E402
from src.admin.submit_manager import SubmitManager, SubmitStartError   # noqa: E402

SWEEP_PATH = ROOT / "scripts" / "10_data_entry_auto.py"


def load_sweep(name="sweep_cli"):
    """Charge le script depuis sa SOURCE, jamais depuis `scripts/__pycache__`.

    2026-09-19 : `spec_from_file_location` + `exec_module` écrit et relit un `.pyc`. Un cache
    périmé a fait passer un test au ROUGE alors que le correctif était bien sur disque — et,
    pire, aurait pu faire passer une mutation au VERT. On compile le texte courant : le test
    parle toujours du fichier tel qu'il est. C'est le troisième piège d'ordre de la journée,
    après la pollution du registre marchand et l'ancrage sur le dispatch."""

    mod = types.ModuleType(name)
    mod.__file__ = str(SWEEP_PATH)
    exec(compile(SWEEP_PATH.read_text(encoding="utf-8"), str(SWEEP_PATH), "exec"), mod.__dict__)
    return mod


SWEEP = load_sweep()

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
            self.manager.add_sweep_target("Gamerall", "13", by="romain", run_id=RUN)
        self.assertEqual(ctx.exception.code, "no_sweep_running")
        self.assertEqual(ctx.exception.http_status, 409)

    def test_a_target_is_queued_and_the_sweep_reads_it(self):
        self._sweep_is_running()
        out = self.manager.add_sweep_target("Gamerall", "13", by="romain", run_id=RUN)
        self.assertTrue(out["queued"])
        self.assertEqual(out["position"], 1)
        self.assertEqual(SWEEP.read_targets_queue(self.run_dir), [("Gamerall", "13")])

    def test_a_double_click_does_not_queue_twice(self):
        self._sweep_is_running()
        self.manager.add_sweep_target("Gamerall", "13", by="romain", run_id=RUN)
        again = self.manager.add_sweep_target("Gamerall", "13", by="romain", run_id=RUN)
        self.assertFalse(again["queued"])
        self.assertEqual(SWEEP.read_targets_queue(self.run_dir), [("Gamerall", "13")])

    def test_the_order_of_addition_is_kept(self):
        self._sweep_is_running()
        self.manager.add_sweep_target("Gamerall", "13", by="romain", run_id=RUN)
        self.manager.add_sweep_target("MMOGA", "12", by="romain", run_id=RUN)
        self.assertEqual(SWEEP.read_targets_queue(self.run_dir),
                         [("Gamerall", "13"), ("MMOGA", "12")])

    def test_a_non_numeric_store_is_refused(self):
        self._sweep_is_running()
        with self.assertRaises(SubmitStartError) as ctx:
            self.manager.add_sweep_target("Gamerall", "treize", by="romain", run_id=RUN)
        self.assertEqual(ctx.exception.code, "bad_store_id")

    def test_the_write_is_atomic(self):
        """Le sweep lit ce fichier pendant qu'il tourne : jamais de troncature visible."""

        self._sweep_is_running()
        self.manager.add_sweep_target("Gamerall", "13", by="romain", run_id=RUN)
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
        """L'ORDRE est la correction : fermer (dans le recap, atomiquement) AVANT la dernière
        relecture. Un ajout que la console a accepté sans voir la fermeture a été écrit avant
        elle, donc la relecture qui suit la fermeture le voit. Et si cette relecture rapporte
        une retardataire, la file est ROUVERTE pendant son balayage. (Le couplage réel est
        joué par TheLoopDrivenEndToEnd ; ceci épingle seulement la forme du protocole.)"""

        body = self.SOURCE[self.SOURCE.index("    index = 0\n    while True:"):]
        body = body[:body.index("        merchant, store_id = targets[index]")]
        drain = body.index("drain_queue()")
        exit_test = body.index("if index >= len(targets):")
        close = body.index("close_queue(True)")
        reopen = body.index("close_queue(False)")
        self.assertLess(drain, exit_test, "la file se relit avant le test de fin")
        self.assertLess(exit_test, close, "on ne ferme qu'au moment de sortir")
        self.assertLess(close, reopen, "après la fermeture on relit, et une retardataire rouvre")
        self.assertIn('if recap["queue_closed"]:\n                break', body)


class TheReaderEnforcesTheAllowlist(unittest.TestCase):
    """P1 (revue de Romain, 2026-09-19) — la route HTTP filtrait la liste blanche, pas le
    lecteur : un marchand interdit au lancement (`Keycense:130`, jamais vetté ; `Difmark:167`
    puis `Wyrel:162` ont tenu ce rôle avant leur entrée en liste blanche, le 2026-09-21 et le
    2026-09-24), écrit directement dans le fichier,
    rejoignait l'exécution. Le point qui DÉCLENCHE les écritures vérifie lui-même."""

    def setUp(self):
        self.run_dir = pathlib.Path(tempfile.mkdtemp())

    def _queue(self, *entries):
        (self.run_dir / "targets_queue.json").write_text(json.dumps(
            [{"merchant": m, "store_id": s} for m, s in entries]), encoding="utf-8")

    def test_a_parked_merchant_written_by_hand_is_refused_not_swept(self):
        self._queue(("Keycense", "130"))
        recap, planned, refused = {}, set(), set()
        taken = SWEEP.take_from_queue(self.run_dir, planned, refused, recap, lambda: "t")
        self.assertEqual(taken, [], "un marchand hors liste ne rejoint JAMAIS l'exécution")
        self.assertEqual([r["merchant"] for r in recap["targets_refused"]], ["Keycense"])
        self.assertIn("Keycense", recap["targets_refused"][0]["reason"])
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
        self._queue(("Keycense", "130"))
        recap, planned, refused = {}, set(), set()
        for _ in range(3):
            SWEEP.take_from_queue(self.run_dir, planned, refused, recap, lambda: "t")
        self.assertEqual(len(recap["targets_refused"]), 1)


def _recap(run_dir, **fields):
    (run_dir / "recap.json").write_text(json.dumps(fields), encoding="utf-8")


class AnAddIsNeverAcceptedThenLost(unittest.TestCase):
    """P2 (revue de Romain, 2026-09-19) — un ajout arrivé APRÈS la dernière relecture
    répondait `queued: true`, puis le sweep se terminait sans le traiter. L'état « fermée »
    vit dans le RECAP (`queue_closed`), écrit atomiquement AVANT la dernière relecture ; la
    console refuse dès qu'elle le voit, et re-vérifie APRÈS avoir écrit.

    Revue `/code-review` du même jour : l'état était un fichier à part, et ses deux cas
    spéciaux (fermer après la boucle, effacer au démarrage) ont chacun ouvert un défaut. Le
    recap est déjà relu à chaque ajout, rebâti à chaque lancement, et stampé sur toute sortie."""

    def setUp(self):
        self.root = pathlib.Path(tempfile.mkdtemp())
        (self.root / "state").mkdir(parents=True)
        self.run_dir = self.root / "runs" / RUN
        self.run_dir.mkdir(parents=True)
        self.manager = SubmitManager(self.root)
        run_marker.write_marker(self.root, run_id=RUN, kind="data_entry_auto", source="admin")

    def test_an_add_after_closing_is_refused_before_anything_is_written(self):
        _recap(self.run_dir, queue_closed=True)
        with self.assertRaises(SubmitStartError) as ctx:
            self.manager.add_sweep_target("Gamerall", "13", by="romain", run_id=RUN)
        self.assertEqual(ctx.exception.code, "sweep_finishing")
        self.assertFalse((self.run_dir / "targets_queue.json").exists(),
                         "rien n'est écrit : pas de fausse promesse, pas de fichier orphelin")

    def test_closing_wins_over_the_duplicate_branches(self):
        """Revue `/code-review` : une relance après « NON garantie » recevait 200 « déjà dans
        la file », qui se lit comme une promesse. Fermé = 409, quoi qu'il y ait dans la file."""

        (self.run_dir / "targets_queue.json").write_text(json.dumps(
            [{"merchant": "Gamerall", "store_id": "13"}]), encoding="utf-8")
        _recap(self.run_dir, queue_closed=True, planned=[{"merchant": "Gamerall", "store_id": "13"}])
        with self.assertRaises(SubmitStartError) as ctx:
            self.manager.add_sweep_target("Gamerall", "13", by="romain", run_id=RUN)
        self.assertEqual(ctx.exception.code, "sweep_finishing")

    def test_a_closing_that_lands_between_write_and_recheck_is_reported_not_promised(self):
        """La fenêtre exacte : la fermeture apparaît juste après l'écriture de l'entrée. On ne
        sait pas de quel côté de la dernière relecture l'écriture est tombée — on le DIT."""

        import src.admin.submit_manager as sm
        real_replace = sm.os.replace

        def replace_then_close(src, dst):
            real_replace(src, dst)
            _recap(self.run_dir, queue_closed=True)      # le sweep ferme à cet instant

        sm.os.replace = replace_then_close
        try:
            out = self.manager.add_sweep_target("Gamerall", "13", by="romain", run_id=RUN)
        finally:
            sm.os.replace = real_replace
        self.assertFalse(out["queued"])
        self.assertIn("NON garantie", out["reason"])

    def test_a_non_dict_recap_does_not_crash_the_route(self):
        """Revue `/code-review` : `{"recap": null}` (la forme émise sans recap) ou une liste au
        sommet faisaient répondre 500 à chaque clic."""

        for shape in ('{"run_id": "x", "recap": null}', '[1, 2, 3]', '"texte"'):
            with self.subTest(shape=shape):
                (self.run_dir / "recap.json").write_text(shape, encoding="utf-8")
                (self.run_dir / "targets_queue.json").unlink(missing_ok=True)
                out = self.manager.add_sweep_target("Gamerall", "13", by="romain", run_id=RUN)
                self.assertTrue(out["queued"])

    def test_every_outcome_is_logged_as_jsonl(self):
        """AGENTS.md : « JSONL logs for every action » — la preuve qu'une course a eu lieu en
        production ne doit pas vivre seulement dans la réponse HTTP."""

        _recap(self.run_dir, planned=[{"merchant": "Gamivo", "store_id": "51"}])
        self.manager.add_sweep_target("Gamerall", "13", by="romain", run_id=RUN)        # queued
        self.manager.add_sweep_target("Gamivo", "51", by="romain", run_id=RUN)          # déjà cible
        with self.assertRaises(SubmitStartError):
            self.manager.add_sweep_target("MMOGA", "12", by="romain", run_id="autre")   # refusé
        log = (self.root / "logs" / f"{RUN}.jsonl").read_text(encoding="utf-8")
        events = [json.loads(l)["event"] for l in log.splitlines() if l.strip()]
        self.assertIn("add_target_queued", events)
        self.assertIn("add_target_ignored", events)
        self.assertIn("add_target_refused", events)

    def test_the_protocol_end_to_end(self):
        """Le protocole de fin de boucle, joué avec les vraies fonctions des deux côtés :
        un ajout AVANT la fermeture est pris par la relecture qui la suit ; un ajout APRÈS
        est refusé. Aucun ajout accepté n'est perdu."""

        planned, refused, taken, recap = set(), set(), set(), {"planned": []}
        targets = []
        _recap(self.run_dir, queue_closed=False, planned=[])
        targets.extend(SWEEP.take_from_queue(self.run_dir, planned, refused, recap, lambda: "t", taken))
        self.assertEqual(targets, [])
        # la console ajoute Gamerall — AVANT la fermeture : accepté
        self.assertTrue(self.manager.add_sweep_target("Gamerall", "13", by="romain", run_id=RUN)["queued"])
        # le sweep ferme (recap), PUIS relit une dernière fois : Gamerall est pris
        _recap(self.run_dir, queue_closed=True, planned=[])
        targets.extend(SWEEP.take_from_queue(self.run_dir, planned, refused, recap, lambda: "t", taken))
        self.assertEqual(targets, [("Gamerall", "13")], "l'ajout accepté est traité")
        # un ajout APRÈS la fermeture : refusé, jamais promis
        with self.assertRaises(SubmitStartError) as ctx:
            self.manager.add_sweep_target("MMOGA", "12", by="romain", run_id=RUN)
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
        handler = app[app.index("def _post_data_entry_auto_add_target"):]
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
        handler = self.APP[self.APP.index("def _post_data_entry_auto_add_target"):]
        handler = handler[:handler.index("def _post_data_entry_by_urls")]
        self.assertIn("rejection_reason(merchant, store_id)", handler)
        self.assertIn("confirm_required", handler)


if __name__ == "__main__":
    unittest.main()


class TheRunIdIsRequiredNotOptional(unittest.TestCase):
    """Réfuteur du 2026-09-19 — la première version rendait `run_id` FACULTATIF côté serveur,
    et le client l'envoie à null dès que l'onglet a vu « Sweep terminé » (bouton jamais
    désactivé) : la garde était sautée, le marchand rejoignait n'importe quel run B. Un
    auto.js en cache (sans le champ) la contournait aussi — même structure que le P1."""

    def setUp(self):
        self.root = pathlib.Path(tempfile.mkdtemp())
        (self.root / "state").mkdir(parents=True)
        (self.root / "runs" / RUN).mkdir(parents=True)
        self.manager = SubmitManager(self.root)
        run_marker.write_marker(self.root, run_id=RUN, kind="data_entry_auto", source="admin")

    def test_no_run_id_is_refused_even_with_a_run_active(self):
        for absent in (None, ""):
            with self.subTest(run_id=absent):
                with self.assertRaises(SubmitStartError) as ctx:
                    self.manager.add_sweep_target("Gamerall", "13", by="romain", run_id=absent)
                self.assertEqual(ctx.exception.code, "run_required")
                self.assertEqual(ctx.exception.http_status, 409)
        self.assertFalse((self.root / "runs" / RUN / "targets_queue.json").exists())

    def test_the_button_is_disabled_until_a_run_is_displayed(self):
        html = (ROOT / "src" / "admin" / "static" / "auto.html").read_text(encoding="utf-8")
        js = (ROOT / "src" / "admin" / "static" / "auto.js").read_text(encoding="utf-8")
        line = next(l for l in html.splitlines() if 'id="add-live-btn"' in l)
        self.assertIn(" disabled", line, "désactivé au chargement")
        start = js[js.index("function startPolling"):]
        self.assertIn('live.disabled = !LIVE_RUN_ID', start[:600], "activé quand un run est affiché")
        sync = js[js.index("function syncGo"):]
        sync = sync[:sync.index("\n}")]
        self.assertIn("live.disabled = !SWEEP_RUNNING", sync, "désactivé quand le sweep finit")
        self.assertIn("ajouté à ${r.run_id}", js, "le run est nommé dans le message")


class AMerchantAlreadyInThePlanIsNotPromised(unittest.TestCase):
    """Réfuteur du 2026-09-19 — un marchand DÉJÀ cible du run (plan initial ou ajout pris)
    recevait « ✔ ajouté — position N », puis le lecteur l'ignorait SANS TRACE. Le sweep publie
    son plan dans le recap (`planned`) ; la console refuse avant de promettre ; le lecteur
    inscrit `targets_ignored` pour un doublon écrit à la main."""

    def setUp(self):
        self.root = pathlib.Path(tempfile.mkdtemp())
        (self.root / "state").mkdir(parents=True)
        self.run_dir = self.root / "runs" / RUN
        self.run_dir.mkdir(parents=True)
        self.manager = SubmitManager(self.root)
        run_marker.write_marker(self.root, run_id=RUN, kind="data_entry_auto", source="admin")
        (self.run_dir / "recap.json").write_text(json.dumps({
            "planned": [{"merchant": "Gamivo", "store_id": "51"}],
            "targets": [{"merchant": "Gamivo", "store_id": "51", "recap": None}],
            "targets_added": [{"merchant": "MMOGA", "store_id": "12", "at": "t"}]}), encoding="utf-8")

    def test_planned_or_already_added_merchants_are_refused_without_writing(self):
        for m, sid in (("Gamivo", "51"), ("gamivo", "51"), ("MMOGA", "12")):
            with self.subTest(merchant=m):
                out = self.manager.add_sweep_target(m, sid, by="romain", run_id=RUN)
                self.assertFalse(out["queued"])
                self.assertIn("déjà cible", out["reason"])
        self.assertFalse((self.run_dir / "targets_queue.json").exists())

    def test_a_new_merchant_still_goes_through(self):
        self.assertTrue(self.manager.add_sweep_target("Gamerall", "13", by="romain", run_id=RUN)["queued"])

    def test_the_reader_leaves_a_trace_for_a_hand_written_duplicate(self):
        (self.run_dir / "targets_queue.json").write_text(json.dumps(
            [{"merchant": "Gamivo", "store_id": "51"}]), encoding="utf-8")
        recap, planned = {}, {("gamivo", "51")}
        taken = SWEEP.take_from_queue(self.run_dir, planned, set(), recap, lambda: "t")
        self.assertEqual(taken, [])
        self.assertEqual(recap["targets_ignored"][0]["reason"], "déjà cible du sweep")
        SWEEP.take_from_queue(self.run_dir, planned, set(), recap, lambda: "t")
        self.assertEqual(len(recap["targets_ignored"]), 1, "une trace, pas une par relecture")

    def test_main_publishes_the_plan_in_the_recap(self):
        src = (ROOT / "scripts" / "10_data_entry_auto.py").read_text(encoding="utf-8")
        self.assertIn('recap["planned"] = [{"merchant": m, "store_id": str(sid)} for m, sid in targets]', src)
        self.assertIn('recap["planned"].extend(', src, "tenu à jour à chaque ajout pris")


class TheChannelIsCleanOnRelaunchOnly(unittest.TestCase):
    """Réfuteur (P3) : une relance avec le MÊME --run-id héritait de l'ancienne file. Revue
    `/code-review` : l'effacement inconditionnel détruisait un ajout accepté PENDANT le
    démarrage (la console déclare le run occupé avant de lancer le processus). Le nettoyage
    n'a lieu que sur une relance — un recap.json déjà présent."""

    SOURCE = (ROOT / "scripts" / "10_data_entry_auto.py").read_text(encoding="utf-8")

    def test_the_unlink_is_gated_on_a_previous_recap(self):
        i = self.SOURCE.index('if (sweep_dir / "recap.json").exists():')
        j = self.SOURCE.index("sweep_dir.mkdir(parents=True, exist_ok=True)")
        self.assertLess(i, j)
        self.assertIn("(sweep_dir / TARGETS_QUEUE).unlink(missing_ok=True)", self.SOURCE[i:j])

    def test_no_closed_file_remains_anywhere(self):
        """L'état vit dans le recap : plus de constante, plus de fonction, plus de fichier."""

        for f in ("scripts/10_data_entry_auto.py", "src/admin/submit_manager.py"):
            src = (ROOT / f).read_text(encoding="utf-8")
            self.assertNotIn("TARGETS_QUEUE_CLOSED", src, f)
            self.assertNotIn("close_targets_queue", src, f)


class TheLoopDrivenEndToEnd(unittest.TestCase):
    """Revue `/code-review` : le couplage boucle ↔ file n'était ancré que par des chaînes de
    caractères — des mutants qui n'étendaient jamais `targets`, ou déplaçaient la relecture
    après le test de fin, passaient la suite entière. Ici la VRAIE boucle de `main()` tourne,
    avec un `run_sweep` bouchonné qui écrit dans la file pendant le run."""

    def setUp(self):
        self.MOD = load_sweep("sweep_cli_loop")
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.MOD.ROOT = self.tmp
        (self.tmp / "state").mkdir()
        self.run_dir = self.tmp / "runs" / RUN

    def _queue(self, *entries):
        self.run_dir.mkdir(parents=True, exist_ok=True)
        (self.run_dir / "targets_queue.json").write_text(json.dumps(
            [{"merchant": m, "store_id": s} for m, s in entries]), encoding="utf-8")

    def _main(self, targets, sweep_hook):
        from unittest import mock
        swept = []

        def fake_run_sweep(cfg, stages, *, on_page=lambda r: None, **kw):
            swept.append(cfg.merchant)
            sweep_hook(cfg.merchant)
            rec = {"merchant": cfg.merchant, "store_id": cfg.store_id, "pages": [], "total_created": 0, "halted": None}
            on_page(rec)
            return rec

        with mock.patch.object(self.MOD, "run_sweep", side_effect=fake_run_sweep), \
                mock.patch.object(sys, "argv", ["10", "--targets", targets, "--run-id", RUN]):
            code = self.MOD.main()
        recap = json.loads((self.run_dir / "recap.json").read_text(encoding="utf-8"))
        return code, swept, recap

    def test_a_merchant_added_mid_run_is_swept_after_the_current_one(self):
        def hook(merchant):
            if merchant == "Kinguin":
                self._queue(("Gamerall", "13"))          # ajouté pendant le 1er marchand
        code, swept, recap = self._main("Kinguin:58,G2A:38", hook)
        self.assertEqual(code, 0)
        self.assertEqual(swept, ["Kinguin", "G2A", "Gamerall"], "la cible ajoutée prend la file")
        self.assertEqual([t["merchant"] for t in recap["targets_added"]], ["Gamerall"])
        self.assertEqual([t["merchant"] for t in recap["planned"]], ["Kinguin", "G2A", "Gamerall"])
        self.assertTrue(recap["queue_closed"], "fermée à la fin")
        self.assertNotIn("targets_not_reached", recap)
        self.assertEqual(recap.get("targets_ignored", []), [],
                         "un ajout pris n'est pas re-tracé « déjà cible » aux relectures suivantes")

    def test_an_add_during_the_last_merchant_is_still_swept(self):
        """La course du P2 : l'ajout tombe pendant le DERNIER marchand."""

        def hook(merchant):
            if merchant == "G2A":
                self._queue(("Gamerall", "13"))
        code, swept, recap = self._main("Kinguin:58,G2A:38", hook)
        self.assertEqual(swept, ["Kinguin", "G2A", "Gamerall"])
        self.assertTrue(recap["queue_closed"])

    def test_the_queue_reopens_for_a_straggler_then_closes_again(self):
        """Revue `/code-review` : la fermeture restait collée pendant tout le balayage de la
        retardataire. Une RETARDATAIRE est un ajout qui tombe APRÈS `queue_closed: true` et
        AVANT la relecture qui la suit — pas un ajout pris à une frontière ordinaire. On
        l'injecte donc au moment exact où le lecteur relit alors que le recap sur disque dit
        « fermée ». Pendant son balayage la file doit être OUVERTE ; refermée à la vraie fin.
        (La première version de ce test ajoutait la cible pendant le 1er marchand : elle était
        prise à une frontière normale et le mutant « pas de réouverture » restait vert.)"""

        from unittest import mock
        real_take = self.MOD.take_from_queue
        injected = {"done": False}

        def take_injecting_straggler(sweep_dir, *a, **k):
            closed_on_disk = json.loads(
                (sweep_dir / "recap.json").read_text(encoding="utf-8")).get("queue_closed")
            if closed_on_disk and not injected["done"]:
                injected["done"] = True
                self._queue(("Gamerall", "13"))        # tombe entre la fermeture et la relecture
            return real_take(sweep_dir, *a, **k)

        seen = {}

        def hook(merchant):
            if merchant == "Gamerall":
                seen["closed_while_straggler_runs"] = json.loads(
                    (self.run_dir / "recap.json").read_text(encoding="utf-8"))["queue_closed"]

        with mock.patch.object(self.MOD, "take_from_queue", side_effect=take_injecting_straggler):
            code, swept, recap = self._main("Kinguin:58", hook)
        self.assertTrue(injected["done"], "le scénario doit avoir injecté la retardataire")
        self.assertEqual(swept, ["Kinguin", "Gamerall"], "la retardataire est balayée")
        self.assertIs(seen["closed_while_straggler_runs"], False, "ROUVERTE pendant la retardataire")
        self.assertTrue(recap["queue_closed"], "refermée à la vraie fin")

    def test_a_hand_written_parked_merchant_is_refused_and_traced(self):
        def hook(merchant):
            if merchant == "Kinguin":
                self._queue(("Keycense", "130"), ("Gamerall", "13"))
        code, swept, recap = self._main("Kinguin:58", hook)
        self.assertEqual(swept, ["Kinguin", "Gamerall"],
                         "un marchand hors liste ne rejoint JAMAIS l'exécution")
        self.assertEqual([t["merchant"] for t in recap["targets_refused"]], ["Keycense"])

    def test_an_add_accepted_then_stopped_is_recorded_as_not_reached(self):
        """Revue `/code-review` : sur un `break` (stop opérateur), un ajout accepté n'était ni
        balayé ni inscrit nulle part. Il est inscrit `targets_not_reached`."""

        def hook(merchant):
            if merchant == "Kinguin":
                self._queue(("Gamerall", "13"))
                self.MOD._RUNNER.stopped = True         # stop opérateur pendant Kinguin
        try:
            code, swept, recap = self._main("Kinguin:58,G2A:38", hook)
        finally:
            self.MOD._RUNNER.stopped = False
        self.assertEqual(swept, ["Kinguin"])
        self.assertIn("operator_stop", recap["halted"])
        self.assertEqual({t["merchant"] for t in recap["targets_not_reached"]}, {"G2A", "Gamerall"})
        self.assertTrue(recap["queue_closed"], "fermée même sur un break")

    def test_a_relaunch_with_the_same_run_id_starts_with_a_clean_queue(self):
        self._queue(("MMOGA", "12"))
        (self.run_dir / "recap.json").write_text("{}", encoding="utf-8")     # un run précédent
        code, swept, recap = self._main("Kinguin:58", lambda m: None)
        self.assertEqual(swept, ["Kinguin"], "l'ancienne file n'est pas rebalayée")

    def test_a_fresh_console_dir_keeps_an_add_made_during_startup(self):
        self._queue(("Gamerall", "13"))          # dossier neuf : pas de recap.json, file présente
        code, swept, recap = self._main("Kinguin:58", lambda m: None)
        self.assertEqual(swept, ["Kinguin", "Gamerall"], "l'ajout fait pendant le démarrage est pris")


class TheSameRunIdIsReservedToItsOwnProcess(unittest.TestCase):
    """Revue `/code-review` : `write_marker` acceptait le MÊME run_id alors que son processus
    était encore vivant — une relance depuis l'historique du shell volait les fichiers du run
    en cours, puis effaçait son marqueur en mourant."""

    def test_a_live_foreign_process_with_the_same_run_id_is_refused(self):
        import os
        root = pathlib.Path(tempfile.mkdtemp()); (root / "state").mkdir()
        run_marker.write_marker(root, run_id="X", kind="data_entry_auto", pid=1)   # pid 1 : vivant, pas nous
        with self.assertRaises(run_marker.ActiveRunExists):
            run_marker.write_marker(root, run_id="X", kind="data_entry_auto")
        # le même processus peut re-stamper son propre run
        run_marker.write_marker(root, run_id="Y", kind="data_entry_auto", pid=os.getpid()) if False else None
        (root / "state" / run_marker.MARKER_NAME).unlink()
        run_marker.write_marker(root, run_id="Y", kind="data_entry_auto")
        self.assertEqual(run_marker.write_marker(root, run_id="Y", kind="data_entry_auto")["run_id"], "Y")


class TheCloseIsPublishedBeforeTheFinalReread(unittest.TestCase):
    """Revue de Romain (2026-09-19, P2) — sur une sortie par `break` (stop opérateur, halte),
    `queue_closed` n'était mis qu'EN MÉMOIRE ; le disque ne le portait qu'au tout dernier
    `persist()`. Entre les deux, la console lisait « ouverte », répondait `queued: true`, et
    l'entrée tombait APRÈS la relecture finale : ni balayée, ni inscrite dans
    `targets_not_reached`. Publier d'abord rétablit le happens-before de la boucle."""

    SOURCE = (ROOT / "scripts" / "10_data_entry_auto.py").read_text(encoding="utf-8")

    def test_the_post_loop_close_goes_through_close_queue_which_persists(self):
        after = self.SOURCE[self.SOURCE.index("    # …et elle est PUBLIÉE"):]
        after = after[:after.index('    recap["finished_at"]')]
        close = after.index("close_queue(True)")
        drain = after.index("take_from_queue(")
        self.assertLess(close, drain, "publier la fermeture AVANT la relecture finale")
        self.assertNotIn('recap["queue_closed"] = True', after,
                         "l'écriture en mémoire seule ne doit plus exister ici")
        # close_queue publie : c'est ce qui rend la garde réelle
        helper = self.SOURCE[self.SOURCE.index("    def close_queue(closed: bool)"):]
        self.assertIn("persist()", helper[:helper.index("\n\n")])

    def test_a_break_exit_leaves_the_flag_on_disk(self):
        """Joué sur la vraie boucle : après un stop, le recap sur disque dit fermée."""
        from unittest import mock
        MOD = load_sweep("s10_close")
        tmp = pathlib.Path(tempfile.mkdtemp()); MOD.ROOT = tmp; (tmp / "state").mkdir()
        seen = {}

        def fake(cfg, stages, *, on_page=lambda r: None, **kw):
            MOD._RUNNER.stopped = True                      # stop pendant le 1er marchand
            rec = {"merchant": cfg.merchant, "store_id": cfg.store_id, "pages": [],
                   "total_created": 0, "halted": None}
            on_page(rec); return rec

        real_take = MOD.take_from_queue

        def spy(sweep_dir, *a, **k):
            path = sweep_dir / "recap.json"
            if a[2].get("queue_closed") and "disk" not in seen:      # a[2] = recap
                seen["disk"] = json.loads(path.read_text(encoding="utf-8")).get("queue_closed")
            return real_take(sweep_dir, *a, **k)

        with mock.patch.object(MOD, "run_sweep", side_effect=fake), \
                mock.patch.object(MOD, "take_from_queue", side_effect=spy), \
                mock.patch.object(sys, "argv", ["10", "--targets", "Kinguin:58", "--run-id", RUN]):
            try:
                MOD.main()
            finally:
                MOD._RUNNER.stopped = False
        self.assertIs(seen.get("disk"), True,
                      "la relecture finale doit trouver la fermeture DÉJÀ publiée")


class TheStopBilanForgetsNoMerchant(unittest.TestCase):
    """Revue de Romain (2026-09-19, P2) — `index += 1` s'exécutait AVANT le contrôle du stop :
    un arrêt entre deux marchands excluait de `targets_not_reached` celui qui venait d'être
    pris et n'avait JAMAIS démarré. Le bilan d'arrêt l'oubliait purement."""

    def _run(self, targets, stop_before):
        from unittest import mock
        MOD = load_sweep("s10_stop")
        tmp = pathlib.Path(tempfile.mkdtemp()); MOD.ROOT = tmp; (tmp / "state").mkdir()
        swept = []

        def fake(cfg, stages, *, on_page=lambda r: None, **kw):
            swept.append(cfg.merchant)
            rec = {"merchant": cfg.merchant, "store_id": cfg.store_id, "pages": [],
                   "total_created": 0, "halted": None}
            on_page(rec); return rec

        with mock.patch.object(MOD, "run_sweep", side_effect=fake), \
                mock.patch.object(sys, "argv", ["10", "--targets", targets, "--run-id", RUN]):
            if stop_before:
                MOD._RUNNER.stopped = True
            try:
                MOD.main()
            finally:
                MOD._RUNNER.stopped = False
        recap = json.loads((tmp / "runs" / RUN / "recap.json").read_text(encoding="utf-8"))
        return swept, recap

    def test_a_stop_before_the_first_merchant_lists_them_all(self):
        swept, recap = self._run("Kinguin:58,G2A:38", stop_before=True)
        self.assertEqual(swept, [], "aucun marchand n'a démarré")
        self.assertEqual([t["merchant"] for t in recap["targets_not_reached"]], ["Kinguin", "G2A"])

    def test_a_merchant_actually_swept_is_not_listed_as_not_reached(self):
        """L'autre bord : les `break` d'APRÈS le balayage trouvent l'index déjà avancé."""
        from unittest import mock
        MOD = load_sweep("s10_stop2")
        tmp = pathlib.Path(tempfile.mkdtemp()); MOD.ROOT = tmp; (tmp / "state").mkdir()
        swept = []

        def fake(cfg, stages, *, on_page=lambda r: None, **kw):
            swept.append(cfg.merchant)
            MOD._RUNNER.stopped = True                     # stop APRÈS le 1er balayage
            rec = {"merchant": cfg.merchant, "store_id": cfg.store_id, "pages": [],
                   "total_created": 0, "halted": None}
            on_page(rec); return rec

        with mock.patch.object(MOD, "run_sweep", side_effect=fake), \
                mock.patch.object(sys, "argv", ["10", "--targets", "Kinguin:58,G2A:38", "--run-id", RUN]):
            try:
                MOD.main()
            finally:
                MOD._RUNNER.stopped = False
        recap = json.loads((tmp / "runs" / RUN / "recap.json").read_text(encoding="utf-8"))
        self.assertEqual(swept, ["Kinguin"])
        self.assertEqual([t["merchant"] for t in recap["targets_not_reached"]], ["G2A"],
                         "Kinguin a bien démarré : il n'est pas « non atteint »")

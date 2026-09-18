"""A run launched from a terminal is visible in the console (2026-09-17).

Romain: « On peut faire en sorte d'avoir un monitoring sur l'admin même lorsqu'on lance en
ligne de commande ? ». The console could already SHOW any run — ``/submit/status`` reads the
run's artefacts from DISK — but it could not DISCOVER one: ``SubmitManager.busy()`` only knew
the children it had spawned. A sweep or a submit started from a terminal was therefore
invisible, and the "Lancer" button did not even refuse while it held the browser; the launch
died later on the browser lock with an opaque error.

The missing half is a marker (``src/run_marker.py``) stamped by the CLI entry points and read
by the manager. Three properties are pinned here:

1. **liveness is the PID, never a timestamp** — a crashed or SIGKILLed run cannot wedge the
   console, and a long-running one is never mistaken for stale (today's GameBoost write ran
   for 1 h 50 and a lost SSH session killed another mid-flight);
2. **only the owner clears it** — a run exiting late must not erase the marker of the run that
   replaced it;
3. **the shape the pages already render** — ``{run_id, kind}`` — so both consoles adopt a CLI
   run with no client-side change at all.

The browser lock remains the hard mutual exclusion. This is the readable label on top of it,
and ``lock_status`` reads that lock WITHOUT taking it, precisely so the indicator can never
make a real stage fail closed.
"""

import json
import os
import pathlib
import tempfile
import unittest

from src import run_marker
from src.browser_lock import browser_lock, lock_status

ROOT = pathlib.Path(__file__).resolve().parent.parent


class MarkerLivenessTests(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())

    def test_a_live_marker_is_active(self):
        run_marker.write_marker(self.tmp, run_id="r1", kind="data_entry_auto")
        m = run_marker.read_marker(self.tmp)
        self.assertIsNotNone(m)
        self.assertEqual(m["run_id"], "r1")
        self.assertEqual(m["kind"], "data_entry_auto")
        self.assertEqual(m["source"], "cli")
        self.assertEqual(m["pid"], os.getpid())

    def test_a_marker_whose_process_is_gone_is_NOT_active(self):
        """The whole point: a killed run must not wedge the console for ever."""

        run_marker.write_marker(self.tmp, run_id="r1", kind="submit", pid=_dead_pid())
        self.assertIsNone(run_marker.read_marker(self.tmp))

    def test_age_is_never_a_criterion(self):
        """A run can legitimately last hours — GameBoost ran 1 h 50 on 2026-09-17."""

        m = run_marker.write_marker(self.tmp, run_id="r1", kind="submit")
        path = self.tmp / "state" / run_marker.MARKER_NAME
        data = json.loads(path.read_text(encoding="utf-8"))
        data["started_at"] = "2020-01-01T00:00:00Z"
        path.write_text(json.dumps(data), encoding="utf-8")
        self.assertIsNotNone(run_marker.read_marker(self.tmp),
                             "an old marker with a LIVE pid is still active")

    def test_absent_or_corrupt_reads_as_nothing_active(self):
        self.assertIsNone(run_marker.read_marker(self.tmp))
        path = self.tmp / "state" / run_marker.MARKER_NAME
        path.parent.mkdir(parents=True, exist_ok=True)
        for junk in ("", "{", "[]", '{"kind": "submit"}'):
            with self.subTest(junk=junk):
                path.write_text(junk, encoding="utf-8")
                self.assertIsNone(run_marker.read_marker(self.tmp))


class OnlyTheOwnerClearsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())

    def test_another_run_cannot_clear_it(self):
        run_marker.write_marker(self.tmp, run_id="r1", kind="submit")
        self.assertFalse(run_marker.clear_marker(self.tmp, "r2"))
        self.assertIsNotNone(run_marker.read_marker(self.tmp))
        self.assertTrue(run_marker.clear_marker(self.tmp, "r1"))
        self.assertIsNone(run_marker.read_marker(self.tmp))

    def test_the_context_manager_always_drops_it(self):
        with run_marker.active_run(self.tmp, run_id="r1", kind="submit"):
            self.assertIsNotNone(run_marker.read_marker(self.tmp))
        self.assertIsNone(run_marker.read_marker(self.tmp))

        with self.assertRaises(RuntimeError):
            with run_marker.active_run(self.tmp, run_id="r2", kind="submit"):
                raise RuntimeError("boom")
        self.assertIsNone(run_marker.read_marker(self.tmp), "dropped on the error path too")

    def test_a_write_is_atomic(self):
        """A reader must never see a half-written marker."""

        src = (ROOT / "src" / "run_marker.py").read_text(encoding="utf-8")
        self.assertIn("tmp.replace(path)", src)


class LockStatusIsReadOnlyTests(unittest.TestCase):
    """It must never take the lock: a probe that did would make a real stage fail closed."""

    def test_it_does_not_flock(self):
        src = (ROOT / "src" / "browser_lock.py").read_text(encoding="utf-8")
        body = src[src.index("def lock_status("):src.index("class BrowserBusyError")]
        code = "\n".join(l for l in body.splitlines()
                         if not l.strip().startswith(("#", '"""', "*")) and '``' not in l)
        self.assertNotIn("fcntl.flock", code,
                         "probing with flock would make a real stage fail closed")

    def test_a_free_lock_reads_free(self):
        tmp = pathlib.Path(tempfile.mkdtemp())
        self.assertEqual(lock_status(tmp)["held"], False)

    def test_a_held_lock_names_its_holder(self):
        tmp = pathlib.Path(tempfile.mkdtemp())
        with browser_lock(tmp, label="05_submit --submit"):
            st = lock_status(tmp)
        self.assertTrue(st["held"])
        self.assertEqual(st["label"], "05_submit --submit")
        self.assertEqual(st["pid"], os.getpid())
        self.assertTrue(st["since"])

    def test_a_label_left_by_a_dead_process_reads_FREE(self):
        """The module's own contract: such a label is residue, the kernel freed the flock."""

        tmp = pathlib.Path(tempfile.mkdtemp())
        (tmp / "state").mkdir(parents=True)
        (tmp / "state" / "browser.lock").write_text(
            f"05_submit --submit pid={_dead_pid()} since 2026-09-17T10:00:00Z\n",
            encoding="utf-8")
        self.assertFalse(lock_status(tmp)["held"])


class TheManagerSeesCliRunsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())

    def _manager(self):
        from src.admin.submit_manager import SubmitManager
        return SubmitManager(repo_root=self.tmp)

    def test_busy_reports_a_cli_run(self):
        mgr = self._manager()
        self.assertIsNone(mgr.busy())
        run_marker.write_marker(self.tmp, run_id="20260917-auto", kind="data_entry_auto")
        busy = mgr.busy()
        self.assertIsNotNone(busy)
        self.assertEqual(busy["run_id"], "20260917-auto")
        self.assertEqual(busy["kind"], "data_entry_auto",
                         "auto.js adopts a sweep on this exact value — do not rename it")
        self.assertEqual(busy["source"], "cli")

    def test_a_dead_cli_run_does_not_show_as_busy(self):
        mgr = self._manager()
        run_marker.write_marker(self.tmp, run_id="r", kind="submit", pid=_dead_pid())
        self.assertIsNone(mgr.busy())

    def test_a_console_launch_is_refused_while_a_cli_run_holds_the_browser(self):
        from src.admin.submit_manager import SubmitStartError
        mgr = self._manager()
        run_marker.write_marker(self.tmp, run_id="cli-run", kind="data_entry_auto")
        with self.assertRaises(SubmitStartError) as ctx:
            mgr._ensure_free()
        self.assertEqual(ctx.exception.code, "cli_run_in_progress")
        self.assertIn("cli-run", str(ctx.exception))

    def test_the_guard_is_lifted_once_the_cli_run_is_gone(self):
        mgr = self._manager()
        run_marker.write_marker(self.tmp, run_id="cli-run", kind="submit", pid=_dead_pid())
        mgr._ensure_free()          # must not raise


class TheApiExposesItOnTheRouteThePagesReadTests(unittest.TestCase):
    """Vérifié en production le 2026-09-18 : mon premier essai posait le champ sur
    /api/runs, qu'aucune des deux consoles n'interroge. Les deux lisent /api/sort/runs
    (sort.js refreshBusy, auto.js fetchBusy)."""

    def test_the_browser_state_is_on_the_polled_route(self):
        app = (ROOT / "src" / "admin" / "app.py").read_text(encoding="utf-8")
        block = app[app.index('if path == "/api/sort/runs":'):]
        block = block[:block.index("if path ==", 40)]
        self.assertIn('"browser": lock_status(', block)
        self.assertIn('"busy": self.state.manager.busy()', block)

    def test_both_consoles_poll_that_route(self):
        static = ROOT / "src" / "admin" / "static"
        for page in ("sort.js", "auto.js"):
            with self.subTest(page=page):
                self.assertIn("api/sort/runs", (static / page).read_text(encoding="utf-8"))


class TheCliEntryPointsStampItTests(unittest.TestCase):
    def test_the_sweep_marks_and_unmarks(self):
        src = (ROOT / "scripts" / "10_data_entry_auto.py").read_text(encoding="utf-8")
        self.assertIn('run_marker.write_marker(ROOT, run_id=run_id, kind="data_entry_auto"', src)
        self.assertIn("atexit.register(run_marker.clear_marker, ROOT, run_id)", src)

    def test_the_manual_submit_marks_and_unmarks(self):
        src = (ROOT / "scripts" / "05_submit.py").read_text(encoding="utf-8")
        self.assertIn('run_marker.write_marker(ROOT, run_id=run_id, kind="submit"', src)
        self.assertIn("atexit.register(run_marker.clear_marker, ROOT, run_id)", src)


def _dead_pid() -> int:
    """A pid that is certainly not running: fork a child and reap it."""

    pid = os.fork()
    if pid == 0:
        os._exit(0)
    os.waitpid(pid, 0)
    return pid


if __name__ == "__main__":
    unittest.main()

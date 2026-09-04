"""CooperativeChildRunner — the orchestrator's cooperative stop + kill escalation
(scripts/10, scripts/12). The load-bearing property: a child that IGNORES SIGTERM
is SIGKILLed by its process group after the grace, so it is never orphaned when the
manager SIGKILLs the orchestrator (adversarial review 2026-08-25)."""
import os
import signal
import sys
import threading
import time
import unittest

from src.child_runner import CooperativeChildRunner


class ChildRunnerTests(unittest.TestCase):
    def setUp(self):
        # Installing handlers hijacks this process's SIGTERM/SIGINT/SIGALRM — save
        # and restore so the test runner is unaffected.
        self._saved = {s: signal.getsignal(s)
                       for s in (signal.SIGTERM, signal.SIGINT, signal.SIGALRM)}
        self.addCleanup(lambda: [signal.signal(s, h) for s, h in self._saved.items()])
        self.addCleanup(lambda: signal.alarm(0))

    def test_returns_child_exit_code(self):
        r = CooperativeChildRunner()
        r.install()
        rc = r.run([sys.executable, "-c", "import sys; sys.exit(3)"], cwd=".")
        self.assertEqual(rc, 3)
        self.assertFalse(r.stopped)

    def test_cooperative_stop_well_behaved_child_exits_fast(self):
        # A child that honors SIGTERM exits well before the grace — no killpg needed.
        r = CooperativeChildRunner(grace_s=30)
        r.install()
        child = "import signal,sys; signal.signal(signal.SIGTERM, lambda *a: sys.exit(0)); import time; time.sleep(30)"
        threading.Timer(0.3, lambda: os.kill(os.getpid(), signal.SIGTERM)).start()
        start = time.monotonic()
        r.run([sys.executable, "-c", child], cwd=".")
        self.assertLess(time.monotonic() - start, 5)   # exited on SIGTERM, not after 30s
        self.assertTrue(r.stopped)

    def test_hung_child_is_group_killed_after_grace(self):
        # THE fix: a child that IGNORES SIGTERM and sleeps is SIGKILLed by its group
        # after the (short, test) grace — never left running for its full sleep.
        r = CooperativeChildRunner(grace_s=1)
        r.install()
        child = ("import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); "
                 "time.sleep(60)")
        threading.Timer(0.3, lambda: os.kill(os.getpid(), signal.SIGTERM)).start()
        start = time.monotonic()
        rc = r.run([sys.executable, "-c", child], cwd=".")
        elapsed = time.monotonic() - start
        self.assertLess(elapsed, 6)                    # killed ~grace, not 60s
        self.assertTrue(r.stopped)
        self.assertEqual(rc, -signal.SIGKILL)          # died by SIGKILL (its group)

    def test_alarm_disarmed_after_clean_run(self):
        # A normal run must not leave an alarm armed that could kill a later child.
        r = CooperativeChildRunner(grace_s=1)
        r.install()
        r.run([sys.executable, "-c", "pass"], cwd=".")
        # if an alarm were still armed, this 1.5s sleep would be interrupted / a
        # stray SIGALRM would fire on no child — assert none pending.
        self.assertEqual(signal.alarm(0), 0)

    def test_p2_10_repeated_stop_arms_alarm_once(self):
        # P2-10 (audit 2026-09-02): a SECOND cooperative stop (repeated /api/sort/stop)
        # must NOT re-arm a fresh full grace — that would push our child-SIGKILL past the
        # manager's fixed orchestrator-SIGKILL window and orphan a hung child. The alarm
        # is armed ONCE, on the first stop; later stops re-forward SIGTERM but don't re-arm.
        from unittest import mock

        class _Alive:
            def poll(self):   return None    # child still running
            def terminate(self):  pass

        r = CooperativeChildRunner(grace_s=5)
        r._child = _Alive()
        with mock.patch("src.child_runner.signal.alarm") as m_alarm:
            r._on_term()   # first stop → arms the grace
            r._on_term()   # second stop → re-forwards SIGTERM, must NOT re-arm
        armed = [c.args[0] for c in m_alarm.call_args_list if c.args and c.args[0]]
        self.assertEqual(armed, [5])   # exactly one arm, at the full grace

    def test_p2_10_subsecond_grace_arms_at_least_one_second(self):
        # max(1, int(grace)) — a sub-second grace must not truncate to alarm(0) (a
        # silent disarm that would let a hung child run unbounded).
        from unittest import mock

        class _Alive:
            def poll(self):   return None
            def terminate(self):  pass

        r = CooperativeChildRunner(grace_s=0.4)
        r._child = _Alive()
        with mock.patch("src.child_runner.signal.alarm") as m_alarm:
            r._on_term()
        armed = [c.args[0] for c in m_alarm.call_args_list if c.args]
        self.assertEqual(armed, [1])   # max(1, int(0.4)) == 1, never 0

    def test_p2_10_alarm_flag_resets_for_reuse(self):
        # a reused runner arms fresh for the next child (flag reset in run()'s finally).
        r = CooperativeChildRunner(grace_s=1)
        r.install()
        r.run([sys.executable, "-c", "pass"], cwd=".")
        self.assertFalse(r._alarm_armed)


if __name__ == "__main__":
    unittest.main()

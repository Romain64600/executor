"""Cooperative-stop subprocess runner for a supervised orchestrator (scripts/10,
scripts/12).

An orchestrator spawns its stage children (05_submit, 02/03, 06_move) in their OWN
session (``start_new_session=True``) so that a SIGKILL of the ORCHESTRATOR never
cascades to a child mid-write — a child must be allowed to finish the current offer
cleanly. The gap the manager's stop escalation exposed (adversarial review
2026-08-25): a child that IGNORES SIGTERM for the whole grace would be ORPHANED —
still writing, unsupervised, holding the browser flock — when the manager SIGKILLs
the orchestrator (a single pid, not the group).

This runner closes that gap. On a cooperative stop it forwards SIGTERM (the child
stops at a safe boundary) AND arms its OWN alarm; if the child is still alive after
``grace_s`` it SIGKILLs the child's PROCESS GROUP — *before* the manager SIGKILLs
the orchestrator — so a hung child is never orphaned. ``grace_s`` MUST be shorter
than the manager's SIGKILL grace for the run's kind (submit / by-urls-submit = 90s,
data_entry_auto = 120s), so our escalation always wins the race.
"""
from __future__ import annotations

import os
import signal
import subprocess

# < the manager's 90s SIGKILL grace (the tightest — submit / by-urls-submit), so the
# orchestrator force-kills a hung child before the manager force-kills the orchestrator.
CHILD_KILL_GRACE_S = 75.0


class CooperativeChildRunner:
    def __init__(self, grace_s: float = CHILD_KILL_GRACE_S) -> None:
        self.grace_s = grace_s
        self._child: "subprocess.Popen | None" = None
        self.stopped = False

    def install(self) -> None:
        """Install SIGTERM/SIGINT (cooperative stop) + SIGALRM (kill escalation)."""
        signal.signal(signal.SIGTERM, self._on_term)
        signal.signal(signal.SIGINT, self._on_term)
        signal.signal(signal.SIGALRM, self._on_alarm)

    def _on_term(self, _signum=None, _frame=None) -> None:
        self.stopped = True
        self._signal_child()

    def _signal_child(self) -> None:
        c = self._child
        if c is not None and c.poll() is None:
            try:
                c.terminate()                    # cooperative SIGTERM: stop at a safe boundary
            except Exception:
                pass
            signal.alarm(int(self.grace_s))      # escalate ourselves if it hangs past the grace

    def _on_alarm(self, _signum=None, _frame=None) -> None:
        c = self._child
        if c is not None and c.poll() is None:
            try:
                # The child is its OWN session/pgroup leader (start_new_session), so
                # its pgid == its pid; killpg(pid) reaches the child + anything it
                # spawned, and NEVER the orchestrator's own group.
                os.killpg(c.pid, signal.SIGKILL)
            except Exception:
                pass

    def run(self, argv: list[str], cwd: str) -> int:
        """Run one child to completion, cooperatively stoppable. Returns its exit code.
        ``start_new_session`` isolates the child from an orchestrator SIGKILL cascade;
        this runner's own escalation is what guarantees a hung child still dies."""
        self._child = subprocess.Popen(argv, cwd=cwd, start_new_session=True,
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if self.stopped:                         # a stop arrived during the fork window
            self._signal_child()
        try:
            return self._child.wait()
        finally:
            signal.alarm(0)                      # disarm — this child is done
            self._child = None

"""Deterministic step guard (a.k.a. ToolGuard) for the AKS controlled executor.

This module is the fail-closed backbone every executor stage runs through. It
contains NO reasoning: it decides purely from the recorded history of step
attempts. A block lives inside this object, never inside an LLM context, so it
cannot be reinterpreted or argued away by a model.

Core ideas
----------
- A *task* is one unit of user intent. Its id is set by the calling loop, never
  by a model. ``start_task(task_id)`` begins a new task and clears any block.
- Before executing anything the caller asks ``check(tool, signature)``.
- After executing, the caller reports the outcome with ``record_result(...)``,
  passing a ``success`` computed by deterministic code (HTTP status, presence of
  an error field, ...) never a model self-assessment.
- When a failure pattern is detected the guard blocks and stays blocked until a
  *new* task is started. No retry, no fallback, no continuation.

The ``signature`` is a fine-grained identity of the exact intent, e.g.
``"cdp_get_version"`` or ``"submit:candidate=1234"``. Two calls that share a
signature are treated as "the same thing"; encode the target in the signature
when repeats on different targets are legitimate.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable


def _utc_now_iso() -> str:
    """Return the current UTC time as an ISO-8601 ``...Z`` string."""

    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass(frozen=True)
class StepAttempt:
    """One recorded attempt. Immutable, JSON-serializable via ``to_dict``."""

    task_id: str
    tool: str
    signature: str
    success: bool
    detail: str
    at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "tool": self.tool,
            "signature": self.signature,
            "success": self.success,
            "detail": self.detail,
            "at": self.at,
        }


@dataclass(frozen=True)
class GuardDecision:
    """Outcome of a ``check``. ``allowed`` is the only thing callers must obey."""

    allowed: bool
    rule: str | None
    reason: str
    task_id: str | None
    signature: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "rule": self.rule,
            "reason": self.reason,
            "task_id": self.task_id,
            "signature": self.signature,
        }


class StepGuardError(RuntimeError):
    """Raised by ``run_step`` when the guard refuses or blocks an action."""

    def __init__(self, decision: GuardDecision) -> None:
        super().__init__(decision.reason)
        self.decision = decision


class StepGuard:
    """A deterministic, dependency-free, fail-closed step guard.

    Parameters
    ----------
    max_attempts_per_signature:
        How many times a single ``signature`` may be *attempted* within a task
        before ``check`` refuses further attempts of that signature. Default 2
        (i.e. one retry). Set to 1 to forbid any retry of the same action.
    max_consecutive_failures:
        A run of this many failures in a row (across any signatures) hard-blocks
        the whole task.
    max_failures_per_task:
        Cumulative failure budget for a task. Reaching it hard-blocks the task.
    clock:
        Callable returning an ISO timestamp string, injectable for tests.
    """

    def __init__(
        self,
        *,
        max_attempts_per_signature: int = 2,
        max_failures_per_signature: int = 2,
        max_consecutive_failures: int = 3,
        max_failures_per_task: int = 5,
        clock: Callable[[], str] = _utc_now_iso,
    ) -> None:
        # ``max_attempts_per_signature`` is the *attempt* ceiling checked BEFORE
        # execution (success or failure count) — a soft, per-signature deny.
        # ``max_failures_per_signature`` is the *failure* threshold that hard-
        # blocks the task. They are intentionally distinct (see docs/AUDIT.md C4):
        # a success followed by a failure can exhaust the attempt ceiling (soft
        # deny) without hard-blocking.
        if max_attempts_per_signature < 1:
            raise ValueError("max_attempts_per_signature must be >= 1")
        if max_failures_per_signature < 1:
            raise ValueError("max_failures_per_signature must be >= 1")
        if max_consecutive_failures < 1:
            raise ValueError("max_consecutive_failures must be >= 1")
        if max_failures_per_task < 1:
            raise ValueError("max_failures_per_task must be >= 1")

        self.max_attempts_per_signature = max_attempts_per_signature
        self.max_failures_per_signature = max_failures_per_signature
        self.max_consecutive_failures = max_consecutive_failures
        self.max_failures_per_task = max_failures_per_task
        self._clock = clock

        self._task_id: str | None = None
        self._blocked = False
        self._blocked_rule: str | None = None
        self._blocked_reason: str | None = None

        self._history: list[StepAttempt] = []
        self._attempts_by_sig: dict[str, int] = {}
        self._failures_by_sig: dict[str, int] = {}
        self._consecutive_failures = 0
        self._total_failures = 0

    # -- task lifecycle -------------------------------------------------
    def start_task(self, task_id: str) -> None:
        """Begin a new task. A *new* id clears any block and resets counters.

        Calling this with the id of the current task is a deliberate no-op: a
        task can never clear its own block. Only genuinely new intent resumes
        execution. This is what makes a block un-negotiable from within a task.
        """

        if not task_id:
            raise ValueError("task_id must be a non-empty string")
        if task_id == self._task_id:
            return

        self._task_id = task_id
        self._blocked = False
        self._blocked_rule = None
        self._blocked_reason = None
        self._attempts_by_sig = {}
        self._failures_by_sig = {}
        self._consecutive_failures = 0
        self._total_failures = 0

    @property
    def task_id(self) -> str | None:
        return self._task_id

    @property
    def blocked(self) -> bool:
        return self._blocked

    @property
    def history(self) -> tuple[StepAttempt, ...]:
        return tuple(self._history)

    # -- decision -------------------------------------------------------
    def check(self, tool: str, signature: str) -> GuardDecision:
        """Ask permission BEFORE executing. Callers must obey ``allowed``."""

        if self._task_id is None:
            return GuardDecision(
                allowed=False,
                rule="no_active_task",
                reason="no active task; call start_task() first",
                task_id=None,
                signature=signature,
            )
        if self._blocked:
            return self._blocked_decision(signature)

        attempts = self._attempts_by_sig.get(signature, 0)
        if attempts >= self.max_attempts_per_signature:
            return GuardDecision(
                allowed=False,
                rule="max_attempts_per_signature",
                reason=(
                    f"signature '{signature}' already attempted {attempts} time(s) "
                    f"(limit {self.max_attempts_per_signature}) in task '{self._task_id}'"
                ),
                task_id=self._task_id,
                signature=signature,
            )

        return GuardDecision(
            allowed=True,
            rule=None,
            reason="allowed",
            task_id=self._task_id,
            signature=signature,
        )

    # -- recording ------------------------------------------------------
    def record_result(
        self, tool: str, signature: str, success: bool, detail: str = ""
    ) -> None:
        """Record an executed step. ``success`` must come from deterministic code.

        A failure may hard-block the task via one of three rules:
        repeated_signature_failure, consecutive_failures, failure_budget.
        """

        if self._task_id is None:
            raise RuntimeError("cannot record_result without an active task")

        self._history.append(
            StepAttempt(
                task_id=self._task_id,
                tool=tool,
                signature=signature,
                success=bool(success),
                detail=detail,
                at=self._clock(),
            )
        )
        self._attempts_by_sig[signature] = self._attempts_by_sig.get(signature, 0) + 1

        if success:
            self._consecutive_failures = 0
            return

        self._consecutive_failures += 1
        self._total_failures += 1
        self._failures_by_sig[signature] = self._failures_by_sig.get(signature, 0) + 1

        if self._blocked:
            return

        sig_failures = self._failures_by_sig[signature]
        if sig_failures >= self.max_failures_per_signature:
            self._block(
                "repeated_signature_failure",
                f"signature '{signature}' failed {sig_failures} time(s) in task "
                f"'{self._task_id}'; stopping instead of hammering the same action",
            )
        elif self._consecutive_failures >= self.max_consecutive_failures:
            self._block(
                "consecutive_failures",
                f"{self._consecutive_failures} consecutive failures in task "
                f"'{self._task_id}'; stopping to avoid thrashing",
            )
        elif self._total_failures >= self.max_failures_per_task:
            self._block(
                "failure_budget",
                f"failure budget exhausted ({self._total_failures}/"
                f"{self.max_failures_per_task}) in task '{self._task_id}'",
            )

    def _block(self, rule: str, reason: str) -> None:
        self._blocked = True
        self._blocked_rule = rule
        self._blocked_reason = reason

    def _blocked_decision(self, signature: str | None = None) -> GuardDecision:
        """Single builder for a blocked decision (used by check and run_step)."""

        return GuardDecision(
            allowed=False,
            rule=self._blocked_rule,
            reason=self._blocked_reason or "guard is blocked until a new task starts",
            task_id=self._task_id,
            signature=signature,
        )

    # -- high-level helper ---------------------------------------------
    def run_step(
        self,
        tool: str,
        signature: str,
        action: Callable[[], Any],
        *,
        success_predicate: Callable[[Any], bool],
        detail: Callable[[Any], str] | str = "",
    ) -> Any:
        """Enforce check -> execute -> record in one call.

        - Refuses (raises ``StepGuardError``) if ``check`` denies.
        - Runs ``action`` exactly once.
        - An exception from ``action`` is recorded as a failure and re-raised.
        - Otherwise ``success_predicate(result)`` decides success deterministically.
        - If recording the outcome hard-blocks the task, raises ``StepGuardError``
          so the caller halts immediately (fail-closed).
        """

        decision = self.check(tool, signature)
        if not decision.allowed:
            raise StepGuardError(decision)

        try:
            result = action()
        except Exception as exc:  # noqa: BLE001 - deterministic: any error is a failure
            self.record_result(tool, signature, False, f"exception: {exc!r}")
            raise

        ok = bool(success_predicate(result))
        detail_text = detail(result) if callable(detail) else detail
        self.record_result(tool, signature, ok, detail_text)

        if self._blocked:
            raise StepGuardError(self._blocked_decision(signature))
        return result

    # -- serialization --------------------------------------------------
    def snapshot(self) -> dict[str, Any]:
        """A JSON-serializable view of the guard, suitable for run logs."""

        return {
            "task_id": self._task_id,
            "blocked": self._blocked,
            "blocked_rule": self._blocked_rule,
            "blocked_reason": self._blocked_reason,
            "limits": {
                "max_attempts_per_signature": self.max_attempts_per_signature,
                "max_failures_per_signature": self.max_failures_per_signature,
                "max_consecutive_failures": self.max_consecutive_failures,
                "max_failures_per_task": self.max_failures_per_task,
            },
            "counters": {
                "consecutive_failures": self._consecutive_failures,
                "total_failures": self._total_failures,
                "attempts_by_signature": dict(self._attempts_by_sig),
                "failures_by_signature": dict(self._failures_by_sig),
            },
            "history": [attempt.to_dict() for attempt in self._history],
        }


class BlockLedger:
    """Cross-process memory of a task's blocked runs (FC3, audit 2026-07-17).

    An in-memory guard block dies with its process: re-running the same script
    with the same run_id used to start from a blank guard, so nothing enforced
    the skill's own anti-loop rule ACROSS processes. This ledger applies G03
    ("the same approach failing twice → STOP, do not try a third time")
    at run granularity:

    - run 1 blocks → recorded; a SECOND pass on the same run stays free — the
      documented standard recovery (idempotent re-pass on the same
      approved.json, Romain 2026-07-07);
    - the second pass blocks TOO → the third needs an explicit human
      acknowledgment (``--acknowledge-block``), which resets the counter.

    The ledger never re-arms a live in-process guard; it only refuses to START
    a new blocked-history run. JSON on disk, stdlib only, fail-open on a
    corrupt file (a broken ledger must not brick the pipeline — the in-run
    guard is still fully armed either way).
    """

    def __init__(self, path: Any, clock: Callable[[], str] | None = None) -> None:
        from pathlib import Path

        self.path = Path(path)
        self._clock = clock or (
            lambda: datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        )

    def load(self) -> dict[str, Any]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"consecutive_blocked_runs": 0}
        if not isinstance(data, dict):
            return {"consecutive_blocked_runs": 0}
        data.setdefault("consecutive_blocked_runs", 0)
        return data

    def requires_ack(self) -> bool:
        return int(self.load().get("consecutive_blocked_runs") or 0) >= 2

    def acknowledge(self, note: str) -> None:
        data = self.load()
        data["consecutive_blocked_runs"] = 0
        data["acknowledged"] = {"note": note, "at": self._clock()}
        self._write(data)

    def record(self, *, task_id: str, blocked: bool,
               rule: str | None = None, reason: str | None = None) -> dict[str, Any]:
        data = self.load()
        if blocked:
            data["consecutive_blocked_runs"] = (
                int(data.get("consecutive_blocked_runs") or 0) + 1
            )
            data["last_block"] = {
                "task_id": task_id, "rule": rule, "reason": reason,
                "at": self._clock(),
            }
        else:
            data["consecutive_blocked_runs"] = 0
        data["task_id"] = task_id
        data["updated_at"] = self._clock()
        self._write(data)
        return data

    def _write(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, indent=2), encoding="utf-8")

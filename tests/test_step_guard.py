import json
import unittest

from src.step_guard import GuardDecision, StepGuard, StepGuardError


FIXED_CLOCK = "2026-07-02T00:00:00Z"


def make_guard(**kwargs):
    kwargs.setdefault("clock", lambda: FIXED_CLOCK)
    return StepGuard(**kwargs)


class ConstructorTests(unittest.TestCase):
    def test_rejects_non_positive_limits(self):
        for bad in (
            "max_attempts_per_signature",
            "max_failures_per_signature",
            "max_consecutive_failures",
            "max_failures_per_task",
        ):
            with self.assertRaises(ValueError):
                make_guard(**{bad: 0})

    def test_start_task_requires_non_empty_id(self):
        guard = make_guard()
        with self.assertRaises(ValueError):
            guard.start_task("")


class CheckTests(unittest.TestCase):
    def test_check_denies_without_active_task(self):
        guard = make_guard()

        decision = guard.check("cdp", "get_version")

        self.assertIsInstance(decision, GuardDecision)
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.rule, "no_active_task")

    def test_allows_within_signature_limit_then_denies_that_signature_only(self):
        guard = make_guard(max_attempts_per_signature=2)
        guard.start_task("t1")

        self.assertTrue(guard.check("tool", "a").allowed)
        guard.record_result("tool", "a", True)
        self.assertTrue(guard.check("tool", "a").allowed)
        guard.record_result("tool", "a", True)

        denied = guard.check("tool", "a")
        self.assertFalse(denied.allowed)
        self.assertEqual(denied.rule, "max_attempts_per_signature")
        # A different signature is unaffected: this is a soft, per-signature gate.
        self.assertTrue(guard.check("tool", "b").allowed)
        self.assertFalse(guard.blocked)


class HardBlockTests(unittest.TestCase):
    def test_repeated_signature_failure_hard_blocks(self):
        guard = make_guard(max_attempts_per_signature=2)
        guard.start_task("t1")

        guard.record_result("tool", "x", False)
        self.assertFalse(guard.blocked)
        guard.record_result("tool", "x", False)

        self.assertTrue(guard.blocked)
        decision = guard.check("tool", "y")
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.rule, "repeated_signature_failure")

    def test_consecutive_failures_block_across_signatures(self):
        guard = make_guard(max_attempts_per_signature=5, max_consecutive_failures=3)
        guard.start_task("t1")

        guard.record_result("tool", "a", False)
        guard.record_result("tool", "b", False)
        self.assertFalse(guard.blocked)
        guard.record_result("tool", "c", False)

        self.assertTrue(guard.blocked)
        self.assertEqual(guard.check("tool", "d").rule, "consecutive_failures")

    def test_success_resets_consecutive_streak(self):
        guard = make_guard(max_attempts_per_signature=5, max_consecutive_failures=3, max_failures_per_task=99)
        guard.start_task("t1")

        guard.record_result("tool", "a", False)
        guard.record_result("tool", "b", False)
        guard.record_result("tool", "c", True)  # resets streak
        guard.record_result("tool", "d", False)
        guard.record_result("tool", "e", False)

        self.assertFalse(guard.blocked)

    def test_failure_budget_blocks(self):
        guard = make_guard(max_attempts_per_signature=99, max_consecutive_failures=99, max_failures_per_task=3)
        guard.start_task("t1")

        guard.record_result("tool", "a", False)
        guard.record_result("tool", "b", False)
        self.assertFalse(guard.blocked)
        guard.record_result("tool", "c", False)

        self.assertTrue(guard.blocked)
        self.assertEqual(guard.check("tool", "z").rule, "failure_budget")


class TaskLifecycleTests(unittest.TestCase):
    def test_same_task_id_does_not_clear_block_but_new_one_does(self):
        guard = make_guard(max_attempts_per_signature=1, max_failures_per_signature=1)
        guard.start_task("t1")
        guard.record_result("tool", "x", False)  # 1 failure hits the limit -> block
        self.assertTrue(guard.blocked)

        guard.start_task("t1")  # same id: cannot clear its own block
        self.assertTrue(guard.blocked)

        guard.start_task("t2")  # genuinely new intent resumes execution
        self.assertFalse(guard.blocked)
        self.assertTrue(guard.check("tool", "x").allowed)

    def test_record_result_requires_active_task(self):
        guard = make_guard()
        with self.assertRaises(RuntimeError):
            guard.record_result("tool", "x", True)

    def test_history_persists_across_tasks(self):
        guard = make_guard()
        guard.start_task("t1")
        guard.record_result("tool", "a", True)
        guard.start_task("t2")
        guard.record_result("tool", "b", True)

        self.assertEqual([h.task_id for h in guard.history], ["t1", "t2"])


class RunStepTests(unittest.TestCase):
    def test_run_step_happy_path_records_success(self):
        guard = make_guard()
        guard.start_task("t1")

        result = guard.run_step(
            "cdp",
            "get_version",
            action=lambda: {"ok": True},
            success_predicate=lambda r: r["ok"],
        )

        self.assertEqual(result, {"ok": True})
        self.assertFalse(guard.blocked)
        self.assertEqual(len(guard.history), 1)
        self.assertTrue(guard.history[0].success)

    def test_run_step_raises_when_denied_before_execution(self):
        guard = make_guard(max_attempts_per_signature=1, max_failures_per_signature=1)
        guard.start_task("t1")
        guard.record_result("tool", "x", False)  # blocks the task

        with self.assertRaises(StepGuardError) as ctx:
            guard.run_step("tool", "y", action=lambda: 1, success_predicate=lambda r: True)
        self.assertFalse(ctx.exception.decision.allowed)

    def test_run_step_raises_when_result_triggers_block(self):
        guard = make_guard(max_attempts_per_signature=1, max_failures_per_signature=1)
        guard.start_task("t1")

        with self.assertRaises(StepGuardError) as ctx:
            guard.run_step("tool", "x", action=lambda: {"ok": False}, success_predicate=lambda r: r["ok"])

        self.assertEqual(ctx.exception.decision.rule, "repeated_signature_failure")
        self.assertTrue(guard.blocked)

    def test_run_step_records_exception_as_failure_and_reraises(self):
        guard = make_guard()
        guard.start_task("t1")

        def boom():
            raise ValueError("network down")

        with self.assertRaises(ValueError):
            guard.run_step("tool", "x", action=boom, success_predicate=lambda r: True)

        self.assertEqual(len(guard.history), 1)
        self.assertFalse(guard.history[0].success)
        self.assertIn("exception", guard.history[0].detail)


class SnapshotTests(unittest.TestCase):
    def test_snapshot_is_json_serializable_and_complete(self):
        guard = make_guard()
        guard.start_task("t1")
        guard.record_result("cdp", "get_version", False, "boom")

        snapshot = guard.snapshot()
        encoded = json.dumps(snapshot)  # must not raise

        self.assertIn("history", snapshot)
        self.assertIn("limits", snapshot)
        self.assertIn("counters", snapshot)
        self.assertEqual(snapshot["task_id"], "t1")
        self.assertEqual(json.loads(encoded)["history"][0]["at"], FIXED_CLOCK)

    def test_injected_clock_is_used(self):
        guard = make_guard(clock=lambda: "2020-01-01T00:00:00Z")
        guard.start_task("t1")
        guard.record_result("tool", "a", True)

        self.assertEqual(guard.history[0].at, "2020-01-01T00:00:00Z")


class P2CoverageTests(unittest.TestCase):
    def test_success_then_failure_soft_denies_without_hard_block(self):
        guard = make_guard(max_attempts_per_signature=2, max_failures_per_signature=2)
        guard.start_task("t1")
        guard.record_result("tool", "a", True)
        guard.record_result("tool", "a", False)

        self.assertFalse(guard.blocked)
        denied = guard.check("tool", "a")
        self.assertFalse(denied.allowed)
        self.assertEqual(denied.rule, "max_attempts_per_signature")
        self.assertTrue(guard.check("tool", "b").allowed)

    def test_blocked_decision_keeps_signature(self):
        guard = make_guard(max_failures_per_signature=1)
        guard.start_task("t1")
        guard.record_result("tool", "x", False)

        decision = guard.check("tool", "y")
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.signature, "y")
        self.assertEqual(decision.rule, "repeated_signature_failure")

    def test_record_while_blocked_keeps_block_and_grows_history(self):
        guard = make_guard(max_failures_per_signature=1)
        guard.start_task("t1")
        guard.record_result("tool", "x", False)  # blocks
        self.assertTrue(guard.blocked)

        guard.record_result("tool", "x", False)  # recorded, block unchanged
        self.assertTrue(guard.blocked)
        self.assertEqual(len(guard.history), 2)

    def test_snapshot_counters_reflect_failures(self):
        guard = make_guard(max_failures_per_signature=5, max_consecutive_failures=5)
        guard.start_task("t1")
        guard.record_result("tool", "a", False)
        guard.record_result("tool", "a", False)
        guard.record_result("tool", "b", True)

        snap = guard.snapshot()
        self.assertEqual(snap["counters"]["failures_by_signature"], {"a": 2})
        self.assertEqual(snap["counters"]["attempts_by_signature"], {"a": 2, "b": 1})
        self.assertIn("max_failures_per_signature", snap["limits"])


if __name__ == "__main__":
    unittest.main()


class BlockLedgerTests(unittest.TestCase):
    """FC3 (audit 2026-07-17): cross-process G03 — two consecutive blocked
    runs of the same task require an explicit acknowledgment; one recovery
    pass stays free (standard idempotent recovery)."""

    def setUp(self):
        import tempfile
        from pathlib import Path

        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        from src.step_guard import BlockLedger

        self.ledger = BlockLedger(
            Path(self.tmp.name) / "guard_ledger.json", clock=lambda: "T"
        )

    def test_fresh_ledger_never_requires_ack(self):
        self.assertFalse(self.ledger.requires_ack())

    def test_one_blocked_run_allows_the_recovery_pass(self):
        self.ledger.record(task_id="r", blocked=True,
                           rule="consecutive_failures", reason="10 in a row")
        self.assertFalse(self.ledger.requires_ack())

    def test_two_blocked_runs_require_ack(self):
        self.ledger.record(task_id="r", blocked=True, rule="x", reason="a")
        self.ledger.record(task_id="r", blocked=True, rule="x", reason="b")
        self.assertTrue(self.ledger.requires_ack())
        last = self.ledger.load()["last_block"]
        self.assertEqual(last["reason"], "b")

    def test_clean_run_resets_the_streak(self):
        self.ledger.record(task_id="r", blocked=True, rule="x", reason="a")
        self.ledger.record(task_id="r", blocked=False)
        self.ledger.record(task_id="r", blocked=True, rule="x", reason="c")
        self.assertFalse(self.ledger.requires_ack())

    def test_acknowledge_resets_and_records_the_note(self):
        self.ledger.record(task_id="r", blocked=True, rule="x", reason="a")
        self.ledger.record(task_id="r", blocked=True, rule="x", reason="b")
        self.ledger.acknowledge("operator checked the feed")
        self.assertFalse(self.ledger.requires_ack())
        self.assertEqual(self.ledger.load()["acknowledged"]["note"],
                         "operator checked the feed")

    def test_corrupt_ledger_fails_open_for_the_ledger_only(self):
        # A broken ledger must not brick the pipeline — the in-run guard is
        # still fully armed either way.
        self.ledger.path.parent.mkdir(parents=True, exist_ok=True)
        self.ledger.path.write_text("{broken", encoding="utf-8")
        self.assertFalse(self.ledger.requires_ack())
        self.ledger.record(task_id="r", blocked=True, rule="x", reason="a")
        self.assertEqual(self.ledger.load()["consecutive_blocked_runs"], 1)

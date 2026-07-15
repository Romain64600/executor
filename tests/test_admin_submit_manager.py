import json
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

from src.admin.submit_manager import (
    SubmitManager,
    SubmitStartError,
    created_offer_ids,
    offer_submit_history,
    tail_log_events,
)

CLOCK = lambda: "2026-07-15T12:00:00Z"  # noqa: E731


def _cand(offer_id="1", pid="207861", region="2", edition="1"):
    return {
        "fingerprint": f"{offer_id}|{pid}|{region}|{edition}",
        "offer": {
            "offer_id": offer_id, "name": "Game", "url": "https://m/x", "merchant": "GameSeal",
            "store_id": "126", "price": None, "stock": None,
        },
        "aks_product_id": pid, "aks_url": "https://aks/x", "aks_name": "Game", "platform": "STEAM",
        "region": {"label": "GLOBAL", "id": region, "implicit": False},
        "edition": {"label": "Standard", "id": edition},
    }


FAKE_SCRIPT = """\
import json, sys, time
from pathlib import Path
out = Path(sys.argv[1]).resolve().parent
time.sleep({sleep})
if "--catalog" not in sys.argv:
    out.joinpath("submit_plan.json").write_text(
        json.dumps({{"created": 1, "write_attempts": 1, "plan": [], "aborted": None,
                     "stopped": None, "data_entry_mode": "safe", "limit": None}}),
        encoding="utf-8",
    )
print(json.dumps({{"argv": sys.argv[1:], "ok": True}}))
sys.exit({exit_code})
"""


class ManagerTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.runs = self.root / "runs"
        self.run = self.runs / "20260715-000000-test"
        self.run.mkdir(parents=True)
        self.logs = self.root / "logs"
        (self.run / "offers.json").write_text(
            json.dumps(
                {
                    "merchant": "GameSeal",
                    "offers": [{"offer_id": "1", "store_id": "126"}],
                }
            ),
            encoding="utf-8",
        )

    def _write_triple(self, approve=True, tamper_approved=False):
        candidate = _cand()
        (self.run / "candidates.json").write_text(json.dumps([candidate]), encoding="utf-8")
        validation = {
            "run_id": self.run.name,
            "validated_by": "Romain",
            "validated_at": CLOCK(),
            "candidates": [{"fingerprint": candidate["fingerprint"], "approve": approve}],
        }
        (self.run / "validation.json").write_text(json.dumps(validation), encoding="utf-8")
        approved = [candidate] if approve else []
        if tamper_approved:
            approved = [dict(candidate, aks_product_id="999")]
        (self.run / "approved.json").write_text(json.dumps(approved), encoding="utf-8")

    def _manager(self, sleep=0.0, exit_code=0):
        script = self.root / f"fake_submit_{sleep}_{exit_code}.py"
        script.write_text(FAKE_SCRIPT.format(sleep=sleep, exit_code=exit_code), encoding="utf-8")
        return SubmitManager(
            self.root, log_dir=self.logs, submit_script=script, clock=CLOCK
        )


class StartGateTests(ManagerTestCase):
    def test_not_validated_refused(self):
        manager = self._manager()
        with self.assertRaises(SubmitStartError) as ctx:
            manager.start_submit(self.run, mode="safe", limit=None, dry_run=False, by="Romain")
        self.assertEqual(ctx.exception.code, "not_validated")

    def test_tampered_approved_refused(self):
        self._write_triple(tamper_approved=True)
        manager = self._manager()
        with self.assertRaises(SubmitStartError) as ctx:
            manager.start_submit(self.run, mode="safe", limit=None, dry_run=False, by="Romain")
        self.assertEqual(ctx.exception.code, "revalidation_failed")

    def test_empty_approved_refused(self):
        self._write_triple(approve=False)
        manager = self._manager()
        with self.assertRaises(SubmitStartError) as ctx:
            manager.start_submit(self.run, mode="safe", limit=None, dry_run=False, by="Romain")
        self.assertEqual(ctx.exception.code, "nothing_approved")

    def test_limit_widening_canary_refused_before_spawn(self):
        self._write_triple()
        manager = self._manager()
        with self.assertRaises(SubmitStartError) as ctx:
            manager.start_submit(self.run, mode="learning", limit=5, dry_run=False, by="Romain")
        self.assertEqual(ctx.exception.code, "limit_widens_canary")
        self.assertFalse((self.run / "admin_submit.json").exists())

    def test_unknown_mode_refused(self):
        self._write_triple()
        manager = self._manager()
        with self.assertRaises(SubmitStartError) as ctx:
            manager.start_submit(self.run, mode="yolo", limit=None, dry_run=False, by="Romain")
        self.assertEqual(ctx.exception.code, "bad_mode")

    def test_ambiguous_store_refused(self):
        self._write_triple()
        (self.run / "offers.json").write_text(
            json.dumps(
                {
                    "merchant": "GameSeal",
                    "offers": [{"store_id": "126"}, {"store_id": "127"}],
                }
            ),
            encoding="utf-8",
        )
        manager = self._manager()
        with self.assertRaises(SubmitStartError) as ctx:
            manager.start_submit(self.run, mode="safe", limit=None, dry_run=False, by="Romain")
        self.assertEqual(ctx.exception.code, "store_ambiguous")


class RunLifecycleTests(ManagerTestCase):
    def test_submit_supervised_to_completion(self):
        self._write_triple()
        manager = self._manager()
        result = manager.start_submit(self.run, mode="safe", limit=None, dry_run=False, by="Romain")
        self.assertTrue(result["started"])
        self.assertIn("--submit", result["argv"])
        self.assertTrue(manager.wait_idle(timeout=10))
        state = json.loads((self.run / "admin_submit.json").read_text(encoding="utf-8"))
        self.assertEqual(state["state"], "done")
        self.assertEqual(state["exit_code"], 0)
        self.assertEqual(state["mode"], "safe")
        self.assertIn('"ok": true', state["stdout_tail"])
        status = manager.status(self.run)
        self.assertEqual(status["state"], "done")
        self.assertEqual(status["submit_plan"]["created"], 1)
        self.assertIsNone(status["busy"])
        events = [e["event"] for e in tail_log_events(self.logs / f"{self.run.name}.jsonl", 0)[0]]
        self.assertEqual(events, ["admin_submit_started", "admin_submit_finished"])

    def test_dry_run_argv_has_no_submit_flag(self):
        self._write_triple()
        manager = self._manager()
        result = manager.start_submit(self.run, mode="safe", limit=2, dry_run=True, by="Romain")
        self.assertNotIn("--submit", result["argv"])
        self.assertIn("--limit", result["argv"])
        self.assertTrue(manager.wait_idle(timeout=10))

    def test_catalog_argv_and_no_validation_needed(self):
        manager = self._manager()
        result = manager.start_catalog(self.run, by="Romain")
        self.assertIn("--catalog", result["argv"])
        self.assertTrue(manager.wait_idle(timeout=10))
        state = json.loads((self.run / "admin_submit.json").read_text(encoding="utf-8"))
        self.assertEqual(state["kind"], "catalog")
        self.assertEqual(state["state"], "done")

    def test_failed_exit_code_recorded(self):
        self._write_triple()
        manager = self._manager(exit_code=2)
        manager.start_submit(self.run, mode="safe", limit=None, dry_run=False, by="Romain")
        self.assertTrue(manager.wait_idle(timeout=10))
        state = json.loads((self.run / "admin_submit.json").read_text(encoding="utf-8"))
        self.assertEqual(state["state"], "failed")
        self.assertEqual(state["exit_code"], 2)

    def test_second_start_refused_while_running(self):
        self._write_triple()
        manager = self._manager(sleep=2.0)
        manager.start_submit(self.run, mode="safe", limit=None, dry_run=False, by="Romain")
        with self.assertRaises(SubmitStartError) as ctx:
            manager.start_catalog(self.run, by="Romain")
        self.assertEqual(ctx.exception.code, "submit_in_progress")
        self.assertIsNotNone(manager.busy())
        self.assertTrue(manager.wait_idle(timeout=10))
        # released after completion
        manager.start_catalog(self.run, by="Romain")
        self.assertTrue(manager.wait_idle(timeout=10))


class RecoverOrphansTests(ManagerTestCase):
    def test_dead_pid_marked_interrupted(self):
        (self.run / "admin_submit.json").write_text(
            json.dumps({"state": "running", "kind": "submit", "pid": 2**22 + 12345}),
            encoding="utf-8",
        )
        manager = self._manager()
        found = manager.recover_orphans(self.runs)
        self.assertEqual(found, [{"run_id": self.run.name, "state": "interrupted"}])
        state = json.loads((self.run / "admin_submit.json").read_text(encoding="utf-8"))
        self.assertEqual(state["state"], "interrupted")
        self.assertIn("inspecter le feed", state["note"])

    def test_alive_pid_blocks_new_starts_until_gone(self):
        proc = subprocess.Popen(["sleep", "30"])
        try:
            (self.run / "admin_submit.json").write_text(
                json.dumps({"state": "running", "kind": "submit", "pid": proc.pid}),
                encoding="utf-8",
            )
            self._write_triple()
            manager = self._manager()
            found = manager.recover_orphans(self.runs)
            self.assertEqual(found[0]["state"], "orphaned")
            with self.assertRaises(SubmitStartError) as ctx:
                manager.start_submit(self.run, mode="safe", limit=None, dry_run=True, by="Romain")
            self.assertEqual(ctx.exception.code, "orphan_alive")
        finally:
            proc.terminate()
            proc.wait()
        manager.start_submit(self.run, mode="safe", limit=None, dry_run=True, by="Romain")
        self.assertTrue(manager.wait_idle(timeout=10))


class SubmitHistoryTests(ManagerTestCase):
    def _log(self, *records):
        self.logs.mkdir(exist_ok=True)
        path = self.logs / f"{self.run.name}.jsonl"
        with open(path, "a", encoding="utf-8") as handle:
            for record in records:
                handle.write((record if isinstance(record, str) else json.dumps(record)) + "\n")
        return path

    def test_history_distinguishes_created_failed_pending(self):
        log = self._log(
            {"event": "submit_offer", "offer_id": "1", "success": True,
             "post_save": "gone from feed (available=all)", "ts": "T1"},
            {"event": "submit_offer", "offer_id": "2", "success": False,
             "blocker": "offer not in current feed", "ts": "T2"},
            "{broken json",
            {"event": "skip", "offer_id": "3"},
        )
        history = offer_submit_history(log)
        self.assertEqual(history["1"]["status"], "created")
        self.assertEqual(history["1"]["at"], "T1")
        self.assertEqual(history["2"]["status"], "failed")
        self.assertEqual(history["2"]["blocker"], "offer not in current feed")
        self.assertNotIn("3", history)  # pending: never attempted

    def test_created_is_sticky_over_later_failure(self):
        log = self._log(
            {"event": "submit_offer", "offer_id": "1", "success": True, "post_save": "gone", "ts": "T1"},
            {"event": "submit_offer", "offer_id": "1", "success": False,
             "blocker": "offer not in current feed", "ts": "T2"},
        )
        history = offer_submit_history(log)
        self.assertEqual(history["1"]["status"], "created")
        self.assertEqual(history["1"]["attempts"], 2)

    def test_submit_plan_unioned_as_secondary_source(self):
        log = self._log(
            {"event": "submit_offer", "offer_id": "1", "success": True, "post_save": "gone", "ts": "T1"},
        )
        plan_path = self.run / "submit_plan.json"
        plan_path.write_text(
            json.dumps({"created": 2, "plan": [
                {"offer_id": "1", "submitted": True, "post_save": "gone"},
                {"offer_id": "5", "submitted": True, "post_save": "gone"},
                {"offer_id": "6", "ready": True, "would_submit": True},  # dry entry: not created
                {"offer_id": "7", "ready": False, "blocker": "x"},
            ]}),
            encoding="utf-8",
        )
        created = created_offer_ids(log, plan_path)
        self.assertEqual(sorted(created), ["1", "5"])
        self.assertEqual(created["1"]["source"], "log")
        self.assertEqual(created["5"]["source"], "submit_plan")

    def test_resubmit_of_created_offer_refused(self):
        self._write_triple()  # approves offer_id "1"
        self._log(
            {"event": "submit_offer", "offer_id": "1", "success": True, "post_save": "gone", "ts": "T1"},
        )
        manager = self._manager()
        with self.assertRaises(SubmitStartError) as ctx:
            manager.start_submit(self.run, mode="safe", limit=None, dry_run=False, by="Romain")
        self.assertEqual(ctx.exception.code, "already_created")
        self.assertIn("1", str(ctx.exception))
        self.assertFalse((self.run / "admin_submit.json").exists())

    def test_submit_allowed_when_created_disjoint(self):
        self._write_triple()  # approves offer_id "1"
        self._log(
            {"event": "submit_offer", "offer_id": "999", "success": True, "post_save": "gone", "ts": "T1"},
        )
        manager = self._manager()
        manager.start_submit(self.run, mode="safe", limit=None, dry_run=True, by="Romain")
        self.assertTrue(manager.wait_idle(timeout=10))


class TailLogEventsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.log = Path(self.tmp.name) / "r.jsonl"

    def test_filter_offset_and_partial_line(self):
        lines = [
            json.dumps({"event": "submit_offer", "offer_id": "1"}),
            json.dumps({"event": "guard_snapshot", "guard": {}}),
            json.dumps({"event": "skip", "offer_id": "2"}),
        ]
        self.log.write_text("\n".join(lines) + "\n", encoding="utf-8")
        events, offset = tail_log_events(self.log, 0)
        self.assertEqual([e["event"] for e in events], ["submit_offer", "skip"])
        # append one complete + one partial line: only the complete one is consumed
        with open(self.log, "a", encoding="utf-8") as handle:
            handle.write(json.dumps({"event": "run_stopped"}) + "\n")
            handle.write('{"event": "submit_of')
        events2, offset2 = tail_log_events(self.log, offset)
        self.assertEqual([e["event"] for e in events2], ["run_stopped"])
        # completing the partial line makes it readable from the new offset
        with open(self.log, "a", encoding="utf-8") as handle:
            handle.write('fer", "offer_id": "3"}\n')
        events3, _ = tail_log_events(self.log, offset2)
        self.assertEqual([e["offer_id"] for e in events3], ["3"])

    def test_events_re_redacted(self):
        self.log.write_text(
            json.dumps({"event": "submit_offer", "token": "SECRET"}) + "\n", encoding="utf-8"
        )
        events, _ = tail_log_events(self.log, 0)
        self.assertEqual(events[0]["token"], "***REDACTED***")

    def test_missing_file_is_empty(self):
        self.assertEqual(tail_log_events(self.log, 0), ([], 0))


if __name__ == "__main__":
    unittest.main()

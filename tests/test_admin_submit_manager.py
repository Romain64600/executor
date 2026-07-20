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

# Mirrors scripts/02_extract_feed.py's relevant CLI shape. Runs with
# cwd=repo_root (same as the real _spawn), so "runs/<run-id>/" resolves the
# same way a real extraction's default --out-dir would.
FAKE_EXTRACT_SCRIPT = """\
import argparse, json, sys, time
from pathlib import Path
p = argparse.ArgumentParser()
p.add_argument("--merchant", required=True)
p.add_argument("--store-id", required=True)
p.add_argument("--run-id", required=True)
args = p.parse_args()
time.sleep({sleep})
out = Path("runs") / args.run_id
out.mkdir(parents=True, exist_ok=True)
out.joinpath("offers.json").write_text(
    json.dumps({{"merchant": args.merchant, "offers": []}}), encoding="utf-8"
)
print(json.dumps({{"run_id": args.run_id, "merchant": args.merchant, "ok": True}}))
sys.exit({exit_code})
"""

# Mirrors scripts/03_match.py's CLI: offers.json positional + --max-candidates.
# Writes candidates.json next to offers.json (what fills the validation table).
FAKE_MATCH_SCRIPT = """\
import argparse, json, sys, time
from pathlib import Path
p = argparse.ArgumentParser()
p.add_argument("offers")
p.add_argument("--max-candidates", type=int, default=100)
args = p.parse_args()
time.sleep({sleep})
out = Path(args.offers).resolve().parent
out.joinpath("candidates.json").write_text(json.dumps([]), encoding="utf-8")
print(json.dumps({{"candidates": 0, "max_candidates": args.max_candidates}}))
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

    def _approved_sha(self):
        import hashlib
        return hashlib.sha256((self.run / "approved.json").read_bytes()).hexdigest()

    def _manager(self, sleep=0.0, exit_code=0):
        script = self.root / f"fake_submit_{sleep}_{exit_code}.py"
        script.write_text(FAKE_SCRIPT.format(sleep=sleep, exit_code=exit_code), encoding="utf-8")
        return SubmitManager(
            self.root, log_dir=self.logs, submit_script=script, clock=CLOCK
        )

    def _extract_manager(self, sleep=0.0, exit_code=0):
        script = self.root / f"fake_extract_{sleep}_{exit_code}.py"
        script.write_text(
            FAKE_EXTRACT_SCRIPT.format(sleep=sleep, exit_code=exit_code), encoding="utf-8"
        )
        return SubmitManager(
            self.root, log_dir=self.logs, extract_script=script, clock=CLOCK
        )

    def _match_manager(self, sleep=0.0, exit_code=0):
        script = self.root / f"fake_match_{sleep}_{exit_code}.py"
        script.write_text(
            FAKE_MATCH_SCRIPT.format(sleep=sleep, exit_code=exit_code), encoding="utf-8"
        )
        return SubmitManager(
            self.root, log_dir=self.logs, match_script=script, clock=CLOCK
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
            manager.start_submit(self.run, mode="safe", limit=None, dry_run=False, by="Romain",
                             expected_approved_sha=self._approved_sha())
        self.assertEqual(ctx.exception.code, "store_ambiguous")


class RunLifecycleTests(ManagerTestCase):
    def test_submit_supervised_to_completion(self):
        self._write_triple()
        manager = self._manager()
        result = manager.start_submit(self.run, mode="safe", limit=None, dry_run=False, by="Romain",
                             expected_approved_sha=self._approved_sha())
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

    def test_max_pages_omitted_by_default(self):
        # No --max-pages in argv when unset — the script keeps its own
        # default (40), unchanged behavior for every merchant that doesn't
        # need it.
        self._write_triple()
        manager = self._manager()
        result = manager.start_submit(self.run, mode="safe", limit=None, dry_run=True, by="Romain")
        self.assertNotIn("--max-pages", result["argv"])
        self.assertTrue(manager.wait_idle(timeout=10))

    def test_max_pages_threaded_into_submit_argv(self):
        # Difmark (2026-07-17): 382-page feed, the default 40-page cap made
        # the feed-index scan abort "coverage unproven" — the operator needs
        # to raise this from the admin page, not just the CLI.
        self._write_triple()
        manager = self._manager()
        result = manager.start_submit(
            self.run, mode="safe", limit=None, dry_run=True, by="Romain", max_pages=400,
        )
        self.assertIn("--max-pages", result["argv"])
        self.assertEqual(result["argv"][result["argv"].index("--max-pages") + 1], "400")
        self.assertTrue(manager.wait_idle(timeout=10))

    def test_bad_max_pages_refused_before_spawn(self):
        self._write_triple()
        manager = self._manager()
        with self.assertRaises(SubmitStartError) as ctx:
            manager.start_submit(
                self.run, mode="safe", limit=None, dry_run=True, by="Romain", max_pages=0,
            )
        self.assertEqual(ctx.exception.code, "bad_max_pages")
        self.assertIsNone(manager.busy())

    def test_catalog_argv_and_no_validation_needed(self):
        manager = self._manager()
        result = manager.start_catalog(self.run, by="Romain")
        self.assertIn("--catalog", result["argv"])
        self.assertTrue(manager.wait_idle(timeout=10))
        state = json.loads((self.run / "admin_submit.json").read_text(encoding="utf-8"))
        self.assertEqual(state["kind"], "catalog")
        self.assertEqual(state["state"], "done")

    def test_catalog_accepts_max_pages(self):
        manager = self._manager()
        result = manager.start_catalog(self.run, by="Romain", max_pages=200)
        self.assertIn("--max-pages", result["argv"])
        self.assertEqual(result["argv"][result["argv"].index("--max-pages") + 1], "200")
        self.assertTrue(manager.wait_idle(timeout=10))

    def test_failed_exit_code_recorded(self):
        self._write_triple()
        manager = self._manager(exit_code=2)
        manager.start_submit(self.run, mode="safe", limit=None, dry_run=False, by="Romain",
                             expected_approved_sha=self._approved_sha())
        self.assertTrue(manager.wait_idle(timeout=10))
        state = json.loads((self.run / "admin_submit.json").read_text(encoding="utf-8"))
        self.assertEqual(state["state"], "failed")
        self.assertEqual(state["exit_code"], 2)

    def test_second_start_refused_while_running(self):
        self._write_triple()
        manager = self._manager(sleep=2.0)
        manager.start_submit(self.run, mode="safe", limit=None, dry_run=False, by="Romain",
                             expected_approved_sha=self._approved_sha())
        with self.assertRaises(SubmitStartError) as ctx:
            manager.start_catalog(self.run, by="Romain")
        self.assertEqual(ctx.exception.code, "submit_in_progress")
        self.assertIsNotNone(manager.busy())
        self.assertTrue(manager.wait_idle(timeout=10))
        # released after completion
        manager.start_catalog(self.run, by="Romain")
        self.assertTrue(manager.wait_idle(timeout=10))


class StartExtractTests(ManagerTestCase):
    """Stage 1, launched from the admin page: merchant + store_id, no existing run_dir."""

    def test_run_id_and_argv(self):
        manager = self._extract_manager()
        result = manager.start_extract("GameSeal", "126", by="Romain")
        self.assertTrue(result["started"])
        self.assertEqual(result["run_id"], "20260715-120000-gameseal")
        self.assertIn("--merchant", result["argv"])
        self.assertIn("GameSeal", result["argv"])
        self.assertIn("--store-id", result["argv"])
        self.assertIn("126", result["argv"])
        self.assertIn("--run-id", result["argv"])
        self.assertTrue(manager.wait_idle(timeout=10))
        self.assertTrue((self.runs / result["run_id"]).is_dir())

    def test_merchant_with_spaces_gets_a_safe_run_id_slug(self):
        # "Instant Gaming" (a real merchant in this catalog) must not produce
        # a run_id containing a space — RUN_ID_RE (admin/runs.py) rejects it.
        manager = self._extract_manager()
        result = manager.start_extract("Instant Gaming", "28", by="Romain")
        self.assertEqual(result["run_id"], "20260715-120000-instant-gaming")
        self.assertTrue(manager.wait_idle(timeout=10))

    def test_bad_store_id_refused_before_spawn(self):
        manager = self._extract_manager()
        with self.assertRaises(SubmitStartError) as ctx:
            manager.start_extract("GameSeal", "not-a-number", by="Romain")
        self.assertEqual(ctx.exception.code, "bad_store_id")
        self.assertIsNone(manager.busy())

    def test_empty_merchant_refused(self):
        manager = self._extract_manager()
        with self.assertRaises(SubmitStartError) as ctx:
            manager.start_extract("   ", "126", by="Romain")
        self.assertEqual(ctx.exception.code, "bad_merchant")

    def test_extract_supervised_to_completion(self):
        manager = self._extract_manager()
        result = manager.start_extract("GameSeal", "126", by="Romain")
        self.assertTrue(manager.wait_idle(timeout=10))
        run_dir = self.runs / result["run_id"]
        state = json.loads((run_dir / "admin_submit.json").read_text(encoding="utf-8"))
        self.assertEqual(state["state"], "done")
        self.assertEqual(state["kind"], "extract")
        self.assertTrue((run_dir / "offers.json").is_file())
        events = [e["event"] for e in tail_log_events(self.logs / f"{run_dir.name}.jsonl", 0)[0]]
        self.assertEqual(events, ["admin_submit_started", "admin_submit_finished"])

    def test_second_start_refused_while_extract_running(self):
        manager = self._extract_manager(sleep=2.0)
        manager.start_extract("GameSeal", "126", by="Romain")
        with self.assertRaises(SubmitStartError) as ctx:
            manager.start_extract("Kinguin", "58", by="Romain")
        self.assertEqual(ctx.exception.code, "submit_in_progress")
        self.assertTrue(manager.wait_idle(timeout=10))


class StartMatchTests(ManagerTestCase):
    """Stage 3, launched from the admin page (Romain 2026-07-20): matches an
    already-extracted run to fill the validation table."""

    def test_argv_and_lifecycle(self):
        manager = self._match_manager()
        result = manager.start_match(self.run, by="Romain", max_candidates=3)
        self.assertTrue(result["started"])
        self.assertEqual(result["kind"], "match")
        self.assertIn(str(self.run / "offers.json"), result["argv"])
        self.assertIn("--max-candidates", result["argv"])
        self.assertIn("3", result["argv"])
        self.assertTrue(manager.wait_idle(timeout=10))
        state = json.loads((self.run / "admin_submit.json").read_text(encoding="utf-8"))
        self.assertEqual(state["state"], "done")
        self.assertEqual(state["kind"], "match")
        self.assertTrue((self.run / "candidates.json").is_file())

    def test_no_max_candidates_omits_the_flag(self):
        manager = self._match_manager()
        result = manager.start_match(self.run, by="Romain")
        self.assertNotIn("--max-candidates", result["argv"])
        self.assertTrue(manager.wait_idle(timeout=10))

    def test_not_extracted_refused(self):
        # A run dir with no offers.json (never extracted) refuses before spawn.
        empty = self.runs / "20260720-000000-empty"
        empty.mkdir(parents=True)
        manager = self._match_manager()
        with self.assertRaises(SubmitStartError) as ctx:
            manager.start_match(empty, by="Romain")
        self.assertEqual(ctx.exception.code, "not_extracted")
        self.assertIsNone(manager.busy())

    def test_bad_max_candidates_refused(self):
        manager = self._match_manager()
        with self.assertRaises(SubmitStartError) as ctx:
            manager.start_match(self.run, by="Romain", max_candidates=0)
        self.assertEqual(ctx.exception.code, "bad_max_candidates")

    def test_refused_while_another_run_active(self):
        manager = self._match_manager(sleep=2.0)
        manager.start_match(self.run, by="Romain")
        with self.assertRaises(SubmitStartError) as ctx:
            manager.start_match(self.run, by="Romain")
        self.assertEqual(ctx.exception.code, "submit_in_progress")
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
            manager.start_submit(self.run, mode="safe", limit=None, dry_run=False, by="Romain",
                             expected_approved_sha=self._approved_sha())
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


class SpawnFailClosedTests(ManagerTestCase):
    def test_failure_after_popen_kills_child_and_frees_manager(self):
        # AS2 (audit 2026-07-17): an OSError between Popen and the start of
        # supervision (state-file write) used to leave a LIVE child running
        # with no supervisor — fire-and-forget, the one thing AGENTS.md
        # forbids. The child must be killed and the manager freed.
        from unittest import mock

        import src.admin.submit_manager as sm

        self._write_triple()
        manager = self._manager(sleep=30)  # child would run 30 s if leaked
        spawned = []
        real_popen = sm.subprocess.Popen

        def tracking_popen(*args, **kwargs):
            proc = real_popen(*args, **kwargs)
            spawned.append(proc)
            return proc

        with mock.patch.object(sm.subprocess, "Popen", tracking_popen), \
                mock.patch.object(sm, "_write_atomic", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                manager.start_submit(
                    self.run, mode="safe", limit=None, dry_run=True, by="Romain"
                )
        self.assertEqual(len(spawned), 1)
        spawned[0].wait(timeout=5)  # would TimeoutExpired if left running
        self.assertIsNotNone(spawned[0].poll())
        self.assertIsNone(manager.busy())  # a new run can start


class ApprovedShaBindingTests(ManagerTestCase):
    def test_real_submit_without_sha_refused(self):
        self._write_triple()
        manager = self._manager()
        with self.assertRaises(SubmitStartError) as ctx:
            manager.start_submit(self.run, mode="safe", limit=None, dry_run=False, by="Romain")
        self.assertEqual(ctx.exception.code, "approved_sha_required")

    def test_real_submit_with_stale_sha_refused(self):
        self._write_triple()
        manager = self._manager()
        with self.assertRaises(SubmitStartError) as ctx:
            manager.start_submit(
                self.run, mode="safe", limit=None, dry_run=False, by="Romain",
                expected_approved_sha="0" * 64,
            )
        self.assertEqual(ctx.exception.code, "approved_changed")
        self.assertEqual(ctx.exception.http_status, 409)

    def test_dry_run_does_not_require_sha(self):
        self._write_triple()
        manager = self._manager()
        result = manager.start_submit(
            self.run, mode="safe", limit=None, dry_run=True, by="Romain"
        )
        self.assertTrue(result["started"])
        self.assertTrue(manager.wait_idle(timeout=10))


class MatchedModeBindingTests(ManagerTestCase):
    """FC5 mirror: a canary-matched run must never submit as safe."""

    def _write_meta(self, mode):
        (self.run / "match_meta.json").write_text(
            json.dumps({"run_id": self.run.name, "data_entry_mode": mode}),
            encoding="utf-8",
        )

    def test_learning_matched_refuses_safe_submit(self):
        self._write_triple()
        self._write_meta("learning")
        manager = self._manager()
        with self.assertRaises(SubmitStartError) as ctx:
            manager.start_submit(
                self.run, mode="safe", limit=None, dry_run=False, by="Romain",
                expected_approved_sha=self._approved_sha(),
            )
        self.assertEqual(ctx.exception.code, "mode_widens_match")

    def test_safe_matched_allows_canary_submit(self):
        self._write_triple()
        self._write_meta("safe")
        manager = self._manager()
        result = manager.start_submit(
            self.run, mode="learning", limit=None, dry_run=False, by="Romain",
            expected_approved_sha=self._approved_sha(),
        )
        self.assertTrue(result["started"])
        self.assertTrue(manager.wait_idle(timeout=10))

    def test_unreadable_meta_refuses(self):
        self._write_triple()
        (self.run / "match_meta.json").write_text("{broken", encoding="utf-8")
        manager = self._manager()
        with self.assertRaises(SubmitStartError) as ctx:
            manager.start_submit(
                self.run, mode="safe", limit=None, dry_run=False, by="Romain",
                expected_approved_sha=self._approved_sha(),
            )
        self.assertEqual(ctx.exception.code, "match_meta_unreadable")


if __name__ == "__main__":
    unittest.main()

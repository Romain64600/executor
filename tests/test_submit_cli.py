"""CLI-level tests for scripts/05_submit.py (Romain's robustness pass, 2026-07-08).

The submit-time re-validation is unit-tested in test_validation.py; these
tests exercise the full CLI path around it: missing validation.json /
candidates.json, a tampered or fabricated approved.json refused in BOTH
dry-run and --submit modes (with no session ever opened), the invariants
gate, and a smoke test of the submit_report.txt header (created vs
write_attempts, audit P2). main() runs in-process with build_report, the
sessions and the submitters replaced by fakes — no CDP, no network.
"""

import contextlib
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]


def _load_cli():
    spec = importlib.util.spec_from_file_location(
        "submit_cli_under_test", ROOT / "scripts" / "05_submit.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MOD = _load_cli()

GREEN = {"ok": True, "authoritative": True, "checks": []}
RED = {"ok": False, "authoritative": False,
       "checks": [{"name": "cdp", "ok": False, "detail": "timeout"}]}


def _candidate(offer_id):
    return {
        "fingerprint": f"{offer_id}|4496|2|1",
        "offer": {
            "offer_id": offer_id, "name": f"Game {offer_id}",
            "url": f"https://driffle.com/game-{offer_id}", "merchant": "Driffle",
            "store_id": "127", "price": "9.99", "stock": None,
        },
        "aks_product_id": "4496", "aks_url": "https://aks/x",
        "aks_name": f"Game {offer_id}", "platform": "STEAM",
        "region": {"label": "GLOBAL", "id": "2", "implicit": False},
        "edition": {"label": "Standard", "id": "1"},
    }


class _FakeLogger:
    def __init__(self, *args, **kwargs):
        pass

    def log(self, *args, **kwargs):
        pass

    def log_guard(self, *args, **kwargs):
        pass


class _FakeSession:
    instantiated = 0

    def __init__(self, endpoint):
        type(self).instantiated += 1
        self.endpoint = endpoint

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _fake_submitter_cls(result):
    class _FakeSubmitter:
        instantiated = 0
        run_kwargs = None

        def __init__(self, session, **kwargs):
            type(self).instantiated += 1

        def run(self, **kwargs):
            type(self).run_kwargs = kwargs
            return result

    return _FakeSubmitter


class SubmitCliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.run_dir = Path(self.tmp.name) / "20260708-000000-test"
        self.run_dir.mkdir()
        self.run_id = self.run_dir.name
        _FakeSession.instantiated = 0

    def _write_fixture(self, *, drop=(), tamper=None, extra_unapproved=False):
        """A coherent candidates/validation/approved triple, then break it."""
        candidates = [_candidate("1")]
        if extra_unapproved:
            candidates.append(_candidate("2"))
        validation = {
            "run_id": self.run_id,
            "validated_by": "romain", "validated_at": "2026-07-08T12:00:00Z",
            "candidates": [
                {"fingerprint": "1|4496|2|1", "approve": True},
                {"fingerprint": "2|4496|2|1", "approve": False},
            ],
        }
        approved = json.loads(json.dumps(candidates))  # deep copy
        if not extra_unapproved:
            approved = approved[:1]
        if tamper:
            tamper(approved)
        files = {
            "candidates.json": candidates,
            "validation.json": validation,
            "approved.json": approved,
        }
        for name, payload in files.items():
            if name in drop:
                continue
            (self.run_dir / name).write_text(json.dumps(payload), encoding="utf-8")
        return str(self.run_dir / "approved.json")

    def _run_cli(self, argv, *, report=GREEN, patches=()):
        out = io.StringIO()
        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch.object(MOD, "build_report", return_value=report))
            stack.enter_context(mock.patch.object(MOD, "RunLogger", _FakeLogger))
            stack.enter_context(mock.patch.object(MOD.time, "sleep", lambda s: None))
            # OP1: keep the tests off the repo's REAL state/browser.lock — a
            # live admin run must never be refused because the suite is running.
            stack.enter_context(mock.patch.object(
                MOD, "browser_lock", lambda root, label: contextlib.nullcontext()
            ))
            stack.enter_context(mock.patch.object(sys, "argv", ["05_submit.py"] + argv))
            stack.enter_context(contextlib.redirect_stdout(out))
            stack.enter_context(contextlib.redirect_stderr(io.StringIO()))
            for patch in patches:
                stack.enter_context(patch)
            code = MOD.main()
        return code, out.getvalue()

    def test_learning_matched_run_refuses_safe_submit(self):
        # FC5 (audit 2026-07-17): a run matched under an unlock (canary) must
        # never take the full-batch safe path.
        approved = self._write_fixture()
        (self.run_dir / "match_meta.json").write_text(
            json.dumps({"run_id": self.run_id, "data_entry_mode": "learning"}),
            encoding="utf-8",
        )
        fake_submitter = _fake_submitter_cls({
            "aborted": None, "stopped": None, "feed_offers": 1,
            "write_attempts": 0, "created": 0, "plan": [],
        })
        code, out = self._run_cli(
            self._base_argv(approved, "--submit"),
            patches=(
                mock.patch.object(MOD, "WriteSubmitSession", _FakeSession),
                mock.patch.object(MOD, "Submitter", fake_submitter),
            ),
        )
        self.assertEqual(code, 2)
        payload = json.loads(out)
        self.assertIn("cannot submit as 'safe'", payload["reason"])
        self.assertEqual(fake_submitter.instantiated, 0)  # never spawned a session

    def test_safe_matched_run_submits_as_canary_narrower_is_fine(self):
        approved = self._write_fixture()
        (self.run_dir / "match_meta.json").write_text(
            json.dumps({"run_id": self.run_id, "data_entry_mode": "safe"}),
            encoding="utf-8",
        )
        fake_submitter = _fake_submitter_cls({
            "aborted": None, "stopped": None, "feed_offers": 1,
            "write_attempts": 1, "created": 1, "plan": [],
        })
        code, out = self._run_cli(
            self._base_argv(approved, "--submit", "--mode", "learning"),
            patches=(
                mock.patch.object(MOD, "WriteSubmitSession", _FakeSession),
                mock.patch.object(MOD, "Submitter", fake_submitter),
            ),
        )
        self.assertEqual(code, 0)
        summary = json.loads(out)
        self.assertEqual(summary["data_entry_mode"], "learning")

    def test_legacy_run_without_meta_still_submits(self):
        approved = self._write_fixture()
        fake_submitter = _fake_submitter_cls({
            "aborted": None, "stopped": None, "feed_offers": 1,
            "write_attempts": 1, "created": 1, "plan": [],
        })
        code, out = self._run_cli(
            self._base_argv(approved, "--submit"),
            patches=(
                mock.patch.object(MOD, "WriteSubmitSession", _FakeSession),
                mock.patch.object(MOD, "Submitter", fake_submitter),
            ),
        )
        self.assertEqual(code, 0)

    def test_third_pass_after_two_blocked_requires_ack(self):
        # FC3: two prior real passes ended guard-blocked → the third refuses
        # without --acknowledge-block; with the flag it runs and resets.
        approved = self._write_fixture()
        (self.run_dir / "guard_ledger.json").write_text(json.dumps({
            "consecutive_blocked_runs": 2,
            "last_block": {"task_id": self.run_id, "rule": "consecutive_failures",
                           "reason": "10 consecutive failures", "at": "T"},
        }), encoding="utf-8")
        fake_submitter = _fake_submitter_cls({
            "aborted": None, "stopped": None, "feed_offers": 1,
            "write_attempts": 0, "created": 0, "plan": [],
        })
        patches = (
            mock.patch.object(MOD, "WriteSubmitSession", _FakeSession),
            mock.patch.object(MOD, "Submitter", fake_submitter),
        )
        code, out = self._run_cli(self._base_argv(approved, "--submit"), patches=patches)
        self.assertEqual(code, 2)
        payload = json.loads(out)
        self.assertIn("--acknowledge-block", payload["reason"])
        self.assertEqual(payload["last_block"]["reason"], "10 consecutive failures")

        code, out = self._run_cli(
            self._base_argv(approved, "--submit", "--acknowledge-block"), patches=patches
        )
        self.assertEqual(code, 0)
        ledger = json.loads((self.run_dir / "guard_ledger.json").read_text(encoding="utf-8"))
        self.assertEqual(ledger["consecutive_blocked_runs"], 0)

    def test_single_blocked_pass_allows_free_recovery(self):
        approved = self._write_fixture()
        (self.run_dir / "guard_ledger.json").write_text(json.dumps({
            "consecutive_blocked_runs": 1,
        }), encoding="utf-8")
        fake_submitter = _fake_submitter_cls({
            "aborted": None, "stopped": None, "feed_offers": 1,
            "write_attempts": 1, "created": 1, "plan": [],
        })
        code, out = self._run_cli(
            self._base_argv(approved, "--submit"),
            patches=(
                mock.patch.object(MOD, "WriteSubmitSession", _FakeSession),
                mock.patch.object(MOD, "Submitter", fake_submitter),
            ),
        )
        self.assertEqual(code, 0)
        # clean pass reset the streak
        ledger = json.loads((self.run_dir / "guard_ledger.json").read_text(encoding="utf-8"))
        self.assertEqual(ledger["consecutive_blocked_runs"], 0)

    def test_browser_lock_busy_refuses_before_anything(self):
        from src.browser_lock import BrowserBusyError

        def busy_lock(root, label):
            raise BrowserBusyError("browser tab busy — held by test pid=1")

        approved = self._write_fixture()
        out = io.StringIO()
        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch.object(MOD, "browser_lock", busy_lock))
            stack.enter_context(mock.patch.object(
                sys, "argv", ["05_submit.py"] + self._base_argv(approved)
            ))
            stack.enter_context(contextlib.redirect_stdout(out))
            stack.enter_context(contextlib.redirect_stderr(io.StringIO()))
            code = MOD.main()
        self.assertEqual(code, 2)
        payload = json.loads(out.getvalue())
        self.assertTrue(payload["aborted"])
        self.assertIn("browser tab busy", payload["reason"])

    def _base_argv(self, approved_path, *extra):
        return [approved_path, "--merchant", "Driffle", "--store-id", "127", *extra]

    # -- gates ---------------------------------------------------------------

    def test_invariants_red_aborts_before_validation(self):
        approved = self._write_fixture()
        code, out = self._run_cli(self._base_argv(approved), report=RED)
        self.assertEqual(code, 2)
        payload = json.loads(out)
        self.assertTrue(payload["aborted"])
        self.assertIn("invariants not green/authoritative", payload["reason"])

    def test_missing_validation_json_refuses_dry_run(self):
        approved = self._write_fixture(drop=("validation.json",))
        code, out = self._run_cli(self._base_argv(approved))
        self.assertEqual(code, 2)
        payload = json.loads(out)
        self.assertIn("submit-time validation re-check failed", payload["reason"])
        self.assertIn("must sit next to approved.json", payload["reason"])

    def test_missing_candidates_json_refuses_dry_run(self):
        approved = self._write_fixture(drop=("candidates.json",))
        code, out = self._run_cli(self._base_argv(approved))
        self.assertEqual(code, 2)
        self.assertIn("submit-time validation re-check failed", json.loads(out)["reason"])

    def test_tampered_approved_refuses_dry_run(self):
        def bump_edition(approved):
            approved[0]["edition"]["id"] = "7"

        approved = self._write_fixture(tamper=bump_edition)
        code, out = self._run_cli(self._base_argv(approved))
        self.assertEqual(code, 2)
        self.assertIn("does not match candidates.json + validation.json",
                      json.loads(out)["reason"])

    def test_tampered_approved_refuses_submit_without_opening_session(self):
        def bump_region(approved):
            approved[0]["region"]["id"] = "9"

        approved = self._write_fixture(tamper=bump_region)
        fake_submitter = _fake_submitter_cls({})
        code, out = self._run_cli(
            self._base_argv(approved, "--submit"),
            patches=(
                mock.patch.object(MOD, "WriteSubmitSession", _FakeSession),
                mock.patch.object(MOD, "Submitter", fake_submitter),
            ),
        )
        self.assertEqual(code, 2)
        self.assertIn("submit-time validation re-check failed", json.loads(out)["reason"])
        self.assertEqual(_FakeSession.instantiated, 0)
        self.assertEqual(fake_submitter.instantiated, 0)

    def test_unapproved_candidate_in_approved_refuses(self):
        # approved.json claims candidate 2, whose validation entry is approve:false.
        approved = self._write_fixture(extra_unapproved=True)
        code, out = self._run_cli(self._base_argv(approved))
        self.assertEqual(code, 2)
        self.assertIn("does not match candidates.json + validation.json",
                      json.loads(out)["reason"])

    # -- pass-through (proves the refusals above are specific) ----------------

    def test_valid_approved_passes_gate_dry_run(self):
        approved = self._write_fixture()
        result = {
            "aborted": None, "stopped": None, "feed_offers": 7,
            "write_attempts": None, "created": None,
            "plan": [{"offer_id": "1", "merchant_title": "Game 1",
                      "ready": True, "would_submit": "region=2 edition=1"}],
        }
        code, out = self._run_cli(
            self._base_argv(approved),
            patches=(
                mock.patch.object(MOD, "SubmitSession", _FakeSession),
                mock.patch.object(MOD, "DryRunSubmitter", _fake_submitter_cls(result)),
            ),
        )
        self.assertEqual(code, 0)
        summary = json.loads(out)
        self.assertEqual(summary["mode"], "dry_run")
        self.assertEqual(summary["ready"], 1)
        report = (self.run_dir / "submit_report.txt").read_text(encoding="utf-8")
        self.assertTrue(report.startswith("DRY-RUN — Driffle — mode=safe (full batch) — 1/1 ready, "))
        self.assertTrue((self.run_dir / "submit_plan.json").exists())

    def test_submit_report_header_shows_created_and_write_attempts(self):
        # Audit P2 smoke test: both counters explicit in the text header.
        approved = self._write_fixture()
        result = {
            "aborted": None, "stopped": None, "feed_offers": 7,
            "write_attempts": 2, "created": 1,
            "plan": [
                {"offer_id": "1", "merchant_title": "Game 1", "ready": True,
                 "submitted": True, "post_save": "gone from feed (available=all)"},
                {"offer_id": "2", "merchant_title": "Game 2", "ready": True,
                 "submitted": False, "post_save": "still_pending", "create": {}},
            ],
        }
        fake_submitter = _fake_submitter_cls(result)
        code, out = self._run_cli(
            self._base_argv(approved, "--submit"),
            patches=(
                mock.patch.object(MOD, "WriteSubmitSession", _FakeSession),
                mock.patch.object(MOD, "Submitter", fake_submitter),
            ),
        )
        self.assertEqual(code, 0)
        # R23b (2026-07-13): no canary-of-1 default — the full approved batch,
        # which R24 makes the `safe` mode's policy (the CLI default).
        self.assertEqual(fake_submitter.run_kwargs["limit"], None)
        report = (self.run_dir / "submit_report.txt").read_text(encoding="utf-8")
        header = report.splitlines()[0]
        self.assertEqual(
            header,
            "SUBMIT — Driffle — mode=safe (full batch) — created=1, write_attempts=2, plan=2, "
            "7 offers in current feed, aborted=None, stopped=None",
        )
        self.assertIn("[CREATED (gone from feed (available=all))] 1 — Game 1", report)
        self.assertIn("[FAILED (still_pending)] 2 — Game 2", report)
        summary = json.loads(out)
        self.assertEqual(summary["created"], 1)
        self.assertEqual(summary["write_attempts"], 2)

    # -- R24: data-entry modes drive the batch size ---------------------------

    _PLAN = {
        "aborted": None, "stopped": None, "feed_offers": 7,
        "write_attempts": 1, "created": 1,
        "plan": [{"offer_id": "1", "merchant_title": "Game 1", "ready": True,
                  "submitted": True, "post_save": "gone from feed (available=all)",
                  "would_submit": "region=2 edition=1"}],
    }

    def _run_submit(self, *extra):
        approved = self._write_fixture()
        fake = _fake_submitter_cls(self._PLAN)
        code, out = self._run_cli(
            self._base_argv(approved, "--submit", *extra),
            patches=(
                mock.patch.object(MOD, "WriteSubmitSession", _FakeSession),
                mock.patch.object(MOD, "Submitter", fake),
            ),
        )
        return code, out, fake

    def test_mode_defaults_to_safe_and_submits_the_full_batch(self):
        # R24 / R23b: safe is the default and carries no canary — the validated
        # report IS the safety gate.
        code, out, fake = self._run_submit()
        self.assertEqual(code, 0)
        self.assertIsNone(fake.run_kwargs["limit"])
        summary = json.loads(out)
        self.assertEqual(summary["data_entry_mode"], "safe")
        self.assertIsNone(summary["limit"])
        header = (self.run_dir / "submit_report.txt").read_text(encoding="utf-8").splitlines()[0]
        self.assertIn("mode=safe (full batch)", header)

    def test_learning_mode_writes_but_is_capped_at_a_canary(self):
        # Romain (2026-07-13): learning is NOT read-only — "il ajoute les offres
        # si le rapport normalisé est valide" — but it stays a canary for now.
        code, out, fake = self._run_submit("--mode", "learning")
        self.assertEqual(code, 0)
        self.assertEqual(fake.run_kwargs["limit"], 1)
        summary = json.loads(out)
        self.assertEqual(summary["data_entry_mode"], "learning")
        self.assertEqual(summary["limit"], 1)
        header = (self.run_dir / "submit_report.txt").read_text(encoding="utf-8").splitlines()[0]
        self.assertIn("mode=learning (canary 1)", header)

    def test_advanced_mode_is_capped_at_a_canary_too(self):
        code, _out, fake = self._run_submit("--mode", "advanced")
        self.assertEqual(code, 0)
        self.assertEqual(fake.run_kwargs["limit"], 1)

    def test_limit_may_not_widen_a_canary_mode(self):
        # "toujours un canary pour le moment" is a cap, not a default: a --limit
        # that tries to widen it is refused, not silently clamped — and nothing
        # opens a session.
        code, _out, fake = self._run_submit("--mode", "learning", "--limit", "5")
        self.assertEqual(code, 2)
        self.assertEqual(_FakeSession.instantiated, 0)
        self.assertEqual(fake.instantiated, 0)

    def test_limit_may_narrow_the_safe_full_batch(self):
        code, _out, fake = self._run_submit("--limit", "3")
        self.assertEqual(code, 0)
        self.assertEqual(fake.run_kwargs["limit"], 3)

    def test_dry_run_rehearses_the_batch_the_mode_would_write(self):
        approved = self._write_fixture()
        fake = _fake_submitter_cls(self._PLAN)
        code, out = self._run_cli(
            self._base_argv(approved, "--mode", "learning"),
            patches=(
                mock.patch.object(MOD, "SubmitSession", _FakeSession),
                mock.patch.object(MOD, "DryRunSubmitter", fake),
            ),
        )
        self.assertEqual(code, 0)
        self.assertEqual(fake.run_kwargs["limit"], 1)
        self.assertEqual(json.loads(out)["data_entry_mode"], "learning")


class ModeLimitTests(unittest.TestCase):
    """R24 — the batch-size policy itself, independent of the CLI."""

    def test_safe_passes_the_request_through(self):
        self.assertIsNone(MOD.mode_limit("safe", None))       # full batch
        self.assertEqual(MOD.mode_limit("safe", 3), 3)

    def test_canary_modes_default_to_one(self):
        self.assertEqual(MOD.mode_limit("learning", None), 1)
        self.assertEqual(MOD.mode_limit("advanced", None), 1)

    def test_canary_modes_clamp_a_wider_request(self):
        # Defence in depth: the CLI refuses --limit > 1 outright, but the policy
        # itself can never hand back a batch wider than the cap.
        self.assertEqual(MOD.mode_limit("learning", 50), 1)
        self.assertEqual(MOD.mode_limit("advanced", 2), 1)


if __name__ == "__main__":
    unittest.main()

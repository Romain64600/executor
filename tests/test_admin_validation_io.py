import json
import tempfile
import unittest
from pathlib import Path

from src.admin.validation_io import ValidationIOError, apply_overrides_and_validate
from src.admin.runs import sha256_file
from src.validation import verify_approved_against_source

REPO_ROOT = Path(__file__).resolve().parents[1]
CLOCK = lambda: "2026-07-15T12:00:00Z"  # noqa: E731


def _cand(offer_id="1", pid="207861", region="2", edition="1", name="Bus Simulator 27"):
    return {
        "fingerprint": f"{offer_id}|{pid}|{region}|{edition}",
        "offer": {
            "offer_id": offer_id, "name": name, "url": "https://m/x", "merchant": "Driffle",
            "store_id": "127", "price": None, "stock": None,
        },
        "aks_product_id": pid, "aks_url": "https://aks/x", "aks_name": name, "platform": "STEAM",
        "region": {"label": "GLOBAL", "id": region, "implicit": False},
        "edition": {"label": "Standard", "id": edition},
    }


def _catalog():
    return {
        "ok": True,
        "offer_id": "1",
        "region_select": "offer[region]",
        "edition_select": "offer[edition]",
        "regions": {
            "master_options": [
                {"key": "1", "text": "Publisher (1)"},
                {"key": "2", "text": "Steam (2)"},
                {"key": "9", "text": "Steam EU (9)"},
            ]
        },
        "editions": {
            "master_options": [
                {"key": "1", "text": "Standard"},
                {"key": "16", "text": "DLC"},
            ]
        },
    }


class ValidationIOTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.run = root / "runs" / "20260715-000000-test"
        self.run.mkdir(parents=True)
        self.logs = root / "logs"

    def _write(self, candidates, catalog=True):
        (self.run / "candidates.json").write_text(json.dumps(candidates, indent=2), encoding="utf-8")
        if catalog:
            (self.run / "session_catalog.json").write_text(json.dumps(_catalog()), encoding="utf-8")
        return sha256_file(self.run / "candidates.json")

    def _save(self, decisions, sha, validated_by="Romain", repo_root=REPO_ROOT):
        return apply_overrides_and_validate(
            self.run,
            {"candidates_sha256": sha, "validated_by": validated_by, "decisions": decisions},
            repo_root=repo_root,
            log_dir=self.logs,
            clock=CLOCK,
        )

    def _triple(self):
        candidates = json.loads((self.run / "candidates.json").read_text(encoding="utf-8"))
        validation = json.loads((self.run / "validation.json").read_text(encoding="utf-8"))
        approved = json.loads((self.run / "approved.json").read_text(encoding="utf-8"))
        return candidates, validation, approved

    def _log_events(self):
        path = self.logs / "20260715-000000-test.jsonl"
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


class ApproveOnlyTests(ValidationIOTestCase):
    def test_happy_path_writes_consistent_triple(self):
        c1, c2, c3 = _cand("1"), _cand("2"), _cand("3")
        sha = self._write([c1, c2, c3])
        result = self._save(
            [
                {"fingerprint": c1["fingerprint"], "approve": True},
                {"fingerprint": c2["fingerprint"], "approve": True},
                {"fingerprint": c3["fingerprint"], "approve": False},
            ],
            sha,
        )
        self.assertEqual(result["approved_count"], 2)
        self.assertTrue(result["check_output"]["valid"])
        candidates, validation, approved = self._triple()
        verify_approved_against_source(
            approved, validation, candidates, expected_run_id="20260715-000000-test"
        )
        self.assertEqual(validation["validated_by"], "Romain")
        self.assertEqual(validation["validated_at"], CLOCK())
        self.assertEqual([c["offer"]["offer_id"] for c in approved], ["1", "2"])

    def test_unmentioned_candidate_defaults_to_rejected(self):
        c1, c2 = _cand("1"), _cand("2")
        sha = self._write([c1, c2])
        result = self._save([{"fingerprint": c1["fingerprint"], "approve": True}], sha)
        self.assertEqual(result["approved_count"], 1)

    def test_missing_validated_by_rejected(self):
        c1 = _cand("1")
        sha = self._write([c1])
        with self.assertRaises(ValidationIOError) as ctx:
            self._save([{"fingerprint": c1["fingerprint"], "approve": True}], sha, validated_by="  ")
        self.assertEqual(ctx.exception.code, "missing_validated_by")

    def test_sha_drift_rejected(self):
        c1 = _cand("1")
        self._write([c1])
        with self.assertRaises(ValidationIOError) as ctx:
            self._save([{"fingerprint": c1["fingerprint"], "approve": True}], "deadbeef")
        self.assertEqual(ctx.exception.code, "stale_candidates")
        self.assertFalse((self.run / "validation.json").exists())

    def test_unknown_fingerprint_rejected(self):
        c1 = _cand("1")
        sha = self._write([c1])
        with self.assertRaises(ValidationIOError) as ctx:
            self._save([{"fingerprint": "9|9|9|9", "approve": True}], sha)
        self.assertEqual(ctx.exception.code, "unknown_fingerprint")

    def test_duplicate_decision_rejected(self):
        c1 = _cand("1")
        sha = self._write([c1])
        with self.assertRaises(ValidationIOError) as ctx:
            self._save(
                [
                    {"fingerprint": c1["fingerprint"], "approve": True},
                    {"fingerprint": c1["fingerprint"], "approve": False},
                ],
                sha,
            )
        self.assertEqual(ctx.exception.code, "duplicate_decision")


class OverrideTests(ValidationIOTestCase):
    def test_override_rewrites_candidate_and_stays_green(self):
        c1 = _cand("1")
        sha = self._write([c1])
        result = self._save(
            [
                {
                    "fingerprint": c1["fingerprint"],
                    "approve": True,
                    "override": {"edition_id": "16", "region_id": "9"},
                }
            ],
            sha,
        )
        candidates, validation, approved = self._triple()
        verify_approved_against_source(
            approved, validation, candidates, expected_run_id="20260715-000000-test"
        )
        rewritten = candidates[0]
        self.assertEqual(rewritten["edition"], {"label": "DLC", "id": "16"})
        self.assertEqual(
            rewritten["region"], {"label": "Steam EU (9)", "id": "9", "implicit": False}
        )
        self.assertEqual(rewritten["fingerprint"], "1|207861|9|16")
        audit = rewritten["operator_override"]
        self.assertEqual(audit["by"], "Romain")
        self.assertEqual(audit["via"], "admin-page")
        self.assertEqual(audit["original"]["fingerprint"], "1|207861|2|1")
        self.assertEqual(audit["original"]["edition"], {"label": "Standard", "id": "1"})
        self.assertEqual(result["overrides"][0]["new_fingerprint"], "1|207861|9|16")
        # the approved entry is the rewritten candidate, audit field included
        self.assertEqual(approved[0]["operator_override"]["original"]["fingerprint"], "1|207861|2|1")

    def test_second_edit_preserves_first_original(self):
        c1 = _cand("1")
        sha = self._write([c1])
        self._save(
            [{"fingerprint": c1["fingerprint"], "approve": True, "override": {"edition_id": "16"}}],
            sha,
        )
        sha2 = sha256_file(self.run / "candidates.json")
        self._save(
            [{"fingerprint": "1|207861|2|16", "approve": True, "override": {"edition_id": "1"}}],
            sha2,
        )
        candidates, _, _ = self._triple()
        self.assertEqual(candidates[0]["edition"]["id"], "1")
        self.assertEqual(
            candidates[0]["operator_override"]["original"]["edition"],
            {"label": "Standard", "id": "1"},
        )
        self.assertEqual(
            candidates[0]["operator_override"]["original"]["fingerprint"], "1|207861|2|1"
        )

    def test_noop_override_leaves_candidate_untouched(self):
        c1 = _cand("1")
        sha = self._write([c1])
        self._save(
            [
                {
                    "fingerprint": c1["fingerprint"],
                    "approve": True,
                    "override": {"edition_id": "1", "region_id": "2", "platform": "STEAM"},
                }
            ],
            sha,
        )
        candidates, _, _ = self._triple()
        self.assertNotIn("operator_override", candidates[0])

    def test_override_without_catalog_rejected(self):
        c1 = _cand("1")
        sha = self._write([c1], catalog=False)
        with self.assertRaises(ValidationIOError) as ctx:
            self._save(
                [{"fingerprint": c1["fingerprint"], "approve": True, "override": {"edition_id": "16"}}],
                sha,
            )
        self.assertEqual(ctx.exception.code, "no_catalog")

    def test_platform_override_works_without_catalog(self):
        c1 = _cand("1")
        sha = self._write([c1], catalog=False)
        self._save(
            [{"fingerprint": c1["fingerprint"], "approve": True, "override": {"platform": "GOG"}}],
            sha,
        )
        candidates, _, _ = self._triple()
        self.assertEqual(candidates[0]["platform"], "GOG")
        # platform is not part of the fingerprint
        self.assertEqual(candidates[0]["fingerprint"], "1|207861|2|1")

    def test_unknown_platform_rejected(self):
        c1 = _cand("1")
        sha = self._write([c1])
        with self.assertRaises(ValidationIOError) as ctx:
            self._save(
                [{"fingerprint": c1["fingerprint"], "approve": True, "override": {"platform": "SWITCH"}}],
                sha,
            )
        self.assertEqual(ctx.exception.code, "bad_option")

    def test_option_not_in_catalog_rejected(self):
        c1 = _cand("1")
        sha = self._write([c1])
        with self.assertRaises(ValidationIOError) as ctx:
            self._save(
                [{"fingerprint": c1["fingerprint"], "approve": True, "override": {"edition_id": "999"}}],
                sha,
            )
        self.assertEqual(ctx.exception.code, "bad_option")

    def test_override_colliding_with_other_candidate_rejected(self):
        c1 = _cand("1", edition="1")
        c2 = _cand("1", edition="16")  # same offer, DLC edition
        sha = self._write([c1, c2])
        with self.assertRaises(ValidationIOError) as ctx:
            self._save(
                [
                    {"fingerprint": c1["fingerprint"], "approve": True},
                    {"fingerprint": c2["fingerprint"], "approve": True, "override": {"edition_id": "1"}},
                ],
                sha,
            )
        self.assertEqual(ctx.exception.code, "duplicate_fingerprint")

    def test_jsonl_audit_events_written(self):
        c1 = _cand("1")
        sha = self._write([c1])
        self._save(
            [{"fingerprint": c1["fingerprint"], "approve": True, "override": {"edition_id": "16"}}],
            sha,
        )
        events = self._log_events()
        kinds = [e["event"] for e in events]
        self.assertIn("operator_override", kinds)
        self.assertIn("validation_saved", kinds)
        override_event = next(e for e in events if e["event"] == "operator_override")
        self.assertEqual(override_event["old_fingerprint"], "1|207861|2|1")
        self.assertEqual(override_event["new_fingerprint"], "1|207861|2|16")
        saved = next(e for e in events if e["event"] == "validation_saved")
        self.assertEqual(saved["approved"], 1)
        self.assertEqual(saved["overrides"], 1)


class CheckSubprocessTests(ValidationIOTestCase):
    def test_check_failure_surfaced_and_no_stale_approved(self):
        c1 = _cand("1")
        sha = self._write([c1])
        (self.run / "approved.json").write_text("[]", encoding="utf-8")  # stale leftover
        fake_root = Path(self.tmp.name) / "fake_repo"
        (fake_root / "scripts").mkdir(parents=True)
        (fake_root / "scripts" / "04_validate.py").write_text(
            'import json, sys\nprint(json.dumps({"valid": False, "error": "boom"}))\nsys.exit(2)\n',
            encoding="utf-8",
        )
        with self.assertRaises(ValidationIOError) as ctx:
            self._save(
                [{"fingerprint": c1["fingerprint"], "approve": True}], sha, repo_root=fake_root
            )
        self.assertEqual(ctx.exception.code, "check_failed")
        self.assertEqual(ctx.exception.detail, {"valid": False, "error": "boom"})
        # the stale approved.json was dropped before the check, nothing green remains
        self.assertFalse((self.run / "approved.json").exists())


if __name__ == "__main__":
    unittest.main()

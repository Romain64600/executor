"""Lot 2 (2026-09-15) — the candidate identity is defined ONCE (``src/candidate_contract.py``).

Three guarantees, all driven by the shared examples
``tests/fixtures/candidate_contract_examples.json`` (the same file the node runner
``tests/js/candidate_contract_check.js`` feeds to the ``app.js`` port in CI):

1. the contract itself reproduces every example (fingerprint, flat targets, refusals);
2. every stage AGREES with it — ``matcher.Candidate`` built with 1 / 2 / 3 targets,
   the ``validation`` aliases, the ``submitter`` alias, ``validation_io``'s mirror;
3. the ``app.js`` mirror block is present and points at the fixture — and, since node became
   an approved TEST dependency on 2026-09-17, the runner is EXECUTED here too instead of only
   in CI, so a drifted port is caught locally and on the VPS. The text guard stays as the
   fallback wherever node is absent.
"""

from __future__ import annotations

import copy
import json
import unittest
from dataclasses import asdict
from pathlib import Path

from src import candidate_contract as contract
from src import submitter, validation
from src.admin import validation_io
from src.candidate_contract import (
    MAX_TARGETS_PER_OFFER,
    TARGET_KEYS,
    TEMPLATE_TARGET_KEYS,
    CandidateContractError,
    fingerprint,
    flatten_target,
    is_multi_target,
    normalize_targets,
    primary_target,
    template_targets,
    to_nested_target,
)
from src.contracts import NormalizedOffer
from src.matcher import Candidate, Target

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "candidate_contract_examples.json"
APP_JS = ROOT / "src" / "admin" / "static" / "app.js"
JS_CHECK = ROOT / "tests" / "js" / "candidate_contract_check.js"

CASES = json.loads(FIXTURE.read_text(encoding="utf-8"))

# Every shape the brief asked the fixture to cover — a case may not be dropped silently.
REQUIRED_CASES = {
    "pc_one_target_nested", "software_publisher_one_target", "console_one_target_88ps5h",
    "console_two_targets_ps4_ps5", "three_targets_play_anywhere",
    "old_candidates_json_without_targets", "targets_empty_list", "targets_null",
    "targets_single_empty_dict", "targets_single_string", "flat_submit_plan_shape",
    "null_region_id_is_refused", "targets0_mirror_mismatch_is_refused",
    "labels_verbatim_bom_free_and_bom",
}


def _case(name: str) -> dict:
    return next(c for c in CASES if c["name"] == name)


class FixtureShapeTests(unittest.TestCase):
    def test_fixture_covers_the_required_shapes(self):
        names = {c["name"] for c in CASES}
        self.assertEqual(len(names), len(CASES), "duplicate case names")
        self.assertTrue(REQUIRED_CASES <= names, sorted(REQUIRED_CASES - names))
        for case in CASES:
            with self.subTest(case["name"]):
                self.assertIn("candidate", case)
                self.assertTrue(("expected_fingerprint" in case) ^ ("expect_error" in case),
                                "exactly one of expected_fingerprint / expect_error")
                self.assertTrue(("expected_targets" in case) ^ ("expect_targets_error" in case),
                                "exactly one of expected_targets / expect_targets_error")


class ContractFixtureTests(unittest.TestCase):
    """The module reproduces every shared example."""

    def test_fingerprint_matches_every_example(self):
        for case in CASES:
            with self.subTest(case["name"]):
                candidate = copy.deepcopy(case["candidate"])
                if "expect_error" in case:
                    with self.assertRaises(CandidateContractError) as ctx:
                        fingerprint(candidate)
                    self.assertIn(case["expect_error"], str(ctx.exception))
                    self.assertIsInstance(ctx.exception, ValueError)
                else:
                    self.assertEqual(fingerprint(candidate), case["expected_fingerprint"])
                self.assertEqual(candidate, case["candidate"], "the contract must not mutate its input")

    def test_normalize_targets_matches_every_example(self):
        for case in CASES:
            with self.subTest(case["name"]):
                candidate = copy.deepcopy(case["candidate"])
                if "expect_targets_error" in case:
                    with self.assertRaises(CandidateContractError) as ctx:
                        normalize_targets(candidate)
                    self.assertIn(case["expect_targets_error"], str(ctx.exception))
                else:
                    targets = normalize_targets(candidate)
                    self.assertEqual(targets, case["expected_targets"])
                    for target in targets:
                        # canonical FLAT shape, canonical key order, ids as str or None
                        self.assertEqual(tuple(target), TARGET_KEYS)
                        for key in ("aks_product_id", "region_id", "edition_id"):
                            self.assertTrue(target[key] is None or isinstance(target[key], str), key)
                self.assertEqual(candidate, case["candidate"])

    def test_stored_fingerprint_key_never_read(self):
        case = _case("stored_fingerprint_key_is_ignored")
        self.assertEqual(case["candidate"]["fingerprint"], "stale|value")
        self.assertEqual(fingerprint(case["candidate"]), case["expected_fingerprint"])

    def test_mirror_check_only_applies_to_multi_target_lists(self):
        # A one-entry list is never compared with the primary (the primary wins) …
        case = _case("single_drifted_entry_defers_to_the_primary")
        self.assertEqual(fingerprint(case["candidate"]), "1|1|2|1")
        self.assertFalse(is_multi_target(case["candidate"]))
        # … while with two entries targets[0] MUST mirror the primary ids.
        case = _case("targets0_mirror_mismatch_is_refused")
        self.assertTrue(is_multi_target(case["candidate"]))
        with self.assertRaises(CandidateContractError):
            fingerprint(case["candidate"])

    def test_primary_target_and_template_projection(self):
        case = _case("console_two_targets_ps4_ps5")
        candidate = case["candidate"]
        self.assertEqual(primary_target(candidate), case["expected_targets"][0])
        self.assertEqual(template_targets(candidate), [
            {"platform": "PS4", "aks_product_id": "85104", "region_id": "88", "edition_id": "1"},
            {"platform": "PS5", "aks_product_id": "85105", "region_id": "88ps5h", "edition_id": "1"},
        ])
        for target in template_targets(candidate):
            self.assertEqual(tuple(target), TEMPLATE_TARGET_KEYS)
        # tolerant on the primary: a missing field is None (the submitter blocks it explicitly)
        self.assertEqual(primary_target({"platform": "STEAM"})["region_id"], None)
        self.assertEqual(primary_target({"region": "EU"})["region_label"], None)

    def test_nested_round_trip(self):
        for case in CASES:
            if "expected_targets" not in case:
                continue
            for flat in case["expected_targets"]:
                with self.subTest(case["name"]):
                    nested = to_nested_target(flat)
                    self.assertEqual(list(nested), ["platform", "aks_product_id", "aks_url", "aks_name", "region", "edition"])
                    self.assertEqual(flatten_target(nested), flat)

    def test_missing_primary_key_is_a_keyerror_as_before(self):
        # The safe-auto sweep relies on this (a malformed candidates.json → StageError).
        with self.assertRaises(KeyError):
            fingerprint({"offer": {"name": "no id"}})
        with self.assertRaises(KeyError):
            fingerprint({"offer": {"offer_id": "1"}, "aks_product_id": "1", "region": {"id": "2"}})

    def test_max_targets_per_offer(self):
        self.assertEqual(MAX_TARGETS_PER_OFFER, 3)
        self.assertIs(submitter.MAX_TARGETS_PER_OFFER, contract.MAX_TARGETS_PER_OFFER)


class StageAgreementTests(unittest.TestCase):
    """Every stage reads the contract — no second copy of the formula anywhere."""

    def test_validation_aliases_agree_on_every_example(self):
        for case in CASES:
            with self.subTest(case["name"]):
                candidate = copy.deepcopy(case["candidate"])
                if "expect_error" in case:
                    with self.assertRaises(validation.ValidationError) as ctx:
                        validation.candidate_fingerprint(candidate)
                    self.assertIn(case["expect_error"], str(ctx.exception))
                    self.assertIsInstance(ctx.exception.__cause__, CandidateContractError)
                else:
                    self.assertEqual(validation.candidate_fingerprint(candidate), case["expected_fingerprint"])
                if "expect_targets_error" in case:
                    with self.assertRaises(validation.ValidationError):
                        validation.candidate_targets(candidate)
                else:
                    self.assertEqual(validation.candidate_targets(candidate),
                                     [{k: t[k] for k in TEMPLATE_TARGET_KEYS} for t in case["expected_targets"]])

    def test_submitter_alias_agrees_on_every_example(self):
        for case in CASES:
            with self.subTest(case["name"]):
                candidate = copy.deepcopy(case["candidate"])
                if "expect_targets_error" in case:
                    with self.assertRaises(CandidateContractError):
                        submitter.normalize_targets(candidate)
                else:
                    self.assertEqual(submitter.normalize_targets(candidate), case["expected_targets"])
        self.assertFalse(hasattr(submitter, "_primary_target"), "the old private copy must be gone")

    def test_validation_io_mirror_uses_the_contract(self):
        candidate = copy.deepcopy(_case("pc_one_target_nested")["candidate"])
        candidate["region"] = {"label": "Steam EU (9)", "id": "9", "implicit": False}
        candidate["targets"][0]["extra_key"] = "kept"
        validation_io._mirror_primary_target(candidate)
        self.assertEqual(candidate["targets"][0], {
            "extra_key": "kept",
            **to_nested_target(primary_target(candidate)),
        })
        self.assertEqual(candidate["targets"][0]["region"], {"label": "Steam EU (9)", "id": "9"})
        self.assertEqual(fingerprint(candidate), "92015031|12345|9|1")
        self.assertIs(validation_io._is_multi_target(_case("console_two_targets_ps4_ps5")["candidate"]), True)
        self.assertIs(validation_io._is_multi_target(candidate), False)


def _offer(offer_id: str, name: str = "Hades") -> NormalizedOffer:
    return NormalizedOffer(offer_id=offer_id, merchant="Kinguin", name=name, url=f"https://m/{offer_id}")


def _target(platform: str, pid: str, region_id: str, region_label: str, edition_id: str = "1") -> Target:
    return Target(platform=platform, aks_product_id=pid, aks_url=f"https://aks/{pid}", aks_name=f"Hades {platform}",
                  region_label=region_label, region_id=region_id, edition_label="Standard", edition_id=edition_id)


def _candidate(offer_id: str, targets: tuple[Target, ...]) -> Candidate:
    first = targets[0]
    return Candidate(offer=_offer(offer_id), aks_product_id=first.aks_product_id, aks_url=first.aks_url,
                     aks_name=first.aks_name, platform=first.platform, region_label=first.region_label,
                     region_id=first.region_id, edition_label=first.edition_label, edition_id=first.edition_id,
                     region_implicit=True, targets=targets if len(targets) > 1 else ())


class MatcherAgreementTests(unittest.TestCase):
    """``matcher.Candidate.fingerprint`` IS ``candidate_contract.fingerprint(to_dict())``."""

    ONE = (_target("PS5", "85105", "88ps5h", "PS5"),)
    TWO = (_target("PS4", "85104", "88", "Playstation Game Code GLOBAL"), _target("PS5", "85105", "88ps5h", "PS5"))
    THREE = (_target("XBOX_ONE", "85102", "306", "Xbox/PC GLOBAL"), _target("XBOX_SERIES", "85103", "306", "Xbox/PC GLOBAL"),
             _target("XBOX_PC", "26712", "306", "Xbox/PC GLOBAL"))

    def test_built_candidates_agree_with_the_contract(self):
        expected = {
            1: "1|85105|88ps5h|1",
            2: "2|85104|88|1|+85105:88ps5h:1",
            3: "3|85102|306|1|+85103:306:1,26712:306:1",
        }
        for n, targets in ((1, self.ONE), (2, self.TWO), (3, self.THREE)):
            with self.subTest(targets=n):
                cand = _candidate(str(n), targets)
                d = cand.to_dict()
                self.assertEqual(cand.fingerprint, expected[n])
                self.assertEqual(fingerprint(d), cand.fingerprint)
                self.assertEqual(d["fingerprint"], cand.fingerprint)
                self.assertEqual(validation.candidate_fingerprint(d), cand.fingerprint)
                # the serialized targets ARE the canonical flat targets, nested
                self.assertEqual(normalize_targets(d), [asdict(t) for t in cand.all_targets])
                self.assertEqual(submitter.normalize_targets(d), [asdict(t) for t in cand.all_targets])
                self.assertEqual(len(d["targets"]), n)
                # JSON round trip (candidates.json) changes nothing
                self.assertEqual(fingerprint(json.loads(json.dumps(d))), cand.fingerprint)

    def test_to_dict_shape_and_key_order_are_unchanged(self):
        d = _candidate("2", self.TWO).to_dict()
        self.assertEqual(list(d), ["fingerprint", "offer", "aks_product_id", "aks_url", "aks_name",
                                   "platform", "region", "edition", "targets"])
        self.assertEqual(d["region"], {"label": "Playstation Game Code GLOBAL", "id": "88", "implicit": True})
        self.assertEqual(d["targets"][1], {
            "platform": "PS5", "aks_product_id": "85105", "aks_url": "https://aks/85105", "aks_name": "Hades PS5",
            "region": {"label": "PS5", "id": "88ps5h"}, "edition": {"label": "Standard", "id": "1"},
        })

    def test_target_to_dict_is_the_contract_nested_shape(self):
        target = self.TWO[1]
        self.assertEqual(tuple(asdict(target)), TARGET_KEYS)
        self.assertEqual(target.to_dict(), to_nested_target(asdict(target)))
        self.assertEqual(flatten_target(target.to_dict()), asdict(target))


class AppJsMirrorTests(unittest.TestCase):
    """The page's port is delimited, documented and fed by the same fixture."""

    def test_app_js_carries_the_marked_mirror_block(self):
        js = APP_JS.read_text(encoding="utf-8")
        self.assertEqual(js.count("// candidate-contract:begin"), 1)
        self.assertEqual(js.count("// candidate-contract:end"), 1)
        block = js[js.index("// candidate-contract:begin"):js.index("// candidate-contract:end")]
        self.assertIn("mirror of src/candidate_contract.py", js)
        self.assertIn("tests/fixtures/candidate_contract_examples.json", js)
        for name in ("function fp(", "function normalizeTargets(", "function primaryTarget(",
                     "function flattenTarget(", "function targetIds(", "function primaryIds("):
            self.assertIn(name, block, name)
        # the formula, verbatim, and the refusals with the Python messages
        self.assertIn("`${candidate.offer.offer_id}|${candidate.aks_product_id}|${candidate.region.id}|${candidate.edition.id}`", block)
        self.assertIn("`${primary}|+${extra}`", block)
        self.assertIn("malformed target entry (R45)", block)
        self.assertIn("targets[0] does not mirror the primary aks_product_id/region/edition (R45)", block)
        # the old ad-hoc helpers are gone
        self.assertNotIn("function targetRegion(", js)
        self.assertNotIn("function targetEdition(", js)

    def test_node_runner_exists_and_reads_the_same_fixture(self):
        js = JS_CHECK.read_text(encoding="utf-8")
        self.assertIn("candidate_contract_examples.json", js)
        self.assertIn("candidate-contract:begin", js)
        self.assertIn("src/admin/static/app.js", js)

    def test_the_app_js_port_actually_agrees_with_the_contract(self):
        """Runs the mirror check instead of merely asserting it exists. Before 2026-09-17 this
        could only happen in CI, after a push; node being an approved test dependency, a
        drifted port now fails on the developer's machine and on the VPS."""

        import shutil
        import subprocess
        node = shutil.which("node") or shutil.which("nodejs")
        if node is None:
            self.skipTest("node absent — le garde textuel ci-dessus reste le filet")
        proc = subprocess.run([node, str(JS_CHECK)], cwd=ROOT, capture_output=True,
                              text=True, timeout=120)
        self.assertEqual(proc.returncode, 0,
                         f"\n--- sortie node ---\n{proc.stdout}\n{proc.stderr}")
        self.assertIn("agrees with", proc.stdout)


if __name__ == "__main__":
    unittest.main()

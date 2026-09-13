import json
import unittest

from src.validation import (
    ValidationError,
    candidate_fingerprint,
    candidate_targets,
    load_validation,
    validation_template,
    verify_approved_against_source,
)


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


def _filled(candidates, *, run_id="r", by="Romain", at="2026-07-02T00:00:00Z", approve_all=False, entries=None):
    if entries is None:
        entries = [{"fingerprint": c["fingerprint"], "approve": approve_all} for c in candidates]
    return {"run_id": run_id, "validated_by": by, "validated_at": at, "candidates": entries}


def _target(pid, region_id, *, platform="PS5", region_label="PS5", edition_id="1"):
    """One candidates.json target (R45): nested region/edition, like the matcher writes."""
    return {
        "platform": platform, "aks_product_id": pid, "aks_url": f"https://aks/{pid}",
        "aks_name": f"Hades {platform}",
        "region": {"label": region_label, "id": region_id},
        "edition": {"label": "Standard", "id": edition_id},
    }


PS5_TARGET = _target("85105", "88ps5h")
PS4_TARGET = _target("85104", "88", platform="PS4", region_label="Playstation Game Code GLOBAL")


def _console_cand(offer_id="1", targets=None):
    """A console candidate (R45, 2026-09-12): the primary fields mirror targets[0]
    (Hades PS5 page 85105, bucket 88ps5h); default targets = PS5 + PS4."""
    if targets is None:
        targets = [PS5_TARGET, PS4_TARGET]
    first = targets[0]
    cand = _cand(offer_id, pid=first["aks_product_id"], region=first["region"]["id"],
                 edition=first["edition"]["id"], name=first["aks_name"])
    cand["platform"] = first["platform"]
    cand["region"] = {"label": first["region"]["label"], "id": first["region"]["id"], "implicit": False}
    cand["targets"] = [json.loads(json.dumps(t)) for t in targets]
    cand["fingerprint"] = candidate_fingerprint(cand)
    return cand


class TargetsFingerprintTests(unittest.TestCase):
    """R45 (2026-09-12): the fingerprint covers EVERY target; one target = unchanged."""

    def test_pre_r45_candidate_without_targets_is_unchanged(self):
        cand = _cand("1")
        del cand["fingerprint"]
        self.assertEqual(candidate_fingerprint(cand), "1|207861|2|1")

    def test_single_target_is_unchanged(self):
        cand = _console_cand("1", targets=[PS5_TARGET])
        self.assertEqual(candidate_fingerprint(cand), "1|85105|88ps5h|1")

    def test_two_targets_append_the_extra_target(self):
        self.assertEqual(candidate_fingerprint(_console_cand("1")), "1|85105|88ps5h|1|+85104:88:1")

    def test_three_targets_join_the_extras_with_commas(self):
        targets = [
            _target("26712", "306", platform="XBOX_PC", region_label="Xbox/PC GLOBAL"),
            _target("85102", "306", platform="XBOX_ONE", region_label="Xbox/PC GLOBAL"),
            _target("85103", "306", platform="XBOX_SERIES", region_label="Xbox/PC GLOBAL"),
        ]
        self.assertEqual(
            candidate_fingerprint(_console_cand("7", targets=targets)),
            "7|26712|306|1|+85102:306:1,85103:306:1",
        )

    def test_flat_target_shape_is_accepted(self):
        cand = _console_cand("1")
        cand["targets"][1] = {"platform": "PS4", "aks_product_id": "85104", "region_id": "88", "edition_id": "1"}
        self.assertEqual(candidate_fingerprint(cand), "1|85105|88ps5h|1|+85104:88:1")

    def test_a_changed_second_target_invalidates_a_stale_approval(self):
        old, new = _console_cand("1"), _console_cand("1")
        new["targets"][1]["region"]["id"] = "88eu"
        self.assertNotEqual(candidate_fingerprint(old), candidate_fingerprint(new))
        data = _filled([old], entries=[{"fingerprint": candidate_fingerprint(old), "approve": True}])
        with self.assertRaises(ValidationError):
            load_validation(data, [new], expected_run_id="r")

    def test_targets0_must_mirror_the_primary(self):
        cand = _console_cand("1")
        cand["targets"][0]["region"]["id"] = "88eu"   # contradicts the primary bucket
        with self.assertRaises(ValidationError):
            candidate_fingerprint(cand)

    def test_malformed_target_is_refused_not_guessed(self):
        cand = _console_cand("1")
        cand["targets"][1] = {"platform": "PS4"}   # no ids at all
        with self.assertRaises(ValidationError):
            candidate_fingerprint(cand)
        cand["targets"][1] = "PS4"
        with self.assertRaises(ValidationError):
            candidate_fingerprint(cand)

    def test_candidate_targets_flattens_and_defaults_to_the_primary(self):
        self.assertEqual(candidate_targets(_cand("1")), [
            {"platform": "STEAM", "aks_product_id": "207861", "region_id": "2", "edition_id": "1"},
        ])
        self.assertEqual(candidate_targets(_console_cand("2")), [
            {"platform": "PS5", "aks_product_id": "85105", "region_id": "88ps5h", "edition_id": "1"},
            {"platform": "PS4", "aks_product_id": "85104", "region_id": "88", "edition_id": "1"},
        ])

    def test_template_carries_targets(self):
        tpl = validation_template([_cand("1"), _console_cand("2")], run_id="r", clock=lambda: "t")
        self.assertEqual(tpl["candidates"][0]["targets"], [
            {"platform": "STEAM", "aks_product_id": "207861", "region_id": "2", "edition_id": "1"},
        ])
        self.assertEqual([t["platform"] for t in tpl["candidates"][1]["targets"]], ["PS5", "PS4"])
        self.assertEqual(tpl["candidates"][1]["fingerprint"], "2|85105|88ps5h|1|+85104:88:1")

    def test_multi_target_roundtrip_through_load_and_verify(self):
        cands = [_console_cand("1"), _cand("2")]
        tpl = validation_template(cands, run_id="r", clock=lambda: "t")
        tpl["validated_by"] = "Romain"
        tpl["validated_at"] = "t"
        for entry in tpl["candidates"]:
            entry["approve"] = True
        approved = load_validation(tpl, cands, expected_run_id="r")
        self.assertEqual(len(approved), 2)
        verify_approved_against_source(approved, tpl, cands, expected_run_id="r")


class TemplateTests(unittest.TestCase):
    def test_template_shape(self):
        tpl = validation_template([_cand("1"), _cand("2")], run_id="r", clock=lambda: "2026-07-02T00:00:00Z")
        self.assertEqual(tpl["run_id"], "r")
        self.assertEqual(tpl["validated_by"], "")
        self.assertEqual(len(tpl["candidates"]), 2)
        self.assertFalse(tpl["candidates"][0]["approve"])
        self.assertIn("fingerprint", tpl["candidates"][0])


class LoadValidationTests(unittest.TestCase):
    def test_happy_path_returns_approved_only(self):
        c1, c2 = _cand("1"), _cand("2")
        data = _filled(
            [c1, c2],
            entries=[
                {"fingerprint": c1["fingerprint"], "approve": True},
                {"fingerprint": c2["fingerprint"], "approve": False},
            ],
        )
        approved = load_validation(data, [c1, c2], expected_run_id="r")
        self.assertEqual([c["offer"]["offer_id"] for c in approved], ["1"])

    def test_run_id_mismatch_rejected(self):
        c1 = _cand("1")
        with self.assertRaises(ValidationError):
            load_validation(_filled([c1], run_id="other", approve_all=True), [c1], expected_run_id="r")

    def test_missing_validated_by_rejected(self):
        c1 = _cand("1")
        with self.assertRaises(ValidationError):
            load_validation(_filled([c1], by="", approve_all=True), [c1], expected_run_id="r")

    def test_missing_validated_at_rejected(self):
        c1 = _cand("1")
        with self.assertRaises(ValidationError):
            load_validation(_filled([c1], at="", approve_all=True), [c1], expected_run_id="r")

    def test_unknown_fingerprint_rejected(self):
        c1 = _cand("1")
        data = _filled([c1], entries=[{"fingerprint": "9|9|9|9", "approve": True}])
        with self.assertRaises(ValidationError):
            load_validation(data, [c1], expected_run_id="r")

    def test_stale_after_region_change_rejected(self):
        # operator approved the old fingerprint; the re-matched candidate now has region 9
        old = _cand("1", region="2")
        current = _cand("1", region="9")
        data = _filled([old], entries=[{"fingerprint": old["fingerprint"], "approve": True}])
        with self.assertRaises(ValidationError):
            load_validation(data, [current], expected_run_id="r")


class VerifyApprovedTests(unittest.TestCase):
    """Submit-time re-verification (Romain's audit P1, 2026-07-08): approved.json
    must equal the re-derivation from candidates.json + validation.json."""

    def _setup(self):
        c1, c2 = _cand("1"), _cand("2")
        data = _filled(
            [c1, c2],
            entries=[
                {"fingerprint": c1["fingerprint"], "approve": True},
                {"fingerprint": c2["fingerprint"], "approve": False},
            ],
        )
        return c1, c2, data

    def test_matching_approved_passes(self):
        c1, c2, data = self._setup()
        verify_approved_against_source([c1], data, [c1, c2], expected_run_id="r")

    def test_fabricated_extra_offer_rejected(self):
        # approved.json smuggles in the offer the operator did NOT approve
        c1, c2, data = self._setup()
        with self.assertRaises(ValidationError):
            verify_approved_against_source([c1, c2], data, [c1, c2], expected_run_id="r")

    def test_hand_edited_field_rejected(self):
        # fingerprint fields intact, but a payload field was edited after check
        c1, c2, data = self._setup()
        tampered = json.loads(json.dumps(c1))
        tampered["aks_url"] = "https://aks/other"
        with self.assertRaises(ValidationError):
            verify_approved_against_source([tampered], data, [c1, c2], expected_run_id="r")

    def test_underlying_validation_errors_propagate(self):
        c1, c2, data = self._setup()
        data["validated_by"] = ""
        with self.assertRaises(ValidationError):
            verify_approved_against_source([c1], data, [c1, c2], expected_run_id="r")

    def test_run_id_mismatch_rejected(self):
        c1, c2, data = self._setup()
        with self.assertRaises(ValidationError):
            verify_approved_against_source([c1], data, [c1, c2], expected_run_id="other")

    def test_approve_none_is_valid_and_empty(self):
        c1 = _cand("1")
        self.assertEqual(load_validation(_filled([c1], approve_all=False), [c1], expected_run_id="r"), [])

    def test_template_then_load_roundtrip(self):
        cands = [_cand("1"), _cand("2")]
        tpl = validation_template(cands, run_id="r", clock=lambda: "t")
        tpl["validated_by"] = "Romain"
        tpl["validated_at"] = "2026-07-02T00:00:00Z"
        for entry in tpl["candidates"]:
            entry["approve"] = True
        approved = load_validation(tpl, cands, expected_run_id="r")
        self.assertEqual(len(approved), 2)


class RobustnessTests(unittest.TestCase):
    def test_works_on_candidates_without_a_stored_fingerprint(self):
        cand = _cand("1")
        del cand["fingerprint"]  # simulate a candidates.json from before the field existed
        tpl = validation_template([cand], run_id="r", clock=lambda: "t")
        fingerprint = tpl["candidates"][0]["fingerprint"]
        data = {
            "run_id": "r", "validated_by": "R", "validated_at": "t",
            "candidates": [{"fingerprint": fingerprint, "approve": True}],
        }
        approved = load_validation(data, [cand], expected_run_id="r")
        self.assertEqual(len(approved), 1)


if __name__ == "__main__":
    unittest.main()

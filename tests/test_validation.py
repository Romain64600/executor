import unittest

from src.validation import ValidationError, load_validation, validation_template


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


if __name__ == "__main__":
    unittest.main()

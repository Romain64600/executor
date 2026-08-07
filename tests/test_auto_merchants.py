import unittest

from src.admin.auto_merchants import (
    AUTO_MERCHANTS,
    allowed_list,
    is_allowed,
    rejection_reason,
)


class AutoMerchantsAllowlistTests(unittest.TestCase):
    def test_suggested_merchant_with_canonical_store_is_allowed(self):
        self.assertIsNone(rejection_reason("Kinguin", "58"))
        self.assertTrue(is_allowed("Kinguin", "58"))

    def test_case_and_whitespace_insensitive_name(self):
        # The picker sends the exact name, but a hand-crafted request may vary
        # case/spacing — the name match tolerates it (store must still match).
        self.assertTrue(is_allowed("  kinguin ", "58"))
        self.assertTrue(is_allowed("CJS-CDKEYS", "30"))

    def test_unknown_merchant_refused(self):
        reason = rejection_reason("Bogus", "999")
        self.assertIsNotNone(reason)
        self.assertIn("Bogus", reason)
        self.assertFalse(is_allowed("Bogus", "999"))

    def test_parked_and_unvetted_merchants_refused(self):
        # Explicitly outside the allowlist (Romain 2026-08-07).
        self.assertFalse(is_allowed("Difmark", "167"))
        self.assertFalse(is_allowed("Gameboost", "157"))

    def test_store_must_match_canonical(self):
        # A suggested name with a tampered/stale store is refused (the UI derives
        # the store, so a mismatch means the request didn't come from the picker).
        reason = rejection_reason("Kinguin", "999")
        self.assertIsNotNone(reason)
        self.assertIn("58", reason)

    def test_empty_inputs_refused(self):
        self.assertFalse(is_allowed("", ""))
        self.assertFalse(is_allowed("Kinguin", ""))

    def test_allowed_list_shape_and_membership(self):
        rows = allowed_list()
        self.assertEqual(len(rows), len(AUTO_MERCHANTS))
        names = {r["name"] for r in rows}
        self.assertIn("Kinguin", names)
        self.assertNotIn("Difmark", names)
        self.assertNotIn("Gameboost", names)
        for r in rows:
            self.assertEqual(set(r), {"name", "store_id"})
            self.assertRegex(r["store_id"], r"^\d+$")


if __name__ == "__main__":
    unittest.main()

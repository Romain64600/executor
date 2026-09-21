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
        # Wyrel (162) tient le rôle du marchand hors liste : « supervisé d'abord »
        # (docs/MERCHANTS.md), jamais allowlisté. Deux boutiques ont fait le chemin inverse
        # après leur première saisie réelle : GameBoost le 2026-09-16 (« Ajoute Gameboost a la
        # whiteliste », 207 candidats sur 992 lignes, zéro PUBLISHER) et **Difmark le
        # 2026-09-21** (« Ajouter difmark a la whitelist », 10 comptes Steam créés et prouvés
        # sur 13 candidats) — leur refus n'est donc plus ce que ce test épingle.
        self.assertFalse(is_allowed("Wyrel", "162"))
        self.assertTrue(is_allowed("GameBoost", "157"))
        self.assertTrue(is_allowed("Difmark", "167"))
        # une boutique jamais vettée reste refusée, quelle que soit son orthographe
        self.assertFalse(is_allowed("Royalcdkeys", "85"))
        self.assertFalse(is_allowed("Keycense", "130"))

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
        self.assertIn("Difmark", names)          # 2026-09-21
        self.assertNotIn("Wyrel", names)         # supervisé, hors liste
        # MMOGA (Romain 2026-09-10): allowed with its FEED store id only — the AKS page
        # merchant id (40) is not a store and must be refused like any tampered id.
        self.assertIn("MMOGA", names)
        self.assertIsNone(rejection_reason("MMOGA", "12"))
        self.assertIsNone(rejection_reason("mmoga", "12"))
        self.assertIsNotNone(rejection_reason("MMOGA", "40"))
        for r in rows:
            self.assertEqual(set(r), {"name", "store_id"})
            self.assertRegex(r["store_id"], r"^\d+$")


if __name__ == "__main__":
    unittest.main()

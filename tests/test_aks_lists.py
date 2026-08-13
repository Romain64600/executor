import unittest

from src.aks_lists import (
    LISTS,
    PENDING_LIST_ID,
    label_for,
    suggest_target_list,
    year_in_name,
)


class AksListsTests(unittest.TestCase):
    def test_software_maps_to_softwares(self):
        self.assertEqual(suggest_target_list("skip category: SOFTWARE"), "16")
        self.assertEqual(
            suggest_target_list("skip category: IOBIT (software/app, not a game)"), "16")

    def test_gift_card_and_account(self):
        self.assertEqual(suggest_target_list("skip category: GIFT CARD"), "21")
        self.assertEqual(suggest_target_list("difmark account offer"), "30")

    def test_skins_soundtracks_artbooks_to_blacklist(self):
        # Romain 2026-07-23: these categories route to Blacklist (8)
        for reason in ("skip category: SKIN (no bundles/skins)",
                       "skip category: MINIMAL WEAR (no bundles/skins)",
                       "skip category: SOUNDTRACK (non-game content)",
                       "skip category: ARTBOOK (non-game content)",
                       "skip category: DIGITAL BOOK (non-game content)",
                       "skip category: RANDOM (random/lootbox, not a game)"):
            self.assertEqual(suggest_target_list(reason), "8", reason)

    def test_bundle_not_blacklisted(self):
        # a bundle shares the "(no bundles/skins)" suffix but is NOT auto-blacklisted
        self.assertIsNone(suggest_target_list("skip category: BUNDLE (no bundles/skins)"))
        self.assertIsNone(suggest_target_list("possible multi-game bundle"))

    def test_forbidden_region_only_the_five_with_a_list(self):
        self.assertEqual(suggest_target_list("forbidden region: AUSTRALIA"), "32")
        self.assertEqual(suggest_target_list("forbidden region: SOUTH AMERICA"), "36")
        # regions without a list AND not blacklisted fall through to garder (None).
        # NB: KOREA is now blacklisted (Romain 2026-08-13, Asia) → see the region-
        # blacklist tests; use plain garder regions here.
        self.assertIsNone(suggest_target_list("forbidden region: NORTH AMERICA"))
        self.assertIsNone(suggest_target_list("forbidden region: ROW"))
        self.assertIsNone(suggest_target_list("forbidden region: TURKEY"))

    def test_ambiguous_reasons_have_no_suggestion(self):
        for reason in ("console", "possible multi-game bundle",
                       "skip category: COINS", "no AKS product page found (slug not 200)",
                       "DLC in title", ""):
            self.assertIsNone(suggest_target_list(reason), reason)

    def test_slug_tokens_never_suggest(self):
        # audit L8: category anchoring — free tokens of the reason (slugs,
        # hyphenated forms) must not trigger a list.
        for reason in ("no AKS steam-account product page found",
                       "no AKS software-inc product page found",
                       "skip category: STEAM PLAYER TRADE (account-bound)"):
            self.assertIsNone(suggest_target_list(reason), reason)

    def test_year_hint(self):
        self.assertEqual(year_in_name("Bus-Simulator 2012 Steam Gift GLOBAL"), "2012")
        self.assertEqual(year_in_name("Some Game 1998"), "1998")
        self.assertIsNone(year_in_name("Just Cause Pack Steam Gift GLOBAL"))

    def test_label_for(self):
        self.assertEqual(label_for("16"), "Softwares")
        self.assertEqual(label_for(PENDING_LIST_ID), "")  # source list not in catalog

    def test_catalog_is_deduped_and_excludes_source_and_delete(self):
        ids = [x["id"] for x in LISTS]
        self.assertEqual(len(ids), len(set(ids)))  # no dup ids
        self.assertNotIn(PENDING_LIST_ID, ids)     # don't offer "move to 9" (self)
        self.assertNotIn("delete", ids)            # delete is out of scope
        for row in LISTS:
            self.assertTrue(row["id"] and row["label"])


if __name__ == "__main__":
    unittest.main()

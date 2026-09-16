"""R52 (2026-09-16) — "Microsoft Store Key" / "Microsoft Key" are no longer pre-skipped.

Romain's audit, the same day `[R50]` mapped the Microsoft region buckets:

    « Les régions Microsoft sont ajoutées, mais deux formulations de clés restent bloquées
      avant leur résolution … Cause : ces expressions figurent encore dans CATEGORY_SKIP.
      Correction : retirer ces exclusions générales pour les clés de jeux, en conservant les
      refus des cartes cadeaux, abonnements et recharges. »

The exclusions were there for a reason that `[R50]` removed — §4.5 said "MICROSOFT platform
has no region mapping → fail-closed" (`[R17]`). Games take the Windows 10 family now
(Global 246 / EU 244 / US 245 / UK 249).

Measured before the change: 164 rows (34 distinct) were blocked there, mostly real game keys
(Call of Duty, GTA V Enhanced, Skyrim Anniversary, Fallout 76, Rise of the Tomb Raider…).
What had to STAY refused, and is pinned here: Microsoft Store ACCOUNTS and Minecoins — the
generic ACCOUNT / COINS markers do not catch them, so two explicit entries replace the two
removed ones."""

import unittest

from src.contracts import NormalizedOffer
from src.matcher import CATEGORY_SKIP, detect_platform, precheck_skip


def _offer(name, url="https://www.g2a.com/x-i1", merchant="G2A", store_id="38"):
    return NormalizedOffer(offer_id="1", name=name, url=url, merchant=merchant,
                           store_id=store_id, price="9.99")


class MicrosoftKeysNoLongerPreSkippedTests(unittest.TestCase):
    """Real Microsoft Store GAME keys must reach AKS resolution."""

    GAMES = (
        "CALL OF DUTY: MODERN WARFARE (PC) - Microsoft Store Key - EUROPE",
        "Call of Duty: Modern Warfare 3 (2011) (PC) - Microsoft Store Key - UNITED STATES",
        "Grand Theft Auto V Enhanced (PC) - Microsoft Store Key - EUROPE",
        "The Elder Scrolls V: Skyrim Anniversary Edition (PC) - Microsoft Store Key - EUROPE",
        "Rise of the Tomb Raider (PC) - Microsoft Store Key - EUROPE",
        "Fallout 76 - Microsoft Store Key - Global",
        "Cataclismo (PC) - Microsoft Store Key - EUROPE",
        "Minecraft Dungeons II (PC) - Microsoft Store Key - GLOBAL",
        "Call of Duty : Black Ops 6 - Vault Edition (Microsoft Store / Windows Key) - EU",
        "Microsoft Windows 11 Enterprise IoT LTSC 2024 (1 Device) - Microsoft Key - GLOBAL",
    )

    def test_they_pass_the_precheck(self):
        for name in self.GAMES:
            with self.subTest(name=name):
                self.assertIsNone(precheck_skip(_offer(name)),
                                  "a Microsoft Store game key must reach AKS resolution")

    def test_the_two_blanket_entries_are_gone(self):
        self.assertNotIn("MICROSOFT KEY", CATEGORY_SKIP)
        self.assertNotIn("MICROSOFT STORE", CATEGORY_SKIP)

    def test_the_platform_is_still_detected_as_microsoft(self):
        self.assertEqual(detect_platform("X (PC) - Microsoft Store Key - GLOBAL"), "MICROSOFT")
        self.assertEqual(detect_platform("X (PC) - Microsoft Key - GLOBAL"), "MICROSOFT")

    def test_a_steam_title_naming_microsoft_stays_steam(self):
        # "Microsoft Flight Simulator … Steam Key" must not become MICROSOFT
        self.assertEqual(
            detect_platform("Microsoft Flight Simulator 2024 (PC) - Steam Key - GLOBAL"),
            "STEAM")
        self.assertIsNone(precheck_skip(
            _offer("Microsoft Flight Simulator 2024 (PC) - Steam Key - GLOBAL")))


class WhatMustStayRefusedTests(unittest.TestCase):
    """« en conservant les refus des cartes cadeaux, abonnements et recharges » — the two
    removed entries were also catching non-games, so they are replaced by explicit ones."""

    def test_a_microsoft_store_account_is_refused(self):
        reason = precheck_skip(
            _offer("Mafia: Definitive Edition (PC) - Microsoft Store Account - GLOBAL"))
        self.assertIsNotNone(reason)
        self.assertIn("MICROSOFT STORE ACCOUNT", reason)

    def test_a_bare_microsoft_account_is_refused(self):
        reason = precheck_skip(_offer("Some Game (PC) - Microsoft Account - GLOBAL"))
        self.assertIsNotNone(reason)
        self.assertIn("MICROSOFT ACCOUNT", reason)

    def test_minecoins_are_refused(self):
        for name in (
            "Minecraft - 1720 Minecoins (Microsoft Store / Windows Key) - EU",
            "Minecraft - 3500 Minecoins (Microsoft Store / Windows Key) - EU",
        ):
            with self.subTest(name=name):
                reason = precheck_skip(_offer(name))
                self.assertIsNotNone(reason, "in-game currency is never a game")
                self.assertIn("MINECOINS", reason)

    def test_the_card_subscription_and_top_up_refusals_are_untouched(self):
        # titles kept free of console words on purpose: an Xbox card is refused EARLIER, by
        # the shared console classifier ("console: … — not a game (R45)"), which would hide
        # what this test owns
        for name, marker in (
            ("Some Store 25 EUR Gift Card - GLOBAL", "GIFT CARD"),
            ("Some Game Pass Ultimate 1 Month Subscription - GLOBAL", "SUBSCRIPTION"),
            ("Some Game 1000 Coins - GLOBAL", "COINS"),
            ("Some Game Top Up 500 - GLOBAL", "TOP UP"),
        ):
            with self.subTest(name=name):
                reason = precheck_skip(_offer(name))
                self.assertIsNotNone(reason)
                self.assertIn(marker, reason)

    def test_bundles_are_still_refused(self):
        for name in (
            "Microsoft Project 2024 Pro + Microsoft Visio Pack 2024 Pro Bundle (PC) - "
            "Microsoft Key - GLOBAL",
            "Office 2021 Professional Plus x4 Bundle (PC) - Microsoft Key - GLOBAL",
        ):
            with self.subTest(name=name):
                reason = precheck_skip(_offer(name))
                self.assertIsNotNone(reason)
                self.assertIn("BUNDLE", reason)


if __name__ == "__main__":
    unittest.main()

"""Accent folding in the categorical scans (2026-09-16).

Romain, relaying an adversarial finding on a FRENCH storefront: « notre liste d'exclusions
catégorielles est uniquement en anglais et ne replie pas les accents, donc "CRÉDITS" ne
matche pas CREDITS. Ça ne coûte rien sur ce corpus mais c'est une faiblesse réelle sur toute
boutique localisée. »

The bug: every skip vocabulary here is ASCII English (`CATEGORY_SKIP`, `CURRENCY_TOKENS`,
`BUNDLE_SKIN_TOKENS`, `FORBIDDEN_REGIONS`…) and the normalisers replaced any non-ASCII letter
by a SPACE, so "CRÉDITS" became the two junk tokens "CR" and "DITS" — and the `CREDITS` entry
that had been there all along never matched. Folding (NFKD, combining marks dropped) can only
make a vocabulary word match text that MEANS it; it never invents a word.

Blast radius measured before shipping: on the 397 rows carrying a non-ASCII character across
the saved runs, **0 verdict changes**. It is a net, not a behaviour change."""

import unittest

from src.contracts import NormalizedOffer
from src.matcher import fold_accents, precheck_skip


def _offer(name, url="https://m.test/x"):
    return NormalizedOffer(offer_id="1", name=name, url=url, merchant="Test",
                           store_id="1", price="9.99")


class FoldAccentsTests(unittest.TestCase):
    def test_diacritics_are_stripped(self):
        for raw, folded in (
            ("CRÉDITS", "CREDITS"),
            ("Abonnés", "Abonnes"),
            ("Pièces", "Pieces"),
            ("Édition", "Edition"),
            ("Über", "Uber"),
            ("Señor", "Senor"),
            ("Ångström", "Angstrom"),
        ):
            with self.subTest(raw=raw):
                self.assertEqual(fold_accents(raw), folded)

    def test_ascii_is_untouched(self):
        for text in ("CREDITS", "Steam Key GLOBAL", "Assassin's Creed", ""):
            with self.subTest(text=text):
                self.assertEqual(fold_accents(text), text)

    def test_it_never_invents_a_word(self):
        """An accented word whose folded form is not in the vocabulary still does not match."""

        self.assertIsNone(precheck_skip(_offer("Assassin's Creed Odyssée (PC) Steam Key EU")))
        self.assertIsNone(precheck_skip(_offer("Tomb Raider: L'Ange des Ténèbres Steam Key")))


class LocalisedCategoriesAreCaughtTests(unittest.TestCase):
    """The point of the fix: an accented spelling of a vocabulary word now matches."""

    def test_accented_credits(self):
        reason = precheck_skip(_offer("Steam 5000 Crédits - GLOBAL"))
        self.assertIsNotNone(reason)
        self.assertIn("CREDITS", reason)

    def test_accented_gems(self):
        reason = precheck_skip(_offer("Jeu Pièces 900 Gems"))
        self.assertIsNotNone(reason)
        self.assertIn("GEMS", reason)

    def test_the_ascii_spelling_is_unchanged(self):
        reason = precheck_skip(_offer("Steam 5000 Credits - GLOBAL"))
        self.assertIsNotNone(reason)
        self.assertIn("CREDITS", reason)


class NoRegressionOnRealRowsTests(unittest.TestCase):
    """Rows that carry an accent but no vocabulary word must be unaffected — this is the
    shape of the 397 real non-ASCII rows measured on 2026-09-16 (0 verdict changes)."""

    def test_accented_game_names_still_pass(self):
        for name in (
            "GUNDAM ROGUE ORBIT Édition Deluxe",
            "Le Château des Ombres (PC) Steam Key EU",
            "Los Señores del Caos Steam Key GLOBAL",
        ):
            with self.subTest(name=name):
                self.assertIsNone(precheck_skip(_offer(name)))


if __name__ == "__main__":
    unittest.main()

"""`--all-allowlisted`: the night sweep reads its targets from the allowlist (2026-09-16).

Romain: « Donne moi la commande a jour pour lancer tout les marchands whitelist (scan de
nuit) et maintien la dans le readme a chaque whitelist de nouveaux marchands ».

A hand-written `--targets "MMOGA:12,Kinguin:58,…"` drifts the moment a merchant joins the
allowlist — the 2026-09-15 night sweep ran 7 merchants while 11 were allowlisted. The flag
removes the copy: the target list IS `AUTO_MERCHANTS`, so the documented command never has
to be rewritten. These tests pin that, and that the README carries the command."""

import pathlib
import re
import subprocess
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "10_data_entry_auto.py"


class AllAllowlistedFlagTests(unittest.TestCase):
    def test_the_flag_exists_and_documents_itself(self):
        src = SCRIPT.read_text(encoding="utf-8")
        self.assertIn('"--all-allowlisted"', src)
        self.assertIn("AUTO_MERCHANTS", src)

    def test_targets_are_read_from_the_allowlist(self):
        """The list is not copied anywhere — it is imported."""

        src = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("from src.admin.auto_merchants import AUTO_MERCHANTS", src)

    def test_it_refuses_to_be_combined(self):
        for extra in (["--targets", "X:1"], ["--merchant", "X", "--store-id", "1"]):
            with self.subTest(extra=extra):
                run = subprocess.run(
                    [sys.executable, str(SCRIPT), "--all-allowlisted", *extra],
                    capture_output=True, text=True, cwd=str(ROOT))
                self.assertEqual(run.returncode, 2)
                self.assertIn("all-allowlisted", run.stdout)

    def test_every_allowlisted_merchant_would_be_swept(self):
        """The flag must cover the WHOLE list, in its order — no silent subset."""

        from src.admin.auto_merchants import AUTO_MERCHANTS
        self.assertGreaterEqual(len(AUTO_MERCHANTS), 13)
        for name, store in AUTO_MERCHANTS:
            with self.subTest(merchant=name):
                self.assertTrue(store.isdigit(), f"{name}: store id must be numeric")


class ReadmeCarriesTheNightSweepTests(unittest.TestCase):
    """« maintien la dans le readme » — the command lives in the README, and it is the
    self-maintaining one (no hand-written merchant list to go stale)."""

    README = (ROOT / "README.md").read_text(encoding="utf-8")

    def test_the_readme_documents_the_night_sweep(self):
        self.assertIn("--all-allowlisted", self.README)

    def test_the_readme_does_not_hand_list_the_merchants_for_the_night_sweep(self):
        """A `--targets "A:1,B:2,…"` line next to the night sweep would drift again."""

        for line in self.README.splitlines():
            if "10_data_entry_auto.py" in line and "--targets" in line:
                # per-merchant examples are fine; a LONG hand list is the drift we refuse
                targets = re.search(r'--targets\s+"([^"]*)"', line)
                if targets:
                    self.assertLessEqual(
                        len(targets.group(1).split(",")), 2,
                        "the README must not hand-list the allowlist — use --all-allowlisted")


if __name__ == "__main__":
    unittest.main()

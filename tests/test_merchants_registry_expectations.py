"""Registry expectations (2026-09-14, Romain's rule R32 / R45): EVERY merchant of the
safe-auto allowlist has its file and the registry maps its name to that file's CONFIG.

This test is written by agent M2 against the registry the integrator wires (agent M1 /
integrator: ``src/merchants/registry.py`` today, ``src.matcher.merchant_config`` re-exported).
It FAILS until the six new entries are wired — that is the point: an allowlisted merchant
whose config is not reachable through ``merchant_config(name)`` is the omission Romain
refused."""

import pathlib
import unittest

from src.admin.auto_merchants import AUTO_MERCHANTS

try:
    from src.merchants.registry import merchant_config
except ImportError:  # pragma: no cover — the registry not relocated yet
    from src.matcher import merchant_config

MERCHANTS_DIR = pathlib.Path(__file__).resolve().parent.parent / "src" / "merchants"

# allowlist spelling (auto_merchants.py) → module file
EXPECTED_MODULE = {
    "Kinguin": "kinguin.py",
    "G2A": "g2a.py",
    "Driffle": "driffle.py",
    "Eneba": "eneba.py",
    "K4G": "k4g.py",
    "Gamivo": "gamivo.py",
    "Instant Gaming": "instant_gaming.py",
    "CJS-CDKeys": "cjs.py",
    "Allyouplay": "allyouplay.py",
    "GameSeal": "gameseal.py",
    "MMOGA": "mmoga.py",
    # allowlistés le 2026-09-16 (Romain : « On va whitelist Eletronicfirst et Gamersoutlet »)
    "Electronicfirst": "electronicfirst.py",
    "GamersOutlet": "gamersoutlet.py",
    "GameBoost": "gameboost.py",
    "Gamerall": "gamerall.py",      # liste blanche le 2026-09-19 (Romain)
    "Difmark": "difmark.py",        # liste blanche le 2026-09-21 (Romain), après sa 1re
                                    # saisie réelle : 10 comptes Steam créés et prouvés
    "GOG": "gog.py",                # liste blanche le 2026-09-22 (Romain : « on peut prendre
                                    # le titre en complément d'information. Testons sur une
                                    # page. »), après l'audit du même jour
    "Wyrel": "wyrel.py",            # liste blanche le 2026-09-24 (Romain : « Go Wyrel, … puis
                                    # whitelist ce marchand »)
}


class RegistryExpectationsTests(unittest.TestCase):
    def test_every_allowlisted_merchant_has_a_module_file(self):
        for name, _store in AUTO_MERCHANTS:
            with self.subTest(merchant=name):
                self.assertIn(name, EXPECTED_MODULE, f"{name}: no module file expected — add it")
                self.assertTrue((MERCHANTS_DIR / EXPECTED_MODULE[name]).is_file(), EXPECTED_MODULE[name])

    def test_every_allowlisted_merchant_is_registered(self):
        for name, _store in AUTO_MERCHANTS:
            with self.subTest(merchant=name):
                cfg = merchant_config(name)
                self.assertIsNotNone(cfg, f"merchant_config({name!r}) is None — wire the registry")
                self.assertEqual(cfg.name.casefold(), name.casefold())

    def test_registered_config_is_the_module_config(self):
        import importlib
        for name, filename in EXPECTED_MODULE.items():
            with self.subTest(merchant=name):
                mod = importlib.import_module("src.merchants." + filename[:-3])
                self.assertIs(merchant_config(name), mod.CONFIG, f"{name}: registry entry is not {filename}'s CONFIG")

    def test_spellings(self):
        # the registry is case / whitespace-insensitive; both allowlist and short spellings resolve
        self.assertIs(merchant_config("instant gaming"), merchant_config("Instant Gaming"))
        self.assertIs(merchant_config(" KINGUIN "), merchant_config("Kinguin"))
        self.assertIsNotNone(merchant_config("CJS-CDKeys"))
        self.assertIsNotNone(merchant_config("cjs-cdkeys"))

    def test_parked_difmark_stays_registered(self):
        from src.merchants import difmark
        self.assertTrue((MERCHANTS_DIR / "difmark.py").is_file())
        self.assertIs(merchant_config("Difmark"), difmark.CONFIG)


if __name__ == "__main__":
    unittest.main()

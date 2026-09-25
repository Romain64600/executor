"""Loaded, ex-CDKeys (feed store 40) — `[R61]`, 2026-09-25, src/merchants/loaded.py.

Romain : « Pars sur CDKeys (nouveau nom du marchand est LOADED) » ; « 1. Europe 2. comme Kinguin
et MMOGA en global » — « (Europe & UK) » est l'Europe, une ligne sans région est GLOBAL.
Les lignes sont celles du feed réel (scan du 21/09)."""

import unittest

from src.console_keys import classify_console
from src.contracts import NormalizedOffer
from src.matcher import precheck_skip
from src.merchants import loaded as L
from src.merchants.registry import merchant_config, merchant_for_store


def _aff(slug):
    return f"https://go.loaded.com/c/1297091/2640470/18216?u=https://www.loaded.com/{slug}"


def _offre(nom, slug):
    return NormalizedOffer(offer_id="1", name=nom, url=_aff(slug), merchant="Loaded", store_id="40")


class LaRegionEstLaParentheseFinale(unittest.TestCase):
    def test_les_decisions_de_romain(self):
        for nom, attendu in (
            ("Attack on Titan 3 / A.O.T. 3 + Pre-order Bonus PC (Europe & UK)", "eu"),   # décision 1
            ("Red Dead Redemption 2: Ultimate Edition Xbox (WW)", "global"),
            ("Zero Caliber 2 Remastered PC", None),        # pas de région → GLOBAL implicite (décision 2)
            ("Old School RuneScape 12-Month Membership + OST PC - DLC", None),
        ):
            with self.subTest(nom):
                self.assertEqual(L.title_region(nom), attendu)

    def test_sans_region_le_matcher_met_global_comme_kinguin_et_mmoga(self):
        from src.matcher import detect_region
        o = _offre("Zero Caliber 2 Remastered PC", "zero-caliber-2-remastered-pc-steam")
        self.assertEqual(detect_region(o, "STEAM")[:2], ("GLOBAL", "2"))

    def test_europe_et_uk_entre_en_steam_eu(self):
        from src.matcher import detect_region
        o = _offre("Attack on Titan 3 / A.O.T. 3 PC (Europe & UK)", "attack-on-titan-3-a-o-t-3-pc-steam-eu")
        self.assertEqual(detect_region(o, "STEAM")[:2], ("EU", "9"))

    def test_north_america_et_region_inconnue_sont_refusees(self):
        na = _offre("Attack on Titan 3 / A.O.T. 3 PC (North America)", "attack-on-titan-3-a-o-t-3-pc-steam-na")
        self.assertEqual(precheck_skip(na, consoles=True), "forbidden region: NORTH AMERICA")
        inconnue = L.precheck("Some Game PC (Moonbase)", _aff("some-game-pc-steam-mb"))
        self.assertIn("Moonbase", inconnue)
        self.assertIn("R61", inconnue)


class LeLienDAffiliationCacheLaFiche(unittest.TestCase):
    def test_la_boutique_pc_vient_du_slug_de_la_fiche(self):
        for slug, attendu in (("attack-on-titan-3-a-o-t-3-pc-steam-eu", "STEAM"),
                              ("zero-caliber-2-remastered-pc-steam", "STEAM"),
                              ("old-school-runescape-12-month-membership-ost-pc-dlc-steam", "STEAM"),
                              ("some-game-pc-epic-eu", "EPIC"),
                              ("towerborne-xbox-series-x-s-pc-eu", None)):
            with self.subTest(slug):
                self.assertEqual(L.url_platform(_aff(slug)), attendu)

    def test_un_lien_sans_fiche_est_refuse(self):
        self.assertIn("paramètre u absent",
                      L.precheck("Zero Caliber 2 Remastered PC", "https://go.loaded.com/c/1297091/2640470/18216"))


class LeNomSansPlateformeNiRegion(unittest.TestCase):
    def test_resolve_name(self):
        for nom, attendu in (
            ("Zero Caliber 2 Remastered PC", "Zero Caliber 2 Remastered"),
            ("Towerborne Xbox/PC (Europe & UK)", "Towerborne"),
            ("METAL GEAR SOLID - Master Collection Version Xbox Series X|S (Europe & UK)",
             "METAL GEAR SOLID - Master Collection Version"),
            ("Super Mario Galaxy 2 Switch & Switch 2 (Europe & UK)", "Super Mario Galaxy 2"),
            ("Old School RuneScape 12-Month Membership + OST PC - DLC",
             "Old School RuneScape 12-Month Membership + OST"),
        ):
            with self.subTest(nom):
                self.assertEqual(L.resolve_name(nom), attendu)

    def test_le_dlc_du_marchand_reste_un_marqueur_pour_les_gardes(self):
        self.assertEqual(L.guard_name("Some Pack PC - DLC"), "Some Pack (DLC)")


class LesConsoles(unittest.TestCase):
    def test_xbox_pc_lit_la_generation_dans_le_slug(self):
        sig = classify_console("Towerborne Xbox/PC (Europe & UK)",
                               _aff("towerborne-xbox-series-x-s-pc-eu"), "Loaded")
        self.assertEqual((sig.families, sig.pc_declared, sig.region_base), (("XBOX_SERIES",), True, "eu"))

    def test_sans_generation_nulle_part_le_refus_d_avant(self):
        sig = classify_console("Kingdom Rush Frontiers Xbox/PC (Europe & UK)",
                               _aff("kingdom-rush-frontiers-xbox-pc-eu"), "Loaded")
        self.assertIn("no declared generation", sig.skip_reason)

    def test_europe_et_uk_est_l_europe_cote_console(self):
        sig = classify_console("METAL GEAR SOLID - Master Collection Version Xbox Series X|S (Europe & UK)",
                               _aff("metal-gear-solid-master-collection-version-xbox-series-x-s-eu"), "Loaded")
        self.assertEqual(sig.region_base, "eu")


class Registre(unittest.TestCase):
    def test_le_store_40_est_loaded(self):
        self.assertEqual(merchant_for_store("40"), "Loaded")
        self.assertIs(merchant_config("Loaded"), L.CONFIG)

    def test_pas_encore_en_liste_blanche(self):
        from src.admin.auto_merchants import AUTO_MERCHANTS
        self.assertNotIn("40", {s for _, s in AUTO_MERCHANTS})


if __name__ == "__main__":
    unittest.main()

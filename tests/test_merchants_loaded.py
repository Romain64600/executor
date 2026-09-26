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

    def test_sans_generation_nulle_part_xbox_sur_les_deux(self):
        # P4 Xbox (Romain 2026-09-25, « Xbox sur les deux ») : un « Xbox/PC » sans génération est
        # lu Xbox One + Series, PC déclaré — le cas Play Anywhere de P2. Avant : refusé.
        sig = classify_console("Kingdom Rush Frontiers Xbox/PC (Europe & UK)",
                               _aff("kingdom-rush-frontiers-xbox-pc-eu"), "Loaded")
        self.assertEqual((sig.families, sig.pc_declared, sig.skip_reason, sig.generation_inferred),
                         (("XBOX_ONE", "XBOX_SERIES"), True, None, True))

    def test_europe_et_uk_est_l_europe_cote_console(self):
        sig = classify_console("METAL GEAR SOLID - Master Collection Version Xbox Series X|S (Europe & UK)",
                               _aff("metal-gear-solid-master-collection-version-xbox-series-x-s-eu"), "Loaded")
        self.assertEqual(sig.region_base, "eu")


class LIdentiteDUneOffreEstSaFiche(unittest.TestCase):
    """Ré-audit de Romain (2026-09-26, P1) : le chemin du lien d'affiliation est le MÊME pour
    toutes les offres Loaded ; l'offre est dans ``u``. Sans ``u`` dans l'identité, la ligne 2
    se faisait prendre pour la ligne 1, et une sœur restée au feed empêchait de prouver la
    disparition d'une offre créée."""

    UN, DEUX = _aff("zero-caliber-2-remastered-pc-steam"), _aff("towerborne-xbox-series-x-s-pc-eu")

    def test_deux_offres_deux_cles(self):
        from src.submitter import _url_key
        self.assertNotEqual(_url_key(self.UN), _url_key(self.DEUX))
        self.assertEqual(_url_key(self.UN), _url_key(self.UN.replace("/18216?", "/18216?utm=x&")))

    def _sub(self, session):
        from src.submitter import Submitter
        sub = Submitter(session)
        sub.empty_retry_wait_s = 0
        sub.empty_confirm_waits = (0,)
        sub.feed_ui_render_waits = ()
        sub.modal_ctx_waits = ()
        return sub

    def test_demander_la_ligne_2_prend_la_ligne_2(self):
        from src.submitter import _url_key
        from tests.test_submitter import FakeSubmitSession
        session = FakeSubmitSession([["1", "2"]], rows={"1": {"url": self.UN}, "2": {"url": self.DEUX}})
        session.navigate("https://x/feed")
        row = self._sub(session)._pin_fresh_row("2", _url_key(self.DEUX))
        self.assertEqual(str(row.get("id")), "2")

    def test_une_soeur_restee_au_feed_ne_bloque_plus_la_preuve(self):
        from tests.test_submitter import FakeSubmitSession
        session = FakeSubmitSession([["2"]], rows={"2": {"url": self.DEUX}})
        gone, _, _ = self._sub(session)._verify_gone("1", self.UN, "40", "aks-merchant-feeds-9", "all", 5)
        self.assertTrue(gone)

    def test_la_meme_offre_reidentifiee_reste_au_feed(self):
        from tests.test_submitter import FakeSubmitSession
        session = FakeSubmitSession([["9"]], rows={"9": {"url": self.UN}})
        gone, _, _ = self._sub(session)._verify_gone("1", self.UN, "40", "aks-merchant-feeds-9", "all", 5)
        self.assertFalse(gone)


class SwitchEtSwitch2(unittest.TestCase):
    """Ré-audit de Romain (2026-09-26, P1) : « Switch & Switch 2 » ne donnait que SWITCH2 —
    la Switch déclarée se perdait, et la saisie aurait consommé l'offre sans elle."""

    def test_les_deux_generations_sont_gardees(self):
        for titre in ("Super Mario Galaxy 2 Switch & Switch 2 (Europe & UK)",
                      "Super Mario Galaxy + Super Mario Galaxy 2 Switch & Switch 2 (Europe & UK)"):
            with self.subTest(titre):
                sig = classify_console(titre, _aff("super-mario-galaxy-2-switch-switch-2-eu"), "Loaded")
                self.assertEqual((sig.families, sig.skip_reason, sig.region_base),
                                 (("SWITCH", "SWITCH2"), None, "eu"))

    def test_un_switch_nu_a_cote_d_une_autre_plateforme_est_refuse(self):
        sig = classify_console("Some Game (PS4 / Switch)", "https://x.test/y", "Shop")
        self.assertIn("never a partial entry", sig.skip_reason)

    def test_la_meme_plateforme_repetee_ne_change_rien(self):
        for titre, fams in (("Some Game (Nintendo Switch) Switch Key", ("SWITCH",)),
                            ("NieR Automata (Europe) (Nintendo Switch) - Nintendo - Digital Key", ("SWITCH",)),
                            ("Diablo IV (Europe) (Nintendo Switch 2) - Nintendo - Digital Key", ("SWITCH2",))):
            with self.subTest(titre):
                sig = classify_console(titre, "https://x.test/y", "Shop")
                self.assertEqual((sig.families, sig.skip_reason), (fams, None))


class Registre(unittest.TestCase):
    def test_le_store_40_est_loaded(self):
        self.assertEqual(merchant_for_store("40"), "Loaded")
        self.assertIs(merchant_config("Loaded"), L.CONFIG)

    def test_en_liste_blanche_dans_le_groupe_a(self):
        """Romain, 2026-09-26 : « 5. Go » (groupe A proposé)."""

        from src.admin.auto_merchants import AUTO_MERCHANTS
        from src.merchant_groups import GROUPS
        self.assertIn(("Loaded", "40"), AUTO_MERCHANTS)
        self.assertEqual([k for k, noms in GROUPS.items() if "Loaded" in noms], ["A"])


if __name__ == "__main__":
    unittest.main()

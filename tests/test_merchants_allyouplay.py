"""Allyouplay (feed store 17) — le lien d'affiliation, 2026-09-30, src/merchants/allyouplay.py.

Romain (« Go ») : « accepter le lien d'affiliation seulement si u pointe vers allyouplay.com, et
u sert d'identité comme Loaded ». Six balayages du groupe B depuis le 17/09 : 296 lignes
distinctes, 100 % refusées « offer URL not on allyouplay.com » — le feed passe par un
redirecteur Impact dont le paramètre `u` porte la fiche. Lignes réelles du feed (runs du 17/09
au 26/09, aperçu par page du 29/09)."""

import unittest
from urllib.parse import quote

from src.console_keys import account_signal, classify_console
from src.contracts import NormalizedOffer
from src.matcher import (detect_edition, detect_region, explicit_platform_from_url,
                         precheck_skip, strip_merchant_url_noise)
from src.merchant_config import MerchantConfig, affiliate_landing
from src.merchants.registry import merchant_config, url_identity_params

HOTE = "https://anandadigitalbv.sjv.io/c/1297091/2866230/30655"


def _aff(chemin, u=True):
    """Le lien du feed, tel qu'AKS le stocke : `u` ENCODÉ, entre `prodsku` et `intsrc`."""

    fiche = quote(f"https://www.allyouplay.com/{chemin}", safe="")
    return (f"{HOTE}?prodsku=42863&u={fiche}&intsrc=CATF_22827" if u
            else f"{HOTE}?prodsku=42863&intsrc=CATF_22827")


def _offre(nom, chemin, **kw):
    return NormalizedOffer(offer_id=kw.get("offer_id", "1"), name=nom, url=kw.get("url") or _aff(chemin),
                           merchant="Allyouplay", store_id="17")


NIVALIS = _aff("pc/nivalis-nights-2")
TF3 = _aff("pc/transport-fever-3")


class LeLienDAffiliationPasseLeDomaine(unittest.TestCase):
    def test_u_vers_allyouplay_est_accepte(self):
        for nom, chemin in (("Nivalis Nights", "pc/nivalis-nights-2"),
                            ("Transport Fever 3", "pc/transport-fever-3"),
                            ("Transport Fever 3 - Deluxe Edition", "pc/transport-fever-3-deluxe-edition")):
            with self.subTest(nom):
                self.assertIsNone(precheck_skip(_offre(nom, chemin), consoles=True))

    def test_la_fiche_est_lue_decodee(self):
        cfg = merchant_config("Allyouplay")
        self.assertEqual(cfg.landing_url(NIVALIS), "https://www.allyouplay.com/pc/nivalis-nights-2")
        # le sans-www aussi (sous-domaine ou domaine nu)
        self.assertEqual(cfg.landing_url(HOTE + "?u=https://allyouplay.com/pc/x"),
                         "https://allyouplay.com/pc/x")

    def test_sans_u_le_refus_nomme_le_lien(self):
        raison = precheck_skip(_offre("Nivalis Nights", "", url=_aff("", u=False)), consoles=True)
        self.assertIsNotNone(raison)
        self.assertIn("merchant-domain mismatch", raison)
        self.assertIn("affiliate link", raison)

    def test_u_vers_un_autre_site_reste_refuse(self):
        for u in ("https://www.g2a.com/nivalis-nights", "https://allyouplay.com.evil.io/pc/x",
                  "https://evilallyouplay.com/pc/x", "javascript:alert(1)", "/pc/nivalis-nights-2"):
            with self.subTest(u):
                url = f"{HOTE}?prodsku=42863&u={quote(u, safe='')}"
                raison = precheck_skip(_offre("Nivalis Nights", "", url=url), consoles=True)
                self.assertIsNotNone(raison)
                self.assertIn("merchant-domain mismatch", raison)

    def test_un_autre_hote_d_affiliation_n_est_pas_accepte(self):
        url = "https://autre.sjv.io/c/1/2/3?u=" + quote("https://www.allyouplay.com/pc/x", safe="")
        raison = precheck_skip(_offre("Nivalis Nights", "", url=url), consoles=True)
        self.assertEqual(raison, "offer URL not on allyouplay.com (merchant-domain mismatch)")

    def test_un_marchand_sans_hote_declare_ne_change_pas(self):
        self.assertEqual(affiliate_landing(NIVALIS, (), "allyouplay.com"), NIVALIS)
        self.assertEqual(MerchantConfig("X", domain="allyouplay.com").landing_url(NIVALIS), NIVALIS)


class LaFicheParleDuProduit(unittest.TestCase):
    """Les lectures de signaux d'URL lisent la fiche ; l'URL stockée ne change jamais."""

    def test_strip_rend_la_fiche_pour_allyouplay_seulement(self):
        self.assertEqual(strip_merchant_url_noise(NIVALIS, "Allyouplay"),
                         "https://www.allyouplay.com/pc/nivalis-nights-2")
        loaded = "https://go.loaded.com/c/1297091/2640470/18216?u=https://www.loaded.com/x-pc-steam"
        self.assertEqual(strip_merchant_url_noise(loaded, "Loaded"), loaded)
        kinguin = "https://www.kinguin.net/category/1/x-steam-cd-key?nosalesbooster=1"
        self.assertEqual(strip_merchant_url_noise(kinguin, "Kinguin"), kinguin)

    def test_une_row_du_slug_est_refusee(self):
        # Règle ROW du 24/09 : jamais GLOBAL sans preuve d'Europe. Le `-row-` n'était pas
        # visible dans le chemin du redirecteur.
        for nom, chemin in (
                ("CLAWPUNK", "pc/clawpunk-row-8ebc69d0-feb8-456a-9ec1-0bc405abcecf"),
                ("Dying Light: The Beast",
                 "pc/dying-light-the-beast-row-september-2026-4ebe03d8-4809-43b9-975e-be6400c3e66e"),
                ("Deliver Us Mars: Deluxe Edition",
                 "pc/deliver-us-mars-deluxe-edition-pre-order-row-df76afd0-f5bc-4dc2-bb0e-3e49169a4961")):
            with self.subTest(nom):
                self.assertEqual(precheck_skip(_offre(nom, chemin), consoles=True), "forbidden region: ROW")

    def test_le_titre_et_l_url_ne_disent_pas_la_region(self):
        # La lecture générique d'une ligne muette reste « GLOBAL implicite » — mais depuis
        # `[R68]` la région d'Allyouplay vient TOUJOURS de la fiche (``offer_page_resolver``,
        # qui l'emporte : tests/test_merchants_allyouplay_r68.py). Ce test garde la lecture
        # générique telle quelle : rien n'y est inventé pour ce marchand.
        self.assertEqual(detect_region(_offre("Nivalis Nights", "pc/nivalis-nights-2"), "STEAM"),
                         ("GLOBAL", "2", True))

    def test_une_region_du_slug_est_lue(self):
        label, rid, implicite = detect_region(_offre("Some Game", "pc/some-game-europe"), "STEAM")
        self.assertEqual((label, rid, implicite), ("EU", "9", False))

    def test_l_edition_reste_celle_du_titre(self):
        # Le slug dit « premium », le titre dit « Deluxe » : le titre fait foi (2 lignes / 251).
        url = _aff("pc/the-elder-scrolls-online-2025-premium-edition-2")
        self.assertEqual(detect_edition("Elder Scrolls Online: Deluxe Edition", url, "Allyouplay"),
                         ("Deluxe", "7"))

    def test_la_plateforme_d_url_lit_la_fiche(self):
        self.assertIsNone(explicit_platform_from_url(NIVALIS, "Allyouplay"))

    def test_une_fiche_xbox_est_une_ligne_console(self):
        # « Pac-Man CE 2 » : titre muet, fiche `/xbox/…` — jamais une clé Steam par défaut.
        sig = classify_console("Pac-Man CE 2", _aff("xbox/pac-man-ce-2"), "Allyouplay")
        self.assertIsNotNone(sig)
        self.assertEqual(sig.families, ("XBOX_ONE", "XBOX_SERIES"))
        self.assertTrue(sig.generation_inferred)
        sig = classify_console("Mass Effect: Andromeda: Andromeda Points Pack 1 (500 PTS)",
                               _aff("cash-points/mass-effect-andromeda-andromeda-points-pack-1-500-pts-xbox-one"),
                               "Allyouplay")
        self.assertIsNotNone(sig)
        self.assertIn("XBOX_ONE", sig.families)

    def test_une_fiche_pc_n_est_pas_une_console(self):
        self.assertIsNone(classify_console("Nivalis Nights", NIVALIS, "Allyouplay"))

    def test_le_jeton_account_se_lit_dans_la_fiche(self):
        self.assertEqual(account_signal("X", _aff("pc/x-steam-account"), "Allyouplay"), "url")
        self.assertIsNone(account_signal("Nivalis Nights", NIVALIS, "Allyouplay"))


class LIdentiteDUneOffreEstSaFiche(unittest.TestCase):
    """Comme Loaded (26/09) : le chemin `/c/1297091/2866230/30655` est le même pour les 296
    lignes ; sans `u` dans l'identité, la ligne 2 se prenait pour la ligne 1 et une sœur restée
    au feed empêchait de prouver la disparition d'une offre créée."""

    UN, DEUX = NIVALIS, TF3

    def test_l_hote_d_affiliation_porte_l_identite(self):
        self.assertEqual(url_identity_params(self.UN), ("u",))

    def test_deux_offres_deux_cles(self):
        from src.submitter import _url_key
        self.assertNotEqual(_url_key(self.UN), _url_key(self.DEUX))
        # la même fiche, encodée ou non, et d'autres paramètres : la même clé
        brut = HOTE + "?prodsku=42863&u=https://www.allyouplay.com/pc/nivalis-nights-2&intsrc=AUTRE"
        self.assertEqual(_url_key(self.UN), _url_key(brut))

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

    def test_une_soeur_restee_au_feed_ne_bloque_pas_la_preuve(self):
        from tests.test_submitter import FakeSubmitSession
        session = FakeSubmitSession([["2"]], rows={"2": {"url": self.DEUX}})
        gone, _, _ = self._sub(session)._verify_gone("1", self.UN, "17", "aks-merchant-feeds-9", "all", 5)
        self.assertTrue(gone)

    def test_la_meme_offre_reidentifiee_reste_au_feed(self):
        from tests.test_submitter import FakeSubmitSession
        session = FakeSubmitSession([["9"]], rows={"9": {"url": self.UN}})
        gone, _, _ = self._sub(session)._verify_gone("1", self.UN, "17", "aks-merchant-feeds-9", "all", 5)
        self.assertFalse(gone)

    def test_le_terme_de_recherche_est_le_slug_de_la_fiche(self):
        # Revue adverse du 30/09 (P1) : « 30655 », dernier segment du chemin COMMUN, rendait tout
        # le magasin, et la page de recherche s'arrête à 300 lignes sans paginer ([P2-13]) — une
        # offre au-delà passait pour « partie ». Le terme est le slug de la fiche (`u`), présent
        # mot pour mot dans l'URL stockée.
        from src.submitter import search_term
        self.assertEqual(search_term(self.UN), "nivalis-nights-2")
        self.assertIn("nivalis-nights-2", self.UN)

    def test_un_slug_absent_du_texte_stocke_garde_l_ancien_terme(self):
        # Le serveur cherche dans le texte STOCKÉ : un slug qui n'y figure pas tel quel (encodé
        # autrement) ne peut pas servir de terme — l'ancien terme reste, et le plafond de
        # `_scan_search` refuse une page pleine.
        from src.submitter import search_term
        encode = HOTE + "?prodsku=42863&u=https%3A%2F%2Fwww.allyouplay.com%2Fpc%2Fcaf%C3%A9&intsrc=X"
        self.assertEqual(search_term(encode), "30655")

    def test_une_page_de_recherche_pleine_ne_prouve_rien(self):
        from src.submitter import FeedScanError
        from tests.test_submitter import FakeSubmitSession
        ids = [str(i) for i in range(1, 301)]
        session = FakeSubmitSession([ids], rows={i: {"url": self.UN} for i in ids})
        with self.assertRaises(FeedScanError) as ctx:
            self._sub(session)._verify_gone("999", self.UN, "17", "aks-merchant-feeds-9", "all", 5,
                                            search_locate=True)
        self.assertIn("capped at 300", str(ctx.exception))

    def test_la_preuve_par_recherche_trouve_l_offre_restee(self):
        from tests.test_submitter import FakeSubmitSession
        session = FakeSubmitSession([["1", "2"]], rows={"1": {"url": self.UN}, "2": {"url": self.UN}})
        gone, _, _ = self._sub(session)._verify_gone("1", self.UN, "17", "aks-merchant-feeds-9", "all", 5,
                                                     search_locate=True)
        self.assertFalse(gone)
        self.assertIn("search%5Bsearch%5D=nivalis-nights-2", session.nav[-1])


class LesAutresMarchandsNeBougentPas(unittest.TestCase):
    def test_le_terme_de_recherche_des_autres_ne_change_pas(self):
        from src.submitter import search_term
        for url, attendu in (
            ("https://go.loaded.com/c/1297091/2640470/18216?u=https://www.loaded.com/x-pc-steam", "18216"),
            ("https://www.kinguin.net/category/928664/nivalis-nights-pc-steam-cd-key", "nivalis-nights-pc-steam-cd-key"),
            ("https://www.g2a.com/nivalis-nights-pc-steam-key-global-i10000515894001?adid=x", "nivalis-nights-pc-steam-key-global-i10000515894001"),
        ):
            with self.subTest(url):
                self.assertEqual(search_term(url), attendu)

    def test_loaded_garde_son_identite(self):
        self.assertEqual(url_identity_params("https://go.loaded.com/c/1/2/3?u=https://www.loaded.com/x"),
                         ("u",))

    def test_aucun_autre_marchand_ne_declare_d_hote_d_affiliation(self):
        from src.merchants.registry import MERCHANT_CONFIGS
        declares = sorted(c.name for c in MERCHANT_CONFIGS.values() if c.affiliate_hosts)
        self.assertEqual(declares, ["Allyouplay"])


if __name__ == "__main__":
    unittest.main()

"""L'identité d'une annonce peut vivre dans la query de son URL (2026-09-24).

Romain : « go pour les deux correctifs ». Le 24/09, 14 créations Wyrel sont sorties « STILL in
feed » alors qu'AKS avait répondu « Offer created … feed entry deleted » pour chacune : la clé
d'identité était le CHEMIN seul, et la variante d'une autre région (même chemin, autre
`region=`) restait au feed. Même chose chez CJS avec `variation=` (13 depuis le 20/09).
`MerchantConfig.url_identity_params` nomme les paramètres qui FONT l'annonce ; les autres
marchands gardent le repli P2-12 à l'identique.
"""

import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.cdp_session import CdpCommandError  # noqa: E402
from src.extractor import NotLoggedInError  # noqa: E402
from src.merchants.registry import url_identity_params  # noqa: E402
from src.submitter import DryRunSubmitter, Submitter, _url_key, _url_path  # noqa: E402
from tests.test_submitter import FakeSubmitSession, _cand  # noqa: E402

BASE = "https://wyrel.com/en/buy-cheap-shores-unknown-pc-12345"
EUROPE = BASE + "?referal=allkeyshop&marketplace_id=2&edition_id=780&region=4&coupon=allkeyshop"
GLOBAL = BASE + "?referal=allkeyshop&marketplace_id=2&edition_id=780&region=1&coupon=allkeyshop"
CJS = "https://www.cjs-cdkeys.com/products/Ash-of-Gods%3A-The-Way-Steam-Key.html"


class LaCleDIdentite(unittest.TestCase):
    def test_wyrel_garde_ses_trois_parametres_et_eux_seuls(self):
        self.assertEqual(url_identity_params(EUROPE), ("marketplace_id", "edition_id", "region"))
        self.assertEqual(_url_key(EUROPE), BASE + "?edition_id=780&marketplace_id=2&region=4")
        self.assertNotEqual(_url_key(EUROPE), _url_key(GLOBAL), "deux régions = deux annonces")

    def test_l_ordre_et_les_parametres_de_campagne_ne_comptent_pas(self):
        melange = BASE + "?region=4&coupon=autre&edition_id=780&marketplace_id=2"
        self.assertEqual(_url_key(melange), _url_key(EUROPE))

    def test_cjs_garde_variation(self):
        self.assertEqual(_url_key(CJS + "?variation=609"), CJS + "?variation=609")
        self.assertNotEqual(_url_key(CJS + "?variation=609"), _url_key(CJS + "?variation=608"))

    def test_les_autres_marchands_gardent_le_chemin_seul(self):
        for url in ("https://www.g2a.com/game-steam-key-global-i1?uuid=abc",
                    "https://www.kinguin.net/category/1/game?referrer=x",
                    "https://m/1?region=4"):
            self.assertEqual(_url_key(url), url.split("?", 1)[0], url)

    def test_le_chemin_reste_disponible_pour_la_recherche(self):
        self.assertEqual(_url_path(EUROPE), BASE)


def _sub(session):
    sub = Submitter(session)
    sub.empty_retry_wait_s = 0
    sub.empty_confirm_waits = (0,)
    sub.feed_ui_render_waits = ()
    sub.modal_ctx_waits = ()
    return sub


class LaPreuveDeDisparition(unittest.TestCase):
    """`_verify_gone` : gone ⇔ ni l'id, ni la CLÉ d'identité ne sont plus au feed."""

    def _gone(self, rows_on_feed, our_url):
        pages = [[rid for rid in rows_on_feed]]
        session = FakeSubmitSession(pages, rows={rid: {"url": u} for rid, u in rows_on_feed.items()})
        gone, _, _ = _sub(session)._verify_gone("1", our_url, "162", "aks-merchant-feeds-9",
                                                  "all", 5)
        return gone

    def test_la_soeur_d_une_autre_region_ne_bloque_plus_la_preuve(self):
        # Europe créée (id 1 disparu) ; la variante Global (id 2, même chemin) reste.
        self.assertTrue(self._gone({"2": GLOBAL}, EUROPE))

    def test_la_meme_annonce_reidentifiee_reste_au_feed(self):
        # Anti-création fantôme (K4G) : même annonce, nouvel id → PAS partie.
        self.assertFalse(self._gone({"9": EUROPE.replace("coupon=allkeyshop", "coupon=x")}, EUROPE))

    def test_p2_12_a_l_identique_pour_un_marchand_sans_parametres(self):
        # « https://m/… » ne déclare rien : une sœur au même chemin bloque toujours.
        self.assertFalse(self._gone({"2": "https://m/1?region=1"}, "https://m/1?region=4"))


class LaRechercheCherchePourtantLeChemin(unittest.TestCase):
    def test_le_terme_de_recherche_est_le_dernier_segment_du_chemin(self):
        session = FakeSubmitSession([[]])
        sub = _sub(session)
        index, by_url = sub._scan_search("162", "aks-merchant-feeds-9", "all", EUROPE)
        self.assertEqual((index, by_url), ({}, {}))
        cherche = [u for u in session.nav if "aks-merchant-feeds-search" in u]
        self.assertTrue(cherche)
        self.assertIn("search%5Bsearch%5D=buy-cheap-shores-unknown-pc-12345&", cherche[-1])


class _PrepareRaises(FakeSubmitSession):
    def __init__(self, pages, exc, **kw):
        super().__init__(pages, **kw)
        self.exc = exc

    def open_offer_modal(self, offer_id):
        raise self.exc


class AvantOuApresLeClic(unittest.TestCase):
    def _run(self, exc):
        sub = DryRunSubmitter(_PrepareRaises([["1", "2"]], exc))
        sub.empty_retry_wait_s = 0
        sub.empty_confirm_waits = (0,)
        sub.feed_ui_render_waits = ()
        sub.modal_ctx_waits = ()
        return sub.run(run_id="r", merchant="Driffle", store_id="127",
                       approved=[_cand("1"), _cand("2")])

    def test_une_panne_avant_le_clic_laisse_l_offre_intacte(self):
        res = self._run(CdpCommandError("Page.navigate failed: net::ERR_CONNECTION_REFUSED"))
        self.assertEqual(res["stopped"], "feed_unreadable_prewrite")
        self.assertIn("offer untouched", res["plan"][0]["post_save"])
        self.assertEqual(len(res["plan"]), 1, "l'arrêt tient : le candidat 2 n'est pas touché")

    def test_une_deconnexion_avant_le_clic_reste_l_arret_d_avant(self):
        res = self._run(NotLoggedInError("bounced to wp-login"))
        self.assertEqual(res["stopped"], "feed_unreadable")
        self.assertIn("UNKNOWN", res["plan"][0]["post_save"])


if __name__ == "__main__":
    unittest.main()

"""La recherche de preuve AKS est INSENSIBLE À LA CASSE — Romain, 2026-09-26.

« go pour vérifier et corriger la recherche CJS ». Trois créations CJS avaient fini « offer
state UNKNOWN … search page 1 rows do not all match term … — stale/foreign DOM re-served » :
Resonance (21/09), To the Stars (25/09), ATLAS (26/09, CJS arrêté pour la nuit). La sonde
lecture seule `scripts/probe_search_rows.py`, lancée le 26/09 sur la nouvelle VM, a rendu les
lignes RÉELLES ci-dessous : le serveur apparie le terme sans la casse — « ATLAS-… » rend aussi
« Starlink-Battle-for-Atlas-… », « Resonance-Steam-Key.html » rend « SIGILLVM%3A-RESONANCE-… ».
Le contrôle sensible à la casse prenait ces lignes légitimes pour une page étrangère."""

import unittest

from src.submitter import DryRunSubmitter, FeedScanError
from tests.test_submitter import _SearchFake

CJS = "https://www.cjs-cdkeys.com/products/"
ATLAS = CJS + "ATLAS-Digital-Download-Key-%28Xbox-One%7B47%7DSeries-X%29.html"
STARLINK = CJS + "Starlink-Battle-for-Atlas-Digital-Download-Key-%28Xbox-One%7B47%7DSeries-X%29.html"

# Les 7 lignes rendues par la recherche 'ATLAS-Digital-Download-Key-%28Xbox-One%7B47%7DSeries-X%29.html'
# (store 30, liste 9, 26/09) : l'offre UK (variation 725, id 101142139) n'y est plus.
LIGNES_ATLAS = [
    {"id": "101142608", "name": "Starlink Battle for Atlas Digital Download Key (Xbox One/Series X): United Kingdom",
     "url": STARLINK + "?variation=725", "store_id": "30"},
    {"id": "101142607", "name": "Starlink Battle for Atlas Digital Download Key (Xbox One/Series X): AR (Argentina)",
     "url": STARLINK + "?variation=701", "store_id": "30"},
    {"id": "101142606", "name": "Starlink Battle for Atlas Digital Download Key (Xbox One/Series X): Europe",
     "url": STARLINK + "?variation=699", "store_id": "30"},
    {"id": "101142605", "name": "Starlink Battle for Atlas Digital Download Key (Xbox One/Series X): USA",
     "url": STARLINK + "?variation=700", "store_id": "30"},
    {"id": "101142138", "name": "ATLAS Digital Download Key (Xbox One/Series X): AR (Argentina)",
     "url": ATLAS + "?variation=701", "store_id": "30"},
    {"id": "101142137", "name": "ATLAS Digital Download Key (Xbox One/Series X): Europe",
     "url": ATLAS + "?variation=699", "store_id": "30"},
    {"id": "101142136", "name": "ATLAS Digital Download Key (Xbox One/Series X): USA",
     "url": ATLAS + "?variation=700", "store_id": "30"},
]
LIGNE_RESONANCE = [{"id": "101127842", "name": "SIGILLVM: RESONANCE Steam Key",
                    "url": CJS + "SIGILLVM%3A-RESONANCE-Steam-Key.html", "store_id": "30"}]


def _sub(session):
    s = DryRunSubmitter(session)
    s.feed_ui_render_waits = (); s.modal_ctx_waits = ()
    s.empty_retry_wait_s = 0
    s.empty_confirm_waits = (0,)
    s.feed_scan_settle = 0
    return s


class LesLignesVoisinesNeSontPlusUnePageEtrangere(unittest.TestCase):
    def _gone(self, rows, url, oid, **kw):
        return _sub(_SearchFake(rows, **kw))._verify_gone(
            oid, url, "30", "aks-merchant-feeds-9", "all", 40, search_locate=True)[0]

    def test_atlas_uk_cree_est_prouve_parti(self):
        # Avant : FeedScanError → « UNKNOWN », CJS arrêté la nuit du 25-26/09.
        self.assertTrue(self._gone(LIGNES_ATLAS, ATLAS + "?variation=725", "101142139"))

    def test_resonance_cree_est_prouve_partie(self):
        self.assertTrue(self._gone(LIGNE_RESONANCE, CJS + "Resonance-Steam-Key.html", "101127835"))

    def test_une_offre_encore_la_n_est_jamais_partie(self):
        # L'offre Europe (id 101142137) est dans les lignes : pas partie — par id comme par clé.
        self.assertFalse(self._gone(LIGNES_ATLAS, ATLAS + "?variation=699", "101142137"))
        self.assertFalse(self._gone(LIGNES_ATLAS, ATLAS + "?variation=699", "999"))


class UnePageEtrangereResteRefusee(unittest.TestCase):
    """La casse repliée ouvre la porte aux lignes voisines : la page doit donc PROUVER qu'elle
    est notre recherche (le terme de son href), comme la page vide le faisait déjà."""

    def test_une_page_sur_un_autre_terme_est_refusee_meme_si_ses_lignes_contiennent_le_notre(self):
        # Le piège exact : une page Starlink périmée — chaque ligne contient 'atlas-digital-…'
        # une fois la casse repliée ; sans le contrôle d'href, l'absence d'ATLAS UK passerait
        # pour un « gone ».
        autre = ("https://aks/x?page=aks-merchant-feeds-search&store=30&search%5Bsearch%5D="
                 "Starlink-Battle-for-Atlas-Digital-Download-Key-%2528Xbox-One%257B47%257DSeries-X%2529.html"
                 "&search%5Bfield%5D=url")
        sub = _sub(_SearchFake(LIGNES_ATLAS[:4], wedge_href=autre))
        with self.assertRaisesRegex(FeedScanError, "not proven on this search"):
            sub._scan_search("30", "aks-merchant-feeds-9", "all", ATLAS + "?variation=725")

    def test_une_page_de_feed_sans_recherche_est_refusee(self):
        sans = "https://aks/x?page=aks-merchant-feeds-9&store=30&p=20"
        sub = _sub(_SearchFake(LIGNES_ATLAS, wedge_href=sans))
        with self.assertRaises(FeedScanError):
            sub._scan_search("30", "aks-merchant-feeds-9", "all", ATLAS + "?variation=725")

    def test_une_ligne_qui_ne_contient_pas_le_terme_reste_refusee(self):
        etrangere = [{"id": "5", "name": "Other", "url": CJS + "Other-Game-Steam-Key.html", "store_id": "30"}]
        sub = _sub(_SearchFake(LIGNES_ATLAS + etrangere))
        with self.assertRaisesRegex(FeedScanError, "do not all match term"):
            sub._scan_search("30", "aks-merchant-feeds-9", "all", ATLAS + "?variation=725")


if __name__ == "__main__":
    unittest.main()

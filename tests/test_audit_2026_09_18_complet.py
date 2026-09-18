"""Audit complet du 2026-09-18 — les constats corrigés, verrouillés un par un.

Rapport : docs/AUDIT_2026-09-18_complet.md. Chaque classe porte l'emplacement du constat
et rouvre la porte exacte qui était ouverte : ces tests doivent passer au ROUGE si on
revient en arrière, pas seulement décrire le comportement souhaité.
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.contracts import NormalizedOffer
from src.matcher import (  # noqa: E402
    REGION_IDS, AksResolution, Candidate, SkippedOffer, match_offer,
)


def _page(editions, *, aks_name="DLC Quest", platforms=("Steam",), regions=None):
    return AksResolution(slug="s", url="https://aks/x", product_id="1", aks_name=aks_name,
                         editions=editions, regions=regions or {"2": "GLOBAL"},
                         official_platforms=platforms)


def _match(name, url, page, merchant="Gamivo"):
    offer = NormalizedOffer(offer_id="1", name=name, url=url, merchant=merchant)
    return match_offer(offer, resolver=lambda n, **k: page)


class R18IsTheSoleAuthorityOnTheDlcBucket(unittest.TestCase):
    """`src/matcher.py:3169` et `:3217` — le durcissement du 17/09 ne fermait qu'une porte
    sur trois vers le seau DLC(16).

    « DLC Quest » est un VRAI JEU DE BASE — EXECUTOR_RULES §4.3 (f) le nomme explicitement.
    Son titre contient le mot DLC, donc `detect_edition` rend DLC(16) ; deux autres
    producteurs adoptaient ensuite le seau DLC de la page par simple égalité de libellé,
    sans exiger de marqueur et sans la condition « seul seau » de [R18]."""

    NAME = "DLC Quest - Steam Key GLOBAL"
    URL = "https://gamivo.com/product/dlc-quest"

    def test_a_base_game_is_NOT_dlc_when_the_page_also_offers_standard(self):
        # La porte E05/R23 : « DLC » est dans le nom AKS, la page vend le seau 16.
        res = _match(self.NAME, self.URL, _page({"1": "Standard", "16": "DLC"}))
        self.assertIsInstance(res, Candidate)
        self.assertEqual((res.edition_label, res.edition_id), ("Standard", "1"))

    def test_a_named_dlc_bucket_is_not_adopted_either(self):
        # Même porte, seau nommé « DLC Pack » sous un id quelconque : PACK est du bruit de
        # format, donc la clé de comparaison valait {DLC} et le seau était adopté.
        res = _match(self.NAME, self.URL, _page({"1": "Standard", "4711": "DLC Pack"}))
        self.assertIsInstance(res, Candidate)
        self.assertEqual((res.edition_label, res.edition_id), ("Standard", "1"))

    def test_R18_itself_is_untouched_on_a_single_bucket_page(self):
        # La décision de Romain du 17/09 : le seau DLC décide quand il est le SEUL.
        res = _match(self.NAME, self.URL, _page({"16": "DLC"}))
        self.assertIsInstance(res, Candidate)
        self.assertEqual((res.edition_label, res.edition_id), ("DLC", "16"))

    def test_the_refusal_names_R18_instead_of_lying_about_the_page(self):
        """La réconciliation P1-1 disait « not sold on the resolved AKS page » alors que la
        page VEND le seau — un motif faux, et qui alimente le routeur de tri des listes."""
        res = _match("Some Game DLC - Steam Key GLOBAL",
                     "https://gamivo.com/product/some-game-dlc",
                     _page({"1": "Standard", "7": "Deluxe", "16": "DLC"},
                           aks_name="Some Game"))
        if isinstance(res, SkippedOffer):
            self.assertNotIn("not sold on the resolved", res.reason)


class MicrosoftIsAStoreWordNotAProductWord(unittest.TestCase):
    """`src/matcher.py:579` — exactement l'histoire de ROCKSTAR du 2026-09-16, rejouée.

    Les seaux MICROSOFT sont mappés depuis [R50], donc la ligne passe la garde de région
    et vient mourir un cran plus loin sur « extra words: ['MICROSOFT'] »."""

    def test_a_microsoft_store_row_is_entered(self):
        res = _match("Test Game (Microsoft Store)",
                     "https://gamerall.com/pc/test-game-microsoft-store-europe",
                     _page({"1": "Standard"}, aks_name="Test Game",
                           platforms=("Microsoft Store",),
                           regions={"2": "GLOBAL", "244": "EU"}),
                     merchant="Gamerall")
        self.assertIsInstance(res, Candidate, getattr(res, "reason", ""))
        self.assertEqual(res.platform, "MICROSOFT")

    def test_the_bucket_mapping_alone_was_not_enough(self):
        """Les deux moitiés sont un seul correctif : sans le jeton de bruit, le mapping des
        seaux ne livre rien (c'est ce que dit déjà la note ROCKSTAR)."""
        self.assertIn("MICROSOFT", REGION_IDS)


class AMerchantFileNeverInventsAPlatformToken(unittest.TestCase):
    """`src/merchants/gamerall.py:60` — le fichier rendait « UPLAY », nom commercial absent
    de REGION_IDS. Le matcher lisait UBISOFT dans le titre et UPLAY dans l'URL : 100 % des
    lignes Ubisoft Connect étaient refusées sur un faux conflit interne au fichier."""

    def test_a_gamerall_ubisoft_row_is_no_longer_refused_on_an_internal_conflict(self):
        res = _match("Anno 1800 (Ubisoft Connect)",
                     "https://gamerall.com/pc/anno-1800-ubisoft-connect-europe",
                     _page({"1": "Standard"}, aks_name="Anno 1800",
                           platforms=("Ubisoft Connect",),
                           regions={"2": "GLOBAL", "244": "EU"}),
                     merchant="Gamerall")
        self.assertIsInstance(res, Candidate, getattr(res, "reason", ""))
        self.assertEqual(res.platform, "UBISOFT")


if __name__ == "__main__":
    unittest.main()

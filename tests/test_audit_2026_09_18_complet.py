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


class ACountryNameInTheGameTitleIsNotARegionLock(unittest.TestCase):
    """`src/matcher.py:930` — le balayage s'appliquait au titre ENTIER : tout jeu dont le NOM
    contient China / India / Japan / Ukraine / Poland était refusé « forbidden region » puis
    routé vers la Blacklist(8), alors qu'il déclare GLOBAL dans son titre ET dans son URL.

    Règle retenue : la région est la DERNIÈRE chose déclarée. Un nom de pays suivi d'un
    marqueur vendable appartient au nom du produit."""

    ENTRENT = [
        ("Assassin's Creed Chronicles: China (PC) - Steam Key - GLOBAL",
         "https://www.g2a.com/assassins-creed-chronicles-china-steam-key-global-i1"),
        ("Crusader Kings II: Rajas of India - Steam Key - GLOBAL",
         "https://www.g2a.com/crusader-kings-ii-rajas-of-india-steam-key-global-i2"),
        ("Cities: Skylines - Content Creator Pack: Modern Japan Steam Key GLOBAL",
         "https://www.g2a.com/cities-skylines-modern-japan-steam-key-global-i3"),
        ("Ukraine War Stories - Steam Key - GLOBAL",
         "https://www.g2a.com/ukraine-war-stories-steam-key-global-i4"),
        ("Civilization VI - Poland Civilization and Scenario Pack Steam Key GLOBAL",
         "https://www.g2a.com/civ-vi-poland-steam-key-global-i5"),
    ]
    VERROUS = [
        ("Cyberpunk 2077 Steam Key BRAZIL", "https://www.g2a.com/cyberpunk-2077-steam-key-brazil-i6"),
        # Le cas qui protège le P1 du 2026-09-06 : le verrou vient APRÈS le mot vendable.
        ("Cyberpunk 2077 Global Steam Key BRAZIL",
         "https://www.g2a.com/cyberpunk-2077-global-steam-key-brazil-i7"),
        ("Hades RUSSIA PC Steam CD Key", "https://www.kinguin.net/x/hades-pc-steam-cd-key-russia"),
        ("Hades Steam Key RUSSIA", "https://www.eneba.com/steam-hades-steam-key-russia"),
    ]

    def test_a_country_in_the_product_name_does_not_blacklist_a_global_key(self):
        from src.matcher import precheck_skip
        for name, url in self.ENTRENT:
            with self.subTest(name=name[:40]):
                offer = NormalizedOffer(offer_id="1", name=name, url=url, merchant="G2A")
                self.assertIsNone(precheck_skip(offer))

    def test_a_real_region_lock_is_still_refused(self):
        from src.matcher import precheck_skip
        for name, url in self.VERROUS:
            with self.subTest(name=name[:40]):
                offer = NormalizedOffer(offer_id="1", name=name, url=url, merchant="G2A")
                reason = precheck_skip(offer)
                self.assertIsNotNone(reason, "un verrou réel doit rester refusé")
                self.assertIn("forbidden region", reason)

    def test_the_slug_keeps_the_country_when_it_is_part_of_the_name(self):
        """Troisième site du même défaut : le strip itératif amputait « Rajas of India » en
        « Rajas of » une fois GLOBAL / KEY / STEAM retirés — mauvaise page sondée."""
        from src.matcher import cleaned_title
        self.assertEqual(cleaned_title("Crusader Kings II: Rajas of India - Steam Key - GLOBAL"),
                         "Crusader Kings II: Rajas of India")
        self.assertEqual(cleaned_title("Cities: Skylines - Content Creator Pack: Modern Japan "
                                       "Steam Key GLOBAL"),
                         "Cities: Skylines - Content Creator Pack: Modern Japan")
        # Mais un vrai verrou est toujours retiré du slug.
        self.assertEqual(cleaned_title("Hades Steam Key RUSSIA"), "Hades")


class ApproveMustBeAJsonBoolean(unittest.TestCase):
    """`src/validation.py:146` — « if not entry.get("approve") » lisait la VÉRITÉ PYTHON :
    la chaîne "false" approuve. Et `verify_approved_against_source` re-dérivant avec le même
    prédicat, la re-vérification au submit CONFIRMAIT l'approbation au lieu de la refuser."""

    def _files(self, approve):
        from src.validation import candidate_fingerprint
        cand = {"offer": {"offer_id": "1", "name": "Hades", "url": "https://m/x",
                          "merchant": "Kinguin"},
                "aks_product_id": "1", "aks_url": "https://aks/x", "aks_name": "Hades",
                "platform": "STEAM", "region": {"label": "GLOBAL", "id": "2", "implicit": False},
                "edition": {"label": "Standard", "id": "1"}}
        fp = candidate_fingerprint(cand)
        validation = {"run_id": "r1", "validated_by": "romain", "validated_at": "2026-09-18",
                      "candidates": [{"fingerprint": fp, "approve": approve}]}
        return [cand], validation

    def test_the_string_false_no_longer_approves(self):
        from src.validation import ValidationError, load_validation
        cands, validation = self._files("false")
        with self.assertRaises(ValidationError) as ctx:
            load_validation(validation, cands, expected_run_id="r1")
        self.assertIn("booléen", str(ctx.exception))

    def test_a_real_boolean_still_works_in_both_directions(self):
        from src.validation import load_validation
        cands, validation = self._files(True)
        self.assertEqual(len(load_validation(validation, cands, expected_run_id="r1")), 1)
        cands, validation = self._files(False)
        self.assertEqual(load_validation(validation, cands, expected_run_id="r1"), [])


class RegionBucketsArePerPlatformInBothDirections(unittest.TestCase):
    """`src/admin/validation_io.py:177` — la garde « les seaux de région sont PAR PLATEFORME »
    n'existait que dans le sens « je change la plateforme ». Changer la SEULE région acceptait
    un seau d'une autre famille, et le `<select>` de la console présente toutes les options de
    toutes les plateformes sans filtrage."""

    CATALOG = {"regions": [{"key": "2", "text": "Steam (2)"},
                           {"key": "9", "text": "Steam EU (9)"},
                           {"key": "88ps5h", "text": "PS5 (88ps5h)"}],
               "editions": [{"key": "1", "text": "Standard"}]}

    def _candidate(self):
        return {"offer": {"offer_id": "1", "name": "Hades", "url": "https://m/x",
                          "merchant": "Kinguin"},
                "aks_product_id": "1", "aks_url": "https://aks/x", "aks_name": "Hades",
                "platform": "STEAM", "region": {"label": "GLOBAL", "id": "2", "implicit": False},
                "edition": {"label": "Standard", "id": "1"}}

    def test_a_foreign_bucket_is_refused_when_only_the_region_changes(self):
        from src.admin.validation_io import ValidationIOError, _apply_override
        cand = self._candidate()
        with self.assertRaises(ValidationIOError) as ctx:
            _apply_override(cand, {"region_id": "88ps5h"}, self.CATALOG,
                            by="romain", now="2026-09-18T00:00:00Z")
        self.assertEqual(ctx.exception.code, "platform_region_mismatch")

    def test_a_bucket_of_the_right_platform_still_passes(self):
        from src.admin.validation_io import _apply_override
        cand = self._candidate()
        _apply_override(cand, {"region_id": "9"}, self.CATALOG,
                        by="romain", now="2026-09-18T00:00:00Z")
        self.assertEqual(cand["region"]["id"], "9")


class TheLanguageRegionMirrorCannotDrift(unittest.TestCase):
    """`src/matcher.py:617` — le commentaire revendique de MIROITER la décision P2-6b (« the
    SAME trailing code a forbidden region »), mais TH était verrou dans l'URL et langue dans
    le titre. Verrouillé ici pour que le miroir ne puisse plus diverger."""

    def test_every_url_lock_code_that_is_also_a_language_is_protected(self):
        import src.matcher as M
        codes = {c.upper() for c, _ in M._URL_FORBIDDEN_CODES}
        drift = (M.LANGUAGE_TOKENS & codes) - M._REGION_LOCK_LANG_CODES
        self.assertEqual(drift, set(),
                         f"codes verrous dans l'URL mais avalés comme langue dans le titre : {drift}")

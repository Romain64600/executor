"""Un COMPTE n'est jamais saisi comme une clé (2026-09-25).

Rapport de bug collé par Romain : l'offre Gamivo
``https://www.gamivo.com/product/hitman-2-xbox-one-series-account-global-standard``, titre
« Hitman 2 Global », a été créée comme clé « Xbox One Game Code » (page 23940) et Xbox Series
(page 60188). Cause : le détecteur de compte du classifieur console ne lisait le jeton
``account`` de l'URL qu'en FIN de chemin, et Gamivo l'écrit au milieu
(``<jeu>-<plateforme>-account-<région>-<édition>``). Même famille d'erreur chez Difmark : huit
comptes « [Steam/Global][OFFLINE] » de la liste account (30) entrés comme clés Steam GLOBAL(2),
parce que la branche Difmark ne croyait que le mot ACCOUNT de la page.

Désormais : UN détecteur (``console_keys.account_signal``), une priorité écrite (grammaire du
marchand, mot du titre, jeton d'URL — rien ne le contredit), et une garde finale avant toute
saisie dans le submitter.
"""

import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.console_keys import account_signal, classify_console, url_path_account_token  # noqa: E402
from src.contracts import NormalizedOffer  # noqa: E402
from src.matcher import is_account_offer, precheck_skip  # noqa: E402
from src.submitter import (  # noqa: E402
    OFFER_TYPE_MISMATCH_BLOCKER, destination_is_account, normalize_targets, offer_type_mismatch,
)
from tests.test_submitter import FakeWriteSession, _real  # noqa: E402

HITMAN_URL = ("https://www.gamivo.com/product/hitman-2-xbox-one-series-account-global-standard"
              "?glv=kiwhuamu&utm_campaign=allkeyshop")


def _offre(name, url, merchant="Gamivo"):
    return NormalizedOffer(offer_id="1", name=name, url=url, merchant=merchant)


class LeDetecteur(unittest.TestCase):
    def test_1_l_url_gamivo_exacte_est_un_compte(self):
        self.assertEqual(account_signal("Hitman 2 Global", HITMAN_URL, "Gamivo"), "url")
        self.assertTrue(is_account_offer("Hitman 2 Global", HITMAN_URL, "Gamivo"))
        sig = classify_console("Hitman 2 Global", HITMAN_URL, "Gamivo")
        self.assertEqual(sig.skip_reason, "console: ACCOUNT — not a game (R45)")
        self.assertEqual(precheck_skip(_offre("Hitman 2 Global", HITMAN_URL), consoles=True),
                         "console: ACCOUNT — not a game (R45)")

    def test_2_la_query_n_influe_pas(self):
        self.assertTrue(url_path_account_token(HITMAN_URL.split("?")[0]))
        self.assertFalse(url_path_account_token(
            "https://www.gamivo.com/product/hitman-2-steam-global?campaign=account&x=account"))

    def test_3_casse_et_encodage(self):
        for url in ("https://x.com/product/Game-XBOX-One-ACCOUNT-Global",
                    "https://x.com/product/game-xbox-one-acc%6Funt-global",
                    "https://x.com/product/game_steam_Account_eu"):
            self.assertTrue(url_path_account_token(url), url)
        self.assertEqual(account_signal("Game (ACCOUNT) Standard", "https://x.com/p/game", ""),
                         "title")

    def test_4_accounting_n_est_pas_un_compte(self):
        for url in ("https://x.com/product/accounting-simulator-steam-key-global",
                    "https://x.com/product/the-accountant-steam-key",
                    "https://x.com/product/accounts-of-war-steam-gift"):
            self.assertFalse(url_path_account_token(url), url)
        self.assertIsNone(account_signal("Accounting+ Steam Key GLOBAL",
                                         "https://x.com/p/accounting-steam-key", ""))

    def test_6_une_cle_xbox_normale_reste_une_cle(self):
        url = "https://www.gamivo.com/product/hitman-2-xbox-one-series-global-standard"
        self.assertIsNone(account_signal("Hitman 2 Global", url, "Gamivo"))
        sig = classify_console("Hitman 2 Global", url, "Gamivo")
        self.assertIsNone(sig.skip_reason)
        self.assertIn("XBOX_ONE", sig.families)

    def test_7_les_comptes_existants_continuent(self):
        # Kinguin : jeton en FIN de chemin (le cas historique).
        k = classify_console("Blocky Farm XBOX One / Xbox Series X|S Account",
                             "https://www.kinguin.net/category/523387/blocky-farm-xbox-one-xbox-series-x-s-account",
                             "Kinguin")
        self.assertEqual(k.skip_reason, "console: ACCOUNT — not a game (R45)")
        # ACCESS garde son libellé (le chemin porte aussi le jeton « account »).
        a = classify_console("Nioh 2 Remastered PS4/PS5 Access",
                             "https://www.kinguin.net/category/1/nioh-2-ps4-ps5-online-account-activation",
                             "Kinguin")
        self.assertEqual(a.skip_reason, "console: ACCESS — not a game (R45)")
        # Difmark : sa grammaire (account_row) l'envoie à SA branche compte — son URL est un
        # gabarit (« …-steam-account-<id> » porte aussi les vraies clés, décision revue du
        # 21/09) : jamais lue par le jeton générique, et le précheck la laisse passer.
        d = _offre("Stellaris Standard Edition",
                   "https://difmark.com/en/buy-console-account-stellaris-steam-account-75948",
                   merchant="Difmark")
        self.assertEqual(account_signal(d.name, d.url, "Difmark"), "merchant")
        self.assertFalse(is_account_offer(d.name, d.url, "Difmark"), "la page décide, pas l'URL")
        self.assertIsNone(precheck_skip(d, consoles=True))

    def test_pc_compte_par_l_url_seule_est_refuse_et_route_en_liste_30(self):
        from src.aks_lists import suggest_target_list
        offre = _offre("Some Game GLOBAL",
                       "https://www.gamivo.com/product/some-game-steam-account-global-standard")
        raison = precheck_skip(offre, consoles=True)
        self.assertTrue(raison.startswith("skip category: ACCOUNT"), raison)
        self.assertEqual(suggest_target_list(raison), "30")


def _candidat(name, url, merchant, cibles):
    primary = cibles[0]
    return {
        "fingerprint": "f", "offer": {"offer_id": "1", "name": name, "url": url, "merchant": merchant,
                                      "store_id": "51"},
        "aks_product_id": "1", "aks_url": primary.get("aks_url"), "aks_name": "Hitman 2",
        "platform": primary.get("platform"),
        "region": {"label": primary.get("region_label"), "id": primary.get("region_id") or "24"},
        "edition": {"label": "Standard", "id": "1"},
        "targets": [{"platform": c.get("platform"), "aks_product_id": "1", "aks_url": c.get("aks_url"),
                     "aks_name": "Hitman 2", "region": {"label": c.get("region_label"),
                                                        "id": c.get("region_id") or "24"},
                     "edition": {"label": "Standard", "id": "1"}} for c in cibles],
    }


XBOX_ONE = {"platform": "XBOX_ONE", "region_label": "Xbox One Game Code", "region_id": "24",
            "aks_url": "https://www.allkeyshop.com/blog/buy-hitman-2-xbox-one-compare-prices/"}
XBOX_SERIES = {"platform": "XBOX_SERIES", "region_label": "Xbox Series", "region_id": "300",
               "aks_url": "https://www.allkeyshop.com/blog/buy-hitman-2-xbox-series-compare-prices/"}
STEAM_ACCOUNT = {"platform": "STEAM", "region_label": "GLOBAL ACCOUNT", "region_id": "412",
                 "aks_url": "https://www.allkeyshop.com/blog/buy-hitman-2-steam-account-compare-prices/"}


class LaGardeFinale(unittest.TestCase):
    def test_types_de_destination(self):
        self.assertFalse(destination_is_account(XBOX_ONE))
        self.assertTrue(destination_is_account(STEAM_ACCOUNT))
        self.assertTrue(destination_is_account({"region_label": "",
                                                "aks_url": "https://aks/buy-x-xbox-one-account-compare-prices/"}))
        self.assertIsNone(destination_is_account({"region_label": "", "aks_url": ""}))

    def test_5_un_compte_vers_xbox_one_game_code_est_bloque_sans_ecriture(self):
        cand = _candidat("Hitman 2 Global", HITMAN_URL, "Gamivo", [XBOX_ONE])
        session = FakeWriteSession([["1"]])
        result = _real(session, [cand])
        entry = result["plan"][0]
        self.assertFalse(entry["ready"])
        self.assertTrue(entry["blocker"].startswith(OFFER_TYPE_MISMATCH_BLOCKER), entry["blocker"])
        self.assertEqual(session.fill_calls, [], "aucune saisie")
        self.assertEqual(session.v2_calls, [], "aucune saisie multi-cibles")
        self.assertEqual(session.created, set())
        self.assertEqual(result["created"], 0)
        # bloqué dans `_prepare`, AVANT l'ouverture de la modale de CETTE ligne (la seule
        # modale ouverte est la sonde de catalogue du départ, sur n'importe quelle ligne)
        self.assertIsNone(entry.get("modal_shape"), "la modale de la ligne n'a pas été ouverte")

    def test_8_type_de_destination_manquant_bloque(self):
        cand = _candidat("Hitman 2 Global",
                         "https://www.gamivo.com/product/hitman-2-xbox-one-series-global-standard",
                         "Gamivo", [{"platform": "XBOX_ONE", "region_label": "", "aks_url": ""}])
        raison = offer_type_mismatch(cand, [{"platform": "XBOX_ONE", "region_label": "", "aks_url": ""}])
        self.assertIn("destination type unknown", raison)

    def test_9_chaque_destination_est_verifiee_seule(self):
        cle_url = "https://www.gamivo.com/product/hitman-2-xbox-one-series-global-standard"
        cle = _candidat("Hitman 2 Global", cle_url, "Gamivo", [XBOX_ONE, XBOX_SERIES])
        self.assertIsNone(offer_type_mismatch(cle, [XBOX_ONE, XBOX_SERIES]),
                          "une clé Xbox One + Series passe sur les deux pages")
        compte = _candidat("Hitman 2 Global", HITMAN_URL, "Gamivo", [XBOX_ONE, XBOX_SERIES])
        self.assertIn("target 1", offer_type_mismatch(compte, [XBOX_ONE, XBOX_SERIES]))
        # la première destination (compte) passe, la seconde (clé Series) est vérifiée seule
        self.assertIn("target 2", offer_type_mismatch(compte, [STEAM_ACCOUNT, XBOX_SERIES]))
        melange = _candidat("Hitman 2 Global", cle_url, "Gamivo", [XBOX_ONE, STEAM_ACCOUNT])
        raison = offer_type_mismatch(melange, [XBOX_ONE, STEAM_ACCOUNT])
        self.assertIn("key offer → account-only destination target 2", raison)

    def test_difmark_la_page_a_decide_la_garde_ne_la_contredit_pas(self):
        url = "https://difmark.com/en/buy-console-account-stellaris-steam-account-75948"
        cle = _candidat("Stellaris Standard Edition", url, "Difmark",
                        [{"platform": "STEAM", "region_label": "GLOBAL", "region_id": "2",
                          "aks_url": "https://www.allkeyshop.com/blog/buy-stellaris-cd-key-compare-prices/"}])
        self.assertIsNone(offer_type_mismatch(cle, normalize_targets(cle)),
                          "une vraie clé Difmark (page « (Steam) ») passe")
        titre_compte = _candidat("Stellaris (Account) Standard Edition", url, "Difmark",
                                 [{"platform": "STEAM", "region_label": "GLOBAL", "region_id": "2",
                                   "aks_url": "https://www.allkeyshop.com/blog/buy-stellaris-cd-key-compare-prices/"}])
        self.assertIn("the title says account", offer_type_mismatch(titre_compte, normalize_targets(titre_compte)))

    def test_un_compte_vers_une_page_compte_passe(self):
        cand = _candidat("Stellaris Standard Edition",
                         "https://difmark.com/en/buy-console-account-stellaris-steam-account-75948",
                         "Difmark", [STEAM_ACCOUNT])
        self.assertIsNone(offer_type_mismatch(cand, [STEAM_ACCOUNT]))


if __name__ == "__main__":
    unittest.main()

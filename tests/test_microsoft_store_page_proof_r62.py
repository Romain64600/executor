"""`[R62]` — une clé Microsoft Store n'entre que si la page AKS liste « Microsoft Windows ».

Romain, 2026-09-26 : « … puis aligne l'ancien chemin Microsoft Store ». La branche « (Windows)
XBOX LIVE Key » (a6da691) exigeait déjà cette preuve ; les chemins historiques vers la
plateforme MICROSOFT (titre « Microsoft Store » / « Microsoft Key », préfixe d'URL Eneba /
MMOGA `windows`, Gamerall « (Microsoft Store) », Gamesplanet `-microsoft-store-download--`,
Discover.games) ne l'exigeaient pas — `PAGE_PLATFORM_NAMES` n'avait pas d'entrée MICROSOFT.
Désormais UNE vérification, `page_sells_microsoft_store`, pour toutes les routes.

Les lignes sont RÉELLES (balayages du 10 au 26/09) et les listes de plateformes sont celles de
leurs pages AKS, lues le 2026-09-26 (UA AKS/Staff) : le libellé est exactement « Microsoft
Windows », jamais « Microsoft Store ».
"""

import dataclasses
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import src.matcher as matcher  # noqa: E402
from src.contracts import NormalizedOffer  # noqa: E402
from src.matcher import (  # noqa: E402
    PAGE_PLATFORM_NAMES, SKIP_MICROSOFT_NO_PAGE, AksResolution, Candidate, SkippedOffer,
    match_offer, page_sells_microsoft_store,
)
from src.console_keys import SKIP_WINDOWS_KEY_NO_PAGE  # noqa: E402
from src.merchants import discover as disc  # noqa: E402
from src.merchants import gamesplanet as gp  # noqa: E402
from src.merchants.registry import merchant_config  # noqa: E402

MS_REGIONS = {"2": "GLOBAL", "246": "WINDOWS GLOBAL", "244": "WINDOWS EU",
              "245": "WINDOWS US", "249": "WINDOWS UK"}

# Listes lues en direct le 2026-09-26.
AVOWED = ("Steam", "Battle.net", "Xbox Play Anywhere", "Xbox")
HELLBLADE_2 = ("Steam", "Xbox Play Anywhere", "Xbox")
NINJA_GAIDEN_4 = ("Steam", "Xbox Play Anywhere", "Microsoft Windows", "Xbox")
MINECRAFT_LEGENDS = ("Steam", "Direct Publisher", "Xbox Play Anywhere", "Microsoft Windows")
HALO_REACH = ("Steam", "Xbox Play Anywhere", "Microsoft Windows")
COD_VANGUARD = ("Xbox", "Steam", "Xbox Play Anywhere", "Battle.net", "Microsoft Windows")
AOE3 = ("Steam", "Xbox Play Anywhere", "Microsoft Windows")


def _page(aks_name, platforms, editions=None):
    return AksResolution(slug="s", url="https://aks/x", product_id="1", aks_name=aks_name,
                         editions=editions or {"1": "Standard"}, regions=dict(MS_REGIONS),
                         official_platforms=platforms)


def _match(name, url, merchant, page, store_id=""):
    """Le matcher tel qu'en production (branche console active depuis le 2026-09-15) ; la page
    PC est la seule que connaît le résolveur."""

    offer = NormalizedOffer(offer_id="1", name=name, url=url, merchant=merchant,
                            store_id=store_id)
    return match_offer(offer, resolver=lambda n, **k: None if k.get("page_kind") else page,
                       consoles=True)


class LeLibelleAks(unittest.TestCase):
    def test_le_seul_libelle_accepte_est_microsoft_windows(self):
        self.assertEqual(PAGE_PLATFORM_NAMES["MICROSOFT"], "Microsoft Windows")
        self.assertTrue(page_sells_microsoft_store(NINJA_GAIDEN_4))
        self.assertTrue(page_sells_microsoft_store(("microsoft windows",)))
        # « Microsoft Store » n'est pas un libellé AKS : il ne prouve rien.
        self.assertFalse(page_sells_microsoft_store(("Microsoft Store",)))
        self.assertFalse(page_sells_microsoft_store(AVOWED))
        self.assertFalse(page_sells_microsoft_store(()))

    def test_le_refus_se_range_dans_la_categorie_plateforme(self):
        from src.feed_status import categorize_reason
        self.assertEqual(categorize_reason(SKIP_MICROSOFT_NO_PAGE), "platform")


class GamesplanetMicrosoftStoreDownload(unittest.TestCase):
    """Les trois candidates du 25/09 que la règle refuse maintenant (jamais créées)."""

    def _gp(self, name, url, platforms, aks_name):
        with mock.patch.object(gp, "fetch_region", return_value=("global", "")):
            return _match(name, url, "Gamesplanet FR", _page(aks_name, platforms), "55")

    def test_avowed_sur_une_page_sans_microsoft_windows_est_refuse(self):
        res = self._gp("Avowed (Microsoft Store)",
                       "https://fr.gamesplanet.com/game/avowed-microsoft-store-download--7367-1",
                       AVOWED, "Avowed")
        self.assertIsInstance(res, SkippedOffer)
        self.assertEqual(res.reason, SKIP_MICROSOFT_NO_PAGE)

    def test_hellblade_2_aussi(self):
        res = self._gp("Senua's Saga: Hellblade II (Microsoft Store)",
                       "https://fr.gamesplanet.com/game/senua-s-saga-hellblade-ii-microsoft-store-download--6928-1",
                       HELLBLADE_2, "Senua’s Saga Hellblade 2")
        self.assertIsInstance(res, SkippedOffer)
        self.assertEqual(res.reason, SKIP_MICROSOFT_NO_PAGE)

    def test_ninja_gaiden_4_cree_le_25_09_entre_toujours(self):
        res = self._gp("NINJA GAIDEN 4 (Microsoft Store)",
                       "https://fr.gamesplanet.com/game/ninja-gaiden-4-microsoft-store-download--7935-1",
                       NINJA_GAIDEN_4, "NINJA GAIDEN 4")
        self.assertIsInstance(res, Candidate, getattr(res, "reason", ""))
        self.assertEqual((res.platform, res.region_id), ("MICROSOFT", "246"))


class GamerallMicrosoftStore(unittest.TestCase):
    NAME = "Minecraft Legends (Microsoft Store)"
    URL = "https://gamerall.com/microsoft-store/minecraft-legends-microsoft-store-global"

    def test_la_ligne_creee_le_19_09_entre_toujours(self):
        res = _match(self.NAME, self.URL, "Gamerall", _page("Minecraft Legends", MINECRAFT_LEGENDS))
        self.assertIsInstance(res, Candidate, getattr(res, "reason", ""))
        self.assertEqual((res.platform, res.region_id), ("MICROSOFT", "246"))

    def test_la_meme_ligne_sur_une_page_steam_seule_est_refusee(self):
        res = _match(self.NAME, self.URL, "Gamerall", _page("Minecraft Legends", ("Steam",)))
        self.assertIsInstance(res, SkippedOffer)
        self.assertEqual(res.reason, SKIP_MICROSOFT_NO_PAGE)

    def test_une_page_sans_aucune_plateforme_ne_suffit_pas(self):
        """Plus strict que R20 : une liste VIDE laissait passer toute plateforme déclarée."""

        res = _match(self.NAME, self.URL, "Gamerall", _page("Minecraft Legends", ()))
        self.assertIsInstance(res, SkippedOffer)
        self.assertEqual(res.reason, SKIP_MICROSOFT_NO_PAGE)

    def test_un_marchand_qui_leve_r20_ne_leve_pas_r62(self):
        """`require_page_platform=False` (GOG) lève R20, jamais la preuve Microsoft Store."""

        cfg = dataclasses.replace(merchant_config("Gamerall"), require_page_platform=False)
        with mock.patch.object(matcher, "merchant_config", return_value=cfg):
            res = _match(self.NAME, self.URL, "Gamerall", _page("Minecraft Legends", ("Steam",)))
        self.assertIsInstance(res, SkippedOffer)
        self.assertEqual(res.reason, SKIP_MICROSOFT_NO_PAGE)


class EnebaPrefixeWindows(unittest.TestCase):
    NAME = "Halo Reach - Windows Store Key EUROPE"
    URL = "https://www.eneba.com/windows-store-halo-reach-windows-store-key-europe"

    def test_creee_le_24_09_entre_toujours(self):
        res = _match(self.NAME, self.URL, "Eneba", _page("Halo Reach", HALO_REACH), "19")
        self.assertIsInstance(res, Candidate, getattr(res, "reason", ""))
        self.assertEqual((res.platform, res.region_id), ("MICROSOFT", "244"))

    def test_refusee_sans_microsoft_windows(self):
        res = _match(self.NAME, self.URL, "Eneba",
                     _page("Halo Reach", ("Steam", "Xbox Play Anywhere")), "19")
        self.assertIsInstance(res, SkippedOffer)
        self.assertEqual(res.reason, SKIP_MICROSOFT_NO_PAGE)


class TitreGenerique(unittest.TestCase):
    """« Microsoft Key » / « Microsoft Store Key » lus par `detect_platform`."""

    def test_gameboost_microsoft_key(self):
        name = "Call of Duty: Vanguard - Microsoft Key - UNITED STATES"
        url = "https://gameboost.com/call-of-duty-vanguard-microsoft-key-united-states-00-67108"
        ok = _match(name, url, "GameBoost", _page("Call of Duty Vanguard", COD_VANGUARD), "157")
        self.assertIsInstance(ok, Candidate, getattr(ok, "reason", ""))
        self.assertEqual((ok.platform, ok.region_id), ("MICROSOFT", "245"))
        ko = _match(name, url, "GameBoost",
                    _page("Call of Duty Vanguard", ("Steam", "Battle.net")), "157")
        self.assertIsInstance(ko, SkippedOffer)
        self.assertEqual(ko.reason, SKIP_MICROSOFT_NO_PAGE)

    def test_gameseal_microsoft_store_key(self):
        name = "Age of Empires III: Definitive Edition (PC) Microsoft Store Key - EU"
        url = "https://gameseal.com/age-of-empires-iii-definitive-edition-pc-microsoft-store-key-eu"
        ok = _match(name, url, "GameSeal", _page("Age of Empires 3 Definitive Edition", AOE3), "126")
        self.assertIsInstance(ok, Candidate, getattr(ok, "reason", ""))
        self.assertEqual((ok.platform, ok.region_id), ("MICROSOFT", "244"))
        ko = _match(name, url, "GameSeal",
                    _page("Age of Empires 3 Definitive Edition", ("Steam",)), "126")
        self.assertIsInstance(ko, SkippedOffer)
        self.assertEqual(ko.reason, SKIP_MICROSOFT_NO_PAGE)


class DiscoverPlateformeDeLaFiche(unittest.TestCase):
    def _disc(self, platforms):
        with mock.patch.object(disc, "fetch_product", return_value=("MICROSOFT", frozenset({"WW"}))):
            return _match("Halo Reach", "https://discover.games/games/halo-reach",
                          "Discover.games", _page("Halo Reach", platforms), "168")

    def test_la_fiche_dit_microsoft_la_page_aks_doit_le_confirmer(self):
        ok = self._disc(HALO_REACH)
        self.assertIsInstance(ok, Candidate, getattr(ok, "reason", ""))
        self.assertEqual((ok.platform, ok.region_id), ("MICROSOFT", "246"))
        ko = self._disc(("Steam",))
        self.assertIsInstance(ko, SkippedOffer)
        self.assertEqual(ko.reason, SKIP_MICROSOFT_NO_PAGE)


class UneSeuleVerification(unittest.TestCase):
    """La branche « (Windows) XBOX LIVE Key » et le chemin commun lisent la MÊME fonction."""

    def test_la_branche_windows_passe_par_la_verification_commune(self):
        name = "World War Z (PC) XBOX LIVE Key EUROPE"
        url = "https://www.eneba.com/xbox-world-war-z-pc-xbox-live-key-europe"
        page = _page("World War Z", ("Steam", "Epic Store", "Microsoft Windows"))
        ok = _match(name, url, "Eneba", page, "19")
        self.assertIsInstance(ok, Candidate, getattr(ok, "reason", ""))
        self.assertEqual(ok.platform, "MICROSOFT")
        with mock.patch.object(matcher, "page_sells_microsoft_store", return_value=False):
            ko = _match(name, url, "Eneba", page, "19")
        # C'est la BRANCHE qui refuse (son motif propre), avec la vérification commune — une
        # copie locale du test laisserait passer la branche et seul le garde commun refuserait.
        self.assertIsInstance(ko, SkippedOffer)
        self.assertEqual(ko.reason, SKIP_WINDOWS_KEY_NO_PAGE)


if __name__ == "__main__":
    unittest.main()

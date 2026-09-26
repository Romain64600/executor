"""Consoles — les réponses de Romain du 2026-09-26 aux points 1 et 2 (docs/EXECUTOR_RULES.md
§4.12).

* **1. Clé Windows / appli Xbox** (« (Windows) XBOX LIVE Key », « PC/XBOX LIVE Key », GameBoost
  « Windows 11/Xbox Live Key », G2A « (PC) - Xbox Live Key », Gamivo ``-xbox-pc-``). Romain a
  répondu par une explication collée : une telle clé s'active dans l'appli Xbox / le Microsoft
  Store sur Windows et marche sur PC ; elle ne débloque AUSSI la console que si le JEU est Xbox
  Play Anywhere — « ne vous fiez pas au titre, vérifiez si le jeu est Play Anywhere ». Donc :
  page PC d'AKS « Xbox Play Anywhere » → cibles Play Anywhere (pages Xbox qu'AKS a + page PC,
  cases XBOX/PC) ; sinon « Microsoft Windows » → clé Microsoft Store (MICROSOFT, Windows 10 :
  246 / 244 / 245 / 249) sur la page PC ; sinon refus. Avant : refus « PC-only Xbox Live key ».
* **2. « les 2 »** — le Xbox sans génération se lit dans le titre ET dans l'URL (etailcard
  « xbox-global-games-<jeu> », lootbar « …/<jeu>-xbox », Gamivo ``-xbox-us``). Une génération
  que l'URL DÉCLARE reste une plateforme déclarée (P1 : cette page seulement).

Les lignes sont RÉELLES (scan du 21/09) ; les pages AKS sont simulées d'après leur lecture du
26/09 (ligne « official platforms » et onglets) : Cassette Beasts {Steam, Xbox Play Anywhere,
Epic Store}, onglets One / Series ; Object Factory {Xbox Play Anywhere}, aucun onglet ;
Dishonored 2 {Xbox, Steam, GoG, Epic Store, Microsoft Windows} ; Lil Gator Game {Steam}."""

import unittest

from src.console_keys import (
    SKIP_NO_GENERATION,
    SKIP_WINDOWS_KEY_NO_PAGE,
    classify_console,
)
from src.contracts import NormalizedOffer
from src.matcher import AksResolution, Candidate, SkippedOffer, match_offer, precheck_skip

AKS = "https://www.allkeyshop.com/blog/"
PA = "Xbox Play Anywhere"


def _url(slug, kind):
    return f"{AKS}buy-{slug}-{kind}-compare-prices/"


def _page(name, pid, slug, kind="cd-key", editions=None, platforms=(), tabs=()):
    return AksResolution(
        slug=slug, url=_url(slug, kind), product_id=pid, aks_name=name,
        editions=editions if editions is not None else {"1": {"name": "Standard"}},
        official_platforms=tuple(platforms),
        console_pages={k: _url(slug, k) for k in tabs})


def _match(merchant, name, url, pc=None, pages=(), anchors=None, calls=None):
    by_url = {p.url: p for p in pages}
    anchors = anchors or {}
    calls = calls if calls is not None else []

    def resolver(resolve_name, **kw):
        calls.append((resolve_name, kw.get("page_kind")))
        return anchors.get(kw["page_kind"]) if "page_kind" in kw else pc

    offer = NormalizedOffer(offer_id="1", name=name, url=url, merchant=merchant)
    return match_offer(offer, resolver, page_resolver=by_url.get, consoles=True)


def _targets(res):
    return [(t.platform, t.aks_product_id, t.region_id, t.edition_id) for t in res.targets]


CASSETTE = ("Cassette Beasts PC/XBOX LIVE Key EUROPE",
            "https://www.eneba.com/xbox-cassette-beasts-pc-xbox-live-key-europe")
MANOR = ("Manor Lords (Windows) XBOX LIVE Key EUROPE",
         "https://www.eneba.com/xbox-manor-lords-windows-xbox-live-key-europe")


class Point1LaClassification(unittest.TestCase):
    def test_les_formes_reelles_sont_une_cle_windows_jamais_p2(self):
        for merchant, name, url, region in (
            ("Eneba", *CASSETTE, "eu"),
            ("Eneba", *MANOR, "eu"),
            ("GameBoost", "Rhythm Doctor - Windows 11/Xbox Live Key  - UNITED STATES",
             "https://gameboost.com/rhythm-doctor-windows-11xbox-live-key-united-states-00-75230", "us"),
            ("GameBoost", "CyberCorp - Xbox Live/PC Key - EU",
             "https://gameboost.com/cybercorp-xbox-livepc-key-eu-00-58571", "eu"),
            ("G2A", "Wolfenstein: The Old Blood (PC) - Xbox Live Key - GLOBAL",
             "https://www.g2a.com/wolfenstein-the-old-blood-pc-xbox-live-key-global-i10000000826004", "global"),
            ("Gamivo", "Dishonored 2 United States",
             "https://www.gamivo.com/product/dishonored-2-xbox-pc-us-standard", "us"),
            ("Eneba", "Call of Duty®: Black Ops II (2012) (Windows) Key UNITED STATES",
             "https://www.eneba.com/xbox-call-of-duty-r-black-ops-ii-2012-windows-key-united-states", "us"),
        ):
            with self.subTest(name):
                sig = classify_console(name, url, merchant)
                self.assertEqual((sig.skip_reason, sig.windows_key, sig.pc_declared, sig.region_base),
                                 (None, True, False, region))
                self.assertEqual(sig.families, ("XBOX_ONE", "XBOX_SERIES"))

    def test_une_vraie_declaration_xbox_plus_pc_reste_p2(self):
        # « (Windows/Xbox Series X|S) » : une génération ET Windows — le cas P2, pas une clé Windows
        sig = classify_console("MOTORSLICE (Windows/Xbox Series X|S) XBOX LIVE Key UNITED STATES",
                               "https://www.eneba.com/xbox-motorslice-windows-xbox-series-x-s-xbox-live-key-united-states",
                               "Eneba")
        self.assertEqual((sig.families, sig.pc_declared, sig.windows_key), (("XBOX_SERIES",), True, False))
        # le titre dit « Xbox » + Windows lui-même : P2, même si le créneau d'URL finit sur -windows- / -pc-
        for name, url in (
            ("BOUNCY BREAD (XBOX AND WINDOWS) XBOX LIVE Key EUROPE",
             "https://www.eneba.com/xbox-bouncy-bread-xbox-and-windows-xbox-live-key-europe"),
            ("Green Soldiers Heroes Collection (Xbox + PC) XBOX LIVE Key UNITED STATES",
             "https://www.eneba.com/xbox-green-soldiers-heroes-collection-xbox-pc-xbox-live-key-united-states"),
        ):
            with self.subTest(name):
                sig = classify_console(name, url, "Eneba")
                self.assertEqual((sig.pc_declared, sig.windows_key, sig.skip_reason), (True, False, None))

    def test_un_item_playstation_ou_nintendo_interdit_la_cle_windows(self):
        for name, url in (
            ("Some Game PC/XBOX LIVE Key EUROPE", "https://shop.example/some-game-pc-xbox-live-psn-key-europe"),
            ("Some Game PC/XBOX LIVE Key / PSN EUROPE", "https://shop.example/some-game"),
        ):
            with self.subTest(name):
                sig = classify_console(name, url, "all-stores")
                self.assertEqual((sig.windows_key, sig.skip_reason), (False, SKIP_NO_GENERATION))

    def test_une_licence_windows_n_est_pas_une_cle_de_jeu(self):
        from src.matcher import is_software_title
        offer = NormalizedOffer(offer_id="1", name="Windows 11 Pro Key GLOBAL", url="https://x/windows-11-pro",
                                merchant="GameBoost")
        self.assertIsNone(classify_console(offer.name, offer.url, offer.merchant))   # aucun marqueur console
        self.assertTrue(is_software_title(offer))
        jeu = NormalizedOffer(offer_id="1", name="Rhythm Doctor - Windows 11/Xbox Live Key  - UNITED STATES",
                              url="https://gameboost.com/rhythm-doctor-windows-11xbox-live-key-united-states-00-75230",
                              merchant="GameBoost")
        self.assertFalse(is_software_title(jeu))


class Point1LaPagePCDAKSTranche(unittest.TestCase):
    def test_play_anywhere_les_pages_xbox_qu_aks_a_et_la_page_pc(self):
        pc = _page("Cassette Beasts", "1000", "cassette-beasts", platforms=("Steam", PA, "Epic Store"),
                   tabs=("xbox-one", "xbox-series"))
        pages = [_page("Cassette Beasts Xbox One", "2000", "cassette-beasts", kind="xbox-one"),
                 _page("Cassette Beasts Xbox Series", "3000", "cassette-beasts", kind="xbox-series")]
        res = _match("Eneba", *CASSETTE, pc=pc, pages=pages)
        self.assertIsInstance(res, Candidate, getattr(res, "reason", None))
        self.assertEqual(_targets(res), [("XBOX_ONE", "2000", "241", "1"), ("XBOX_SERIES", "3000", "241", "1"),
                                         ("XBOX_PC", "1000", "241", "1")])

    def test_play_anywhere_sans_page_xbox_la_page_pc_seule(self):
        pc = _page("Object Factory", "1000", "object-factory", platforms=(PA,))
        res = _match("Eneba", "Object Factory (Windows) XBOX LIVE Key EUROPE",
                     "https://www.eneba.com/xbox-object-factory-windows-xbox-live-key-europe", pc=pc)
        self.assertIsInstance(res, Candidate, getattr(res, "reason", None))
        self.assertEqual((res.platform, res.aks_product_id, res.region_id), ("XBOX_PC", "1000", "241"))

    def test_sans_play_anywhere_mais_microsoft_windows_une_cle_microsoft_store(self):
        pc = _page("Dishonored 2", "1000", "dishonored-2",
                   platforms=("Xbox", "Steam", "GoG", "Epic Store", "Microsoft Windows"), tabs=("xbox-series",))
        calls = []
        res = _match("Gamivo", "Dishonored 2 United States",
                     "https://www.gamivo.com/product/dishonored-2-xbox-pc-us-standard", pc=pc, calls=calls)
        self.assertIsInstance(res, Candidate, getattr(res, "reason", None))
        self.assertEqual((res.platform, res.aks_product_id, res.region_id, res.edition_id),
                         ("MICROSOFT", "1000", "245", "1"))
        self.assertEqual(len(res.targets), 0)          # une clé PC : aucune cible console
        self.assertEqual(calls, [("Dishonored 2", None)])   # jamais une page console en ancre

    def test_chaque_region_prend_sa_case_windows_10(self):
        pc = _page("Manor Lords", "1000", "manor-lords", platforms=("Steam", "GoG", "Microsoft Windows"))
        for suffix, rid in (("EUROPE", "244"), ("UNITED STATES", "245"), ("UNITED KINGDOM", "249"),
                            ("GLOBAL", "246")):
            with self.subTest(suffix):
                res = _match("Eneba", f"Manor Lords (Windows) XBOX LIVE Key {suffix}",
                             "https://www.eneba.com/xbox-manor-lords-windows-xbox-live-key-"
                             + suffix.lower().replace(" ", "-"), pc=pc)
                self.assertIsInstance(res, Candidate, getattr(res, "reason", None))
                self.assertEqual((res.platform, res.region_id), ("MICROSOFT", rid))

    def test_ni_play_anywhere_ni_microsoft_windows_refus(self):
        pc = _page("Lil Gator Game", "1000", "lil-gator-game", platforms=("Steam",),
                   tabs=("xbox-one", "xbox-series"))
        res = _match("Eneba", "Lil Gator Game PC/XBOX LIVE Key EUROPE",
                     "https://www.eneba.com/xbox-lil-gator-game-pc-xbox-live-key-europe", pc=pc)
        self.assertIsInstance(res, SkippedOffer)
        self.assertEqual(res.reason, SKIP_WINDOWS_KEY_NO_PAGE)

    def test_le_titre_seul_ne_fait_jamais_play_anywhere(self):
        # le « Xbox + PC = Play Anywhere » de P2 ne s'applique PAS : sans la page, pas de console
        pc = _page("Lil Gator Game", "1000", "lil-gator-game", platforms=("Steam", "Microsoft Windows"),
                   tabs=("xbox-one", "xbox-series"))
        pages = [_page("Lil Gator Game Xbox One", "2000", "lil-gator-game", kind="xbox-one")]
        res = _match("Eneba", "Lil Gator Game PC/XBOX LIVE Key EUROPE",
                     "https://www.eneba.com/xbox-lil-gator-game-pc-xbox-live-key-europe", pc=pc, pages=pages)
        self.assertIsInstance(res, Candidate, getattr(res, "reason", None))
        self.assertEqual(res.platform, "MICROSOFT")

    def test_sans_page_pc_refus_meme_si_une_page_console_existe(self):
        calls = []
        res = _match("Eneba", *CASSETTE, pc=None,
                     anchors={"xbox-one": _page("Cassette Beasts Xbox One", "2000", "cassette-beasts",
                                                kind="xbox-one")}, calls=calls)
        self.assertIsInstance(res, SkippedOffer)
        self.assertIn("no AKS PC page", res.reason)
        self.assertEqual(calls, [("Cassette Beasts", None)])

    def test_un_dlc_microsoft_store_suit_r43(self):
        # le DLC n'a pas sa propre page : la page du jeu de base ne le porte pas → refus R43
        base = _page("Fortress Merge", "1000", "fortress-merge", platforms=("Steam", "Microsoft Windows"))
        res = _match("Eneba", "Fortress Merge: Strong Start Pack (DLC) PC/XBOX LIVE Key UNITED KINGDOM",
                     "https://www.eneba.com/xbox-fortress-merge-strong-start-pack-dlc-pc-xbox-live-key-united-kingdom",
                     pc=base)
        self.assertIsInstance(res, SkippedOffer)
        self.assertIn("R43", res.reason)
        # sa propre page, avec le seau DLC → entre en DLC(16), case Windows 10 UK
        own = _page("Fortress Merge: Strong Start Pack", "1001", "fortress-merge-strong-start-pack",
                    editions={"16": {"name": "DLC"}}, platforms=("Steam", "Microsoft Windows"))
        res = _match("Eneba", "Fortress Merge: Strong Start Pack (DLC) PC/XBOX LIVE Key UNITED KINGDOM",
                     "https://www.eneba.com/xbox-fortress-merge-strong-start-pack-dlc-pc-xbox-live-key-united-kingdom",
                     pc=own)
        self.assertIsInstance(res, Candidate, getattr(res, "reason", None))
        self.assertEqual((res.platform, res.region_id, res.edition_id), ("MICROSOFT", "249", "16"))


class Point2LeXboxDeLUrl(unittest.TestCase):
    def test_etailcard_et_lootbar_xbox_nu_dans_l_url(self):
        for name, url in (
            ("PAW Patrol World", "https://etailcard.com/xbox-global-games-paw-patrol-world-1354962"),
            ("Like a Dragon: Infinite Wealth",
             "https://etailcard.com/microsoft-games-xbox-usa-like-a-dragon-infinite-wealth-3031852"),
            ("FINAL FANTASY VII REMAKE INTERGRADE Global",
             "https://www.lootbar.com/game-key/final-fantasy-vii-remake-intergrade-xbox?assetid=2332792&activate=direct"),
        ):
            with self.subTest(url):
                sig = classify_console(name, url, "all-stores")
                self.assertEqual((sig.families, sig.skip_reason, sig.generation_inferred, sig.windows_key),
                                 (("XBOX_ONE", "XBOX_SERIES"), None, True, False))

    def test_les_pages_qu_aks_a(self):
        pc = _page("PAW Patrol World", "1000", "paw-patrol-world", platforms=("Steam",), tabs=("xbox-series",))
        pages = [_page("PAW Patrol World Xbox Series", "3000", "paw-patrol-world", kind="xbox-series")]
        res = _match("all-stores", "PAW Patrol World",
                     "https://etailcard.com/xbox-global-games-paw-patrol-world-1354962", pc=pc, pages=pages)
        self.assertIsInstance(res, Candidate, getattr(res, "reason", None))
        self.assertEqual(_targets(res), [("XBOX_SERIES", "3000", "300", "1")])

    def test_les_bornes(self):
        for name, url in (
            # le titre nomme une boutique PC : l'URL seule ne fait pas une clé Xbox
            ("Some Game (PC) Steam Key GLOBAL", "https://shop.example/xbox-deals-some-game-steam"),
            # pc / windows collé au Xbox nu : ambigu dans le vocabulaire partagé
            ("Some Game", "https://shop.example/some-game-xbox-pc-eu"),
            # un item PlayStation dans l'URL : jamais de Xbox déduit
            ("Some Game", "https://shop.example/some-game-xbox-psn-eu"),
        ):
            with self.subTest(url):
                sig = classify_console(name, url, "all-stores")
                self.assertEqual((sig.families, sig.skip_reason), ((), SKIP_NO_GENERATION))

    def test_une_generation_declaree_dans_l_url_reste_cette_page(self):
        sig = classify_console("Some Game", "https://shop.example/some-game-xbox-one-eu", "all-stores")
        self.assertEqual((sig.families, sig.generation_inferred), (("XBOX_ONE",), False))

    def test_gamivo_magasin_xbox_sans_segment_de_plateforme(self):
        sig = classify_console("Necromunda Underhive Wars EN/DE/FR/IT/PL/RU/ZH/ES United States",
                               "https://www.gamivo.com/product/necromunda-underhive-wars-xbox-us", "Gamivo")
        self.assertEqual((sig.families, sig.generation_inferred, sig.region_base),
                         (("XBOX_ONE", "XBOX_SERIES"), True, "us"))
        sig = classify_console("Destiny - The Collection EN United States",
                               "https://www.gamivo.com/product/destiny-the-collection-xbox-standard-xboxoneseries-us-en",
                               "Gamivo")
        self.assertEqual((sig.families, sig.generation_inferred), (("XBOX_ONE", "XBOX_SERIES"), False))

    def test_la_monnaie_reste_refusee_par_sa_categorie(self):
        for merchant, name, url in (
            ("Gamivo", "WWE 2K26 EU 32500 Virtual Currency",
             "https://www.gamivo.com/product/wwe-2k26-xbox-eu-32500-virtual-currency"),
            ("all-stores", "NBA 2K24 450000 VC",
             "https://etailcard.com/nba-2k24-vc-points-xbox-global-nba-2k24-450000-vc-1354781"),
        ):
            with self.subTest(name):
                offer = NormalizedOffer(offer_id="1", name=name, url=url, merchant=merchant)
                reason = precheck_skip(offer, consoles=True)
                self.assertIsNotNone(reason)
                self.assertNotIn("no declared generation", reason)


class P2ResteSansVerificationDePage(unittest.TestCase):
    """Romain, 2026-09-26 : « Xbox + PC reste playanywhere, pas de pb » — P2 (Xbox + PC DÉCLARÉS)
    ne lit pas la page PC ; seule la clé Windows SEULE (point 1) exige « Xbox Play Anywhere »."""

    def test_xbox_plus_pc_declares_sans_play_anywhere_sur_la_page(self):
        pc = _page("PAC-MAN MUSEUM+", "1000", "pac-man-museum", platforms=("Steam",),
                   tabs=("xbox-one", "xbox-series"))
        pages = [_page("PAC-MAN MUSEUM+ Xbox One", "2000", "pac-man-museum", kind="xbox-one"),
                 _page("PAC-MAN MUSEUM+ Xbox Series", "3000", "pac-man-museum", kind="xbox-series")]
        res = _match("K4G", "PAC-MAN MUSEUM+ EU XBOX One / Xbox Series X|S / PC CD Key",
                     "https://k4g.com/product/pac-man-museum-eu-xbox-one-xbox-series-x-s-pc-cd-key-X1",
                     pc=pc, pages=pages)
        self.assertIsInstance(res, Candidate, getattr(res, "reason", None))
        self.assertEqual(_targets(res), [("XBOX_ONE", "2000", "241", "1"), ("XBOX_SERIES", "3000", "241", "1"),
                                         ("XBOX_PC", "1000", "241", "1")])


if __name__ == "__main__":
    unittest.main()

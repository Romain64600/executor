"""Consoles — les décisions de Romain du 2026-09-25 : « P3 A, P5 A, P2 saisir sur les xbox
déclarées et sur PC (on le considère Play Anywhere) » (docs/EXECUTOR_RULES.md §4.12).

* **P3** — une clé PS5 hors GLOBAL prend la case PlayStation de PS4 : Europe `88eu`, US `88us`,
  UK `88uk` (GLOBAL garde `88ps5h`). Avant : « no region id for PS5/EU (R45) ».
* **P5** — un DLC / season pass console suit la règle des DLC PC `[R43]` : il n'entre que sur la
  page console DU DLC LUI-MÊME (slug du nom complet), qui porte le seau DLC (16) ; CHAQUE page
  cible est vérifiée, une seule qui manque et la ligne entière est refusée. Avant : « console:
  DLC / season pass on console — not entered yet (R45) ».
* **P2** — Xbox + PC déclarés alors que la page AKS ne liste pas « Xbox Play Anywhere » : on le
  considère Play Anywhere (pages Xbox déclarées + page PC, case XBOX/PC). « PC + famille non
  Xbox » reste une contradiction. Avant : « … does not list Xbox Play Anywhere — not entered ».

Les lignes sont des lignes RÉELLES refusées dans les skipped.json des deux VM (22-25/09) ; le
classifieur console est le vrai, seules les pages AKS sont simulées."""

import unittest

from src.contracts import NormalizedOffer
from src.matcher import AksResolution, Candidate, SkippedOffer, match_offer

AKS = "https://www.allkeyshop.com/blog/"
KINDS = ("cd-key", "xbox-one", "xbox-series", "ps4", "ps5", "nintendo-switch")


def _url(slug, kind):
    return f"{AKS}buy-{slug}-{kind}-compare-prices/"


def _page(name, pid, slug, kind="cd-key", editions=None, platforms=(), tabs=()):
    return AksResolution(
        slug=slug, url=_url(slug, kind), product_id=pid, aks_name=name,
        editions=editions if editions is not None else {"1": {"name": "Standard"}},
        official_platforms=tuple(platforms),
        console_pages={k: _url(slug, k) for k in tabs})


DLC = {"16": {"name": "DLC"}}


def _match(merchant, name, url, pc=None, pages=(), anchors=None, calls=None):
    """match_offer(consoles=True) — the REAL classifier; ``pc`` answers the PC-page resolution,
    ``anchors`` {kind: page} the console-anchor probe, ``pages`` the tab pages by URL."""

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


class P3LaPs5HorsGlobalPrendLaCasePlayStation(unittest.TestCase):
    def _ps5(self, slug, name, tabs=("ps5",)):
        pc = _page(name, "1000", slug, tabs=tabs)
        pages = [_page(f"{name} {k.upper()}", str(2000 + i), slug, kind=k) for i, k in enumerate(tabs)]
        return pc, pages

    def test_gta_vi_ps5_etats_unis_entre_en_88us(self):
        pc, pages = self._ps5("grand-theft-auto-vi", "Grand Theft Auto VI")
        res = _match("GameSeal", "Grand Theft Auto VI PRE-ORDER (PS5) PSN Key - UNITED STATES",
                     "https://gameseal.com/grand-theft-auto-vi-ps5-psn-key-united-states", pc=pc, pages=pages)
        self.assertIsInstance(res, Candidate, getattr(res, "reason", None))
        self.assertEqual((res.platform, res.region_id, res.region_label),
                         ("PS5", "88us", "Playstation Game Code US"))

    def test_kinguin_europe_entre_en_88eu(self):
        pc, pages = self._ps5("wrap-house-simulator", "Wrap House Simulator")
        res = _match("Kinguin", "Wrap House Simulator EU PS5 CD Key",
                     "https://www.kinguin.net/category/808771/wrap-house-simulator-eu-ps5-cd-key", pc=pc, pages=pages)
        self.assertIsInstance(res, Candidate, getattr(res, "reason", None))
        self.assertEqual(_targets(res), [("PS5", "2000", "88eu", "1")])

    def test_cjs_royaume_uni_entre_en_88uk(self):
        pc, pages = self._ps5("grand-theft-auto-online", "Grand Theft Auto Online")
        res = _match("CJS-CDKeys",
                     "Grand Theft Auto Online (PlayStation5) PSN Download Key (Playstation) UNITED KINGDOM",
                     "https://www.cjs-cdkeys.com/products/Grand-Theft-Auto-Online-%28PlayStation5%29-PSN-Download-"
                     "Key-%28Playstation%29-UNITED-KINGDOM.html", pc=pc, pages=pages)
        self.assertIsInstance(res, Candidate, getattr(res, "reason", None))
        self.assertEqual((res.region_id, res.region_label), ("88uk", "Playstation Game Code UK"))

    def test_cross_gen_ps4_ps5_us_les_deux_pages_en_88us(self):
        pc, pages = self._ps5("mortal-kombat-legacy-kollection", "Mortal Kombat: Legacy Kollection", tabs=("ps4", "ps5"))
        res = _match("Electronicfirst", "Mortal Kombat: Legacy Kollection  PS4 / PS5 US",
                     "https://www.electronicfirst.com/mortal-kombat-legacy-kollection-ps4-ps5-us", pc=pc, pages=pages)
        self.assertIsInstance(res, Candidate, getattr(res, "reason", None))
        self.assertEqual(_targets(res), [("PS4", "2000", "88us", "1"), ("PS5", "2001", "88us", "1")])

    def test_ps5_global_garde_sa_case(self):
        pc, pages = self._ps5("wrap-house-simulator", "Wrap House Simulator")
        res = _match("Kinguin", "Wrap House Simulator PS5 CD Key",
                     "https://www.kinguin.net/category/808771/wrap-house-simulator-ps5-cd-key", pc=pc, pages=pages)
        self.assertIsInstance(res, Candidate, getattr(res, "reason", None))
        self.assertEqual(res.region_id, "88ps5h")


class P5LeDlcConsoleSuitLaRegleDesDlcPc(unittest.TestCase):
    BF4 = ("GameSeal", "Battlefield 4 Premium (DLC) (Xbox One) Xbox Live Key - EU",
           "https://gameseal.com/battlefield-4-premium-dlc-xbox-one-xbox-live-key-eu")
    FENYX = ("GameSeal", "Immortals Fenyx Rising - Season Pass (DLC) (Xbox One / Xbox Series X|S) Xbox Live Key - GLOBAL",
             "https://gameseal.com/immortals-fenyx-rising-season-pass-dlc-xbox-one-xbox-series-x-s-xbox-live-key-global")

    def test_battlefield_4_premium_entre_en_dlc_sur_la_page_xbox_one_du_dlc(self):
        slug = "battlefield-4-premium"
        pc = _page("Battlefield 4 Premium", "1000", slug, editions=DLC, tabs=("xbox-one",))
        one = _page("Battlefield 4 Premium Xbox One", "2000", slug, kind="xbox-one", editions=DLC)
        calls = []
        res = _match(*self.BF4, pc=pc, pages=[one], calls=calls)
        self.assertIsInstance(res, Candidate, getattr(res, "reason", None))
        self.assertEqual(_targets(res), [("XBOX_ONE", "2000", "24eu", "16")])
        self.assertEqual(res.edition_label, "DLC")
        self.assertEqual(calls[0], ("Battlefield 4 Premium", None))      # le marqueur n'est pas dans le slug

    def test_la_page_du_jeu_de_base_est_refusee(self):
        # la devinette retombe sur « Battlefield 4 » (palier moins précis) : pas la page du DLC
        base = _page("Battlefield 4", "1000", "battlefield-4", tabs=("xbox-one",))
        one = _page("Battlefield 4 Xbox One", "2000", "battlefield-4", kind="xbox-one")
        res = _match(*self.BF4, pc=base, pages=[one])
        self.assertIsInstance(res, SkippedOffer)
        self.assertTrue(res.reason.startswith("console: XBOX_ONE — DLC in title but AKS page 'battlefield-4' "
                                              "carries no DLC edition"), res.reason)
        self.assertTrue(res.reason.endswith("(R43, R45)"))

    def test_une_page_dlc_qui_nest_pas_celle_du_nom_complet_est_refusee(self):
        # seau DLC présent, mais la page a été atteinte sous un autre slug que celui du titre
        pc = _page("Battlefield 4 Premium", "1000", "battlefield-4-premium-pack", editions=DLC, tabs=("xbox-one",))
        one = _page("Battlefield 4 Premium Xbox One", "2000", "battlefield-4-premium-pack", kind="xbox-one", editions=DLC)
        res = _match(*self.BF4, pc=pc, pages=[one])
        self.assertIsInstance(res, SkippedOffer)
        self.assertIn("not the DLC's own page", res.reason)
        self.assertIn("(R43, R45)", res.reason)

    def test_un_dlc_sans_nom_propre_sur_une_page_qui_vend_aussi_le_jeu_est_refuse(self):
        both = {"1": {"name": "Standard"}, "16": {"name": "DLC"}}
        pc = _page("Battlefield 4 Premium", "1000", "battlefield-4-premium", editions=both, tabs=("xbox-one",))
        one = _page("Battlefield 4 Premium Xbox One", "2000", "battlefield-4-premium", kind="xbox-one", editions=both)
        res = _match(*self.BF4, pc=pc, pages=[one])
        self.assertIsInstance(res, SkippedOffer)
        self.assertIn("without a DLC name of its own", res.reason)

    def test_season_pass_cross_gen_entre_sur_les_deux_pages_du_dlc(self):
        slug = "immortals-fenyx-rising-season-pass"
        pc = _page("Immortals Fenyx Rising Season Pass", "1000", slug, editions=DLC, tabs=("xbox-one", "xbox-series"))
        one = _page("Immortals Fenyx Rising Season Pass Xbox One", "2000", slug, kind="xbox-one", editions=DLC)
        series = _page("Immortals Fenyx Rising Season Pass Xbox Series", "3000", slug, kind="xbox-series", editions=DLC)
        res = _match(*self.FENYX, pc=pc, pages=[one, series])
        self.assertIsInstance(res, Candidate, getattr(res, "reason", None))
        self.assertEqual(_targets(res), [("XBOX_ONE", "2000", "24", "16"), ("XBOX_SERIES", "3000", "300", "16")])

    def test_une_page_de_dlc_qui_manque_refuse_toute_la_ligne(self):
        slug = "immortals-fenyx-rising-season-pass"
        pc = _page("Immortals Fenyx Rising Season Pass", "1000", slug, editions=DLC, tabs=("xbox-one", "xbox-series"))
        one = _page("Immortals Fenyx Rising Season Pass Xbox One", "2000", slug, kind="xbox-one", editions=DLC)
        series = _page("Immortals Fenyx Rising Season Pass Xbox Series", "3000", slug, kind="xbox-series")
        res = _match(*self.FENYX, pc=pc, pages=[one, series])
        self.assertIsInstance(res, SkippedOffer)
        self.assertTrue(res.reason.startswith("console: XBOX_SERIES — SEASON PASS in title but AKS page"), res.reason)

    def test_dlc_play_anywhere_la_page_pc_est_verifiee_aussi(self):
        name = ("ARK: Survival Ascended - ARK Animated Series 109-Costumes Pack DLC EU Xbox Series X|S / PC CD Key")
        url = ("https://www.kinguin.net/category/496729/ark-survival-ascended-ark-animated-series-109-costumes-pack-"
               "dlc-eu-xbox-series-x-s-pc-cd-key")
        slug = "ark-survival-ascended-ark-animated-series-109-costumes-pack"
        aks_name = "ARK Survival Ascended ARK Animated Series 109-Costumes Pack"
        series = _page(f"{aks_name} Xbox Series", "3000", slug, kind="xbox-series", editions=DLC)
        pc_dlc = _page(aks_name, "1000", slug, editions=DLC, tabs=("xbox-series",))
        res = _match("Kinguin", name, url, pc=pc_dlc, pages=[series])
        self.assertIsInstance(res, Candidate, getattr(res, "reason", None))
        self.assertEqual(_targets(res), [("XBOX_SERIES", "3000", "241", "16"), ("XBOX_PC", "1000", "241", "16")])
        pc_sans_dlc = _page(aks_name, "1000", slug, tabs=("xbox-series",))
        res = _match("Kinguin", name, url, pc=pc_sans_dlc, pages=[series])
        self.assertIsInstance(res, SkippedOffer)
        self.assertTrue(res.reason.startswith("console: XBOX_PC — DLC in title"), res.reason)


class P2XboxEtPcDeclaresEstPlayAnywhere(unittest.TestCase):
    def _pages(self, slug, name, platforms=("Steam",)):
        pc = _page(name, "1000", slug, platforms=platforms, tabs=("xbox-one", "xbox-series"))
        one = _page(f"{name} Xbox One", "2000", slug, kind="xbox-one")
        series = _page(f"{name} Xbox Series", "3000", slug, kind="xbox-series")
        return pc, [one, series]

    def test_pac_man_museum_trois_cibles_en_xbox_pc_eu(self):
        pc, pages = self._pages("pac-man-museum", "PAC-MAN MUSEUM+")
        res = _match("Electronicfirst", "PAC-MAN MUSEUM+ EU XBOX One / Xbox Series X|S / PC CD Key",
                     "https://www.electronicfirst.com/pac-man-museum-eu-xbox-one-xbox-series-xs-pc-cd-key",
                     pc=pc, pages=pages)
        self.assertIsInstance(res, Candidate, getattr(res, "reason", None))
        self.assertEqual(_targets(res), [("XBOX_ONE", "2000", "241", "1"), ("XBOX_SERIES", "3000", "241", "1"),
                                         ("XBOX_PC", "1000", "241", "1")])
        self.assertEqual(res.region_label, "XBOX/PC EU")

    def test_riot_civil_unrest_pc_en_tete(self):
        pc, pages = self._pages("riot-civil-unrest", "RIOT - Civil Unrest")
        res = _match("Electronicfirst", "RIOT- Civil Unrest PC EU XBOX One / Xbox Series X|S CD Key",
                     "https://www.electronicfirst.com/riot-civil-unrest-pc-eu-xbox-one-xbox-series-xs-cd-key",
                     pc=pc, pages=pages)
        self.assertIsInstance(res, Candidate, getattr(res, "reason", None))
        self.assertEqual([t.platform for t in res.targets], ["XBOX_ONE", "XBOX_SERIES", "XBOX_PC"])
        self.assertEqual({t.region_id for t in res.targets}, {"241"})

    def test_meme_resultat_que_quand_la_page_liste_play_anywhere(self):
        pc_pa, pages = self._pages("pac-man-museum", "PAC-MAN MUSEUM+", platforms=("Steam", "Xbox Play Anywhere"))
        pc_sans, _ = self._pages("pac-man-museum", "PAC-MAN MUSEUM+")
        args = ("Electronicfirst", "PAC-MAN MUSEUM+ EU XBOX One / Xbox Series X|S / PC CD Key",
                "https://www.electronicfirst.com/pac-man-museum-eu-xbox-one-xbox-series-xs-pc-cd-key")
        self.assertEqual(_targets(_match(*args, pc=pc_pa, pages=pages)), _targets(_match(*args, pc=pc_sans, pages=pages)))

    def test_sans_page_pc_chez_aks_la_ligne_est_refusee(self):
        _pc, pages = self._pages("pac-man-museum", "PAC-MAN MUSEUM+")
        one = pages[0]
        one = AksResolution(**{**one.__dict__, "console_pages": {"xbox-series": pages[1].url}})
        res = _match("Electronicfirst", "PAC-MAN MUSEUM+ EU XBOX One / Xbox Series X|S / PC CD Key",
                     "https://www.electronicfirst.com/pac-man-museum-eu-xbox-one-xbox-series-xs-pc-cd-key",
                     pc=None, pages=pages, anchors={"xbox-one": one})
        self.assertIsInstance(res, SkippedOffer)
        self.assertIn("AKS has no PC page", res.reason)

    def test_pc_avec_une_famille_non_xbox_reste_une_contradiction(self):
        res = _match("GameSeal", "FINAL FANTASY VIII - REMASTERED (PC) (Nintendo Switch) Nintendo Key - EU",
                     "https://gameseal.com/final-fantasy-viii-remastered-pc-nintendo-switch-nintendo-key-eu",
                     pc=_page("FINAL FANTASY VIII - REMASTERED", "1000", "final-fantasy-viii-remastered"))
        self.assertIsInstance(res, SkippedOffer)
        self.assertIn("contradictory delivery", res.reason)


if __name__ == "__main__":
    unittest.main()

"""Gamebillet `[R71]` — la fiche produit fait foi (2026-10-06, src/merchants/gamebillet.py).

Romain : « Puis Gamebillet » (après le go d'Indiegala `[R69]`). Modèle : Indiegala `[R69]` /
Allyouplay `[R68]`. Les fiches de ``tests/fixtures/gamebillet/`` sont des pages RÉELLES de
gamebillet.com relevées le 2026-10-06 ; les titres et les URL sont ceux du feed (scan
tous-magasins du 21/09, store 15). Hors liste blanche et hors groupe : rien ici n'écrit."""

import pathlib
import re
import unittest
from unittest import mock
from urllib.parse import urlsplit

from src.aks_env import HttpProbeResult
from src.console_keys import classify_console
from src.contracts import NormalizedOffer
from src.matcher import AksResolution, Candidate, SkippedOffer, match_offer
from src.merchants import gamebillet as gb
from src.merchants import indiegala
from src.merchants.gamesplanet import EU_MEMBERS, UK, US, region_from_lock
from src.merchants.registry import MERCHANT_STORE_IDS, merchant_config, merchant_for_store

FIX = pathlib.Path(__file__).resolve().parent / "fixtures" / "gamebillet"
BASE = "https://www.gamebillet.com/"


def _fiche(nom):
    return (FIX / f"{nom}.html").read_text(encoding="utf-8")


def _page(nom, chemin="/x"):
    return gb.parse_product_page(_fiche(nom), chemin)


def _offre(nom, chemin):
    return NormalizedOffer(offer_id="1", name=nom, url=BASE + chemin, merchant="Gamebillet",
                           store_id="15")


# (fixture, titre du feed, chemin après gamebillet.com/)
DUNEBOUND = ("monde_dunebound_tactics", "Dunebound Tactics", "dunebound-tactics")
V8 = ("monde_dlc_v8_power_pack", "Project Motor Racing: V8 Power Pack", "project-motor-racing-v8-power-pack")
BL4 = ("monde_dlc_borderlands_4_story_pack_2", "Borderlands®4 - Story Pack 2: FL4K and the Last Resort",
       "borderlands4-story-pack-2-fl4k-and-the-last-resort")
MGS = ("europe_usa_exclus_mgs_v_fatigues", "METAL GEAR SOLID V: THE PHANTOM PAIN - Fatigues (Naked Snake)",
       "metal-gear-solid-v-the-phantom-pain-fatigues-naked-snake-z")
RE1 = ("europe_usa_exclus_resident_evil_1996", "Resident Evil (1996)", "resident-evil-1996-z")
MHW = ("europe_usa_exclus_mh_wilds_cosmetic_pack", "Monster Hunter Wilds Extras Cosmetic DLC Pack",
       "monster-hunter-wilds-extras-cosmetic-dlc-pack-z")
DL2 = ("us_un_pays_ue_exclu_dying_light_2_reloaded", "Dying Light 2 Stay Human: Reloaded Edition",
       "dying-light-2-stay-human-reloaded-edition-z")
TW3 = ("linux_dlc_total_war_glottkin", "Total War: WARHAMMER III - The Glottkin – Lords of the End Times",
       "total-war-warhammer-iii-the-glottkin-lords-of-the-end-times-")
AOT3 = ("precommande_aot3", "Attack on Titan 3 / A.O.T. 3", "attack-on-titan-3-aot-3-pre-purchase-2")
BUNDLE = ("bundle_hello_games", "Hello Games (No Man's Sky) Exclusive Bundle", "hello-games-no-mans-sky-exclusive-bundle")
MORTE = ("fiche_morte_404_accueil", "Fiche morte", "this-product-does-not-exist-xyz-123")
FICHES = (DUNEBOUND, V8, BL4, MGS, RE1, MHW, DL2, TW3, AOT3, BUNDLE)


class _FetchFixture:
    """Remplace ``fetch_product_page`` : la fiche nommée, lue par le vrai parseur pour le chemin de
    l'URL demandée."""

    def __init__(self, nom):
        self.nom, self.appels = nom, []

    def __call__(self, url, http_get_fn=None):
        self.appels.append(url)
        cible = gb.product_url(url)
        return gb.parse_product_page(_fiche(self.nom), urlsplit(cible).path.lower())


def _aks(nom, plateformes=("Steam",), editions=None):
    return AksResolution(slug="x", url="https://aks/x", product_id="1", aks_name=nom,
                         editions=editions or {"1": "Standard", "7": "Deluxe", "16": "DLC"},
                         regions={"2": "GLOBAL"}, official_platforms=plateformes)


def _match(row, aks_name=None, plateformes=("Steam",), titre=None, editions=None):
    fixture, nom, chemin = row
    nom = titre or nom
    page = _aks(aks_name or nom, plateformes, editions)
    fetch = _FetchFixture(fixture)
    with mock.patch.object(gb, "fetch_product_page", side_effect=fetch):
        res = match_offer(_offre(nom, chemin), resolver=lambda n, **k: page, consoles=True)
    return res, fetch


class LaFiche(unittest.TestCase):
    """Le tableau de spécifications et la fenêtre « Restricted countries », sur les pages réelles."""

    def test_la_livraison_est_la_plateforme_pas_le_systeme(self):
        for row in FICHES:
            with self.subTest(row[1]):
                p = _page(row[0])
                self.assertEqual(p.delivery_text, "Steam")
                self.assertEqual(gb.page_platform(p), "STEAM")
        self.assertEqual(_page(TW3[0]).os_text, "Linux", "la ligne Platform est l'OS : lue, jamais décisive")
        self.assertEqual(_page(DUNEBOUND[0]).os_text, "Windows")
        self.assertEqual(_page(DUNEBOUND[0]).title, "Dunebound Tactics")

    def test_la_region_par_la_liste_des_pays_restreints(self):
        attendu = {DUNEBOUND: ("global", 36), V8: ("global", 0), BL4: ("global", 2), MGS: ("eu", 125),
                   RE1: ("eu", 132), MHW: ("eu", 132), DL2: ("us", 23), TW3: ("global", 33),
                   AOT3: ("global", 0), BUNDLE: ("global", 35)}
        for row, (base, n) in attendu.items():
            with self.subTest(row[1]):
                p = _page(row[0])
                self.assertEqual(len(p.restricted), n)
                self.assertEqual(gb.page_region(p), (base, ""))
        self.assertIn(US, _page(MGS[0]).restricted, "USA exclus → EU")
        self.assertNotIn(UK, _page(MGS[0]).restricted)
        self.assertEqual({c for c in _page(DL2[0]).restricted if c in EU_MEMBERS}, {"germany"},
                         "un pays de l'UE exclu (USK), USA autorisés → US ([R59], règle de Romain)")
        self.assertFalse(EU_MEMBERS & _page(DUNEBOUND[0]).restricted)

    def test_une_fenetre_vide_est_une_absence_de_restriction(self):
        # V8 Power Pack et la précommande AOT3 : la fenêtre est là, sans aucun pays → GLOBAL
        # (décision PROPOSÉE, à confirmer : aucune restriction publiée).
        self.assertEqual(_page(V8[0]).restricted, frozenset())
        self.assertEqual(gb.page_region(_page(V8[0])), ("global", ""))

    def test_une_fenetre_absente_est_un_refus_pas_un_global(self):
        corps = _fiche(DUNEBOUND[0]).replace('id="restrictedcountries-popup"', 'id="autre-chose"')
        with self.assertRaises(gb.GamebilletPageUnreadable) as ctx:
            gb.parse_product_page(corps, "/x")
        self.assertIn("Restricted countries", str(ctx.exception))

    def test_la_fiche_ne_porte_aucun_signal_dlc(self):
        # « Downloadable Content » dans Features est une catégorie Steam que portent aussi des jeux
        # de base (FAIRY TAIL 2 Digital Deluxe à l'aperçu du 06/10, refusée à tort par un premier
        # essai) ; 42 DLC sur 45 ne la portaient pas. La fiche ne dit donc rien du DLC.
        self.assertIn("Downloadable Content", _page(V8[0]).features)
        self.assertNotIn("Downloadable Content", _page(TW3[0]).features)   # un vrai DLC sans le mot
        self.assertFalse(hasattr(gb.ProductPage, "is_dlc"))
        for row in (V8, BL4, DUNEBOUND, TW3):
            with self.subTest(row[1]):
                fetch = _FetchFixture(row[0])
                with mock.patch.object(gb, "fetch_product_page", side_effect=fetch):
                    sig = gb.offer_signals(BASE + row[2], row[1])
                self.assertIsNone(sig.dlc)

    def test_la_page_d_accueil_n_est_pas_une_fiche(self):
        with self.assertRaises(gb.GamebilletPageUnreadable) as ctx:
            _page(MORTE[0])
        self.assertIn("table-responsive", str(ctx.exception))

    def test_une_livraison_inconnue_ou_absente_refuse_jamais_steam(self):
        corps = _fiche(DUNEBOUND[0]).replace("Delivery</td><td>Steam</td>", "Delivery</td><td>Amazon</td>")
        with self.assertRaises(gb.GamebilletPageUnreadable) as ctx:
            gb.page_platform(gb.parse_product_page(corps, "/x"))
        self.assertIn("Amazon", str(ctx.exception))
        corps = _fiche(DUNEBOUND[0]).replace("Delivery</td><td>Steam</td>", "Rien</td><td>Steam</td>")
        with self.assertRaises(gb.GamebilletPageUnreadable) as ctx:
            gb.parse_product_page(corps, "/x")
        self.assertIn("Delivery", str(ctx.exception))

    def test_les_autres_livraisons_connues(self):
        for texte, jeton in (("GOG", "GOG"), ("Epic Games", "EPIC"), ("Ubisoft Connect", "UBISOFT"),
                             ("EA app", "EA"), ("Rockstar", "ROCKSTAR"), ("Battle.net", "BATTLENET"),
                             ("Microsoft Store", "MICROSOFT")):
            corps = _fiche(DUNEBOUND[0]).replace("Delivery</td><td>Steam</td>", f"Delivery</td><td>{texte}</td>")
            self.assertEqual(gb.page_platform(gb.parse_product_page(corps, "/x")), jeton)

    def test_la_coupe_aux_virgules_ne_touche_aucun_nom_qui_decide(self):
        # « Korea, Democratic People's Republic of » se coupe en deux fragments — sans effet :
        # seuls les 27 noms de l'UE, « united kingdom » et « united states » décident, et une coupe
        # qui garde les parenthèses / qualificatifs donne les MÊMES décideurs sur toutes les fiches.
        deciders = EU_MEMBERS | {UK, US}
        for row in FICHES:
            with self.subTest(row[1]):
                brut = _fiche(row[0])
                naive = _page(row[0]).restricted & deciders
                m = gb._MODAL_RE.search(brut)
                bloc = gb._balanced_div(brut, m.start())
                texte = gb._clean(gb._MODAL_BODY_RE.search(bloc).group("body"))
                # coupe « prudente » : une virgule suivie d'un qualificatif (« Democratic… »,
                # « Republic… », « Islamic… ») reste dans le nom
                prudent = re.split(r",(?!\s*(?:Democratic|Republic|Islamic|Plurinational|Province|Federated|State|Bolivarian|U\.S\.|the))", texte)
                prudent_set = {gb.country_name(x) for x in prudent if x.strip()} & deciders
                self.assertEqual(naive, prudent_set)


class LaRequete(unittest.TestCase):
    def _get(self, corps, status=200):
        appels = []

        def get(url, timeout=20, user_agent=None):
            appels.append((url, user_agent))
            return HttpProbeResult(url=url, ok=status == 200, status=status, body=corps)
        return get, appels

    def setUp(self):
        gb.clear_cache()

    def test_la_fiche_est_ouverte_une_fois_avec_un_ua_navigateur(self):
        get, appels = self._get(_fiche(DUNEBOUND[0]))
        for _ in range(2):
            sig = gb.offer_signals(BASE + DUNEBOUND[2], DUNEBOUND[1], http_get_fn=get)
            self.assertEqual((sig.platform, sig.region_resolved, sig.region_base, sig.dlc),
                             ("STEAM", True, "global", None))
        self.assertEqual(len(appels), 1, "une seule requête par fiche")
        self.assertEqual(appels[0][0], BASE + DUNEBOUND[2])
        self.assertIn("Mozilla", appels[0][1])

    def test_la_query_et_le_fragment_sont_retires(self):
        get, appels = self._get(_fiche(DUNEBOUND[0]))
        gb.offer_signals(BASE + DUNEBOUND[2] + "?ref=aks#x", DUNEBOUND[1], http_get_fn=get)
        self.assertEqual(appels[0][0], BASE + DUNEBOUND[2])

    def test_un_404_est_une_fiche_retiree(self):
        get, _ = self._get(_fiche(MORTE[0]), status=404)
        with self.assertRaises(gb.GamebilletPageUnreadable) as ctx:
            gb.offer_signals(BASE + MORTE[2], http_get_fn=get)
        self.assertIn("404", str(ctx.exception))
        self.assertIn("retirée", str(ctx.exception))

    def test_un_lien_hors_domaine_ou_sans_slug_n_ouvre_rien(self):
        for url in ("https://www.gamebillet.com/", "https://autre.com/dunebound-tactics",
                    "https://www.gamebillet.com/a/b"):
            with self.subTest(url):
                with self.assertRaises(gb.GamebilletPageUnreadable):
                    gb.offer_signals(url, http_get_fn=lambda *a, **k: self.fail("aucune requête"))

    def test_un_echec_est_mis_en_cache_comme_un_refus(self):
        get, appels = self._get("", status=503)
        for _ in range(2):
            with self.assertRaises(gb.GamebilletPageUnreadable):
                gb.offer_signals(BASE + DUNEBOUND[2], http_get_fn=get)
        self.assertEqual(len(appels), 1)

    def test_le_moteur_par_defaut_est_la_bibliotheque_standard(self):
        import inspect
        for fn in (gb.fetch_product_page, gb.offer_signals):
            self.assertIs(inspect.signature(fn).parameters["http_get_fn"].default, gb.page_get)
        self.assertIsNot(gb.page_get, indiegala.page_get)
        self.assertIsNone(gb.product_url("https://www.indiegala.com/store/game/x/1"))
        self.assertEqual(gb.product_url("http://gamebillet.com/dunebound-tactics/"), BASE + "dunebound-tactics")


class DeBoutEnBout(unittest.TestCase):
    """Par ``match_offer`` : la page AKS est simulée, la fiche Gamebillet est la vraie."""

    def test_un_titre_nu_devient_un_candidat_steam_dans_la_region_de_la_fiche(self):
        for row, aks, region_id, label, edition in (
            (DUNEBOUND, "Dunebound Tactics", "2", "GLOBAL", "1"),
            (RE1, "Resident Evil (1996)", "9", "EU", "1"),
            (DL2, "Dying Light 2 Stay Human: Reloaded Edition", "8", "US", "1"),
        ):
            with self.subTest(row[1]):
                res, fetch = _match(row, aks_name=aks)
                self.assertIsInstance(res, Candidate, getattr(res, "reason", ""))
                self.assertEqual((res.platform, res.region_id, res.region_label,
                                  res.region_implicit, res.edition_id),
                                 ("STEAM", region_id, label, False, edition))
                self.assertEqual(fetch.appels, [BASE + row[2]])

    def test_le_seau_dlc_vient_de_la_page_aks_jamais_de_la_fiche(self):
        # V8 Power Pack : sur SA page AKS à seau DLC unique → DLC(16) par R18 (titre sans marqueur,
        # seau DLC seul). La fiche n'y est pour rien, et une édition Deluxe dont la fiche porte
        # « Downloadable Content » (FAIRY TAIL 2 Digital Deluxe) entre en Deluxe, pas en refus.
        res, _ = _match(V8, aks_name="Project Motor Racing: V8 Power Pack", editions={"16": "DLC"})
        self.assertIsInstance(res, Candidate, getattr(res, "reason", ""))
        self.assertEqual(res.edition_id, "16")
        # (la fiche V8 — avec le mot — servie pour un titre d'édition Deluxe, comme FAIRY TAIL 2 ;
        # l'URL de l'offre ne doit pas dire « pack », que le matcher lit comme un bundle)
        fetch = _FetchFixture(V8[0])
        with mock.patch.object(gb, "fetch_product_page", side_effect=fetch):
            res = match_offer(_offre("FAIRY TAIL 2 Digital Deluxe", "fairy-tail-2-digital-deluxe"),
                              resolver=lambda n, **k: _aks("Fairy Tail 2", editions={"1": "Standard", "7": "Deluxe"}),
                              consoles=True)
        self.assertIsInstance(res, Candidate, getattr(res, "reason", ""))
        self.assertEqual(res.edition_id, "7")
        self.assertEqual(len(fetch.appels), 1)

    def test_la_page_aks_doit_vendre_la_plateforme_de_la_fiche(self):
        res, _ = _match(DUNEBOUND, plateformes=("Epic Store",))
        self.assertIsInstance(res, SkippedOffer)
        self.assertIn("R20", res.reason)

    def test_un_bundle_est_refuse_sans_ouvrir_la_fiche(self):
        res, fetch = _match(BUNDLE, aks_name="No Man's Sky")
        self.assertIsInstance(res, SkippedOffer)
        self.assertIn("BUNDLE", res.reason)
        self.assertEqual(fetch.appels, [])

    def test_une_fiche_illisible_n_entre_jamais(self):
        with mock.patch.object(gb, "fetch_product_page",
                               side_effect=gb.GamebilletPageUnreadable("503")):
            res = match_offer(_offre(*DUNEBOUND[1:]),
                              resolver=lambda n, **k: _aks("Dunebound Tactics", ("Steam", "Direct Publisher")),
                              consoles=True)
        self.assertIsInstance(res, SkippedOffer)
        self.assertIn("unreadable", res.reason)
        self.assertIn("(R71)", res.reason) if "R71" in res.reason else None

    def test_le_verrou_ue_et_usa_est_un_refus_nomme(self):
        corps = _fiche(MGS[0]).replace("United States,", "United States,France,")
        page = gb.parse_product_page(corps, "/x")
        self.assertEqual(gb.page_region(page), (None, "GAMEBILLET LOCK (EU + US)"))
        fetch = _FetchFixture(MGS[0])

        def faux(url, http_get_fn=None):
            fetch.appels.append(url)
            return page
        with mock.patch.object(gb, "fetch_product_page", side_effect=faux):
            res = match_offer(_offre(MGS[1], MGS[2]),
                              resolver=lambda n, **k: _aks(MGS[1]), consoles=True)
        self.assertIsInstance(res, SkippedOffer)
        self.assertEqual(res.reason, "forbidden region: GAMEBILLET LOCK (EU + US)")

    def test_le_titre_bilingue_reste_entier(self):
        # « Attack on Titan 3 / A.O.T. 3 » : pas d'alias inventé, R01 refuse si la page AKS ne
        # porte pas ces mots (même décision qu'Indiegala [R69]).
        res, _ = _match(AOT3, aks_name="Attack on Titan 3")
        self.assertIsInstance(res, SkippedOffer)
        self.assertNotIn("unreadable", res.reason)

    def test_une_ligne_console_lit_la_fiche_et_refuse_le_conflit(self):
        nom = "Hades (Nintendo Switch)"
        self.assertIsNotNone(classify_console(nom, BASE + DUNEBOUND[2], "Gamebillet"))
        fetch = _FetchFixture(DUNEBOUND[0])
        with mock.patch.object(gb, "fetch_product_page", side_effect=fetch):
            res = match_offer(_offre(nom, DUNEBOUND[2]), resolver=lambda n, **k: None, consoles=True)
        self.assertIsInstance(res, SkippedOffer)
        self.assertIn("platform conflict: console row vs offer page=STEAM", res.reason)
        self.assertEqual(len(fetch.appels), 1)


class LeRegistre(unittest.TestCase):
    def test_gamebillet_est_enregistre_hors_liste_blanche_et_hors_groupe(self):
        cfg = merchant_config("Gamebillet")
        self.assertIs(cfg.offer_page_resolver, gb.offer_signals)
        self.assertTrue(cfg.console_page_authoritative)
        self.assertEqual(cfg.domain, "gamebillet.com")
        self.assertIsNone(cfg.title_region)
        self.assertEqual(MERCHANT_STORE_IDS["Gamebillet"], "15")
        trouve = merchant_for_store("15")
        self.assertEqual(getattr(trouve, "name", trouve), "Gamebillet")
        # Hors liste blanche, hors groupe : aperçu à blanc d'abord, go de Romain ensuite.
        from src.admin.auto_merchants import AUTO_MERCHANTS
        from src import merchant_groups
        self.assertNotIn("15", {store for _, store in AUTO_MERCHANTS})
        self.assertNotIn("GAMEBILLET", {nom.upper() for nom, _ in AUTO_MERCHANTS})
        for groupe in merchant_groups.group_names():
            with self.subTest(groupe):
                self.assertNotIn("15", {store for _, store in merchant_groups.group_targets(groupe)})

    def test_les_autres_marchands_ne_bougent_pas(self):
        self.assertIs(merchant_config("Indiegala").offer_page_resolver, indiegala.offer_signals)
        self.assertEqual(region_from_lock(("NOT", frozenset({"germany"}))), ("us", ""))
        self.assertEqual(region_from_lock(("NOT", frozenset({US}))), ("eu", ""))
        self.assertEqual(region_from_lock(None), ("global", ""))


if __name__ == "__main__":
    unittest.main()

"""Allyouplay `[R68]` — la fiche produit fait foi (2026-09-30, src/merchants/allyouplay.py).

Romain : « go pour 1 » — « lire la page Allyouplay de chaque offre, comme pour Gamesplanet FR :
elle s'ouvre sans blocage et donne la plateforme (Platform: Steam) et la liste complète des pays
où la clé s'active ». Les fiches de ``tests/fixtures/allyouplay/`` sont des extraits RÉELS
d'allyouplay.com relevés le 2026-09-30 (titre, lien canonique, payload Nuxt). Les titres et les
liens sont ceux du feed (runs du groupe B, 17/09 → 26/09 ; aperçu par page du 29/09)."""

import pathlib
import unittest
from unittest import mock
from urllib.parse import quote, urlsplit

from src.aks_env import HttpProbeResult
from src.contracts import NormalizedOffer
from src.matcher import AksResolution, Candidate, SkippedOffer, match_offer, precheck_skip
from src.merchants import allyouplay as a
from src.merchants import gamesplanet
from src.merchants.registry import merchant_config

FIX = pathlib.Path(__file__).resolve().parent / "fixtures" / "allyouplay"
HOTE = "https://anandadigitalbv.sjv.io/c/1297091/2866230/30655"


def _aff(chemin):
    return f"{HOTE}?prodsku=42863&u={quote('https://www.allyouplay.com/' + chemin, safe='')}&intsrc=CATF_22827"


def _fiche(nom):
    return (FIX / f"{nom}.html").read_text(encoding="utf-8")


def _page(nom):
    """La fiche lue par le vrai parseur, pour le chemin qu'elle déclare elle-même."""

    corps = _fiche(nom)
    chemin = urlsplit(a._CANONICAL_RE.search(corps).group("href")).path.lower()
    return a.parse_product_page(corps, chemin)


def _offre(nom, chemin):
    return NormalizedOffer(offer_id="1", name=nom, url=_aff(chemin), merchant="Allyouplay",
                           store_id="17")


# (fixture, titre du feed, chemin de `u`)
NIVALIS = ("monde_nivalis_nights", "Nivalis Nights", "pc/nivalis-nights-2")
HUMAN = ("europe_human_fall_flat", "Human Fall Flat", "pc/human-fall-flat-3")
FROSTPUNK = ("us_frostpunk_goty", "Frostpunk: Game Of The Year Edition",
             "pc/frostpunk-game-of-the-year-edition")
XCOM = ("url_gog_page_steam_xcom_apocalypse", "X-COM: Apocalypse",
        "pc/x-com-apocalypse-take-ga-gog-xcomapocal-xxx-t2wwd-take-ga-gog-xcomapocal-xxx-t2wwd")
PERSIA = ("mac_os_seul_civ_vi_persia_macedon",
          "Sid Meier's Civilization VI - Persia and Macedon Civilization & Scenar",
          "pc/sid-meiers-civilization-vi-persia-and-macedon-civilization-scenario")
ESO = ("plateforme_inconnue_eso", "Elder Scrolls Online: Deluxe Edition (Steam)",
       "pc/the-elder-scrolls-online-2025-premium-edition-2")
TINDER = ("sans_plateforme_tinder_fr", "Tinder Gold - One Month FR",
          "subscription/tinder-gold-1-month-fr")
NHL_BE = ("belgique_nhl_26_xbox", "NHL 26: Standard Edition - Xbox Series X|S - BE",
          "pc/nhl-26-standard-edition-xbox-series-xs-game-alleen-voor-belgie-ep2-28972-ep2-28972")
ONIMUSHA = ("xbox_onimusha", "Onimusha: Way of the Sword - Xbox Series X|S",
            "xbox/onimusha-way-of-the-sword-xbox-series-xs-game-7d4-00792-7d4-00792")


class _FetchFixture:
    """Remplace ``fetch_product_page`` : la fiche du chemin demandé, lue par le vrai parseur."""

    def __init__(self, nom):
        self.nom, self.appels = nom, 0

    def __call__(self, url, http_get_fn=None):
        self.appels += 1
        cible = a.landing(url)
        return a.parse_product_page(_fiche(self.nom), urlsplit(cible).path.lower())


def _match(row, plateformes=("Steam",), consoles=True, resolver=None):
    fixture, nom, chemin = row
    page = AksResolution(slug="x", url="https://aks/x", product_id="1", aks_name=nom.split(" - ")[0],
                         editions={"1": "Standard", "7": "Deluxe", "11": "GOTY"},
                         regions={"2": "GLOBAL"}, official_platforms=plateformes)
    fetch = _FetchFixture(fixture)
    with mock.patch.object(a, "fetch_product_page", side_effect=fetch):
        res = match_offer(_offre(nom, chemin), resolver=resolver or (lambda n, **k: page),
                          consoles=consoles)
    return res, fetch


class LOrdreTitreUrlPage(unittest.TestCase):
    """Romain, 2026-09-18 : « un check du titre par défaut avant d'ouvrir la page »."""

    def test_titre_mac_refuse_sans_ouvrir_la_page(self):
        for nom in ("Sid Meier's Civilization VI [Mac]", "Torn [Mac]",
                    "BioShock Infinite - Season Pass [Mac]"):
            with self.subTest(nom):
                offre = _offre(nom, "pc/torn-2")
                raison = precheck_skip(offre, consoles=True)
                self.assertIn("clé Mac", raison)
                self.assertIn("R68", raison)
                with mock.patch.object(a, "fetch_product_page") as fetch:
                    res = match_offer(offre, resolver=lambda n, **k: None, consoles=True)
                self.assertIsInstance(res, SkippedOffer)
                fetch.assert_not_called()

    def test_les_codes_observes_du_slug(self):
        for chemin, attendu in (
            ("pc/108-silly-ways-to-die-azic-ga-ste-108sillywa-sta-res30-azic-ga-ste-108sillywa-sta-res30",
             "STEAM"),
            ("pc/sid-meiers-civilization-vi-take-ga-ste-civiliza22-xxx-t2wwd-take-ga-ste-civiliza22-xxx-t2wwd",
             "STEAM"),
            ("pc/x-com-terror-from-the-deep-take-ga-gog-xcomterror-xxx-t2wwd-take-ga-gog-xcomterror-xxx-t2wwd",
             "GOG"),
            ("pc/nivalis-nights-2", None),                         # rien n'est deviné
            ("pc/puddle-ww", None),
            ("pc/cloudscrapers-curv-ga-ste-cloudscrap-sta-cnprc-curv-ga-ste-cloudscrap-sta-cnprc",
             "STEAM"),
        ):
            with self.subTest(chemin):
                self.assertEqual(a.url_platform(_aff(chemin)), attendu)

    def test_un_lien_d_un_autre_site_ne_donne_rien(self):
        self.assertIsNone(a.url_platform("https://www.g2a.com/x-take-ga-ste-y"))

    def test_url_et_page_en_desaccord_est_un_refus(self):
        # X-COM Apocalypse : `-ga-gog-` dans le slug, « Platform: Steam » sur la fiche (30/09).
        res, _ = _match(XCOM)
        self.assertIsInstance(res, SkippedOffer)
        self.assertIn("platform conflict", res.reason)
        self.assertIn("GOG", res.reason)


class LaFiche(unittest.TestCase):
    def test_fiches_reelles(self):
        for nom, plateforme, region in (
            ("monde_nivalis_nights", "STEAM", ("global", "")),        # 177 pays, UE + GB + US
            ("europe_human_fall_flat", "STEAM", ("eu", "")),          # 50 pays, sans les USA
            ("us_frostpunk_goty", "STEAM", ("us", "")),               # sans CY / CZ / HU / PL
            ("url_gog_page_steam_xcom_apocalypse", "STEAM", ("global", "")),
            ("belgique_nhl_26_xbox", None, (None, "ALLYOUPLAY LOCK (EU + US)")),   # Belgique seule
            ("xbox_onimusha", None, (None, "ALLYOUPLAY LOCK (EU + US)")),          # 22 pays
        ):
            with self.subTest(nom):
                page = _page(nom)
                self.assertEqual(a.page_platform(page), plateforme)
                self.assertEqual(a.page_region(page), region)

    def test_le_visiteur_n_est_pas_le_produit(self):
        # `customer_country` (FR) et `is_available_for_country` décrivent le VISITEUR : la fiche
        # Belgique seule reste un refus, lue depuis la France.
        corps = _fiche("belgique_nhl_26_xbox")
        self.assertIn('"customer_country"', corps)
        self.assertEqual(_page("belgique_nhl_26_xbox").available_countries, frozenset({"BE"}))

    def test_une_plateforme_inconnue_est_refusee_par_son_nom(self):
        with self.assertRaises(a.AllyouplayPageUnreadable) as ctx:
            a.page_platform(_page("plateforme_inconnue_eso"))
        self.assertIn("ELDER SCROLLS ONLINE", str(ctx.exception))

    def test_une_cle_mac_os_seule_n_est_pas_une_cle_pc(self):
        # « Civilization VI - Persia and Macedon … » : titre SANS « [Mac] », fiche « Mac OS » seul.
        for nom in ("mac_os_seul_civ_vi_persia_macedon", "mac_civ_vi"):
            with self.subTest(nom), self.assertRaises(a.AllyouplayPageUnreadable) as ctx:
                a.page_platform(_page(nom))
            self.assertIn("pas Windows", str(ctx.exception))

    def test_sans_attribut_platform_la_fiche_est_illisible(self):
        # Tinder Gold FR (/subscription/) : « Universal OS », pas de « Platform ».
        with self.assertRaises(a.AllyouplayPageUnreadable) as ctx:
            _page("sans_plateforme_tinder_fr")
        self.assertIn("Platform", str(ctx.exception))

    def test_la_page_doit_etre_la_fiche_demandee(self):
        with self.assertRaises(a.AllyouplayPageUnreadable) as ctx:
            a.parse_product_page(_fiche("monde_nivalis_nights"), "/pc/transport-fever-3")
        self.assertIn("fiche demandée", str(ctx.exception))

    def test_les_formes_cassees_levent_au_lieu_de_donner_global(self):
        corps = _fiche("monde_nivalis_nights")
        chemin = "/pc/nivalis-nights-2"
        for nom, casse in (
            ("sans canonique", corps.replace('rel="canonical"', 'rel="alternate"')),
            ("sans payload", corps.replace('id="__NUXT_DATA__"', 'id="autre"')),
            ("payload illisible", corps.replace('id="__NUXT_DATA__">[', 'id="__NUXT_DATA__">[[')),
            ("sans pays", corps.replace('"available_countries"', '"countries_x"')),
            ("maintenance", "<html><body>Maintenance</body></html>"),
        ):
            with self.subTest(nom), self.assertRaises(a.AllyouplayPageUnreadable):
                a.parse_product_page(casse, chemin)


class LaRegleDeRomainSurLesPaysAutorises(unittest.TestCase):
    """`[R59]` (Gamesplanet FR, 25/09), la MÊME table, lue sur la liste des pays AUTORISÉS."""

    UE = sorted(k for k in a.ISO2_TO_NAME if k not in ("GB", "US"))

    def _region(self, pays):
        return a.page_region(a.ProductPage("STEAM", ("Windows",), frozenset(pays)))

    def test_table(self):
        for pays, attendu in (
            (self.UE + ["GB", "US", "CA", "JP"], "global"),
            (self.UE + ["GB", "US"], "global"),           # le reste du monde absent : GLOBAL
            (self.UE + ["GB", "NO", "CH"], "eu"),          # UE complète, USA absents
            (self.UE + ["NO"], "eu"),                      # idem, Royaume-Uni absent aussi
            ([c for c in self.UE if c != "PL"] + ["GB", "US"], "us"),   # un pays de l'UE absent
            (["US", "CA"], "us"),                          # UE absente, USA présents
            (["BE"], None),                                # UE incomplète ET USA absents
            (["FR"], None),
        ):
            with self.subTest(n=len(pays), attendu=attendu):
                base, libelle = self._region(pays)
                self.assertEqual(base, attendu)
                if base is None:
                    self.assertEqual(libelle, "ALLYOUPLAY LOCK (EU + US)")

    def test_ue_et_usa_la_royaume_uni_seul_absent_est_un_refus(self):
        base, libelle = self._region(self.UE + ["US"])
        self.assertIsNone(base)
        self.assertEqual(libelle, "ALLYOUPLAY LOCK (UK)")

    def test_une_seule_table_de_l_ue(self):
        self.assertEqual(frozenset(v for k, v in a.ISO2_TO_NAME.items() if k not in ("GB", "US")),
                         gamesplanet.EU_MEMBERS)

    def test_gamesplanet_garde_son_libelle(self):
        self.assertEqual(gamesplanet.region_from_lock(("ONLY", frozenset({"japan"})))[1],
                         "GAMESPLANET LOCK (EU + US)")


class LaRequete(unittest.TestCase):
    """Une requête par fiche et par processus ; tout échec est un refus, jamais un défaut."""

    def setUp(self):
        a.clear_cache()
        self.addCleanup(a.clear_cache)

    def _get(self, corps, status=200, leve=None):
        appels = []

        def get(url, timeout=20, user_agent=None, **kw):
            appels.append((url, user_agent))
            if leve:
                raise leve
            return HttpProbeResult(url=url, ok=status == 200, status=status, body=corps)
        return get, appels

    def test_la_fiche_de_u_est_ouverte_une_fois_avec_un_ua_navigateur(self):
        get, appels = self._get(_fiche("monde_nivalis_nights"))
        url = _aff("pc/nivalis-nights-2")
        for _ in range(2):
            sig = a.offer_signals(url, "Nivalis Nights", http_get_fn=get)
            self.assertEqual((sig.platform, sig.region_resolved, sig.region_base),
                             ("STEAM", True, "global"))
        self.assertEqual(len(appels), 1, "une seule requête par fiche")
        self.assertEqual(appels[0][0], "https://www.allyouplay.com/pc/nivalis-nights-2")
        self.assertIn("Mozilla", appels[0][1])

    def test_un_echec_est_garde_et_ne_rouvre_pas_la_page(self):
        get, appels = self._get("", status=503)
        url = _aff("pc/nivalis-nights-2")
        for _ in range(2):
            with self.assertRaises(a.AllyouplayPageUnreadable):
                a.offer_signals(url, "Nivalis Nights", http_get_fn=get)
        self.assertEqual(len(appels), 1)

    def test_injoignable_leve(self):
        get, _ = self._get("", leve=OSError("reset"))
        with self.assertRaises(a.AllyouplayPageUnreadable) as ctx:
            a.offer_signals(_aff("pc/nivalis-nights-2"), http_get_fn=get)
        self.assertIn("injoignable", str(ctx.exception))

    def test_aucune_autre_page_n_est_lue(self):
        get, appels = self._get(_fiche("monde_nivalis_nights"))
        for url in ("https://www.g2a.com/nivalis-nights", f"{HOTE}?prodsku=42863",
                    f"{HOTE}?u={quote('https://www.g2a.com/x', safe='')}"):
            with self.subTest(url), self.assertRaises(a.AllyouplayPageUnreadable):
                a.offer_signals(url, http_get_fn=get)
        self.assertEqual(appels, [])

    def test_une_fiche_servie_pour_un_autre_produit_est_refusee(self):
        get, _ = self._get(_fiche("monde_nivalis_nights"))
        with self.assertRaises(a.AllyouplayPageUnreadable):
            a.offer_signals(_aff("pc/transport-fever-3"), http_get_fn=get)


class DeBoutEnBout(unittest.TestCase):
    """Par ``match_offer`` : la page AKS est simulée, la fiche Allyouplay est la vraie."""

    def test_un_titre_pc_nu_devient_un_candidat_steam(self):
        # Avant `[R68]` : « no platform in title and AKS page does not confirm Direct
        # Publisher » (R27 / [R51]) — 0 candidat PC sur 219 à l'aperçu du 30/09.
        for row, region_id in ((NIVALIS, "2"), (HUMAN, "9"), (FROSTPUNK, "8")):
            with self.subTest(row[1]):
                res, fetch = _match(row)
                self.assertIsInstance(res, Candidate, getattr(res, "reason", ""))
                self.assertEqual((res.platform, res.region_id, res.region_implicit),
                                 ("STEAM", region_id, False))
                self.assertEqual(fetch.appels, 1)

    def test_le_code_steam_du_slug_et_la_fiche_s_accordent(self):
        row = ("monde_nivalis_nights", "Nivalis Nights",
               "pc/nivalis-nights-azic-ga-ste-nivalis-sta-res30")
        # la fiche Nivalis déclare son propre chemin : on la sert pour ce chemin-ci
        fetch = lambda url, http_get_fn=None: _page("monde_nivalis_nights")   # noqa: E731
        page = AksResolution(slug="x", url="https://aks/x", product_id="1", aks_name="Nivalis Nights",
                             editions={"1": "Standard"}, regions={"2": "GLOBAL"},
                             official_platforms=("Steam",))
        with mock.patch.object(a, "fetch_product_page", side_effect=fetch):
            res = match_offer(_offre(row[1], row[2]), resolver=lambda n, **k: page, consoles=True)
        self.assertIsInstance(res, Candidate, getattr(res, "reason", ""))
        self.assertEqual(res.platform, "STEAM")

    def test_la_page_aks_doit_vendre_la_plateforme_de_la_fiche(self):
        res, _ = _match(NIVALIS, plateformes=("Epic Store",))
        self.assertIsInstance(res, SkippedOffer)
        self.assertIn("R20", res.reason)

    def test_les_refus_de_fiche(self):
        for row, attendu in ((PERSIA, "pas Windows"), (ESO, "ELDER SCROLLS ONLINE"),
                             (TINDER, "Platform")):
            with self.subTest(row[1]):
                res, _ = _match(row)
                self.assertIsInstance(res, SkippedOffer)
                self.assertIn(attendu, res.reason)
                self.assertIn("R32", res.reason)

    def test_une_fiche_illisible_n_entre_jamais(self):
        page = AksResolution(slug="x", url="https://aks/x", product_id="1", aks_name="Nivalis Nights",
                             editions={"1": "Standard"}, regions={"2": "GLOBAL"},
                             official_platforms=("Steam", "Direct Publisher"))
        with mock.patch.object(a, "fetch_product_page",
                               side_effect=a.AllyouplayPageUnreadable("503")):
            res = match_offer(_offre("Nivalis Nights", "pc/nivalis-nights-2"),
                              resolver=lambda n, **k: page, consoles=True)
        self.assertIsInstance(res, SkippedOffer)
        self.assertIn("unreadable", res.reason)

    def test_xbox_la_region_vient_de_la_fiche_jamais_global(self):
        # NHL 26 « - BE » (Belgique seule) et Onimusha (22 pays, ni l'UE entière ni les USA) :
        # à l'aperçu du 30/09 (sans fiche), Onimusha entrait en XBOX/PC GLOBAL implicite.
        for row in (NHL_BE, ONIMUSHA):
            with self.subTest(row[1]):
                res, _ = _match(row, resolver=lambda n, **k: None)
                self.assertIsInstance(res, SkippedOffer)
                self.assertNotIn("GLOBAL", getattr(res, "region_label", "") or "")
                self.assertTrue("forbidden region" in res.reason or "BE" in res.reason
                                or "BELGIUM" in res.reason, res.reason)


class LesAutresMarchandsNeBougentPas(unittest.TestCase):
    def test_seul_allyouplay_lit_cette_fiche(self):
        self.assertIs(merchant_config("Allyouplay").offer_page_resolver, a.offer_signals)
        self.assertIsNone(merchant_config("Loaded").offer_page_resolver)
        self.assertIs(merchant_config("Gamesplanet FR").offer_page_resolver,
                      gamesplanet.offer_signals)


if __name__ == "__main__":
    unittest.main()

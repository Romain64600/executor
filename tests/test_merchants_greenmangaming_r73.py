"""Greenmangaming `[R73]` — la fiche produit fait foi (2026-10-09, src/merchants/greenmangaming.py).

Romain : « go pour Greenmangaming avec ta règle R59, 1. L'executor continue de rentrer l'offre en ROW
mais il vérifie que ce soit bien dispo en EU + US avant de l'ajouter, sinon il skip 2. consoles oui
mais ça peut être xbox + PC sur certaines offres, 3. Standard oui 4. OK, go ». Les fiches de
``tests/fixtures/greenmangaming/`` sont des extraits RÉELS de greenmangaming.com relevés le
2026-10-09 (titre, lien canonique, le JSON « var games »). Les titres et les liens sont ceux du
feed (scan tous-magasins du 21/09)."""

import pathlib
import unittest
from unittest import mock
from urllib.parse import quote, urlsplit

from src.aks_env import HttpProbeResult
from src.console_keys import classify_console
from src.contracts import NormalizedOffer
from src.matcher import REGION_IDS, AksResolution, Candidate, SkippedOffer, match_offer, precheck_skip
from src.merchants import greenmangaming as g
from src.merchants import gamesplanet
from src.merchants.registry import merchant_config, merchant_for_store, url_identity_params

FIX = pathlib.Path(__file__).resolve().parent / "fixtures" / "greenmangaming"
HOTE = "https://greenmangaming.sjv.io/c/1297091/1272000/15105"


def _aff(sku, slug):
    return f"{HOTE}?prodsku={quote(sku)}&u={quote('https://www.greenmangaming.com/games/' + slug + '/', safe='')}"


def _fiche(nom):
    return (FIX / f"{nom}.html").read_text(encoding="utf-8")


def _variant(nom, sku):
    corps = _fiche(nom)
    return g.parse_product_page(corps, g._canonical_path(corps), sku)


def _offre(nom, sku, slug):
    return NormalizedOffer(offer_id="1", name=nom, url=_aff(sku, slug), merchant="Greenmangaming",
                           store_id="22")


# (fixture, titre du feed, prodsku, slug de la fiche)
REUS = ("reus_2_jurassic", "Reus 2 - Jurassic", "Reus 2 Jurassic - PC", "reus-2-jurassic-pc")
ALLEY = ("the_alley", "The Alley", "The Alley - PC", "the-alley-pc")
COZY = ("cozy_builder", "Cozy Builder", "Cozy Builder - PC", "cozy-builder-pc")
GBVSR = ("gbvsr_dlc_bb_bs", "GBVSR - Additional Character Set (Id)",
         "GBVSR Additional Character Set Id ZTORM - PC", "gbvsr-additional-character-set-id-pc")
BOF4 = ("breath_of_fire_iv_asie", "Breath of Fire IV", "Breath of Fire IV CAPCOMDIRECT - PC",
        "breath-of-fire-iv-pc")
LUMA = ("luma_island_2_pack", "Luma Island - 2 Pack", "Luma Island 2 Pack - PC", "luma-island-2-pack-pc")
MIDWEST = ("midwest_games_bundle", "Midwest Games Bundle", "Midwest Games Bundle - PC",
           "midwest-games-bundle-pc")
MINECRAFT = ("minecraft_windows_10", "Minecraft: Java & Bedrock Edition Ultimate Collection",
             "Minecraft Java Bedrock Edition Ultimate Collection - Windows 10",
             "minecraft-java-bedrock-edition-ultimate-collection-windows-10")
NHL = ("nhl_27_xbox_series", "NHL 27", "NHL 27 - Xbox Series XS", "nhl-27-xbox")
FC27 = ("fc_27_ultimate_xbox", "EA SPORTS FC™ 27 Ultimate Edition",
        "EA SPORTS FC 27 Ultimate Edition - Xbox Series XS", "ea-sports-fc-27-ultimate-edition-xbox")
TMNT = ("tmnt_cowabunga_xbox_one", "Teenage Mutant Ninja Turtles: The Cowabunga Collection",
        "Teenage Mutant Ninja Turtles The Cowabunga Collection - Xbox One",
        "teenage-mutant-ninja-turtles-the-cowabunga-collection-xbox")


class _HttpFixture:
    """Remplace ``page_get`` : la fiche de la fixture, quel que soit le chemin demandé — le parseur
    réel vérifie ensuite le lien canonique."""

    def __init__(self, nom):
        self.nom, self.appels = nom, 0

    def __call__(self, url, timeout=20, user_agent=None):
        self.appels += 1
        return HttpProbeResult(url=url, ok=True, status=200, body=_fiche(self.nom))


def _page(nom, editions=None, regions=None, plateformes=("Steam",)):
    return AksResolution(slug="x", url="https://aks/x", product_id="1", aks_name=nom,
                         editions=editions or {"1": "Standard", "7": "Deluxe", "21": "Ultimate"},
                         regions=regions or {"2": "GLOBAL"}, official_platforms=plateformes)


def _match(row, slug=None, consoles=True, page=None, resolver=None):
    fixture, nom, sku, chemin = row
    g.clear_cache()
    http = _HttpFixture(fixture)
    offre = _offre(nom, sku, slug or chemin)
    with mock.patch.object(g, "page_get", side_effect=http):
        res = match_offer(offre, resolver=resolver or (lambda n, **k: page or _page(nom)),
                          consoles=consoles)
    return res, http


class LeLienDAffiliation(unittest.TestCase):
    def test_la_fiche_est_dans_u_et_le_sku_dans_prodsku(self):
        url = _aff("Reus 2 Jurassic - PC", "reus-2-jurassic-pc")
        self.assertEqual(g.landing(url), "https://www.greenmangaming.com/games/reus-2-jurassic-pc/")
        self.assertEqual(g.prodsku(url), "Reus 2 Jurassic - PC")
        self.assertEqual(g.sku_platform(url), "PC")
        self.assertEqual(url_identity_params(url), ("u", "prodsku"))   # une fiche, plusieurs éditions

    def test_un_lien_sans_fiche_gmg_ou_sans_sku_est_refuse_par_son_nom(self):
        sans_u = f"{HOTE}?prodsku=Reus%202%20Jurassic%20-%20PC"
        ailleurs = f"{HOTE}?prodsku=x&u={quote('https://www.g2a.com/x', safe='')}"
        sans_sku = f"{HOTE}?u={quote('https://www.greenmangaming.com/games/x/', safe='')}"
        self.assertIn("sans fiche greenmangaming.com", g.precheck("Reus 2 - Jurassic", sans_u))
        self.assertIn("sans fiche greenmangaming.com", g.precheck("Reus 2 - Jurassic", ailleurs))
        self.assertIn("sans prodsku", g.precheck("Reus 2 - Jurassic", sans_sku))
        self.assertIsNone(g.precheck("Reus 2 - Jurassic", _aff("Reus 2 Jurassic - PC", "reus-2-jurassic-pc")))

    def test_le_registre(self):
        self.assertIs(merchant_config("Greenmangaming"), g.CONFIG)
        self.assertEqual(merchant_for_store("22"), "Greenmangaming")
        self.assertEqual(g.CONFIG.affiliate_hosts, ("greenmangaming.sjv.io",))
        self.assertTrue(g.CONFIG.console_page_authoritative)
        self.assertIs(g.CONFIG.offer_page_resolver, g.offer_signals)
        self.assertIs(g.CONFIG.console_url_families, g.console_url_families)
        self.assertIs(g.CONFIG.console_pc_declared, g.console_pc_declared)


class LeTitreEtLeSku(unittest.TestCase):
    """Romain, 2026-09-18 : le titre, puis l'URL, puis la page."""

    def test_mac_psn_et_monnaies_refuses_sans_ouvrir_la_fiche(self):
        for nom, sku, attendu in (
            ("Sid Meier’s Civilization®: Beyond Earth™ (MAC)", "Sid Meiers Civilization Beyond Earth MAC - PC", "clé Mac"),
            ("PSN CREDIT $100", "PSN CREDIT 100 - PlayStation 4", "monnaie / crédit"),
            ("skate.™ - 1,600 San Van Bucks", "skate 1600 San Van Bucks - Xbox Series XS", "monnaie / crédit"),
            ("Some PS Game", "Some PS Game - PlayStation 4", "sku PlayStation"),
        ):
            with self.subTest(nom):
                offre = _offre(nom, sku, "x")
                raison = precheck_skip(offre, consoles=True)
                self.assertIn(attendu, raison)
                self.assertIn("R73", raison)
                with mock.patch.object(g, "page_get") as http:
                    res = match_offer(offre, resolver=lambda n, **k: None, consoles=True)
                self.assertIsInstance(res, SkippedOffer)
                http.assert_not_called()

    def test_la_generation_console_vient_du_sku(self):
        self.assertEqual(g.console_url_families(_aff("NHL 27 - Xbox Series XS", "nhl-27-xbox")), ("XBOX_SERIES",))
        self.assertEqual(g.console_url_families(_aff("TMNT - Xbox One", "tmnt-xbox")), ("XBOX_ONE",))
        self.assertIsNone(g.console_url_families(_aff("Reus 2 Jurassic - PC", "reus-2-jurassic-pc")))
        self.assertIsNone(g.console_url_families(_aff("Minecraft - Windows 10", "minecraft-windows-10")))
        self.assertIsNone(g.console_url_families(_aff("Sans suffixe", "x")))
        inconnu = g.console_url_families(_aff("Game - Stadia", "game-stadia"))
        self.assertTrue(inconnu.startswith("console:") and "R73" in inconnu)

    def test_le_classifieur_console_lit_la_generation_declaree(self):
        sig = classify_console("NHL 27", _aff("NHL 27 - Xbox Series XS", "nhl-27-xbox"), "Greenmangaming")
        self.assertEqual(tuple(sig.families), ("XBOX_SERIES",))
        self.assertFalse(sig.pc_declared)


class LaFiche(unittest.TestCase):
    def test_fiches_reelles(self):
        for row, plateforme, nom_edition, region in (
            (REUS, "STEAM", "", ("global", "")),
            (ALLEY, "STEAM", "Standard Edition", ("global", "")),
            (COZY, "STEAM", "Standard Edition", ("global", "")),
            (GBVSR, "STEAM", "", ("row", "")),                        # BB + BS exclus
            (BOF4, "STEAM", "Standard Edition", ("row", "")),         # CN, HK, JP, KR… exclus
            (MINECRAFT, "MICROSOFT", "Bundle", ("global", "")),
            (NHL, None, "Standard Edition", ("global", "")),          # xbox-one : pas une boutique PC
            (FC27, None, "Ultimate Edition", ("global", "")),
            (TMNT, None, "Standard Edition", ("global", "")),
        ):
            with self.subTest(row[0]):
                v = _variant(row[0], row[2])
                self.assertEqual(v.code, row[2])
                self.assertEqual(g.variant_platform(v), plateforme)
                self.assertEqual(v.edition_name, nom_edition)
                self.assertEqual(g.variant_region(v), region)

    def test_gbvsr_exclut_la_barbade_et_les_bahamas(self):
        v = _variant(GBVSR[0], GBVSR[2])
        self.assertEqual(sorted(v.excluded_countries), ["BB", "BS"])
        bof = _variant(BOF4[0], BOF4[2])
        self.assertTrue({"CN", "HK", "JP", "KR"} <= bof.excluded_countries)
        self.assertFalse(bof.excluded_countries & set(gamesplanet.ISO2_TO_NAME))   # ni UE, ni GB, ni US

    def test_une_fiche_sert_plusieurs_editions_le_sku_choisit(self):
        # EA SPORTS FC 27 : la fiche Xbox liste l'Ultimate Edition ET cinq packs de FC Points, chacun
        # avec son Code ; le sku du feed est l'identité — jamais « la première édition ».
        corps = _fiche(FC27[0])
        ultimate = g.parse_product_page(corps, g._canonical_path(corps), FC27[2])
        self.assertEqual(ultimate.edition_name, "Ultimate Edition")
        # les packs de FC Points ont leur Code sur la page (produits associés) mais ne sont PAS des
        # éditions : un sku de pack ne trouve pas d'édition → refus, comme un sku d'une autre fiche
        for sku in ("EA SPORTS FC 27 FC Points 1050 - Xbox Series XS", "EA SPORTS FC 27 - PC"):
            with self.subTest(sku):
                with self.assertRaises(g.GreenmangamingPageUnreadable) as cm:
                    g.parse_product_page(corps, g._canonical_path(corps), sku)
                self.assertIn("n'est pas une édition de la fiche", str(cm.exception))

    def test_la_page_servie_doit_etre_la_fiche_demandee(self):
        corps = _fiche(REUS[0])
        with self.assertRaises(g.GreenmangamingPageUnreadable) as cm:
            g.parse_product_page(corps, "/games/cozy-builder-pc", REUS[2])
        self.assertIn("n'est pas la fiche demandée", str(cm.exception))
        with self.assertRaises(g.GreenmangamingPageUnreadable):
            g.parse_product_page("<html><head><title>x</title></head></html>", "/games/x", "x")
        with self.assertRaises(g.GreenmangamingPageUnreadable) as cm:
            g.parse_product_page('<link rel="canonical" href="https://www.greenmangaming.com/games/x/" />'
                                 "<script>var other = 1;</script>", "/games/x", "x")
        self.assertIn("var games", str(cm.exception))

    def test_un_drm_inconnu_ou_double_est_un_refus_nomme(self):
        v = _variant(ALLEY[0], ALLEY[2])
        for drm in (("stadia",), ("steam", "epic")):
            with self.subTest(drm):
                with self.assertRaises(g.GreenmangamingPageUnreadable) as cm:
                    g.variant_platform(v.__class__(**{**v.__dict__, "drm": drm}))
                self.assertIn("R73", str(cm.exception))
        # le vocabulaire est FERMÉ : seuls steam et microsoft ont été observés le 09/10
        self.assertEqual(g.DRM_PLATFORM["steam"], "STEAM")
        self.assertEqual(g.DRM_PLATFORM["microsoft"], "MICROSOFT")
        self.assertIn("xbox-one", g.CONSOLE_DRM)

    def test_la_region_de_romain(self):
        """Vide → GLOBAL ; exclus hors UE / UK / USA → ROW ; UE, UK ou USA exclus → refus, jamais
        le repli US / EU de [R59]."""

        base = _variant(ALLEY[0], ALLEY[2])
        def avec(*pays):
            return base.__class__(**{**base.__dict__, "excluded_countries": frozenset(pays)})
        self.assertEqual(g.variant_region(avec()), ("global", ""))
        self.assertEqual(g.variant_region(avec("CN", "RU", "BR")), ("row", ""))
        self.assertEqual(g.variant_region(avec("DE")), (None, "GREENMANGAMING LOCK (EU: germany excluded)"))
        self.assertEqual(g.variant_region(avec("US", "CN")), (None, "GREENMANGAMING LOCK (US excluded)"))
        self.assertEqual(g.variant_region(avec("GB")), (None, "GREENMANGAMING LOCK (UK excluded)"))
        self.assertEqual(g.variant_region(avec("FR", "US")),
                         (None, "GREENMANGAMING LOCK (EU: france + US excluded)"))

    def test_lots_et_paliers_non_nommes_par_le_titre(self):
        self.assertIn("lot de plusieurs clés", g.edition_refusal(_variant(LUMA[0], LUMA[2]), LUMA[1]))
        self.assertIn("lot de plusieurs clés", g.edition_refusal(_variant(MIDWEST[0], MIDWEST[2]), MIDWEST[1]))
        self.assertIn("lot de plusieurs clés", g.edition_refusal(_variant(MINECRAFT[0], MINECRAFT[2]), MINECRAFT[1]))
        # FC 27 : la fiche dit Ultimate, le titre aussi → rien à redire
        self.assertIsNone(g.edition_refusal(_variant(FC27[0], FC27[2]), FC27[1]))
        # une fiche « Deluxe Edition » sur un titre nu « NHL 27 » → refus ; nommée par le titre → rien
        nhl = _variant(NHL[0], NHL[2])
        deluxe = nhl.__class__(**{**nhl.__dict__, "edition_name": "Deluxe Edition"})
        self.assertIn("ne la nomme pas", g.edition_refusal(deluxe, "NHL 27"))
        self.assertIsNone(g.edition_refusal(deluxe, "NHL 27 Deluxe Edition"))
        # « Standard Edition » et vide : le chemin générique (Romain : « Standard oui »)
        self.assertIsNone(g.edition_refusal(_variant(ALLEY[0], ALLEY[2]), "The Alley"))
        self.assertIsNone(g.edition_refusal(_variant(REUS[0], REUS[2]), "Reus 2 - Jurassic"))

    def test_xbox_plus_pc_declare_par_la_fiche(self):
        g.clear_cache()
        http = _HttpFixture(FC27[0])
        self.assertFalse(g.console_pc_declared(FC27[1], _aff(FC27[2], FC27[3]), http_get_fn=http))
        v = _variant(FC27[0], FC27[2])
        self.assertEqual(v.platform_names, ("Xbox Series X/S", "Xbox One"))
        # une fiche qui listerait PC à côté d'une Xbox déclarerait « Xbox + PC » (P2)
        with mock.patch.object(g, "fetch_variant", return_value=v.__class__(**{**v.__dict__, "platform_names": ("PC", "Xbox Series X/S")})):
            self.assertTrue(g.console_pc_declared(FC27[1], _aff(FC27[2], FC27[3])))
        # une ligne PC ne déclare jamais une console
        self.assertFalse(g.console_pc_declared(REUS[1], _aff(REUS[2], REUS[3]), http_get_fn=_HttpFixture(REUS[0])))


class LeMatcher(unittest.TestCase):
    def test_une_cle_steam_sans_restriction_entre_en_global_standard(self):
        res, http = _match(COZY)
        self.assertIsInstance(res, Candidate, getattr(res, "reason", None))
        self.assertEqual((res.platform, res.region_id, res.edition_id), ("STEAM", "2", "1"))
        self.assertEqual(http.appels, 1)

    def test_une_cle_steam_restreinte_hors_ue_uk_us_entre_en_steam_row(self):
        res, _ = _match(BOF4, page=_page("Breath of Fire IV", regions={"2": "GLOBAL", "steamrow": "ROW"}))
        self.assertIsInstance(res, Candidate, getattr(res, "reason", None))
        self.assertEqual((res.platform, res.region_id, res.edition_id), ("STEAM", "steamrow", "1"))
        self.assertEqual(REGION_IDS["STEAM"]["row"], "steamrow")

    def test_une_cle_qui_exclut_l_ue_ou_les_usa_est_refusee(self):
        v = _variant(ALLEY[0], ALLEY[2])
        for pays, attendu in ((("DE",), "EU: germany"), (("US",), "US excluded"), (("GB",), "UK excluded")):
            with self.subTest(pays):
                variante = v.__class__(**{**v.__dict__, "excluded_countries": frozenset(pays)})
                with mock.patch.object(g, "fetch_variant", return_value=variante):
                    res = match_offer(_offre(*ALLEY[1:]), resolver=lambda n, **k: _page("The Alley"), consoles=True)
                self.assertIsInstance(res, SkippedOffer)
                self.assertIn("forbidden region: GREENMANGAMING LOCK", res.reason)
                self.assertIn(attendu, res.reason)

    def test_un_lot_est_refuse(self):
        res, _ = _match(LUMA)
        self.assertIsInstance(res, SkippedOffer)
        self.assertIn("lot de plusieurs clés", res.reason)

    def test_une_fiche_illisible_est_un_refus_jamais_un_repli(self):
        g.clear_cache()
        http = lambda url, timeout=20, user_agent=None: HttpProbeResult(url=url, ok=False, status=403, body="", error="403")
        with mock.patch.object(g, "page_get", side_effect=http):
            res = match_offer(_offre(*COZY[1:]), resolver=lambda n, **k: _page("Cozy Builder"), consoles=True)
        self.assertIsInstance(res, SkippedOffer)
        self.assertIn("403", res.reason)

    def test_une_ligne_xbox_prend_la_page_de_sa_generation_declaree(self):
        # NHL 27 Standard, sku « Xbox Series XS », fiche sans restriction → la page Xbox Series
        # d'AKS, GLOBAL (300), Standard (P1 : la génération DÉCLARÉE, cette page seulement).
        fixture, nom, sku, chemin = NHL
        g.clear_cache()
        http = _HttpFixture(fixture)
        aks = "https://www.allkeyshop.com/blog/buy-nhl-27-xbox-series-x-compare-prices/"
        series = AksResolution(slug="nhl-27", url=aks, product_id="9", aks_name="NHL 27 Xbox Series X",
                               editions={"1": {"name": "Standard"}}, official_platforms=("Xbox Series X|S",),
                               console_pages={"xbox-series": aks})
        appels = []

        def resolver(n, **kw):
            appels.append((n, kw.get("page_kind")))
            return series if kw.get("page_kind") == "xbox-series" else None

        with mock.patch.object(g, "page_get", side_effect=http):
            res = match_offer(_offre(nom, sku, chemin), resolver, page_resolver={aks: series}.get,
                              consoles=True)
        self.assertIsInstance(res, Candidate, getattr(res, "reason", None))
        cibles = [(t.platform, t.aks_product_id, t.region_id, t.edition_id) for t in res.targets]
        self.assertEqual(cibles, [("XBOX_SERIES", "9", "300", "1")])
        self.assertEqual(http.appels, 1)
        self.assertNotIn("xbox-one", [k for _, k in appels])      # jamais la page sœur (P1)

    def test_une_ligne_xbox_sans_consoles_reste_console(self):
        res, _ = _match(NHL, consoles=False)
        self.assertIsInstance(res, SkippedOffer)
        self.assertTrue(res.reason.startswith("console"), res.reason)


class LeModule(unittest.TestCase):
    def test_n_importe_pas_la_couche_generique(self):
        import re
        src = pathlib.Path(g.__file__).read_text(encoding="utf-8")
        self.assertIsNone(re.search(r"^\s*(?:from|import)\s+src\.(?:matcher|console_keys|merchants\.registry)\b", src, re.M))

    def test_pas_en_liste_blanche_avant_l_apercu(self):
        from src.admin.auto_merchants import AUTO_MERCHANTS
        self.assertNotIn("Greenmangaming", [n for n, _ in AUTO_MERCHANTS])


if __name__ == "__main__":
    unittest.main()

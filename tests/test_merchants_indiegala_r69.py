"""Indiegala `[R69]` — la fiche produit fait foi (2026-10-06, src/merchants/indiegala.py).

Romain : « Si on peut ouvrir la page, on trouvera les infos » (après l'étude du 06/10,
docs/PROCHAINS_MARCHANDS.md). Modèle : Allyouplay `[R68]`. Les fiches de
``tests/fixtures/indiegala/`` sont des extraits RÉELS d'indiegala.com relevés le 2026-10-06 (titre,
lien canonique, encarts latéraux, avertissements d'article) ; les titres et les URL sont ceux du
feed (scan tous-magasins du 21/09, store 95). En liste blanche depuis le go de Romain du 06/10
(après l'aperçu ligne par ligne) ; rien ici n'écrit."""

import pathlib
import re
import unittest
from unittest import mock
from urllib.parse import urlsplit

from src.aks_env import HttpProbeResult
from src.console_keys import classify_console
from src.contracts import NormalizedOffer
from src.matcher import AksResolution, Candidate, SkippedOffer, match_offer, precheck_skip
from src.merchants import allyouplay, gamesplanet
from src.merchants import indiegala as ig
from src.merchants.gamesplanet import EU_MEMBERS, UK, US, region_from_lock
from src.merchants.registry import MERCHANT_STORE_IDS, merchant_config, merchant_for_store

FIX = pathlib.Path(__file__).resolve().parent / "fixtures" / "indiegala"
BASE = "https://www.indiegala.com/store/game/"


def _fiche(nom):
    return (FIX / f"{nom}.html").read_text(encoding="utf-8")


def _page(nom):
    """La fiche lue par le vrai parseur, pour le chemin qu'elle déclare elle-même."""

    corps = _fiche(nom)
    return ig.parse_product_page(corps, ig.canonical_path(corps))


def _offre(nom, chemin):
    return NormalizedOffer(offer_id="1", name=nom, url=BASE + chemin, merchant="Indiegala",
                           store_id="95")


# (fixture, titre du feed, chemin après /store/game/)
MHW = ("monde_monster_hunter_wilds_gold", "Monster Hunter Wilds Gold Edition",
       "monster-hunter-wilds-gold-edition/1723312")
SCUM = ("monde_dlc_scum_specialist_scout_pack", "SCUM Specialist Scout Pack",
        "scum-specialist-scout-pack/4635250")
LBA2 = ("monde_little_big_adventure_2", "Little Big Adventure 2", "little-big-adventure-2/398000")
BELMONT = ("chypre_et_usa_interdits_belmonts_curse_eu", "Castlevania: Belmont's Curse (EU)",
           "castlevania-belmonts-curse-eu/4231820")
TOWNFALL = ("us_silent_hill_townfall_standard_us", "SILENT HILL: Townfall Standard (US)",
            "silent-hill-townfall-standard-us/1636440_us")
BUNDLE = ("europe_castlevania_lords_of_shadow_2_bundle",
          "Castlevania: Lords of Shadow 2 Digital Bundle",
          "castlevania-lords-of-shadow-2-digital-bundle/45707")
REACH = ("verrou_pays_reach", "Reach", "reach/3273480")
THUNDER = ("sans_avertissement_dlc_thunder_ray_origin", "Thunder Ray - Origin",
           "thunder-ray-origin/2681380")
AOT3 = ("fiche_perimee_accueil_aot3_deluxe", "Attack on Titan 3 / A.O.T. 3 Digital Deluxe Edition",
        "attack-on-titan-3-aot-3-digital-deluxe-edition/2916700_deluxe")
FICHES = (MHW, SCUM, LBA2, BELMONT, TOWNFALL, BUNDLE, REACH, THUNDER)


class _FetchFixture:
    """Remplace ``fetch_product_page`` : la fiche nommée, lue par le vrai parseur pour le chemin
    de l'URL demandée (le lien canonique de la fiche doit donc être celui de l'offre)."""

    def __init__(self, nom):
        self.nom, self.appels = nom, []

    def __call__(self, url, http_get_fn=None):
        self.appels.append(url)
        cible = ig.product_url(url)
        return ig.parse_product_page(_fiche(self.nom), urlsplit(cible).path.lower())


def _aks(nom, plateformes=("Steam",), editions=None):
    return AksResolution(slug="x", url="https://aks/x", product_id="1", aks_name=nom,
                         editions=editions or {"1": "Standard", "7": "Deluxe", "10": "Gold"},
                         regions={"2": "GLOBAL"}, official_platforms=plateformes)


def _match(row, aks_name=None, plateformes=("Steam",), titre=None, editions=None):
    fixture, nom, chemin = row
    nom = titre or nom
    page = _aks(aks_name or ig.resolve_name(nom), plateformes, editions)
    fetch = _FetchFixture(fixture)
    with mock.patch.object(ig, "fetch_product_page", side_effect=fetch):
        res = match_offer(_offre(nom, chemin), resolver=lambda n, **k: page, consoles=True)
    return res, fetch


class LeTitre(unittest.TestCase):
    """Le titre ne dit que deux choses : un suffixe de région en queue, une traduction après « / »."""

    def test_le_suffixe_de_region_en_queue(self):
        # Les 7 lignes du feed du 21/09, mot pour mot.
        for nom, attendu in (
            ("SILENT HILL: Townfall - DELUXE (US)", "us"),
            ("SILENT HILL: Townfall Standard (US)", "us"),
            ("Once Upon A KATAMARI - King of All Sounds Edition (US)", "us"),
            ("PAC-MAN WORLD 2 Re-PAC (US)", "us"),
            ("PAC-MAN World 2 Re-PAC: Deluxe Edition (US)", "us"),
            ("Castlevania: Belmont's Curse (EU)", "eu"),
            ("Castlevania: Belmont's Curse Midnight Edition (EU)", "eu"),
            ("Some Game (UK)", "uk"),
            ("Reach", None),
            ("Monster Hunter Wilds Gold Edition", None),
            ("(US) Something", None),                        # en tête : pas le suffixe
            ("Game (EU) Deluxe", None),                      # au milieu : pas le suffixe
        ):
            with self.subTest(nom):
                self.assertEqual(ig.title_region(nom), attendu)

    def test_le_suffixe_sort_du_nom_resolu_et_du_nom_des_gardes(self):
        for nom, attendu in (
            ("SILENT HILL: Townfall Standard (US)", "SILENT HILL: Townfall Standard"),
            ("Castlevania: Belmont's Curse (EU)", "Castlevania: Belmont's Curse"),
            ("PAC-MAN World 2 Re-PAC: Deluxe Edition (US)", "PAC-MAN World 2 Re-PAC: Deluxe Edition"),
            ("Reach", "Reach"),
        ):
            with self.subTest(nom):
                self.assertEqual(ig.resolve_name(nom), attendu)
                self.assertEqual(ig.guard_name(nom), attendu)

    def test_un_titre_multilingue_est_reduit_a_sa_premiere_partie(self):
        # Les parties japonaise / chinoise sont des traductions : le nom AKS est la première.
        for nom, attendu in (
            ("Death End re;Quest Deluxe Edition Bundle / デラックスエディション / 豪華組合包",
             "Death End re;Quest Deluxe Edition Bundle"),
            ("Colosseum + Characters DLC / コンテンツ追加パック５ / 鬥技場 + 角色DLC",
             "Colosseum + Characters DLC"),
            ("Foo Bar / Foo Bar", "Foo Bar"),                 # le même nom répété
        ):
            with self.subTest(nom):
                self.assertEqual(ig.resolve_name(nom), attendu)

    def test_une_alternative_latine_n_est_pas_coupee(self):
        # « A.O.T. 3 » n'est pas une traduction : on ne devine pas lequel des deux noms AKS
        # publie — le titre entier va aux gardes d'identité (refus au pire, jamais un nom deviné).
        for nom in (
            "Attack on Titan 3 / A.O.T. 3",
            "Attack on Titan 3 / A.O.T. 3 Digital Deluxe Edition",
            # la dernière partie est latine (français) : pas de coupe non plus
            "Complete Deluxe Edition Bundle / コンプリートデラックスエディション /完全豪華組合包 / "
            "Ensemble Edition Deluxe Complet",
            "Half-Life/Portal",                               # pas un séparateur
        ):
            with self.subTest(nom):
                self.assertEqual(ig.resolve_name(nom), nom)
                self.assertEqual(ig.guard_name(nom), nom)

    def test_un_accent_latin_n_est_pas_une_autre_ecriture(self):
        self.assertEqual(ig.resolve_name("Mon Jeu / Mon Jeu Édition"), "Mon Jeu / Mon Jeu Édition")
        self.assertEqual(ig.resolve_name("Pokémon (EU)"), "Pokémon")

    def test_le_precheck_generique_garde_la_main(self):
        # Rien n'est ajouté au precheck : les bundles sont refusés par le générique, les clés nues
        # passent (et iront à la fiche).
        self.assertIn("BUNDLE", precheck_skip(_offre(*BUNDLE[1:]), consoles=True))
        for row in (MHW, SCUM, LBA2, BELMONT, TOWNFALL, REACH, THUNDER):
            with self.subTest(row[1]):
                self.assertIsNone(precheck_skip(_offre(*row[1:]), consoles=True))


class LaFiche(unittest.TestCase):
    """Les 8 fiches réelles du 06/10, lues par le vrai parseur."""

    def test_fiches_reelles(self):
        for row, dlc, nb, region in (
            (MHW, False, 18, ("global", "")),          # 18 pays, ni UE, ni UK, ni USA
            (SCUM, True, 59, ("global", "")),
            (LBA2, False, 77, ("global", "")),
            (TOWNFALL, False, 222, ("us", "")),        # toute l'UE + UK interdits, USA autorisés
            (BUNDLE, False, 215, ("eu", "")),          # USA interdits, UE entière autorisée
            (BELMONT, False, 125, (None, "INDIEGALA LOCK (EU + US)")),   # Chypre + USA interdits
            (REACH, False, 0, (None, "INDIEGALA LOCK (COUNTRY OF PURCHASE)")),
            (THUNDER, True, 0, ("global", "")),        # aucun avertissement
        ):
            with self.subTest(row[1]):
                page = _page(row[0])
                self.assertEqual(page.platform_text, "Steam Key")
                self.assertEqual(ig.page_platform(page), "STEAM")
                self.assertEqual(page.is_dlc, dlc)
                self.assertEqual(len(page.banned_countries), nb)
                self.assertEqual(ig.page_region(page), region)

    def test_le_dlc_est_expose_pas_route(self):
        # 2 fiches sur 8 : exposé (`is_dlc`), aucun hook `dlc_marker` — R18 / [R43] gardent la main.
        self.assertTrue(_page(SCUM[0]).is_dlc)
        self.assertTrue(_page(THUNDER[0]).is_dlc)
        self.assertFalse(_page(MHW[0]).is_dlc)
        self.assertIsNone(getattr(merchant_config("Indiegala"), "dlc_marker", None))

    def test_la_decision_belmont_eu(self):
        # Le titre dit « (EU) », la liste interdit Chypre ET les USA : lecture stricte de [R59],
        # refus — point soumis à Romain (docstring du module), rien de plus souple n'est codé.
        page = _page(BELMONT[0])
        self.assertEqual((EU_MEMBERS | {UK, US}) & page.banned_countries, {"cyprus", US})
        self.assertEqual(ig.page_region(page), (None, "INDIEGALA LOCK (EU + US)"))

    def test_les_pays_qui_decident(self):
        self.assertEqual((EU_MEMBERS | {UK, US}) & _page(TOWNFALL[0]).banned_countries,
                         EU_MEMBERS | {UK})
        self.assertEqual((EU_MEMBERS | {UK, US}) & _page(BUNDLE[0]).banned_countries, {US})
        for row in (MHW, SCUM, LBA2):
            with self.subTest(row[1]):
                self.assertEqual((EU_MEMBERS | {UK, US}) & _page(row[0]).banned_countries, set())

    def test_les_virgules_des_noms_composes_sont_sans_effet(self):
        # La liste est coupée à la virgule ; « Korea, Republic of » donne « korea » + « republic
        # of ». Le fragment existe bien… et ne vaut aucun des 29 noms qui décident ; et chaque nom
        # qui décide est un item ENTIER de la liste brute (jamais un fragment).
        page = _page(MHW[0])
        self.assertIn("republic of", page.banned_countries)
        self.assertEqual(ig.page_region(page), ("global", ""))
        decideurs = EU_MEMBERS | {UK, US}
        # Une coupe « savante » (test seulement) recolle les qualificatifs ISO (« Republic of »,
        # « The Democratic Republic of the », « U.S. », « British », « Province of China »…) :
        # elle doit donner les MÊMES décideurs que la coupe naïve du module, sur chaque fiche.
        qualificatif = (r",(?!\s*(?:the\s|republic|democratic|islamic|bolivarian|plurinational|"
                        r"federated|united republic|province|state of|u\.s|british|french part|"
                        r"dutch part|sint eustatius|ascension|former))")
        for row in (MHW, SCUM, LBA2, BELMONT, TOWNFALL, BUNDLE):
            brut = ig._LIST_RE.search(_fiche(row[0])).group("list")
            entiers = [ig.country_name(x) for x in re.split(qualificatif, brut, flags=re.I)]
            with self.subTest(row[1]):
                self.assertLess(len(entiers), len(brut.split(",")), "des noms à virgule existent")
                self.assertEqual(decideurs & set(entiers),
                                 decideurs & _page(row[0]).banned_countries)
        # Un ensemble synthétique de noms à virgule seuls : GLOBAL, pas un refus.
        corps = _fiche(MHW[0]).replace(
            ig._LIST_RE.search(_fiche(MHW[0])).group("list"),
            "Korea, Republic of, Virgin Islands, U.S., United States Minor Outlying Islands, "
            "Congo, The Democratic Republic of the, Czech Republic")
        page = ig.parse_product_page(corps, ig.canonical_path(corps))
        self.assertIn("czechia", page.banned_countries)          # l'alias de [R59] joue
        self.assertEqual(ig.page_region(page), ("us", ""))   # Tchéquie exclue, USA autorisés

    def test_l_encart_region_d_achat_est_ignore(self):
        # 7 fiches sur 8 portent l'encart latéral « Region locked product — It will only work in
        # the region from where it is bought » : politique de vente, pas la liste d'activation.
        for row in (MHW, SCUM, LBA2, TOWNFALL, BUNDLE, BELMONT, REACH):
            with self.subTest(row[1]):
                self.assertIn("region from where it is bought", _fiche(row[0]))
        self.assertNotIn("region from where it is bought", _fiche(THUNDER[0]))
        self.assertEqual(ig.page_region(_page(MHW[0])), ("global", ""))
        self.assertFalse(_page(MHW[0]).country_locked)

    def test_le_verrou_pays_est_l_avertissement_d_article(self):
        # Reach : h3 « Region locked product » dans l'article → verrou pays, refus nommé.
        page = _page(REACH[0])
        self.assertTrue(page.country_locked)
        self.assertEqual(page.warnings, (("region locked product", frozenset()),))
        self.assertEqual(ig.page_region(page), (None, "INDIEGALA LOCK (COUNTRY OF PURCHASE)"))

    def test_une_fiche_perimee_renvoie_a_l_accueil(self):
        # Attack on Titan 3 Digital Deluxe, 06/10 : la page servie est l'accueil du magasin
        # (canonique `/store`) → refus « fiche périmée », jamais une lecture de l'accueil.
        chemin = "/store/game/" + AOT3[2]
        with self.assertRaises(ig.IndiegalaPageUnreadable) as ctx:
            ig.parse_product_page(_fiche(AOT3[0]), chemin)
        self.assertIn("fiche périmée", str(ctx.exception))
        self.assertIn("/store", str(ctx.exception))

    def test_une_fiche_servie_pour_un_autre_produit_est_refusee(self):
        with self.assertRaises(ig.IndiegalaPageUnreadable) as ctx:
            ig.parse_product_page(_fiche(MHW[0]), "/store/game/" + LBA2[2])
        self.assertIn("n'est pas la fiche demandée", str(ctx.exception))

    def test_sans_lien_canonique_refus(self):
        corps = re.sub(r'<link href="[^"]*" rel="canonical"/>', "", _fiche(MHW[0]))
        with self.assertRaises(ig.IndiegalaPageUnreadable) as ctx:
            ig.parse_product_page(corps, "/store/game/" + MHW[2])
        self.assertIn("sans lien canonique", str(ctx.exception))

    def test_le_lien_canonique_se_lit_dans_les_deux_ordres_d_attributs(self):
        corps = _fiche(MHW[0]).replace(
            f'<link href="https://www.indiegala.com/store/game/{MHW[2]}" rel="canonical"/>',
            f'<link rel="canonical" href="https://www.indiegala.com/store/game/{MHW[2]}" />')
        self.assertEqual(ig.canonical_path(corps), "/store/game/" + MHW[2])

    def test_plateforme_inconnue_ou_absente_refus_nomme(self):
        corps = _fiche(MHW[0])
        chemin = "/store/game/" + MHW[2]
        page = ig.parse_product_page(
            corps.replace("<strong>Steam Key</strong>", "<strong>Amazon Key</strong>"), chemin)
        with self.assertRaises(ig.IndiegalaPageUnreadable) as ctx:
            ig.page_platform(page)
        self.assertIn("Amazon Key", str(ctx.exception))
        self.assertIn("R69", str(ctx.exception))
        with self.assertRaises(ig.IndiegalaPageUnreadable) as ctx:
            ig.parse_product_page(corps.replace("is provided via", "is sold as"), chemin)
        self.assertIn("is provided via", str(ctx.exception))

    def test_les_autres_libelles_connus(self):
        for texte, jeton in (("GOG Key", "GOG"), ("Epic Games Key", "EPIC"), ("Origin Key", "EA"),
                             ("EA App Key", "EA"), ("Ubisoft Connect Key", "UBISOFT"),
                             ("Uplay Key", "UBISOFT"), ("Rockstar Key", "ROCKSTAR"),
                             ("Battle.net Key", "BATTLENET"), ("Microsoft Store Key", "MICROSOFT")):
            with self.subTest(texte):
                page = ig.parse_product_page(
                    _fiche(MHW[0]).replace("<strong>Steam Key</strong>", f"<strong>{texte}</strong>"),
                    "/store/game/" + MHW[2])
                self.assertEqual(ig.page_platform(page), jeton)

    def test_un_avertissement_inconnu_ou_sans_liste_est_un_refus(self):
        corps = _fiche(MHW[0])
        chemin = "/store/game/" + MHW[2]
        with self.assertRaises(ig.IndiegalaPageUnreadable) as ctx:
            ig.parse_product_page(corps.replace("Country availability", "Age restriction"), chemin)
        self.assertIn("Age restriction", str(ctx.exception))
        sans_liste = re.sub(r'<div class="store-product-contents-article-warning-list">.*?</div>',
                            "", corps, flags=re.S)
        with self.assertRaises(ig.IndiegalaPageUnreadable) as ctx:
            ig.parse_product_page(sans_liste, chemin)
        self.assertIn("sans liste de pays", str(ctx.exception))
        vide = re.sub(r'(<div class="store-product-contents-article-warning-list">).*?(</div>)',
                      r"\1 , \2", corps, flags=re.S)
        with self.assertRaises(ig.IndiegalaPageUnreadable) as ctx:
            ig.parse_product_page(vide, chemin)
        self.assertIn("liste de pays vide", str(ctx.exception))

    def test_une_page_sans_les_reperes_d_une_fiche_est_refusee(self):
        corps = _fiche(MHW[0]).replace('class="store-product-contents', 'class="autre-chose')
        with self.assertRaises(ig.IndiegalaPageUnreadable) as ctx:
            ig.parse_product_page(corps, "/store/game/" + MHW[2])
        self.assertIn("repères", str(ctx.exception))

    def test_la_table_de_region_est_celle_de_gamesplanet(self):
        pays = _page(TOWNFALL[0]).banned_countries
        self.assertEqual(region_from_lock(("NOT", pays), label="INDIEGALA"), ("us", ""))
        self.assertEqual(region_from_lock(("NOT", pays)), ("us", ""))      # la même table


class LeSuffixeEtLaFiche(unittest.TestCase):
    """Le suffixe du titre doit s'accorder avec la fiche ; la fiche décide du reste."""

    def _sig(self, row, titre=None):
        fixture, nom, chemin = row
        with mock.patch.object(ig, "fetch_product_page", side_effect=_FetchFixture(fixture)):
            return ig.offer_signals(BASE + chemin, titre or nom)

    def test_us_du_titre_et_fiche_us(self):
        sig = self._sig(TOWNFALL)
        self.assertEqual((sig.platform, sig.region_resolved, sig.region_base), ("STEAM", True, "us"))

    def test_sans_suffixe_la_fiche_seule_decide(self):
        for row, base in ((MHW, "global"), (LBA2, "global"), (THUNDER, "global"), (BUNDLE, "eu")):
            with self.subTest(row[1]):
                sig = self._sig(row)
                self.assertEqual((sig.platform, sig.region_resolved, sig.region_base),
                                 ("STEAM", True, base))

    def test_suffixe_et_fiche_en_desaccord_refus_nomme(self):
        for row, titre in ((TOWNFALL, "SILENT HILL: Townfall Standard (EU)"),
                           (MHW, "Monster Hunter Wilds Gold Edition (US)"),
                           (BUNDLE, "Castlevania: Lords of Shadow 2 Digital Bundle (UK)")):
            with self.subTest(titre), self.assertRaises(ig.IndiegalaPageUnreadable) as ctx:
                self._sig(row, titre)
            self.assertIn("contredit la fiche", str(ctx.exception))
            self.assertIn("R69", str(ctx.exception))

    def test_un_verrou_de_la_fiche_prime_sur_le_suffixe(self):
        sig = self._sig(BELMONT)                               # « (EU) » dans le titre
        self.assertEqual((sig.region_resolved, sig.region_base, sig.region_label),
                         (True, None, "INDIEGALA LOCK (EU + US)"))
        sig = self._sig(REACH, "Reach (US)")
        self.assertEqual((sig.region_base, sig.region_label),
                         (None, "INDIEGALA LOCK (COUNTRY OF PURCHASE)"))


class LaRequete(unittest.TestCase):
    """Une requête par fiche et par processus ; tout échec est un refus, jamais un défaut."""

    def setUp(self):
        ig.clear_cache()
        self.addCleanup(ig.clear_cache)

    def _get(self, corps, status=200, leve=None):
        appels = []

        def get(url, timeout=20, user_agent=None, **kw):
            appels.append((url, user_agent))
            if leve:
                raise leve
            return HttpProbeResult(url=url, ok=status == 200, status=status, body=corps)
        return get, appels

    def test_la_fiche_est_ouverte_une_fois_avec_un_ua_navigateur(self):
        get, appels = self._get(_fiche(MHW[0]))
        for _ in range(2):
            sig = ig.offer_signals(BASE + MHW[2], MHW[1], http_get_fn=get)
            self.assertEqual((sig.platform, sig.region_resolved, sig.region_base),
                             ("STEAM", True, "global"))
        self.assertEqual(len(appels), 1, "une seule requête par fiche")
        self.assertEqual(appels[0][0], BASE + MHW[2])
        self.assertIn("Mozilla", appels[0][1])

    def test_la_query_ne_fait_pas_une_autre_fiche(self):
        get, appels = self._get(_fiche(MHW[0]))
        ig.offer_signals(BASE + MHW[2], MHW[1], http_get_fn=get)
        ig.offer_signals(BASE + MHW[2] + "?ref=aks#x", MHW[1], http_get_fn=get)
        self.assertEqual(len(appels), 1)
        self.assertEqual(ig.product_url(BASE + MHW[2] + "?ref=aks#x"), BASE + MHW[2])

    def test_un_echec_est_garde_et_ne_rouvre_pas_la_page(self):
        get, appels = self._get("", status=503)
        for _ in range(2):
            with self.assertRaises(ig.IndiegalaPageUnreadable):
                ig.offer_signals(BASE + MHW[2], MHW[1], http_get_fn=get)
        self.assertEqual(len(appels), 1)

    def test_injoignable_leve(self):
        get, _ = self._get("", leve=OSError("reset"))
        with self.assertRaises(ig.IndiegalaPageUnreadable) as ctx:
            ig.offer_signals(BASE + MHW[2], http_get_fn=get)
        self.assertIn("injoignable", str(ctx.exception))

    def test_aucune_autre_page_n_est_lue(self):
        get, appels = self._get(_fiche(MHW[0]))
        for url in ("https://www.g2a.com/store/game/reach/3273480",
                    "https://www.indiegala.com/bundle/some-bundle",
                    "https://www.indiegala.com/",
                    "https://indiegala.com.evil.example/store/game/reach/3273480"):
            with self.subTest(url), self.assertRaises(ig.IndiegalaPageUnreadable) as ctx:
                ig.offer_signals(url, http_get_fn=get)
            self.assertIn("aucune autre page", str(ctx.exception))
        self.assertEqual(appels, [])

    def test_une_fiche_servie_pour_un_autre_produit_est_refusee(self):
        get, _ = self._get(_fiche(MHW[0]))
        with self.assertRaises(ig.IndiegalaPageUnreadable):
            ig.offer_signals(BASE + LBA2[2], http_get_fn=get)

    def test_la_fiche_perimee_est_refusee_et_gardee(self):
        get, appels = self._get(_fiche(AOT3[0]))
        for _ in range(2):
            with self.assertRaises(ig.IndiegalaPageUnreadable) as ctx:
                ig.offer_signals(BASE + AOT3[2], AOT3[1], http_get_fn=get)
            self.assertIn("fiche périmée", str(ctx.exception))
        self.assertEqual(len(appels), 1)


class LeMoteurDeLaRequete(unittest.TestCase):
    """Comme `[R68]` : la fiche est lue par la bibliothèque standard (`page_get`), jamais par
    `aks_env.http_get` — le moteur partagé des requêtes vers AKS n'est pas touché."""

    def test_le_moteur_par_defaut_est_page_get_pas_http_get(self):
        import inspect
        from src import aks_env
        for fn in (ig.fetch_product_page, ig.offer_signals):
            with self.subTest(fn.__name__):
                defaut = inspect.signature(fn).parameters["http_get_fn"].default
                self.assertIs(defaut, ig.page_get)
                self.assertIsNot(defaut, aks_env.http_get)

    def _ouvrir(self, final, status=200, corps=b"<html>ok</html>"):
        reponse = mock.MagicMock()
        reponse.__enter__.return_value = reponse
        reponse.geturl.return_value = final
        reponse.status = status
        reponse.read.return_value = corps
        return mock.patch("urllib.request.urlopen", return_value=reponse)

    def test_la_requete_porte_le_ua_navigateur(self):
        with self._ouvrir(BASE + REACH[2]) as ouvert:
            r = ig.page_get(BASE + REACH[2])
        requete = ouvert.call_args.args[0]
        self.assertEqual(requete.get_header("User-agent"), ig.REQUIRED_USER_AGENT)
        self.assertEqual((r.ok, r.status, r.body), (True, 200, "<html>ok</html>"))

    def test_une_redirection_hors_d_indiegala_est_une_reponse_ratee(self):
        with self._ouvrir("https://ailleurs.example/store/game/reach/3273480"):
            r = ig.page_get(BASE + REACH[2])
        self.assertFalse(r.ok)
        self.assertEqual(r.body, "")
        self.assertIn("hors d'indiegala.com", r.error)

    def test_un_403_ou_une_panne_ne_leve_jamais(self):
        import urllib.error
        erreur = urllib.error.HTTPError("u", 403, "Forbidden", {}, None)
        with mock.patch("urllib.request.urlopen", side_effect=erreur):
            r = ig.page_get(BASE + REACH[2])
        self.assertEqual((r.ok, r.status), (False, 403))
        with mock.patch("urllib.request.urlopen", side_effect=TimeoutError("lent")):
            r = ig.page_get(BASE + REACH[2])
        self.assertEqual((r.ok, r.status), (False, None))

    def test_la_cadence(self):
        self.assertGreaterEqual(ig.PROBE_DELAY_S, 1.0)


class DeBoutEnBout(unittest.TestCase):
    """Par ``match_offer`` : la page AKS est simulée, la fiche Indiegala est la vraie."""

    def test_un_titre_nu_devient_un_candidat_steam_dans_la_region_de_la_fiche(self):
        # Avant [R69] : « no platform in title and AKS page does not confirm Direct Publisher »
        # (R27 / [R51]) pour les 161 lignes qui passent le precheck.
        for row, aks, region_id, label, edition in (
            (MHW, "Monster Hunter Wilds", "2", "GLOBAL", "10"),
            (LBA2, "Little Big Adventure 2", "2", "GLOBAL", "1"),
            (TOWNFALL, "SILENT HILL: Townfall", "8", "US", "1"),
        ):
            with self.subTest(row[1]):
                res, fetch = _match(row, aks_name=aks)
                self.assertIsInstance(res, Candidate, getattr(res, "reason", ""))
                self.assertEqual((res.platform, res.region_id, res.region_label,
                                  res.region_implicit, res.edition_id),
                                 ("STEAM", region_id, label, False, edition))
                self.assertEqual(fetch.appels, [BASE + row[2]])

    def test_les_refus_de_region(self):
        for row, attendu in ((BELMONT, "forbidden region: INDIEGALA LOCK (EU + US)"),
                             (REACH, "forbidden region: INDIEGALA LOCK (COUNTRY OF PURCHASE)")):
            with self.subTest(row[1]):
                res, fetch = _match(row)
                self.assertIsInstance(res, SkippedOffer)
                self.assertEqual(res.reason, attendu)
                self.assertEqual(len(fetch.appels), 1)

    def test_la_fiche_perimee_n_entre_pas(self):
        res, fetch = _match(AOT3, aks_name="Attack on Titan 3")
        self.assertIsInstance(res, SkippedOffer)
        self.assertIn("unreadable", res.reason)
        self.assertIn("fiche périmée", res.reason)
        self.assertIn("R32", res.reason)

    def test_le_suffixe_qui_contredit_la_fiche_n_entre_pas(self):
        res, _ = _match(TOWNFALL, aks_name="SILENT HILL: Townfall",
                        titre="SILENT HILL: Townfall Standard (EU)")
        self.assertIsInstance(res, SkippedOffer)
        self.assertIn("contredit la fiche", res.reason)

    def test_un_bundle_est_refuse_sans_ouvrir_la_fiche(self):
        res, fetch = _match(BUNDLE, aks_name="Castlevania: Lords of Shadow 2")
        self.assertIsInstance(res, SkippedOffer)
        self.assertIn("BUNDLE", res.reason)
        self.assertEqual(fetch.appels, [])

    def test_la_page_aks_doit_vendre_la_plateforme_de_la_fiche(self):
        res, _ = _match(LBA2, plateformes=("Epic Store",))
        self.assertIsInstance(res, SkippedOffer)
        self.assertIn("R20", res.reason)

    def test_une_fiche_illisible_n_entre_jamais(self):
        with mock.patch.object(ig, "fetch_product_page",
                               side_effect=ig.IndiegalaPageUnreadable("503")):
            res = match_offer(_offre(*LBA2[1:]),
                              resolver=lambda n, **k: _aks("Little Big Adventure 2",
                                                           ("Steam", "Direct Publisher")),
                              consoles=True)
        self.assertIsInstance(res, SkippedOffer)
        self.assertIn("unreadable", res.reason)

    def test_le_dlc_de_la_fiche_est_une_garde_pas_un_routage(self):
        # Aperçu du 06/10 : « Thunder Ray - Origin » (fiche DLC, titre sans marqueur, ORIGIN =
        # bruit de plateforme) sortait Standard(1) sur la page du jeu de base. La fiche ne
        # choisit pas le seau (R18 / [R43] / [R57] le font), mais une fiche DLC qui n'aboutit
        # pas en DLC(16) est refusée — jamais un DLC écrit sur un seau de jeu de base.
        res, fetch = _match(THUNDER, aks_name="Thunder Ray")
        self.assertIsInstance(res, SkippedOffer, getattr(res, "edition_id", ""))
        self.assertIn("offer page says DLC", res.reason)
        self.assertIn("Standard(1)", res.reason)
        self.assertIn("(R69)", res.reason)
        self.assertEqual(len(fetch.appels), 1)
        # SCUM Specialist Scout Pack sur une page AKS simulée SANS seau DLC : même refus…
        res, _ = _match(SCUM, aks_name="SCUM Specialist Scout Pack")
        self.assertIsInstance(res, SkippedOffer)
        self.assertIn("offer page says DLC", res.reason)
        # … et sur SA page à seau DLC unique (la vraie, lue à l'aperçu) : candidat DLC(16) par
        # R18 — la fiche n'a rien routé, elle a laissé passer ce qui aboutit en DLC.
        res, _ = _match(SCUM, aks_name="SCUM Specialist Scout Pack", editions={"16": "DLC"})
        self.assertIsInstance(res, Candidate, getattr(res, "reason", ""))
        self.assertEqual((res.edition_id, res.region_id), ("16", "2"))
        # Une fiche qui ne dit PAS « DLC » n'est jamais retenue par la garde (LBA2, Standard).
        res, _ = _match(LBA2, aks_name="Little Big Adventure 2")
        self.assertIsInstance(res, Candidate, getattr(res, "reason", ""))
        self.assertEqual(res.edition_id, "1")

    def test_le_signal_dlc_est_porte_par_offer_signals(self):
        for row, attendu in ((THUNDER, True), (SCUM, True), (LBA2, False), (MHW, False)):
            with self.subTest(row[1]):
                fetch = _FetchFixture(row[0])
                with mock.patch.object(ig, "fetch_product_page", side_effect=fetch):
                    sig = ig.offer_signals(BASE + row[2], row[1])
                self.assertIs(sig.dlc, attendu)

    def test_une_ligne_console_lit_la_fiche_et_refuse_le_conflit(self):
        # Aucune ligne console au feed du 21/09 ; si la grammaire partagée en lisait une, la fiche
        # « Steam Key » est un conflit (`console_page_authoritative`, [R68]) — jamais une page
        # console écrite sur une clé Steam.
        nom = "Hades (Nintendo Switch)"
        self.assertIsNotNone(classify_console(nom, BASE + REACH[2], "Indiegala"))
        fetch = _FetchFixture(REACH[0])
        with mock.patch.object(ig, "fetch_product_page", side_effect=fetch):
            res = match_offer(_offre(nom, REACH[2]), resolver=lambda n, **k: None, consoles=True)
        self.assertIsInstance(res, SkippedOffer)
        self.assertIn("platform conflict: console row vs offer page=STEAM", res.reason)
        self.assertEqual(len(fetch.appels), 1)


class LeRegistre(unittest.TestCase):
    def test_indiegala_est_enregistre_hors_liste_blanche(self):
        cfg = merchant_config("Indiegala")
        self.assertIs(cfg.offer_page_resolver, ig.offer_signals)
        self.assertIs(cfg.title_region, ig.title_region)
        self.assertIs(cfg.resolve_name, ig.resolve_name)
        self.assertIs(cfg.guard_name, ig.guard_name)
        self.assertTrue(cfg.console_page_authoritative)
        self.assertEqual(cfg.domain, "indiegala.com")
        self.assertEqual(MERCHANT_STORE_IDS["Indiegala"], "95")
        trouve = merchant_for_store("95")
        self.assertEqual(getattr(trouve, "name", trouve), "Indiegala")
        # Liste blanche : Romain, 2026-10-06, « go pour la liste blanche », APRÈS l'aperçu à blanc
        # ligne par ligne (docs/apercu_indiegala_2026-10-06.md) — jamais avant.
        from src.admin.auto_merchants import AUTO_MERCHANTS
        from src import merchant_groups
        self.assertIn(("Indiegala", "95"), AUTO_MERCHANTS)
        # Groupe B (Romain, 06/10, même soir : « groupe B pour Indiegala ») — et un seul groupe.
        dans = [g for g in merchant_groups.group_names()
                if "95" in {store for _, store in merchant_groups.group_targets(g)}]
        self.assertEqual(dans, ["B"])


class LesAutresMarchandsNeBougentPas(unittest.TestCase):
    def test_seul_indiegala_lit_cette_fiche(self):
        self.assertIs(merchant_config("Allyouplay").offer_page_resolver, allyouplay.offer_signals)
        self.assertIs(merchant_config("Gamesplanet FR").offer_page_resolver,
                      gamesplanet.offer_signals)
        self.assertIsNone(merchant_config("Loaded").offer_page_resolver)
        self.assertIsNone(merchant_config("Allyouplay").title_region)
        self.assertIsNone(merchant_config("Allyouplay").resolve_name)

    def test_la_table_r59_est_intacte(self):
        self.assertEqual(region_from_lock(("NOT", frozenset({"cyprus", US}))),
                         (None, "GAMESPLANET LOCK (EU + US)"))
        self.assertEqual(region_from_lock(("NOT", frozenset({"japan"}))), ("global", ""))
        self.assertEqual(region_from_lock(None), ("global", ""))


if __name__ == "__main__":
    unittest.main()

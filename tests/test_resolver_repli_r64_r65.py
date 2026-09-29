"""[R64] rang de repli « nom d'édition retiré, confirmé par l'index » et [R65] gabarits console
« -key » / « -code » — audit « pas de page produit AKS » du 2026-09-28, propositions 1 et 2.

Romain, 2026-09-29 : « go pour les corrections 1 et 2 et les vérifications ».

Tout passe par le VRAI chemin : `resolve_aks` / `resolve_aks_url` / `match_offer`, un faux GET
qui ne sert que des pages AKS RÉELLES réduites aux blocs lus par le matcher
(`tests/fixtures/pages_r64_r65/`, lues en UA AKS/Staff les 28 et 29/09), et un index sitemap
fait des entrées RÉELLES du relevé du 2026-09-28 (213 780 pages) qui concernent chaque cas.
Toute autre URL répond 404 ; chaque URL demandée est notée, pour prouver qu'aucune sonde ne
part à l'aveugle. Les titres sont ceux de la population de l'audit (refus « no AKS product page
found » des balayages A pass 9 / groupe B)."""

import functools
import unittest
import unittest.mock
from pathlib import Path

import src.matcher as M
from src.aks_env import HttpProbeResult
from src.aks_sitemap import SitemapIndex
from src.console_keys import (
    CONSOLE_FALLBACK_TEMPLATES,
    CONSOLE_PAGE_KINDS,
    classify_console,
    console_template_of,
    extract_console_pages,
)
from src.contracts import NormalizedOffer
from src.matcher import Candidate, SkippedOffer, match_offer, resolve_aks, resolve_aks_url

FIX = Path(__file__).resolve().parent / "fixtures" / "pages_r64_r65"
AKS = "https://www.allkeyshop.com/blog/"


def _url(slug_kind):
    return f"{AKS}buy-{slug_kind}-compare-prices/"


# Entrées RÉELLES du relevé sitemap du 2026-09-28 (extraits par préfixe de slug).
INDEX_28_09 = {
    "the-secret-of-monkey-island-cd-key", "the-secret-of-monkey-island-steam-account",
    "wwe-2k26-cd-key", "wwe-2k26-ps5-key", "wwe-2k26-xbox-series-key",
    "wwe-2k26-nintendo-switch-2-key", "wwe-2k26-king-of-kings-edition-pack-cd-key",
    "wwe-2k26-king-of-kings-edition-pack-xbox-series-key", "wwe-2k26-steam-account",
    "ground-control-2-operation-exodus-cd-key",
    "destiny-2-cd-key", "destiny-2-xbox-one-code", "destiny-2-ps4-game-code",
    "destiny-2-the-collection-xbox-key", "destiny-2-the-collection-ps4-key",
    "destiny-2-the-collection-ps5-key", "destiny-2-the-collection-xbox-one-key",
    "nhl-27-xbox-key", "nhl-27-ps5-key",
    "priest-simulator-vampire-show-xbox-series-key", "priest-simulator-vampire-show-ps5-key",
    "priest-simulator-vampire-show-epic-account",
    "grizzy-and-the-lemmings-crazy-party-xbox-key", "grizzy-and-the-lemmings-crazy-party-key",
    "grizzy-and-the-lemmings-crazy-party-ps4-key", "grizzy-and-the-lemmings-crazy-party-ps5-key",
    "marvels-midnight-suns-cd-key", "marvels-midnight-suns-xbox-one",
    "marvels-midnight-suns-xbox-series", "marvels-midnight-suns-ps4", "marvels-midnight-suns-ps5",
    "assassins-creed-chronicles-china-cd-key", "assassins-creed-chronicles-china-xbox-one",
    "assassins-creed-chronicles-china-xbox-series", "assassins-creed-chronicles-xbox-one-code",
    "assassins-creed-chronicles-ps4-game-code", "assassins-creed-chronicles-trilogy-xbox-one",
    "f1-25-cd-key", "f1-25-2026-season-edition-xbox-key", "f1-25-xbox-series",
    "star-wars-battlefront-2-xbox-one", "star-wars-battlefront-2-xbox-one-code",
    "star-wars-battlefront-2-cd-key",
    "hidden-legends-2-xbox-key", "hidden-legends-2-xbox-one-key", "hidden-legends-2-nintendo-switch",
    "tomb-raider-definitive-edition-xbox-one-code", "tomb-raider-definitive-edition-xbox-series-key",
    "tomb-raider-definitive-edition-ps4-key", "tomb-raider-definitive-edition-nintendo-switch",
    "far-cry-3-xbox-one", "far-cry-3-xbox-key", "far-cry-3-xbox-360-code",
}


def _index(entries=INDEX_28_09):
    return SitemapIndex(entries=frozenset(entries), fetched_at="2099-01-01T00:00:00Z",
                        incomplete=False, legacy=frozenset(), legacy_indexed=True)


def _fixture_pages():
    return {_url(p.stem): p.read_text(encoding="utf-8") for p in FIX.glob("*.html")}


class _Base(unittest.TestCase):
    extra_pages: dict = {}

    def setUp(self):
        saved = list(M._SITEMAP_CACHE)
        self.addCleanup(lambda: (M._SITEMAP_CACHE.clear(), M._SITEMAP_CACHE.extend(saved)))
        M.set_sitemap_index(_index())
        self.pages = dict(_fixture_pages())
        self.pages.update(self.extra_pages)
        self.asked = []

    def get(self, url, **_kw):
        self.asked.append(url)
        body = self.pages.get(url)
        if body:
            return HttpProbeResult(url=url, ok=True, status=200, body=body)
        return HttpProbeResult(url=url, ok=False, status=404, body="")

    def match(self, merchant, title, url="https://merchant.example/offer", consoles=True):
        resolver = functools.partial(resolve_aks, http_get_fn=self.get)
        page_resolver = functools.partial(resolve_aks_url, http_get_fn=self.get)
        offer = NormalizedOffer(offer_id="1", name=title, url=url, merchant=merchant)
        return match_offer(offer, resolver, M.resolve_difmark_offer, resolver,
                           page_resolver=page_resolver, consoles=consoles)

    def assertEnters(self, res, url, region_id, edition_id):
        self.assertIsInstance(res, Candidate, getattr(res, "reason", None))
        self.assertEqual((res.aks_url, res.region_id, res.edition_id), (url, region_id, edition_id))


# ─────────────────────────────── [R64] ───────────────────────────────────────────────────
class R64LesBases(unittest.TestCase):
    def test_un_a_trois_mots_avant_edition_du_plus_precis_au_moins_precis(self):
        self.assertEqual(M.edition_rank_bases("The Secret of Monkey Island: Special Edition (PC)"),
                         [("The Secret of Monkey Island", "Special Edition")])
        self.assertEqual(
            M.edition_rank_bases("WWE 2K26 | King of Kings Edition (PC) - Steam Key - GLOBAL")[-1],
            ("WWE 2K26", "King of Kings Edition"))
        self.assertEqual(
            M.edition_rank_bases("Ground Control 2: Operation Exodus Special Edition")[0],
            ("Ground Control 2: Operation Exodus", "Special Edition"))

    def test_jamais_definitive_remastered_anniversary(self):
        for titre in ("Age of Empires II: Definitive Edition", "Some Game Remastered Edition",
                      "Some Game 20th Anniversary Edition", "Some Game HD Collection"):
            with self.subTest(titre):
                self.assertEqual(M.edition_rank_bases(titre), [])

    def test_jamais_au_dela_d_un_separateur(self):
        bases = [b for b, _ in M.edition_rank_bases("Foo - Bar Special Edition")]
        self.assertEqual(bases, ["Foo - Bar", "Foo"],
                         "on s'arrête AU séparateur, on ne mange jamais le nom au-delà")

    def test_build_slug_candidates_n_est_pas_touche(self):
        """[R57] lit `build_slug_candidates` : le rang de repli n'y entre pas (revue adverse :
        52 titres y basculaient)."""
        self.assertNotIn("the-secret-of-monkey-island",
                         M.build_slug_candidates("The Secret of Monkey Island: Special Edition"))


class R64Resolution(_Base):
    def test_monkey_island_la_page_de_base_apres_tous_les_rangs(self):
        res = resolve_aks("The Secret of Monkey Island: Special Edition (PC)", self.get)
        self.assertEqual(res.url, _url("the-secret-of-monkey-island-cd-key"))
        self.assertEqual(res.edition_rank, "Special Edition")
        # la soupape (rang 1) d'abord, puis la seule base PUBLIÉE — rien d'autre
        self.assertEqual(self.asked, [_url("the-secret-of-monkey-island-special-edition-cd-key"),
                                      _url("the-secret-of-monkey-island-cd-key")])

    def test_aucune_sonde_a_l_aveugle(self):
        """Base non publiée → jamais sondée (pas de soupape dans ce rang)."""
        M.set_sitemap_index(_index(INDEX_28_09 - {"the-secret-of-monkey-island-cd-key"}))
        self.assertIsNone(resolve_aks("The Secret of Monkey Island: Special Edition (PC)", self.get))
        self.assertNotIn(_url("the-secret-of-monkey-island-cd-key"), self.asked)

    def test_sans_index_frais_le_rang_n_existe_pas(self):
        M.set_sitemap_index(None)
        with unittest.mock.patch.object(M, "search_aks_slugs", return_value=[]):
            self.assertIsNone(resolve_aks("The Secret of Monkey Island: Special Edition (PC)",
                                          self.get))
        self.assertNotIn(_url("the-secret-of-monkey-island-cd-key"), self.asked)

    def test_apres_tous_les_rangs_existants(self):
        """Une page que les rangs existants trouvent n'est jamais remplacée par la base."""
        self.pages[_url("the-secret-of-monkey-island-special-edition-cd-key")] = self.pages[
            _url("the-secret-of-monkey-island-cd-key")].replace(
            "Buy The Secret of Monkey Island CD Key", "Buy The Secret of Monkey Island Special Edition CD Key")
        res = resolve_aks("The Secret of Monkey Island: Special Edition (PC)", self.get)
        self.assertEqual((res.url, res.edition_rank),
                         (_url("the-secret-of-monkey-island-special-edition-cd-key"), ""))

    def test_nom_complet_publie_sous_un_autre_gabarit_rien_n_est_retire(self):
        """`f1-25-2026-season-edition-xbox-key` existe : AKS en fait un produit distinct."""
        self.assertEqual(M.edition_rank_probes("F1 25 | 2026 Season Edition (PC) - Steam Key - GLOBAL"), [])
        self.assertEqual(M.edition_rank_probes("Destiny 2: The Collection"), [],
                         "`destiny-2-the-collection-xbox-key` est publié")
        M.set_sitemap_index(_index(INDEX_28_09 - {"f1-25-2026-season-edition-xbox-key"}))
        self.assertEqual([u for _, u, _ in M.edition_rank_probes(
            "F1 25 | 2026 Season Edition (PC) - Steam Key - GLOBAL")], [_url("f1-25-cd-key")])


class R64Saisie(_Base):
    def test_monkey_island_entre_en_special_41(self):
        for merchant, titre, url, region in (
                ("GameSeal", "The Secret of Monkey Island: Special Edition (PC) Steam Key - EU",
                 "https://gameseal.com/the-secret-of-monkey-island-special-edition-pc-steam-key-eu", "9"),
                ("GameSeal", "The Secret of Monkey Island: Special Edition (PC) Steam Key - GLOBAL",
                 "https://gameseal.com/monkey-island-bundle-special-edition-en-de-fr-it-es-global", "2"),
                ("Gamerall", "The Secret of Monkey Island: Special Edition (Steam)",
                 "https://gamerall.com/game-genres/the-secret-of-monkey-island-special-edition-special-edition-steam-global",
                 "2")):
            with self.subTest(merchant=merchant, titre=titre):
                self.assertEnters(self.match(merchant, titre, url),
                                  _url("the-secret-of-monkey-island-cd-key"), region, "41")

    def test_wwe_2k26_king_of_kings_entre_dans_le_seau_10860(self):
        res = self.match("G2A", "WWE 2K26 | King of Kings Edition (PC) - Steam Key - GLOBAL",
                         "https://www.g2a.com/wwe-2k26-king-of-kings-edition-pc-steam-key-global-i10000514007047")
        self.assertEnters(res, _url("wwe-2k26-cd-key"), "2", "10860")

    def test_gog_ground_control_2_special_edition(self):
        res = self.match("GOG", "Ground Control 2: Operation Exodus Special Edition",
                         "https://www.gog.com/en/game/ground_control_2_operation_exodus")
        self.assertEnters(res, _url("ground-control-2-operation-exodus-cd-key"), "6", "41")

    def test_jamais_standard_marvels_midnight_suns_digital_plus(self):
        """Revue adverse : « mauvais palier ». La page de base vend « Digital+ Edition », mais
        DIGITAL et EDITION sont du bruit de format : aucun mot du titre ne NOMME ce seau, le bloc
        édition sortirait Standard(1). Refus, jamais Standard."""
        res = self.match("Gamesplanet FR", "Marvel's Midnight Suns Digital+ Edition",
                         "https://fr.gamesplanet.com/game/marvel-s-midnight-suns-digital-edition-steam-key--5306-2")
        if isinstance(res, SkippedOffer) and "(R32)" in res.reason:
            # Gamesplanet lit sa fiche (R32) : même titre, chez un marchand sans fiche.
            res = self.match("GameSeal", "Marvel's Midnight Suns Digital+ Edition (PC) Steam Key - GLOBAL")
        self.assertIsInstance(res, SkippedOffer)
        self.assertIn("(R64)", res.reason)
        self.assertIn("Digital+ Edition", res.reason, "le motif dit ce que la page vend")

    def test_destiny_2_the_collection_jamais_standard(self):
        """Contre-exemple de l'audit. Avec l'index réel, rien n'est retiré (le nom complet est
        publié en `-xbox-key`). Sans lui, la base `destiny-2` vend « Collection »(98) : la ligne
        y entre, jamais en Standard(1)."""
        res = self.match("MMOGA", "Destiny 2: The Collection",
                         "https://www.mmoga.com/Steam-Games/Destiny-2-The-Collection.html?ref=615")
        self.assertIsInstance(res, SkippedOffer)
        self.assertIn("no AKS product page found", res.reason)
        M.set_sitemap_index(_index({e for e in INDEX_28_09
                                    if not e.startswith("destiny-2-the-collection-")}))
        res = self.match("MMOGA", "Destiny 2: The Collection",
                         "https://www.mmoga.com/Steam-Games/Destiny-2-The-Collection.html?ref=615")
        self.assertIsInstance(res, Candidate, getattr(res, "reason", None))
        self.assertEqual((res.aks_url, res.edition_id), (_url("destiny-2-cd-key"), "98"))

    def test_un_titre_console_garde_la_marque_de_son_ancre(self):
        """La page console primaire est lue par URL et ne sait rien du rang : c'est l'ANCRE PC
        atteinte par le repli qui porte la marque jusqu'au bloc édition."""
        self.pages[_url("marvels-midnight-suns-xbox-one")] = (
            '<meta property="og:title" content="Buy Marvel&#039;s Midnight Suns Xbox One Compare Prices">'
            '<meta data-itemprop="platform" content="Xbox One" /><div data-product-id="93101"></div>'
            '<script>var a={"editions":{"1":{"name":"Standard"},"2065":{"name":"Digital+ Edition"}}};'
            '</script>')
        res = self.match("Kinguin", "Marvel's Midnight Suns Digital+ Edition US Xbox One CD Key",
                         "https://www.kinguin.net/category/909347/marvel-s-midnight-suns-digital-edition-us-xbox-one-cd-key")
        self.assertIsInstance(res, SkippedOffer)
        self.assertIn("(R64)", res.reason)

    def test_un_logiciel_n_entre_pas_par_ce_rang(self):
        """Titre réel (Kinguin), page SIMULÉE — aucune base logicielle de la population n'est
        publiée. Une page à licence UNIQUE serait adoptée par `resolve_software_edition` sans
        que le titre la nomme : « Ultra » perdu. Refus par ce rang."""
        M.set_sitemap_index(_index(INDEX_28_09 | {"cyberlink-powerdvd-24-cd-key"}))
        self.pages[_url("cyberlink-powerdvd-24-cd-key")] = (
            '<meta property="og:title" content="Buy CyberLink PowerDVD 24 CD Key Compare Prices">'
            '<div data-product-id="9"></div>'
            '<script>var a={"editions":{"lifetime":{"name":"Lifetime"}}};</script>')
        res = self.match("Kinguin", "CyberLink PowerDVD 24 Ultra Edition CD Key",
                         "https://www.kinguin.net/category/1/cyberlink-powerdvd-24-ultra-edition-cd-key")
        self.assertIsInstance(res, SkippedOffer)
        self.assertIn("software is not entered through the edition fallback rank (R64)", res.reason)


# ─────────────────────────────── [R65] ───────────────────────────────────────────────────
class R65Grammaire(unittest.TestCase):
    def test_console_page_kinds_n_est_pas_allonge(self):
        """Il nourrit `_AKS_PAGE_URL_RE` et [R18c] (`game_page`), qui ne passent jamais par un
        gabarit de repli."""
        self.assertEqual(CONSOLE_PAGE_KINDS, ("ps4", "ps5", "xbox-one", "xbox-series",
                                              "nintendo-switch", "nintendo-switch-2", "cd-key"))
        self.assertIsNone(M._AKS_PAGE_URL_RE.search("/blog/buy-nhl-27-xbox-key-compare-prices/"))

    def test_les_sept_gabarits_et_la_page_combinee(self):
        self.assertEqual(set(CONSOLE_FALLBACK_TEMPLATES), {
            "xbox-one-key", "xbox-series-key", "ps4-key", "ps5-key", "nintendo-switch-2-key",
            "xbox-one-code", "xbox-series-x", "xbox-key"})
        self.assertEqual(console_template_of(_url("wwe-2k26-xbox-series-key")),
                         ("wwe-2k26", "xbox-series-key"))
        self.assertEqual(console_template_of(_url("cod-black-ops-cold-war-xbox-series-x")),
                         ("cod-black-ops-cold-war", "xbox-series-x"))
        self.assertIsNone(console_template_of(_url("hades-xbox-series")))

    def test_la_barre_d_onglets_reelle_de_wwe_2k26(self):
        body = (FIX / "wwe-2k26-cd-key.html").read_text(encoding="utf-8")
        self.assertEqual(extract_console_pages(body), {
            "ps5-key": _url("wwe-2k26-ps5-key"),
            "xbox-series-key": _url("wwe-2k26-xbox-series-key"),
            "nintendo-switch-2-key": _url("wwe-2k26-nintendo-switch-2-key")})

    def test_key_nintendo_switch_2_reste_lu_comme_avant(self):
        body = ('<ul class="aks-offer-tabulations"><li><a href="'
                + _url("resident-evil-2-key-nintendo-switch-2") + '">x</a></li></ul>')
        self.assertEqual(extract_console_pages(body),
                         {"nintendo-switch-2": _url("resident-evil-2-key-nintendo-switch-2")})


class R65Prealable(_Base):
    DRIFFLE = ("Assassin's Creed Chronicles China (Europe) (Xbox One / Xbox Series X|S) - "
               "Xbox Live - Digital Key",
               "https://www.driffle.com/assassins-creed-chronicles-china-europe-xbox-one-xbox-series-xs-xbox-live-digital-key-p9933983")

    def test_le_nom_de_pays_reste_dans_le_nom_de_garde(self):
        sig = classify_console(*self.DRIFFLE, "Driffle")
        self.assertEqual((sig.resolve_name, sig.region_base, sig.region_words),
                         ("Assassin's Creed Chronicles China", "eu", ("Europe",)))

    def test_le_slug_garde_le_pays_quand_le_classifieur_l_a_garde(self):
        """Le nom de garde console n'a plus le créneau « (Europe) » : sans ``keep_country``,
        `cleaned_title` lirait « … China » comme un verrou en queue (règle PC inchangée)."""
        self.assertEqual(M.build_slug_candidates("Assassin's Creed Chronicles China")[0],
                         "assassins-creed-chronicles")
        self.assertEqual(M.build_slug_candidates("Assassin's Creed Chronicles China",
                                                 keep_country=True)[0],
                         "assassins-creed-chronicles-china")
        self.assertTrue(classify_console(*self.DRIFFLE, "Driffle").country_in_name)

    def test_un_vrai_verrou_pays_reste_un_verrou(self):
        sig = classify_console("Hades (Xbox One) Xbox Live Key CHINA", "https://x.test/hades", "Eneba")
        self.assertEqual((sig.resolve_name, sig.region_label), ("Hades", "CHINA"))

    def test_driffle_chine_entre_sur_l_episode_jamais_sur_la_trilogie(self):
        res = self.match("Driffle", *self.DRIFFLE)
        self.assertIsInstance(res, Candidate, getattr(res, "reason", None))
        self.assertEqual([(t.aks_url, t.region_id, t.edition_id) for t in res.all_targets], [
            (_url("assassins-creed-chronicles-china-xbox-one"), "24eu", "1"),
            (_url("assassins-creed-chronicles-china-xbox-series"), "302", "1")])
        self.assertFalse([u for u in self.asked if "assassins-creed-chronicles-xbox-one-code" in u
                          or "trilogy" in u], self.asked)


class R65Saisie(_Base):
    def test_eneba_priest_simulator_page_xbox_series_key_302(self):
        res = self.match("Eneba", "Priest Simulator: Vampire Show (Xbox Series X|S) XBOX LIVE Key EUROPE",
                         "https://www.eneba.com/xbox-priest-simulator-vampire-show-xbox-series-x-s-xbox-live-key-europe")
        self.assertEnters(res, _url("priest-simulator-vampire-show-xbox-series-key"), "302", "1")
        self.assertNotIn(_url("priest-simulator-vampire-show-xbox-series-x"), self.asked,
                         "gabarit non publié : jamais sondé")

    def test_g2a_nhl_27_deluxe_page_combinee_qui_se_declare_series(self):
        res = self.match("G2A", "NHL 27 | Deluxe Edition (Xbox Series X/S) - Xbox Live Key - EUROPE",
                         "https://www.g2a.com/nhl-27-deluxe-edition-xbox-series-x-s-xbox-live-key-europe-i10000515909006")
        self.assertEnters(res, _url("nhl-27-xbox-key"), "302", "7")
        self.assertEqual([t.platform for t in res.all_targets], ["XBOX_SERIES"])

    def test_onglet_de_repli_depuis_la_page_pc(self):
        """WWE 2K26 PC → onglet `-xbox-series-key` : lu par `resolve_aks_url` (sa grammaire).
        La ligne Gamivo réelle combine les deux correctifs : l'ancre PC `wwe-2k26` n'est
        atteinte que par [R64], la page Xbox Series par l'onglet [R65], et l'édition
        « King of Kings Edition »(10860) est NOMMÉE par le titre sur la page console."""
        res = self.match("Gamivo", "WWE 2K26 King of Kings Edition EN United States",
                         "https://www.gamivo.com/product/wwe-2k26-xbox-xbox-series-us-king-of-kings")
        self.assertEnters(res, _url("wwe-2k26-xbox-series-key"), "303", "10860")
        # GameBoost, Xbox sans génération (P4) : AKS n'a pas de page Xbox One, la page Xbox
        # Series est l'onglet `-xbox-series-key` de la page PC.
        res = self.match("GameBoost", "WWE 2K26 (Xbox Live) (EU)",
                         "https://gameboost.com/wwe-2k26-xbox-live-eu-00-75030")
        self.assertEnters(res, _url("wwe-2k26-xbox-series-key"), "302", "1")
        self.assertEqual([t.platform for t in res.all_targets], ["XBOX_SERIES"])

    def test_gabarit_code_son_nom_porte_code(self):
        """Gamivo déclare One + Series ; AKS n'a pour ce jeu que `-xbox-one-code` (nommée
        « … Xbox One Code ») et `-xbox-series-key`. CODE fait partie du suffixe de plateforme :
        sinon l'identité des deux pages divergeait (refus « is not … Xbox One Code »)."""
        from src.console_keys import console_page_identity
        self.assertEqual(console_page_identity("Tomb Raider Definitive Edition Xbox One Code"),
                         "Tomb Raider Definitive Edition")
        res = self.match("Gamivo", "Tomb Raider Definitive Edition EN United Kingdom",
                         "https://www.gamivo.com/product/tomb-raider-xbox-xboxoneseries-uk-en-definitive")
        # L'identité passe ; la ligne s'arrête plus loin, sur une vraie raison : la page Xbox
        # Series réelle (lue le 29/09) n'a AUCUNE carte d'éditions — une page vide (R19).
        self.assertIsInstance(res, SkippedOffer)
        self.assertIn("AKS XBOX_SERIES page carries no editions map", res.reason)
        self.assertEqual(self.asked[-2:], [_url("tomb-raider-definitive-edition-xbox-one-code"),
                                           _url("tomb-raider-definitive-edition-xbox-series-key")])

    def test_ligne_deja_creee_far_cry_3_devient_2b(self):
        """LA régression mesurée sur les 11 503 lignes créées de cette machine : Gamerall « Far
        Cry 3 - Classic Edition (Xbox Live) » (offre 101109116, créée le 25/09 sur la page Xbox
        One seule). AKS a AUSSI la page combinée `far-cry-3-xbox-key`, qui se déclare Xbox
        Series X (lue le 29/09) : pour une génération DÉDUITE, c'est 2b — refus, au lieu d'une
        saisie qui perd la page Series. Page PC et page Xbox One SIMULÉES (onglet et éditions
        d'après la création du 25/09) ; page combinée réelle."""
        pc = M.AksResolution(slug="far-cry-3", url=f"{AKS}compare-and-buy-cd-key-for-digital-download-far-cry-3/",
                             product_id="10", aks_name="Far Cry 3",
                             editions={"1": {"name": "Standard"}, "classic": {"name": "Classic"}},
                             official_platforms=("Ubisoft Connect",),
                             console_pages={"xbox-one": _url("far-cry-3-xbox-one")})
        one = M.AksResolution(slug="far-cry-3", url=_url("far-cry-3-xbox-one"), product_id="11",
                              aks_name="Far Cry 3 Xbox One",
                              editions={"1": {"name": "Standard"}, "classic": {"name": "Classic"}},
                              page_platform="Xbox One")
        combined = resolve_aks_url(_url("far-cry-3-xbox-key"), self.get)
        by_url = {one.url: one, combined.url: combined}
        offer = NormalizedOffer(offer_id="101109116", name="Far Cry 3 - Classic Edition (Xbox Live)",
                                url="https://gamerall.com/xbox/far-cry-3-classic-edition-classic-edition-xbox-live-europe",
                                merchant="Gamerall")
        res = match_offer(offer, lambda name, **kw: pc if "page_kind" not in kw else None,
                          page_resolver=by_url.get, consoles=True)
        self.assertIsInstance(res, SkippedOffer)
        self.assertIn("2b, non tranché", res.reason)

    def test_2b_generation_deduite_sur_la_page_combinee_reste_refusee(self):
        """Eneba, « XBOX LIVE Key » sans génération (P4). Grizzy : la page PC (`-key`) relie
        la page combinée, qui se déclare Xbox Series. Hidden Legends 2 : une page Xbox One
        `-xbox-one-key` ET la combinée pour Series — jamais une saisie One seule en perdant
        la page Series qu'AKS A."""
        for titre, url in (
                ("Grizzy and the Lemmings - Crazy Party XBOX LIVE Key EUROPE",
                 "https://www.eneba.com/xbox-grizzy-and-the-lemmings-crazy-party-xbox-live-key-europe"),
                ("Hidden Legends 2 XBOX LIVE Key EUROPE",
                 "https://www.eneba.com/xbox-hidden-legends-2-xbox-live-key-europe")):
            with self.subTest(titre):
                res = self.match("Eneba", titre, url)
                self.assertIsInstance(res, SkippedOffer)
                self.assertIn("2b, non tranché", res.reason)
                self.assertIn("XBOX_SERIES", res.reason)

    def test_generation_declaree_la_page_combinee_sert_la_generation_qu_elle_declare(self):
        """Kinguin déclare One ET Series : `-xbox-one-key` pour One, la combinée (méta Xbox
        Series X) pour Series — les deux pages réelles de « Destiny 2 The Collection »."""
        res = self.match("Kinguin", "Destiny 2: The Collection EU XBOX One / Xbox Series X|S CD Key",
                         "https://www.kinguin.net/category/714079/destiny-2-the-collection-eu-xbox-one-xbox-series-x-s-cd-key")
        self.assertIsInstance(res, Candidate, getattr(res, "reason", None))
        self.assertEqual([(t.platform, t.aks_url, t.region_id, t.edition_id) for t in res.all_targets], [
            ("XBOX_ONE", _url("destiny-2-the-collection-xbox-one-key"), "24eu", "1"),
            ("XBOX_SERIES", _url("destiny-2-the-collection-xbox-key"), "302", "1")])

    def test_p1_une_cle_series_n_entre_jamais_sur_la_seule_page_xbox_one(self):
        """Kinguin « Kinect Sports Rivals EU Xbox Series X|S » : AKS n'a que
        `kinect-sports-rivals-xbox-one-code` (relevé du 28/09). Jamais sondée, jamais saisie."""
        M.set_sitemap_index(_index(INDEX_28_09 | {"kinect-sports-rivals-xbox-one-code"}))
        res = self.match("Kinguin", "Kinect Sports Rivals EU Xbox Series X|S CD Key",
                         "https://www.kinguin.net/category/159485/kinect-sports-rivals-eu-xbox-series-x-s-cd-key")
        self.assertIsInstance(res, SkippedOffer)
        self.assertIn("no AKS product page found (console)", res.reason)
        self.assertFalse([u for u in self.asked if "xbox-one" in u], self.asked)

    def test_deux_pages_pour_une_meme_console_refus(self):
        """`star-wars-battlefront-2-xbox-one` ET `…-xbox-one-code` sont publiés (relevé du 28/09) :
        on ne choisit pas. Titre construit dans la grammaire Kinguin et page PC SIMULÉE (onglet
        `-xbox-one-code`, comme la page PC réelle de Destiny 2) : la population de l'audit n'a
        pas de ligne console sur ces 21 jeux."""
        self.pages[_url("star-wars-battlefront-2-cd-key")] = (
            '<meta property="og:title" content="Buy Star Wars Battlefront 2 CD Key Compare Prices">'
            '<div data-product-id="1"></div><p>official platforms: Origin.</p>'
            '<ul class="aks-offer-tabulations"><li><a href="'
            + _url("star-wars-battlefront-2-xbox-one-code") + '">x</a></li></ul>'
            '<script>var a={"editions":{"1":{"name":"Standard"}}};</script>')
        res = self.match("Kinguin", "Star Wars Battlefront 2 EU XBOX One CD Key",
                         "https://www.kinguin.net/category/1/star-wars-battlefront-2-eu-xbox-one-cd-key")
        self.assertIsInstance(res, SkippedOffer)
        self.assertIn("2 different XBOX_ONE pages", res.reason)
        self.assertIn("(R65)", res.reason)

    def test_la_meta_reste_juge(self):
        """Un onglet `-xbox-one-key` dont la page se déclare Xbox Series : refus. Page SIMULÉE
        (la vraie `hidden-legends-2-xbox-one-key` se déclare Xbox One), titre construit."""
        self.pages[_url("hidden-legends-2-xbox-one-key")] = (
            '<meta property="og:title" content="Buy Hidden Legends 2 Xbox One Compare Prices">'
            '<meta data-itemprop="platform" content="Xbox Series X" />'
            '<div data-product-id="2"></div>'
            '<script>var a={"editions":{"1":{"name":"Standard"}}};</script>')
        res = self.match("Kinguin", "Hidden Legends 2 EU Xbox One CD Key",
                         "https://www.kinguin.net/category/1/hidden-legends-2-eu-xbox-one-cd-key")
        self.assertIsInstance(res, SkippedOffer)
        self.assertIn("se déclare XBOX_SERIES", res.reason)

    def test_sans_index_aucun_gabarit_de_repli_n_est_sonde(self):
        M.set_sitemap_index(None)
        self.assertIsNone(resolve_aks("Priest Simulator: Vampire Show", self.get,
                                      page_kind="xbox-series-key"))
        self.assertEqual(self.asked, [])


if __name__ == "__main__":
    unittest.main()

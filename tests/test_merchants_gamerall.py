"""Gamerall (store 13, marchand AKS 317) — `[R54]`, 2026-09-18.

Romain : « pour le data entry auto, on va devoir travailler sur Gamerall ». Les règles sont
écrites à partir de 783 lignes réelles, pages 1-6 ET 26-31 — pas d'une seule page, et c'est la
leçon la plus chère de cette mise en place : la page 1 dit que 11 % des lignes portent leur
région, les pages profondes disent 100 %, l'ensemble 82 %. J'avais annoncé « 89 % sans région »
d'après la page 1 seule, et c'était faux.

Ce que le feed dit vraiment :

* le titre finit TOUJOURS par sa plateforme entre parenthèses — Steam 681, Xbox Live 38,
  EA App 25, Ubisoft Connect 14, Nintendo Switch 7, PSN 4, Microsoft Store 3, GOG.com 2,
  Epic Games 2, Rockstar 1 ;
* le titre ne porte JAMAIS de région, sur aucune des 783 lignes ;
* l'URL porte la plateforme (274 slugs sur 275) et, dans 82 % des cas, la région ;
* le vocabulaire de région tient en trois mots : ``global`` 514, ``europe`` 123, ``usa`` 6.

**Région absente ⇒ on ouvre la page** (arbitrage de Romain). La page Gamerall répond en 200 et
porte sa région dans son JSON embarqué. Une page illisible, ou lisible sans région, est un
REFUS — jamais un repli sur GLOBAL, exactement la règle qu'Instant Gaming s'est donnée après
son audit #2.
"""

import unittest

from src.merchants import gamerall as g
from src.merchants.registry import merchant_config, merchant_for_store


class _Page:
    def __init__(self, body="", status=200, ok=True, error=None):
        self.body, self.status, self.ok, self.error = body, status, ok, error


def _get(body="", **kw):
    def _fn(url, **_):
        return _Page(body=body, **kw)
    return _fn


PAGE_GLOBAL = '... "Region","value":"Global" ...'
PAGE_ESCAPED = '... Region&quot;,&quot;value&quot;:&quot;Europe&quot; ...'


class TitleGrammarTests(unittest.TestCase):
    def test_the_platform_is_read_from_the_trailing_parenthesis(self):
        for name, token in (
            ("The Witcher 3: Wild Hunt - Complete Edition (Xbox Live)", "XBOX"),
            ("Die in the Dungeon (Steam)", "STEAM"),
            ("Anno 1800 (Ubisoft Connect)", "UPLAY"),
            ("EA FC 25 (EA App)", "EA"),
            ("Mario Kart (Nintendo Switch)", "NINTENDO"),
            ("Ghost of Tsushima (PSN)", "PSN"),
            ("Cyberpunk 2077 (GOG.com)", "GOG"),
        ):
            with self.subTest(name=name):
                self.assertEqual(g.title_platform(name), token)

    def test_an_unknown_platform_is_refused_BY_NAME_not_guessed(self):
        reason = g.precheck("Some Game (Amiga)", "https://gamerall.com/a/some-game-amiga")
        self.assertIsNotNone(reason)
        self.assertIn("R54", reason)
        self.assertIn("Amiga", reason, "le refus doit nommer ce qu'il n'a pas compris")

    def test_a_title_without_a_platform_is_refused(self):
        self.assertIsNotNone(g.precheck("Some Game", "https://gamerall.com/a/some-game"))

    def test_the_platform_is_peeled_from_the_name(self):
        self.assertEqual(
            g.resolve_name("The Witcher 3: Wild Hunt - Complete Edition (Xbox Live)"),
            "The Witcher 3: Wild Hunt - Complete Edition")
        self.assertEqual(g.resolve_name("Die in the Dungeon (Steam)"), "Die in the Dungeon")

    def test_resolve_name_never_returns_empty(self):
        self.assertTrue(g.resolve_name("(Steam)").strip())


class UrlGrammarTests(unittest.TestCase):
    def test_the_region_is_read_from_the_end_of_the_slug(self):
        for url, base in (
            ("https://gamerall.com/steam-games-and-more/x-steam-global", "global"),
            ("https://gamerall.com/xbox/the-witcher-3-xbox-live-usa", "us"),
            ("https://gamerall.com/pc/y-steam-europe", "eu"),
        ):
            with self.subTest(url=url):
                self.assertEqual(g.url_region(url), base)

    def test_no_region_in_the_url_reads_as_absent_not_as_global(self):
        """Le cœur de la règle : l'absence n'est pas une valeur."""

        self.assertIsNone(g.url_region("https://gamerall.com/a/risk-of-rain-returns-steam"))

    def test_a_region_word_inside_the_name_is_not_mined(self):
        """« Europa » n'est pas « europe » : seule la FIN du slug compte."""

        self.assertIsNone(g.url_region("https://gamerall.com/a/europa-universalis-iv-steam"))

    def test_the_platform_is_also_readable_from_the_slug(self):
        for url, token in (
            ("https://gamerall.com/a/x-steam-global", "STEAM"),
            ("https://gamerall.com/a/y-xbox-live-usa", "XBOX"),
            ("https://gamerall.com/a/z-ea-app-global", "EA"),
            ("https://gamerall.com/a/w-gog-com", "GOG"),
        ):
            with self.subTest(url=url):
                self.assertEqual(g.url_platform(url), token)

    def test_the_section_is_not_mistaken_for_a_platform(self):
        """« steam-games-and-more » est une rubrique : le mot cherché est en fin de slug."""

        self.assertIsNone(g.url_platform("https://gamerall.com/steam-games-and-more/"))


class TheTitleIsCheckedFIRSTTests(unittest.TestCase):
    """Romain 2026-09-18 : « pour certains marchands on peut avoir une info dans le titre qui
    n'est pas dans l'URL […] mets un check du titre par défaut avant d'ouvrir la page, ça reste
    plus opti ». L'ordre est donc TITRE, puis URL, puis page — du gratuit vers le coûteux.

    Sur Gamerall le titre ne donne rien aujourd'hui (0 ligne sur 783 en porte une) ; le crible
    existe pour le jour où ce feed changera d'habitude, et parce que le contrat doit être le
    même pour tous les marchands."""

    def test_a_region_written_in_the_title_is_read(self):
        for name, base in (
            ("Die in the Dungeon (Steam) GLOBAL", "global"),
            ("X (Steam) EUROPE", "eu"),
            ("X (Steam) - United States", "us"),
            ("Z (DLC) (Steam) UK", "uk"),
        ):
            with self.subTest(name=name):
                self.assertEqual(g.title_region(name), base)

    def test_a_title_without_a_region_says_nothing(self):
        self.assertIsNone(g.title_region("Die in the Dungeon (Steam)"))

    def test_the_game_name_is_never_mined_for_a_region(self):
        """« Europa Universalis » ne doit pas devenir « eu » : on ne lit que ce qui SUIT la
        parenthèse de plateforme."""

        self.assertIsNone(g.title_region("Europa Universalis IV (Steam)"))
        self.assertIsNone(g.title_region("US Route 66 Simulator (Steam)"))

    def test_the_title_wins_WITHOUT_opening_the_page(self):
        def _boom(*a, **k):
            raise AssertionError("la page ne devait pas être ouverte")
        sig = g.offer_signals("https://gamerall.com/a/x-steam", "X (Steam) EUROPE", _boom)
        self.assertEqual(sig.region_base, "eu")
        self.assertEqual(sig.platform, "STEAM")

    def test_the_title_is_read_even_when_the_parenthesis_is_not_last(self):
        """Le défaut trouvé en écrivant ce test : la parenthèse de plateforme était cherchée
        ANCRÉE en fin de titre, or un titre portant une région ne finit plus par elle — le
        crible ne se déclenchait donc jamais."""

        self.assertIsNotNone(g.title_region("Die in the Dungeon (Steam) GLOBAL"))


class PageIsOnlyReadWhenNeededTests(unittest.TestCase):
    """Le matcher appelle le résolveur pour CHAQUE offre ; 550 ko par ligne serait absurde."""

    def test_a_url_that_carries_its_region_never_fetches(self):
        def _boom(*a, **k):
            raise AssertionError("la page ne devait pas être ouverte")
        sig = g.offer_signals("https://gamerall.com/a/x-steam-global", "X (Steam)", _boom)
        self.assertTrue(sig.region_resolved)
        self.assertEqual(sig.region_base, "global")
        self.assertEqual(sig.platform, "STEAM")

    def test_a_url_without_a_region_reads_the_page(self):
        sig = g.offer_signals("https://gamerall.com/a/x-steam", "X (Steam)", _get(PAGE_GLOBAL))
        self.assertEqual(sig.region_base, "global")
        self.assertTrue(sig.region_resolved)

    def test_the_escaped_json_form_is_read_too(self):
        sig = g.offer_signals("https://gamerall.com/a/x-steam", "X (Steam)", _get(PAGE_ESCAPED))
        self.assertEqual(sig.region_base, "eu")


class TheFailClosedRulesTests(unittest.TestCase):
    """« On ne se replie jamais sur GLOBAL » — la règle d'Instant Gaming après son audit #2."""

    def test_an_unreachable_page_raises(self):
        def _fail(*a, **k):
            raise OSError("connexion refusée")
        with self.assertRaises(g.GamerallPageUnreadable):
            g.offer_signals("https://gamerall.com/a/x-steam", "X (Steam)", _fail)

    def test_a_non_200_raises(self):
        with self.assertRaises(g.GamerallPageUnreadable):
            g.offer_signals("https://gamerall.com/a/x-steam", "X (Steam)", _get("", status=503, ok=False))

    def test_a_page_without_a_region_raises_instead_of_defaulting(self):
        with self.assertRaises(g.GamerallPageUnreadable) as ctx:
            g.offer_signals("https://gamerall.com/a/x-steam", "X (Steam)", _get("<html>rien ici</html>"))
        self.assertIn("GLOBAL", str(ctx.exception))

    def test_a_region_read_but_NOT_sellable_is_reported_not_swallowed(self):
        """Le libellé brut remonte : le routage blacklist/garder est décidé ailleurs, en un
        seul endroit, pas ici."""

        sig = g.offer_signals("https://gamerall.com/a/x-steam", "X (Steam)",
                              _get('"Region","value":"Latin America"'))
        self.assertTrue(sig.region_resolved)
        self.assertIsNone(sig.region_base)
        self.assertEqual(sig.region_label, "Latin America")

    def test_a_forbidden_region_in_the_url_is_refused_by_the_precheck(self):
        reason = g.precheck("X (Steam)", "https://gamerall.com/a/x-steam-turkey")
        self.assertIsNone(reason, "une région inconnue de la table n'est pas une interdiction")


class RegistryTests(unittest.TestCase):
    def test_registered_and_domain_locked(self):
        cfg = merchant_config("Gamerall")
        self.assertIs(cfg, g.CONFIG)
        self.assertEqual(cfg.domain, "gamerall.com")
        self.assertIs(cfg.precheck, g.precheck)
        self.assertIs(cfg.resolve_name, g.resolve_name)

    def test_the_store_id_resolves(self):
        self.assertEqual(merchant_for_store("13"), "Gamerall")
        self.assertEqual(g.STORE_ID, "13")
        self.assertEqual(g.AKS_MERCHANT_ID, "317")

    def test_the_page_resolver_is_declared(self):
        cfg = merchant_config("Gamerall")
        self.assertIsNotNone(cfg.offer_page_resolver)
        self.assertTrue(cfg.title_is_platform_source)

    def test_off_the_safe_auto_allowlist_until_proven(self):
        from src.admin.auto_merchants import AUTO_MERCHANTS
        self.assertNotIn("Gamerall", [n for n, _ in AUTO_MERCHANTS])


if __name__ == "__main__":
    unittest.main()

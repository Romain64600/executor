import json
import unittest

from src.aks_env import HttpProbeResult
from src.contracts import NormalizedFeed, NormalizedOffer
from src.matcher import (
    AksNameUnreadable,
    AksProbeUnreliable,
    AksResolution,
    Candidate,
    DifmarkOfferAttributes,
    DifmarkPageUnreadable,
    SkippedOffer,
    build_slug_candidates,
    dangerous_qualifier,
    detect_edition,
    detect_platform,
    detect_region,
    explicit_platform,
    explicit_platform_from_url,
    extra_significant_words,
    extract_aks_name,
    extract_difmark_top_offer_url,
    extract_editions,
    extract_official_platforms,
    extract_prices,
    match_feed,
    match_offer,
    missing_aks_words,
    parse_difmark_offer_attributes,
    precheck_skip,
    resolve_aks,
    resolve_difmark_offer,
    search_aks_slugs,
    strip_merchant_url_noise,
    tokenize,
)

AKS_PAGE = (
    '<html><head>'
    '<meta property="og:title" content="Buy Neon Beats CD Key Compare Prices">'
    '</head><body>'
    '<div data-product-id="205027"></div>'
    '<script>var x={"editions":{"1":{"name":"Standard"},"7":{"name":"Deluxe"}}};</script>'
    '</body></html>'
)


def _offer(name, url="https://m.test/x", oid="1"):
    return NormalizedOffer(offer_id=oid, name=name, url=url, merchant="Test")


class TokenizeTests(unittest.TestCase):
    def test_normalizes_apostrophes(self):
        self.assertEqual(tokenize("Dragon’s Dogma"), ["DRAGON'S", "DOGMA"])

    def test_unicode_roman_numeral_survives_tokenization(self):
        # Eneba escape (2026-07-16): "Road to Empress Ⅱ" (U+2161, a single
        # Unicode Roman numeral codepoint) used to tokenize to just
        # ROAD/TO/EMPRESS — the sequel indicator silently vanished and the
        # offer matched the unrelated base game "Road To Empress". NFKC
        # decomposes it to plain ASCII "II" before tokenizing.
        self.assertEqual(
            tokenize("Road to Empress Ⅱ Steam Key"),
            ["ROAD", "TO", "EMPRESS", "II", "STEAM", "KEY"],
        )
        self.assertEqual(
            extra_significant_words("Road To Empress", "Road to Empress Ⅱ Steam Key"),
            ["II"],
        )

    def test_unicode_roman_numeral_survives_slug_building(self):
        # Same escape: build_slug_candidates feeds the AKS resolve URL from
        # the same text, so the wrong page was being probed in the first
        # place, not just wrongly approved after tokenizing.
        self.assertIn(
            "road-to-empress-ii", build_slug_candidates("Road to Empress Ⅱ Steam Key")
        )

    def test_r01_all_words_present(self):
        self.assertEqual(
            missing_aks_words("Neon Beats", "Neon Beats - Full Version (PC) - Steam Key - GLOBAL"),
            [],
        )

    def test_r01_apostrophe_mismatch_is_missing(self):
        self.assertEqual(missing_aks_words("Dragon's Dogma", "Dragons Dogma"), ["DRAGON'S"])


class QualifierTests(unittest.TestCase):
    def test_dangerous_qualifier_detected(self):
        self.assertEqual(dangerous_qualifier("Dead Space Remake", "Dead Space"), "REMAKE")

    def test_qualifier_present_in_aks_name_is_ok(self):
        self.assertIsNone(dangerous_qualifier("Dead Space Remake", "Dead Space Remake"))


class MerchantUrlNoiseTests(unittest.TestCase):
    def test_strips_difmark_boilerplate_case_insensitively(self):
        self.assertEqual(
            strip_merchant_url_noise(
                "https://difmark.com/en/Buy-Console-Account-rogue-loops-166307",
                "Difmark",
            ),
            "https://difmark.com/en/rogue-loops-166307",
        )

    def test_unmapped_merchant_is_untouched(self):
        url = "https://difmark.com/en/buy-console-account-rogue-loops-166307"
        self.assertEqual(strip_merchant_url_noise(url, "SomeOtherMerchant"), url)


# Trimmed real fixtures (Romain, 2026-07-17): captured live from
# https://difmark.com/en/buy-console-account-rogue-loops-steam-account-166307
# and its embedded top-offer API link.
DIFMARK_PAGE_HTML = (
    '<link rel="canonical" href="https://difmark.com/en/x">'
    '"tabs":[{"name":"Steam Account","product_id":166307,"offer_type_id":9,'
    '"url_top_offer":"https:\\/\\/difmark.com\\/en\\/products\\/166307\\/top-offer?offer_type=9",'
    '"url_top_offer_with_get_params":"https:\\/\\/difmark.com\\/en\\/products\\/166307\\/top-offer'
    '?offer_type=9&referal=allkeyshop&marketplace_id=2&edition_id=780&region_product_id=1'
    '&seller_id%5B0%5D=275327&seller_id%5B1%5D=2300110",'
    '"url_offers_by_type":"https:\\/\\/difmark.com\\/en\\/products\\/166307\\/offers-by-type\\/9"}]'
)
DIFMARK_TOP_OFFER_URL = (
    "https://difmark.com/en/products/166307/top-offer?offer_type=9&referal=allkeyshop"
    "&marketplace_id=2&edition_id=780&region_product_id=1&seller_id%5B0%5D=275327"
    "&seller_id%5B1%5D=2300110"
)


def _difmark_top_offer_body(region="Global", edition="Standard"):
    return json.dumps({
        "offer": {
            "id": 12273300,
            "offer_attributes": [
                {"code": "id", "name": "ID", "value": 12273300},
                {"code": "marketplace", "name": "Platform", "value": "Steam"},
                {"code": "edition", "name": "Edition", "value": edition},
                {"code": "region", "name": "Region", "value": region},
                {"code": "delivery_time", "name": "Delivery", "value": "15 minutes"},
                {"code": "warranty", "name": "Warranty", "value": "180 days"},
                {"code": "stock", "name": "Stock", "value": 100},
            ],
        }
    })


class DifmarkOfferResolverTests(unittest.TestCase):
    def test_extract_top_offer_url_from_real_page_fixture(self):
        self.assertEqual(extract_difmark_top_offer_url(DIFMARK_PAGE_HTML), DIFMARK_TOP_OFFER_URL)

    def test_extract_top_offer_url_missing_is_none(self):
        self.assertIsNone(extract_difmark_top_offer_url("<html>no such field</html>"))

    def test_parse_offer_attributes_real_shape(self):
        attrs = parse_difmark_offer_attributes(_difmark_top_offer_body())
        self.assertEqual(attrs["region"], "Global")
        self.assertEqual(attrs["edition"], "Standard")
        self.assertEqual(attrs["marketplace"], "Steam")

    def test_parse_offer_attributes_bad_json_is_none(self):
        self.assertIsNone(parse_difmark_offer_attributes("not json"))

    def test_parse_offer_attributes_unexpected_shape_is_none(self):
        self.assertIsNone(parse_difmark_offer_attributes(json.dumps({"offer": {}})))

    def test_resolve_offer_global_steam_end_to_end(self):
        product_url = "https://difmark.com/en/buy-console-account-rogue-loops-steam-account-166307"

        def fake_http(url, timeout=15, user_agent=None):
            if url == product_url:
                return HttpProbeResult(url=url, ok=True, status=200, body=DIFMARK_PAGE_HTML)
            if url == DIFMARK_TOP_OFFER_URL:
                return HttpProbeResult(
                    url=url, ok=True, status=200,
                    body=_difmark_top_offer_body(region="Global"),
                )
            return HttpProbeResult(url=url, ok=False, status=404, body="")

        attrs = resolve_difmark_offer(product_url, fake_http)
        self.assertEqual(attrs, DifmarkOfferAttributes(raw_platform="STEAM", raw_region="GLOBAL"))

    def test_resolve_offer_europe_end_to_end(self):
        product_url = "https://difmark.com/en/buy-console-account-some-game-1"

        def fake_http(url, timeout=15, user_agent=None):
            if url == product_url:
                return HttpProbeResult(url=url, ok=True, status=200, body=DIFMARK_PAGE_HTML)
            if url == DIFMARK_TOP_OFFER_URL:
                return HttpProbeResult(
                    url=url, ok=True, status=200,
                    body=_difmark_top_offer_body(region="Europe"),
                )
            return HttpProbeResult(url=url, ok=False, status=404, body="")

        attrs = resolve_difmark_offer(product_url, fake_http)
        self.assertEqual(attrs, DifmarkOfferAttributes(raw_platform="STEAM", raw_region="EUROPE"))

    def test_resolve_offer_product_page_unreadable_raises(self):
        def fake_http(url, timeout=15, user_agent=None):
            return HttpProbeResult(url=url, ok=False, status=500, body="", error="boom")

        with self.assertRaises(DifmarkPageUnreadable):
            resolve_difmark_offer("https://difmark.com/en/x", fake_http)

    def test_resolve_offer_top_offer_api_unreadable_raises(self):
        product_url = "https://difmark.com/en/buy-console-account-x"

        def fake_http(url, timeout=15, user_agent=None):
            if url == product_url:
                return HttpProbeResult(url=url, ok=True, status=200, body=DIFMARK_PAGE_HTML)
            return HttpProbeResult(url=url, ok=False, status=404, body="")

        with self.assertRaises(DifmarkPageUnreadable):
            resolve_difmark_offer(product_url, fake_http)


class PrecheckSkipTests(unittest.TestCase):
    def test_console(self):
        self.assertEqual(precheck_skip(_offer("Halo Xbox Series X")), "console")

    def test_kinguin_row_on_foreign_domain_fails_closed(self):
        # EXECUTOR_RULES §11: a Kinguin candidate URL must contain kinguin.net.
        offer = NormalizedOffer(
            offer_id="1", name="Elden Ring Steam Key GLOBAL",
            url="https://www.g2a.com/elden-ring", merchant="Kinguin",
        )
        self.assertIn("merchant-domain mismatch", precheck_skip(offer))

    def test_kinguin_row_on_kinguin_net_passes_precheck(self):
        offer = NormalizedOffer(
            offer_id="1", name="Elden Ring Steam Key GLOBAL",
            url="https://www.kinguin.net/en/category/1/elden-ring", merchant="Kinguin",
        )
        self.assertIsNone(precheck_skip(offer))

    def test_unmapped_merchant_has_no_domain_rule(self):
        # _offer uses merchant="Test" — no §11 domain rule, any host passes.
        self.assertIsNone(precheck_skip(_offer("Elden Ring Steam Key GLOBAL")))

    def test_difmark_buy_console_account_url_is_not_skipped(self):
        # EXECUTOR_RULES §11 (Romain 2026-07-17): "buy-console-account-" is
        # boilerplate on every Difmark URL, not a marker of an actual
        # account sale — it must never cause a skip.
        offer = NormalizedOffer(
            offer_id="1", name="Elden Ring Steam Key GLOBAL",
            url="https://www.difmark.com/buy-console-account-elden-ring-steam-key",
            merchant="Difmark",
        )
        self.assertIsNone(precheck_skip(offer))

    def test_forbidden_region(self):
        self.assertIn("forbidden region", precheck_skip(_offer("Game Steam Key TURKEY")))

    def test_currency_category(self):
        self.assertIn("POINTS", precheck_skip(_offer("500 FIFA Points")))

    def test_multi_game_bundle(self):
        self.assertIn("bundle", precheck_skip(_offer("Game A + Game B")))

    def test_any_bundle_is_skipped_even_single_game(self):
        # Romain (2026-07-07): no bundles, ever — even a cosmetic bundle with a
        # token-perfect AKS page (the wrongly-proposed Overwatch candidate).
        reason = precheck_skip(_offer(
            "Overwatch Genji Complete Mythic Weapon Skin Bundle (Global) (PC) - Battle.net Gift"
        ))
        self.assertIn("no bundles/skins", reason)

    def test_skins_are_skipped(self):
        self.assertIn("no bundles/skins", precheck_skip(_offer("CS2 Dragon Lore Skin (PC) Steam")))
        self.assertIn("no bundles/skins", precheck_skip(_offer("Rust Weapon Skins (PC) Steam")))
        self.assertIn("no bundles/skins", precheck_skip(_offer("Valve Anthology Bundle Steam Key")))

    def test_skin_requires_word_boundary(self):
        # "Skinwalker Hunt" is a game, not a skin — must NOT be skipped.
        self.assertIsNone(precheck_skip(_offer("Skinwalker Hunt Steam GLOBAL")))

    def test_software_apps_are_skipped(self):
        # Romain (2026-07-08): "Skip c est une app" — EaseUS reached the human
        # gate; software/applications are never candidates, games only.
        for title in (
            "EaseUS Todo Backup Workstation CD Key",
            "Microsoft Office 2021 Professional Plus CD Key",
            "Windows 11 Pro OEM CD Key",
            "Avast Premium Security 2024 Key",
            "Express VPN 12 Months Key",
            # Eneba escape (2026-07-16): "Glary Utilities PRO 5" reached the
            # candidate list — a PC cleaning/optimization utility, same
            # category as CCleaner/IObit, missing from the brand list.
            "Glary Utilities PRO 5 (Windows) Key GLOBAL",
        ):
            self.assertIn("software/app", precheck_skip(_offer(title)), title)

    def test_software_tokens_require_word_boundary(self):
        # Bare OFFICE / WINDOWS / BACKUP stay legal in game titles.
        self.assertIsNone(precheck_skip(_offer("The Office Quest Steam GLOBAL")))
        self.assertIsNone(precheck_skip(_offer("Backup Crew Steam GLOBAL")))

    def test_language_restriction(self):
        self.assertIn("language", precheck_skip(_offer("Game (EN/FR) Steam")))

    def test_sea_word_is_not_a_forbidden_region(self):
        self.assertIsNone(precheck_skip(_offer("Sea of Thieves Steam GLOBAL")))

    def test_normal_offer_survives(self):
        self.assertIsNone(precheck_skip(_offer("Neon Beats Steam GLOBAL")))


class DetectTests(unittest.TestCase):
    def test_platform(self):
        self.assertEqual(detect_platform("Game GOG Key"), "GOG")
        self.assertEqual(detect_platform("Game Steam Key"), "STEAM")
        self.assertEqual(detect_platform("Final Fantasy Origin Steam"), "STEAM")  # R14

    def test_region_url_first(self):
        self.assertEqual(detect_region(_offer("X", url="https://g/game-pc-steam-global"), "STEAM"),
                         ("GLOBAL", "2", False))
        self.assertEqual(detect_region(_offer("X", url="https://g/game-steam-eu"), "STEAM"),
                         ("EU", "9", False))

    def test_region_implicit_global(self):
        label, rid, implicit = detect_region(_offer("Game PC Steam CD Key"), "STEAM")
        self.assertEqual((label, rid), ("GLOBAL", "2"))
        self.assertTrue(implicit)

    def test_edition(self):
        self.assertEqual(detect_edition("Game Deluxe Edition"), ("Deluxe", "7"))
        self.assertEqual(detect_edition("Game Ultimate Collection"), ("Ultimate Collection", "348"))
        self.assertEqual(detect_edition("Game"), ("Standard", "1"))

    def test_edition_from_driffle_url_slug(self):
        # Driffle carries the edition in the URL slug; it wins over the title.
        self.assertEqual(
            detect_edition(
                "Some Game (Europe) (PC) - Steam - Digital Key",
                "https://www.driffle.com/some-game-deluxe-edition-europe-pc-steam-digital-key-p123",
            ),
            ("Deluxe", "7"),
        )
        # Base games (no edition token in the slug) fall back to Standard.
        self.assertEqual(
            detect_edition(
                "Demigod (EU) (PC) - Steam - Digital Code",
                "https://www.driffle.com/demigod-eu-pc-steam-digital-code-p9899229?currency=EUR",
            ),
            ("Standard", "1"),
        )
        # The trailing -p<id> and region/platform tokens must not be mistaken for
        # an edition.
        self.assertEqual(
            detect_edition(
                "Gambonanza (Europe) (PC / Mac / Linux) - Steam - Digital Key",
                "https://www.driffle.com/gambonanza-europe-pc-mac-linux-steam-digital-key-p9988321",
            ),
            ("Standard", "1"),
        )

    def test_region_ignores_difmark_url_boilerplate(self):
        # Real Difmark URL (Romain, 2026-07-17): region/edition are read from
        # the link, but "buy-console-account-" is boilerplate on every
        # listing and must be stripped first (rule Ga01 — URL wins over
        # title for region).
        offer = NormalizedOffer(
            offer_id="1", name="Rogue Loops Steam Account",
            url=(
                "https://difmark.com/en/buy-console-account-rogue-loops-steam-account-166307"
                "?referal=allkeyshop&marketplace_id=2&edition_id=780&region_product_id=1"
                "&seller_id[]=275327&seller_id[]=2300110"
            ),
            merchant="Difmark",
        )
        label, region_id, implicit = detect_region(offer, "STEAM")
        self.assertEqual((label, region_id), ("GLOBAL", "2"))
        self.assertTrue(implicit)

    def test_edition_ignores_difmark_url_boilerplate(self):
        # Romain 2026-07-17: "buy-console-account-" sits on every Difmark URL
        # regardless of what's sold — it must be stripped before edition
        # detection, not treated as a signal (and never as a skip, tested in
        # PrecheckSkipTests). A real edition token elsewhere in the slug still
        # has to be found once the boilerplate is out of the way.
        self.assertEqual(
            detect_edition(
                "Elden Ring Deluxe Edition Steam Key GLOBAL",
                "https://www.difmark.com/buy-console-account-elden-ring-deluxe-edition",
                "Difmark",
            ),
            ("Deluxe", "7"),
        )
        # No edition token at all → Standard, boilerplate alone must not
        # falsely resolve to any EDITION_HINTS entry.
        self.assertEqual(
            detect_edition(
                "Elden Ring Steam Key GLOBAL",
                "https://www.difmark.com/buy-console-account-elden-ring",
                "Difmark",
            ),
            ("Standard", "1"),
        )
        # Same URL shape, but merchant not marked for cleanup: boilerplate
        # stays in the derived text (still no accidental EDITION_HINTS hit,
        # so behavior is unchanged for merchants without a §11 entry).
        self.assertEqual(
            detect_edition(
                "Elden Ring Steam Key GLOBAL",
                "https://www.difmark.com/buy-console-account-elden-ring",
                "SomeOtherMerchant",
            ),
            ("Standard", "1"),
        )


class SlugAndResolveTests(unittest.TestCase):
    def test_slug_candidates_strip_parens_and_suffix(self):
        slugs = build_slug_candidates("Tom Clancy's Rainbow Six Siege (EU) (PC) - Ubisoft - Digital Key")
        self.assertIn("tom-clancys-rainbow-six-siege", slugs)

    def test_slug_candidates_k4g_grammar_no_separators(self):
        # K4G: `<Product> [Region] <Platform> CD Key`, no parens or dashes —
        # the 2026-07-07 K4G run 404'd all 95 slugs before suffix peeling.
        slugs = build_slug_candidates("Kingdom Two Crowns Call of Olympus Europe Steam CD Key")
        self.assertEqual(slugs[0], "kingdom-two-crowns-call-of-olympus")
        slugs = build_slug_candidates("Champions of Anteria United States Ubisoft Connect CD Key")
        self.assertEqual(slugs[0], "champions-of-anteria")

    def test_slug_candidates_edition_variant_after_full(self):
        slugs = build_slug_candidates("FIFA 21 Ultimate Edition Europe Steam CD Key")
        self.assertIn("fifa-21-ultimate-edition", slugs)
        self.assertIn("fifa-21", slugs)
        self.assertLess(slugs.index("fifa-21-ultimate-edition"), slugs.index("fifa-21"))

    def test_slug_candidates_keep_dashed_subtitle_first(self):
        # Dash-split used to amputate real names ("Endless Space - Disharmony"
        # → "endless-space", the wrong product). Full name now goes first; the
        # legacy head stays as a later fallback for Driffle/G2A grammar.
        slugs = build_slug_candidates("Endless Space - Disharmony Steam CD Key")
        self.assertEqual(slugs[0], "endless-space-disharmony")
        self.assertIn("endless-space", slugs)
        slugs = build_slug_candidates("Endzone - A World Apart (PC) - Steam Key - EUROPE")
        self.assertEqual(slugs[0], "endzone-a-world-apart")
        self.assertIn("endzone", slugs)

    def test_slug_candidates_word_boundary_protects_titles(self):
        # ORIGINS must not lose its S to the ORIGIN phrase; "Among Us" must
        # survive (bare US/EU are not in the trailing-noise list).
        slugs = build_slug_candidates("Assassin's Creed Origins Ubisoft Connect CD Key")
        self.assertEqual(slugs[0], "assassins-creed-origins")
        slugs = build_slug_candidates("Among Us (PC) - Steam Key - GLOBAL")
        self.assertEqual(slugs[0], "among-us")

    def test_platform_leftovers_are_not_significant_extras(self):
        # CONNECT/GAMES/LAUNCHER/STORE are storefront noise, not product words:
        # without this, every K4G "… Ubisoft Connect CD Key" title skipped as
        # "different/expanded product" after a correct AKS resolution.
        self.assertEqual(
            extra_significant_words(
                "Champions of Anteria",
                "Champions of Anteria United States Ubisoft Connect CD Key",
            ),
            [],
        )
        self.assertEqual(
            extra_significant_words(
                "Alan Wake", "Alan Wake Epic Games Store CD Key"
            ),
            [],
        )

    def test_extract_aks_name_both_title_grammars(self):
        def page(title):
            return f'<meta property="og:title" content="{title}">'

        # Classic grammar.
        self.assertEqual(
            extract_aks_name(page("Buy Neon Beats CD Key Compare Prices")),
            "Neon Beats",
        )
        # Second live grammar (fifa-21 page, 2026-07-07): no Buy, no CD Key.
        self.assertEqual(
            extract_aks_name(page("FIFA 21 PC KEY Compare Prices")), "FIFA 21"
        )
        # Bare trailing "Key" is a real name, not a platform marker.
        self.assertEqual(
            extract_aks_name(page("Buy The Key CD Key Compare Prices")), "The Key"
        )

    def test_extract_aks_name_unescapes_entities(self):
        # Live og:titles, K4G run 2026-07-07 (AKS flattens punctuation, keeps
        # entities): "Exile&#039;s" tokenized to EXILE/039/S and falsely failed
        # R01; "&amp;" left an AMP token.
        body = (
            '<meta property="og:title" '
            'content="Buy Fellowship Exile&#039;s Supporter Pack CD Key Compare Prices">'
        )
        self.assertEqual(extract_aks_name(body), "Fellowship Exile's Supporter Pack")
        body = (
            '<meta property="og:title" '
            'content="Buy Demeo x Dungeons &amp; Dragons Battlemarked CD Key Compare Prices">'
        )
        self.assertEqual(extract_aks_name(body), "Demeo x Dungeons & Dragons Battlemarked")

    def test_resolve_returns_first_real_page(self):
        def fake_http(url, timeout=8, user_agent=None):
            return HttpProbeResult(url=url, ok=True, status=200, body=AKS_PAGE)

        res = resolve_aks("Neon Beats", fake_http)
        self.assertIsNotNone(res)
        self.assertEqual(res.product_id, "205027")
        self.assertEqual(res.aks_name, "Neon Beats")
        self.assertIn("7", res.editions)

    def test_resolve_none_when_not_found(self):
        def fake_http(url, timeout=8, user_agent=None):
            return HttpProbeResult(url=url, ok=False, status=404, body="")

        self.assertIsNone(resolve_aks("Nope", fake_http))

    def test_resolve_transient_failure_raises_not_none(self):
        # 403/429/timeout are throttling, not proof of absence: a silent None
        # here made candidate lists flap between back-to-back runs (2026-07-07).
        def fake_http(url, timeout=8, user_agent=None):
            return HttpProbeResult(url=url, ok=False, status=403, body="", error="403")

        with self.assertRaises(AksProbeUnreliable):
            resolve_aks("Neon Beats", fake_http)

    def test_resolve_unreadable_name_raises_not_echoes(self):
        # A 200 page with a product id but no extractable name must NOT fall
        # back to the offer title (2026-07-07: the fallback made every name
        # check compare the title to itself — a Microsoft Store Key offer
        # became a candidate).
        page = '<html><body><div data-product-id="207"></div></body></html>'

        def fake_http(url, timeout=8, user_agent=None):
            return HttpProbeResult(url=url, ok=True, status=200, body=page)

        with self.assertRaises(AksNameUnreadable):
            resolve_aks("Call of Duty: Modern Warfare 3 (2011)", fake_http)

    def test_resolve_probe_sends_staff_ua(self):
        seen = []

        def fake_http(url, timeout=8, user_agent=None):
            seen.append(user_agent)
            return HttpProbeResult(url=url, ok=False, status=404, body="")

        resolve_aks("Neon Beats", fake_http)
        self.assertTrue(seen)
        self.assertTrue(all(ua == "AKS/Staff" for ua in seen))


class SearchFallbackTests(unittest.TestCase):
    """R30 (2026-07-16, Romain): AKS's own site search, tried only when
    slug-guessing finds nothing — filtered by the SAME R01/R01b checks as a
    guessed slug, never trusted on its own."""

    SEARCH_PAGE = (
        '<a href="https://www.allkeyshop.com/blog/buy-road-to-empress-cd-key-compare-prices/">x</a>'
        '<a href="https://www.allkeyshop.com/blog/buy-gta-5-cd-key-compare-prices/">x</a>'
        '<a href="https://www.allkeyshop.com/blog/buy-road-to-empress-cd-key-compare-prices/">dup</a>'
        '<a href="https://www.allkeyshop.com/blog/buy-palworld-cd-key-compare-prices/">x</a>'
        '<a href="https://www.allkeyshop.com/blog/buy-forza-horizon-6-cd-key-compare-prices/">x</a>'
    )

    def test_search_extracts_distinct_slugs_respecting_limit(self):
        def fake_http(url, timeout=8, user_agent=None):
            return HttpProbeResult(url=url, ok=True, status=200, body=self.SEARCH_PAGE)

        slugs = search_aks_slugs("Road to Empress", fake_http, limit=3)
        self.assertEqual(slugs, ["road-to-empress", "gta-5", "palworld"])

    def test_search_empty_on_non_200(self):
        def fake_http(url, timeout=8, user_agent=None):
            return HttpProbeResult(url=url, ok=False, status=500, body="")

        self.assertEqual(search_aks_slugs("Road to Empress", fake_http), [])

    def test_resolve_falls_back_to_search_when_slugs_all_404(self):
        calls = []

        def fake_http(url, timeout=8, user_agent=None):
            calls.append(url)
            if "?s=" in url:
                return HttpProbeResult(url=url, ok=True, status=200, body=self.SEARCH_PAGE)
            if "road-to-empress" in url and "?s=" not in url:
                return HttpProbeResult(url=url, ok=True, status=200, body=AKS_PAGE)
            return HttpProbeResult(url=url, ok=False, status=404, body="")

        res = resolve_aks("Some Title Slug-Guessing Cannot Build", fake_http)
        self.assertIsNotNone(res)
        self.assertEqual(res.slug, "road-to-empress")
        self.assertTrue(any("?s=" in c for c in calls), "search was never queried")

    def test_resolve_skips_search_after_transient_failure(self):
        # A transient signal from a GUESSED slug still fails closed
        # immediately — the fallback never runs, search is never queried.
        calls = []

        def fake_http(url, timeout=8, user_agent=None):
            calls.append(url)
            return HttpProbeResult(url=url, ok=False, status=403, body="", error="403")

        with self.assertRaises(AksProbeUnreliable):
            resolve_aks("Neon Beats", fake_http)
        self.assertFalse(any("?s=" in c for c in calls), "search must not run after a transient failure")

    def test_resolve_skips_search_after_unreadable_name(self):
        calls = []
        page = '<html><body><div data-product-id="207"></div></body></html>'

        def fake_http(url, timeout=8, user_agent=None):
            calls.append(url)
            return HttpProbeResult(url=url, ok=True, status=200, body=page)

        with self.assertRaises(AksNameUnreadable):
            resolve_aks("Call of Duty: Modern Warfare 3 (2011)", fake_http)
        self.assertFalse(any("?s=" in c for c in calls), "search must not run after an unreadable name")

    def test_resolve_none_when_search_also_finds_nothing(self):
        def fake_http(url, timeout=8, user_agent=None):
            return HttpProbeResult(url=url, ok=False, status=404, body="")

        self.assertIsNone(resolve_aks("Nope", fake_http))


class ExtractEditionsTests(unittest.TestCase):
    def test_populated_object(self):
        body = '<script>var x={"editions":{"1":{"name":"Standard"},"16":{"name":"DLC"}}};</script>'
        self.assertEqual(
            extract_editions(body),
            {"1": {"name": "Standard"}, "16": {"name": "DLC"}},
        )

    def test_stub_page_php_empty_array_artifact(self):
        # Stub AKS pages (zero offers) serialize the empty editions map as a
        # PHP empty array — `"editions":[]`, not `{}` (live: DCS A-10C
        # Warthog, 2026-07-08). The object-only regex must yield {} so R19
        # sees it as empty rather than crashing or matching garbage.
        body = '<script>var x={"merchants":[],"editions":[],"prices":[],"regions":[]};</script>'
        self.assertEqual(extract_editions(body), {})

    def test_absent_blob(self):
        self.assertEqual(extract_editions("<html><body>nothing</body></html>"), {})


class ExtractOfficialPlatformsTests(unittest.TestCase):
    def test_single(self):
        body = "<p>Official platforms: Steam.</p>"
        self.assertEqual(extract_official_platforms(body), ("Steam",))

    def test_multi(self):
        # Live Su-27 page shape (2026-07-08): the second name is why R20 exists.
        body = "official platforms: Steam, Direct Publisher<br>"
        self.assertEqual(extract_official_platforms(body), ("Steam", "Direct Publisher"))

    def test_absent(self):
        self.assertEqual(extract_official_platforms("<html><body>nothing</body></html>"), ())


class ExtractPricesTests(unittest.TestCase):
    def test_populated_array(self):
        body = (
            '<script>var x={"prices":[{"merchant":47,"merchantName":"Kinguin",'
            '"edition":"1","region":"6","price":3.91}]};</script>'
        )
        self.assertEqual(
            extract_prices(body),
            ({"merchant": 47, "merchantName": "Kinguin", "edition": "1", "region": "6", "price": 3.91},),
        )

    def test_stub_page_php_empty_array_artifact(self):
        body = '<script>var x={"merchants":[],"editions":[],"prices":[],"regions":[]};</script>'
        self.assertEqual(extract_prices(body), ())

    def test_absent_blob(self):
        self.assertEqual(extract_prices("<html><body>nothing</body></html>"), ())


class ExplicitPlatformTests(unittest.TestCase):
    def test_steam_token_is_explicit(self):
        self.assertEqual(explicit_platform("Neon Beats - Steam Key - GLOBAL"), "STEAM")

    def test_no_token_is_none_but_detect_still_defaults(self):
        # R20 root cause: the STEAM default is a guess, not a detection.
        self.assertIsNone(explicit_platform("Su-27 for DCS World Key GLOBAL"))
        self.assertEqual(detect_platform("Su-27 for DCS World Key GLOBAL"), "STEAM")


class ExplicitPlatformFromUrlTests(unittest.TestCase):
    def test_eneba_steam_prefix(self):
        # Eneba escape (2026-07-16): "Apothecarium: The Renaissance of Evil -
        # Premium Edition" carries no platform word in the title at all, but
        # Eneba's URL convention (eneba.com/<platform>-<slug>) still declares
        # it: eneba.com/steam-apothecarium-....
        self.assertEqual(
            explicit_platform_from_url(
                "https://www.eneba.com/steam-apothecarium-the-renaissance-of-evil-premium-edition"
            ),
            "STEAM",
        )

    def test_eneba_other_recognized_prefixes(self):
        cases = {
            "https://www.eneba.com/gog-some-game-key-global": "GOG",
            "https://www.eneba.com/epic-games-divine-knockout-epic-games-key-global": "EPIC",
            "https://www.eneba.com/uplay-far-cry-new-dawn-ubisoft-connect-key-europe": "UBISOFT",
            "https://www.eneba.com/origin-mysims-cozy-bundle-origin-key-global": "EA",
            "https://www.eneba.com/blizzard-world-of-warcraft-mystic-runesaber-battle-net-key": "BATTLENET",
            "https://www.eneba.com/windows-store-sid-meiers-civilization-vi-windows-store-key": "MICROSOFT",
        }
        for url, expected in cases.items():
            self.assertEqual(explicit_platform_from_url(url), expected, url)

    def test_eneba_unrecognized_prefix_is_none(self):
        # Console/currency/software prefixes are left unmapped — already
        # caught by other categorical skips before platform detection runs.
        for url in (
            "https://www.eneba.com/xbox-some-game-xbox-live-key-europe",
            "https://www.eneba.com/psn-lets-sing-2025-psn-key-europe",
            "https://www.eneba.com/top-up-hay-day-diamonds-philippines",
            "https://www.eneba.com/other-glary-utilities-pro-5-windows-key-global",
        ):
            self.assertIsNone(explicit_platform_from_url(url), url)

    def test_non_eneba_url_is_none(self):
        # Scoped to eneba.com only — no other merchant uses this URL shape,
        # and a coincidental "steam-"-prefixed game title elsewhere must not
        # be misread as a platform declaration.
        self.assertIsNone(
            explicit_platform_from_url("https://www.kinguin.net/en/category/1/steam-punk-cd-key")
        )


class MatchOfferTests(unittest.TestCase):
    def _resolver(self, aks_name="Neon Beats", editions=None, official_platforms=("Steam",),
                  prices=()):
        # {} must stay {} (R19 exercises a truly empty map) — only None
        # means "default Standard map". official_platforms passes through
        # untransformed for the same reason: () must stay () (R20).
        res = AksResolution(
            slug="neon-beats", url="https://aks/buy-neon-beats", product_id="205027",
            aks_name=aks_name,
            editions=editions if editions is not None else {"1": {"name": "Standard"}},
            official_platforms=official_platforms,
            prices=prices,
        )
        return lambda name: res

    def test_candidate_built(self):
        offer = _offer("Neon Beats - Full Version (PC) - Steam Key - GLOBAL")
        result = match_offer(offer, self._resolver())
        self.assertIsInstance(result, Candidate)
        self.assertEqual(result.aks_product_id, "205027")
        self.assertEqual((result.region_label, result.region_id), ("GLOBAL", "2"))
        self.assertEqual((result.edition_label, result.edition_id), ("Standard", "1"))

    def test_difmark_implicit_region_resolved_via_merchant_page(self):
        # Romain (2026-07-17): title/URL give no region for this offer — the
        # page-verified result must win over the implicit-GLOBAL default.
        # Title uses "(Steam Key)", not "(Steam Account)": the real Rogue
        # Loops example is a full-credential account sale, which the
        # pre-existing STEAM ACCOUNT categorical skip correctly rejects on
        # its own merits — unrelated to region resolution, tested in
        # isolation here with a plausible key-type title instead. Platform
        # is already explicit from "Steam Key", so only the region path is
        # exercised (platform page-verification is tested separately below).
        offer = NormalizedOffer(
            offer_id="1", name="Rogue Loops (Steam Key)",
            url="https://difmark.com/en/buy-console-account-rogue-loops-steam-account-166307",
            merchant="Difmark",
        )
        result = match_offer(
            offer, self._resolver(aks_name="Rogue Loops"),
            difmark_offer_resolver=lambda url: DifmarkOfferAttributes(
                raw_platform="STEAM", raw_region="EUROPE"
            ),
        )
        self.assertIsInstance(result, Candidate)
        self.assertEqual((result.region_label, result.region_id), ("EU", "9"))

    def test_difmark_explicit_url_region_skips_page_lookup(self):
        # detect_region already found EUROPE from the (cleaned) URL/title,
        # and the title declares Steam explicitly — neither is implicit, so
        # the page resolver must not even be called.
        offer = NormalizedOffer(
            offer_id="1", name="Rogue Loops (Europe) (Steam Key)",
            url="https://difmark.com/en/buy-console-account-rogue-loops-europe-steam-account-166307",
            merchant="Difmark",
        )

        def boom(url):
            raise AssertionError("page resolver should not be called when both are explicit")

        result = match_offer(
            offer, self._resolver(aks_name="Rogue Loops"), difmark_offer_resolver=boom
        )
        self.assertIsInstance(result, Candidate)
        self.assertEqual(result.region_label, "EU")

    def test_difmark_unverifiable_region_skips_offer(self):
        offer = NormalizedOffer(
            offer_id="1", name="Rogue Loops (Steam Key)",
            url="https://difmark.com/en/buy-console-account-rogue-loops-steam-account-166307",
            merchant="Difmark",
        )

        def failing_resolver(url):
            raise DifmarkPageUnreadable("top-offer API unreadable: 500")

        result = match_offer(
            offer, self._resolver(aks_name="Rogue Loops"),
            difmark_offer_resolver=failing_resolver,
        )
        self.assertIsInstance(result, SkippedOffer)
        self.assertIn("Difmark region unverifiable", result.reason)

    def test_difmark_missing_platform_resolved_via_merchant_page(self):
        # Batch 1 (2026-07-17, Romain: "étends au platform aussi"): 77% of
        # the Difmark feed has NO platform token in the title at all
        # ("Afterlife VR Standard Edition") — the merchant page is used
        # directly rather than falling through to R20/R27's AKS-page
        # inference. Region is ALSO implicit here, so this proves the two
        # signals share ONE fetch instead of two.
        offer = NormalizedOffer(
            offer_id="1", name="Rogue Loops Standard Edition",
            url="https://difmark.com/en/buy-console-account-rogue-loops-166307",
            merchant="Difmark",
        )
        calls = []

        def fake_resolver(url):
            calls.append(url)
            return DifmarkOfferAttributes(raw_platform="STEAM", raw_region="GLOBAL")

        result = match_offer(
            offer, self._resolver(aks_name="Rogue Loops"),
            difmark_offer_resolver=fake_resolver,
        )
        self.assertIsInstance(result, Candidate)
        self.assertEqual(result.platform, "STEAM")
        self.assertEqual((result.region_label, result.region_id), ("GLOBAL", "2"))
        self.assertEqual(calls, [offer.url])  # one combined fetch, not two

    def test_difmark_unrecognized_platform_skips_offer(self):
        offer = NormalizedOffer(
            offer_id="1", name="Some Weird Game Standard Edition",
            url="https://difmark.com/en/buy-console-account-some-weird-game-1",
            merchant="Difmark",
        )
        result = match_offer(
            offer, self._resolver(aks_name="Some Weird Game"),
            difmark_offer_resolver=lambda url: DifmarkOfferAttributes(
                raw_platform="XBOX", raw_region="GLOBAL"
            ),
        )
        self.assertIsInstance(result, SkippedOffer)
        self.assertIn("Difmark page platform unrecognized", result.reason)

    def test_difmark_platform_unverifiable_skips_offer(self):
        offer = NormalizedOffer(
            offer_id="1", name="Some Game Standard Edition",
            url="https://difmark.com/en/buy-console-account-some-game-1",
            merchant="Difmark",
        )

        def failing_resolver(url):
            raise DifmarkPageUnreadable("product page unreadable: 500")

        result = match_offer(
            offer, self._resolver(aks_name="Some Game"),
            difmark_offer_resolver=failing_resolver,
        )
        self.assertIsInstance(result, SkippedOffer)
        self.assertIn("Difmark platform unverifiable", result.reason)

    def test_difmark_page_verified_platform_contradicted_by_aks_page_attributes_source(self):
        # R20 still cross-checks against the AKS page's official platforms,
        # but the skip message must say it came from the Difmark page, not
        # the title (the title had no platform token at all here).
        offer = NormalizedOffer(
            offer_id="1", name="Some Game Standard Edition",
            url="https://difmark.com/en/buy-console-account-some-game-1",
            merchant="Difmark",
        )
        result = match_offer(
            offer,
            self._resolver(aks_name="Some Game", official_platforms=("GoG",)),
            difmark_offer_resolver=lambda url: DifmarkOfferAttributes(
                raw_platform="STEAM", raw_region="GLOBAL"
            ),
        )
        self.assertIsInstance(result, SkippedOffer)
        self.assertIn("Difmark merchant page says Steam", result.reason)

    def test_duplicate_price_on_page_skips(self):
        # R25 (2026-07-15, Kinguin/Darkwood escape): the page already lists
        # this exact merchant/region/edition combo — a duplicate, not a new
        # candidate, regardless of when it was added or by whom.
        offer = _offer("Neon Beats - Full Version (PC) - Steam Key - GLOBAL")
        prices = ({"merchantName": "Test", "edition": "1", "region": "2"},)
        result = match_offer(offer, self._resolver(prices=prices))
        self.assertIsInstance(result, SkippedOffer)
        self.assertIn("already lists a price", result.reason)
        self.assertIn("R25", result.reason)

    def test_different_merchant_price_does_not_skip(self):
        offer = _offer("Neon Beats - Full Version (PC) - Steam Key - GLOBAL")
        prices = ({"merchantName": "SomeOtherStore", "edition": "1", "region": "2"},)
        result = match_offer(offer, self._resolver(prices=prices))
        self.assertIsInstance(result, Candidate)

    def test_same_merchant_different_region_does_not_skip(self):
        offer = _offer("Neon Beats - Full Version (PC) - Steam Key - GLOBAL")
        prices = ({"merchantName": "Test", "edition": "1", "region": "9"},)
        result = match_offer(offer, self._resolver(prices=prices))
        self.assertIsInstance(result, Candidate)

    def test_same_merchant_different_edition_does_not_skip(self):
        offer = _offer("Neon Beats - Full Version (PC) - Steam Key - GLOBAL")
        prices = ({"merchantName": "Test", "edition": "7", "region": "2"},)
        result = match_offer(offer, self._resolver(prices=prices))
        self.assertIsInstance(result, Candidate)

    def test_precheck_skip_wins(self):
        self.assertIsInstance(match_offer(_offer("Halo Xbox"), self._resolver()), SkippedOffer)

    def test_dangerous_qualifier_skips(self):
        result = match_offer(_offer("Neon Beats Remastered - Steam"), self._resolver())
        self.assertIsInstance(result, SkippedOffer)
        self.assertIn("qualifier", result.reason)

    def test_name_mismatch_skips(self):
        result = match_offer(_offer("Neon Beats - Steam"), self._resolver(aks_name="Different Game"))
        self.assertIsInstance(result, SkippedOffer)
        self.assertIn("mismatch", result.reason)

    def test_no_aks_page_skips(self):
        result = match_offer(_offer("Neon Beats - Steam"), lambda name: None)
        self.assertIsInstance(result, SkippedOffer)

    def test_dlc_bucket_on_aks_page_sets_dlc_edition(self):
        # R18 revised (Romain 2026-07-08, replacing the 07-07 skip): titles
        # hide DLC-ness ("Exoplanets Pack"); the resolved page's editions map
        # is the truth. DLC bucket → the product IS a DLC → entered with the
        # DLC edition, even when a Standard bucket coexists (Brotato:
        # Abyssal Terrors).
        for editions in (
            {"16": {"name": "DLC"}},
            {"1": {"name": "Standard"}, "16": {"name": "DLC"}},
        ):
            result = match_offer(
                _offer("Neon Beats - Steam GLOBAL"), self._resolver(editions=editions)
            )
            self.assertIsInstance(result, Candidate, editions)
            self.assertEqual((result.edition_label, result.edition_id), ("DLC", "16"))

    def test_dlc_bucket_matched_by_name_when_id_moves(self):
        result = match_offer(
            _offer("Neon Beats - Steam GLOBAL"),
            self._resolver(editions={"99": {"name": "dlc"}}),
        )
        self.assertIsInstance(result, Candidate)
        self.assertEqual((result.edition_label, result.edition_id), ("DLC", "16"))

    def test_dlc_bucket_overrides_title_edition_hints(self):
        # The page's DLC nature beats any edition word in the title — a
        # "Deluxe" marker on a DLC product must not yield Deluxe(7).
        result = match_offer(
            _offer("Neon Beats Deluxe - Steam GLOBAL"),
            self._resolver(editions={"16": {"name": "DLC"}}),
        )
        self.assertIsInstance(result, Candidate)
        self.assertEqual((result.edition_label, result.edition_id), ("DLC", "16"))

    def test_non_dlc_buckets_do_not_alter_edition(self):
        # Bundle/Early Access buckets on the page describe other offers there,
        # not the product's nature — GUILTY GEAR (Standard+Bundle) and the
        # Early Access indies stay Standard.
        for editions in (
            {"1": {"name": "Standard"}, "8": {"name": "Bundle"}},
            {"5": {"name": "Early Access"}},
        ):
            result = match_offer(
                _offer("Neon Beats - Steam GLOBAL"), self._resolver(editions=editions)
            )
            self.assertIsInstance(result, Candidate, editions)
            self.assertEqual(result.edition_id, "1", editions)

    def test_name_embedded_edition_word_uses_page_verified_edition(self):
        # R23 (2026-07-13, Valve Complete Pack escape): "Complete" is part of
        # the AKS name ("Neon Beats Complete Pack"), so E05 would collapse to
        # Standard — but the page's own editions map genuinely offers a
        # distinct "Complete Pack" tier (id 92, not the generic hint id 91).
        # The page-verified entry must win.
        result = match_offer(
            _offer("Neon Beats Complete Pack - Steam GLOBAL"),
            self._resolver(
                aks_name="Neon Beats Complete Pack",
                editions={"1": {"name": "Standard"}, "92": {"name": "Complete Pack"}},
            ),
        )
        self.assertIsInstance(result, Candidate)
        self.assertEqual((result.edition_label, result.edition_id), ("Complete Pack", "92"))

    def test_name_embedded_edition_word_without_page_match_falls_back_to_standard(self):
        # Same name-embedded "Complete" word, but the page offers no distinct
        # non-Standard tier — the E05 collapse to Standard still applies.
        result = match_offer(
            _offer("Neon Beats Complete Pack - Steam GLOBAL"),
            self._resolver(
                aks_name="Neon Beats Complete Pack",
                editions={"1": {"name": "Standard"}},
            ),
        )
        self.assertIsInstance(result, Candidate)
        self.assertEqual((result.edition_label, result.edition_id), ("Standard", "1"))

    def test_page_verified_edition_prefers_exact_match(self):
        # P2 fix (2026-07-13, Romain's review of R23): when the page lists
        # both an exact label match and a substring-only match, the exact one
        # wins deterministically — not whichever the page happened to list
        # first (dict/page order is not a matching criterion).
        result = match_offer(
            _offer("Neon Beats Complete Pack - Steam GLOBAL"),
            self._resolver(
                aks_name="Neon Beats Complete Pack",
                editions={
                    "1": {"name": "Standard"},
                    "92": {"name": "Complete Pack"},
                    "91": {"name": "Complete"},
                },
            ),
        )
        self.assertIsInstance(result, Candidate)
        self.assertEqual((result.edition_label, result.edition_id), ("Complete", "91"))

    def test_page_verified_edition_ambiguous_is_skipped(self):
        # P2 fix: two distinct non-Standard entries both matching the
        # detected label, neither an exact match — a guess, not a
        # page-verified pick. Fail closed instead of taking page order.
        result = match_offer(
            _offer("Neon Beats Complete Pack - Steam GLOBAL"),
            self._resolver(
                aks_name="Neon Beats Complete Pack",
                editions={
                    "1": {"name": "Standard"},
                    "92": {"name": "Complete Pack"},
                    "93": {"name": "Complete Deluxe Pack"},
                },
            ),
        )
        self.assertIsInstance(result, SkippedOffer)
        self.assertIn("ambiguous page-verified edition", result.reason)

    def test_bundle_label_never_page_verified(self):
        # P2 fix: a title whose OWN AKS name embeds "Trilogy" (detected label
        # "Bundle") must still collapse to Standard, even when the page
        # happens to list its own Bundle-named tier — "we never enter
        # bundles, ever" is absolute, there is no legitimate page-verified
        # Bundle pick to resurrect here.
        result = match_offer(
            _offer("Neon Beats Trilogy - Steam GLOBAL"),
            self._resolver(
                aks_name="Neon Beats Trilogy",
                editions={"1": {"name": "Standard"}, "50": {"name": "Trilogy Bundle"}},
            ),
        )
        self.assertIsInstance(result, Candidate)
        self.assertEqual((result.edition_label, result.edition_id), ("Standard", "1"))

    def test_empty_editions_map_skips_edition_unverifiable(self):
        # R19 (2026-07-08): an empty editions map = stub AKS record (zero
        # offers) that can hide a DLC — "DCS: A-10C Warthog" went in as
        # Standard(1) and Romain had to fix the DB by hand, while sibling
        # "DCS: P-51D Mustang" (populated map, DLC bucket) was correctly
        # entered DLC(16) by R18 the same run. No other deterministic edition
        # signal exists → fail closed, whatever the title hints say.
        for title in ("Neon Beats - Steam GLOBAL", "Neon Beats Deluxe - Steam GLOBAL"):
            result = match_offer(_offer(title), self._resolver(editions={}))
            self.assertIsInstance(result, SkippedOffer, title)
            self.assertIn("R19", result.reason)
            self.assertIn("editions map", result.reason)

    def test_defaulted_on_publisher_page_enters_publisher(self):
        # R20 (2026-07-08): "Su-27 for DCS World Key GLOBAL" carries no
        # platform token; detect_platform DEFAULTED to Steam and the offer was
        # entered Steam GLOBAL(2), but its AKS page says "official platforms:
        # Steam, Direct Publisher" — the key is an Eagle Dynamics (publisher)
        # key. Revised same day (Romain: "Rentrons les en publisher"): such an
        # offer is entered as PUBLISHER — region "Publisher (1)" is the GLOBAL
        # bucket in the WP-admin dropdown — instead of skipped.
        for page in (("Steam", "Direct Publisher"), ("Direct Publisher",)):
            result = match_offer(
                _offer("Neon Beats Key GLOBAL"),
                self._resolver(official_platforms=page),
            )
            self.assertIsInstance(result, Candidate, page)
            self.assertEqual(
                (result.platform, result.region_label, result.region_id),
                ("PUBLISHER", "GLOBAL", "1"),
                page,
            )

    def test_defaulted_publisher_maps_eu_region(self):
        result = match_offer(
            _offer("Neon Beats (Europe)"),
            self._resolver(official_platforms=("Steam", "Direct Publisher")),
        )
        self.assertIsInstance(result, Candidate)
        self.assertEqual(
            (result.platform, result.region_label, result.region_id),
            ("PUBLISHER", "EU", "12"),
        )

    def test_defaulted_publisher_gift_fails_closed(self):
        # PUBLISHER has no gift mapping in REGION_IDS — a token-less gift on a
        # publisher page must skip, not fall back to another platform's id.
        result = match_offer(
            _offer("Neon Beats Gift GLOBAL"),
            self._resolver(official_platforms=("Steam", "Direct Publisher")),
        )
        self.assertIsInstance(result, SkippedOffer)
        self.assertIn("no region id for PUBLISHER", result.reason)

    def test_defaulted_platform_skips_on_non_publisher_page_mix(self):
        # R27 (2026-07-15, Gameboost escape, same day as R26): R26 defaulted
        # ANY token-less title to Publisher whenever the page had some
        # platform signal — Gameboost proved that wrong (genuinely-Steam
        # token-less offers got defaulted to Publisher too). Without an
        # explicit "Direct Publisher" confirmation, skip rather than guess —
        # Steam+GoG, same as Steam-only.
        result = match_offer(
            _offer("Neon Beats Key GLOBAL"),
            self._resolver(official_platforms=("Steam", "GoG")),
        )
        self.assertIsInstance(result, SkippedOffer)
        self.assertIn("R27", result.reason)

    def test_defaulted_platform_skips_on_steam_only_page(self):
        # R27: both live DCS pages say "official platforms: Steam." only —
        # no "Direct Publisher" entry. R26 defaulted this to Publisher (right
        # for DCS), but Gameboost has the identical page-signal shape with
        # genuinely-Steam ground truth — neither default is safe without a
        # positive Direct Publisher confirmation, so this now skips. DCS
        # itself reverts to skip; a human enters cases like it deliberately.
        result = match_offer(
            _offer("Neon Beats Key GLOBAL"), self._resolver(official_platforms=("Steam",))
        )
        self.assertIsInstance(result, SkippedOffer)
        self.assertIn("R27", result.reason)

    def test_defaulted_steam_skips_when_page_lists_no_platforms(self):
        result = match_offer(
            _offer("Neon Beats Key GLOBAL"), self._resolver(official_platforms=())
        )
        self.assertIsInstance(result, SkippedOffer)
        self.assertIn("R20", result.reason)
        self.assertIn("no official platforms", result.reason)

    def test_explicit_steam_trusted_on_multi_platform_page(self):
        # An explicit token is the merchant's declaration of what it sells;
        # multi-platform pages are normal (Osmos: Steam+GoG page, Steam key —
        # retro sweep 2026-07-08 confirmed every explicit entry was right).
        result = match_offer(
            _offer("Neon Beats - Steam Key - GLOBAL"),
            self._resolver(official_platforms=("Steam", "Direct Publisher")),
        )
        self.assertIsInstance(result, Candidate)
        self.assertEqual(result.platform, "STEAM")

    def test_explicit_platform_contradicted_by_page_skips(self):
        # The cross-check fires only on contradiction: title says GOG but the
        # page's official platforms exclude GoG entirely.
        result = match_offer(
            _offer("Neon Beats GOG Key GLOBAL"),
            self._resolver(official_platforms=("Steam",)),
        )
        self.assertIsInstance(result, SkippedOffer)
        self.assertIn("R20", result.reason)

    def test_explicit_platform_confirmed_by_page(self):
        result = match_offer(
            _offer("Neon Beats GOG Key GLOBAL"),
            self._resolver(official_platforms=("Steam", "GoG")),
        )
        self.assertIsInstance(result, Candidate)
        self.assertEqual((result.platform, result.region_id), ("GOG", "6"))

    def test_explicit_platform_without_page_vocab_is_trusted(self):
        # EA has no PAGE_PLATFORM_NAMES entry — no cross-check possible; the
        # merchant declaration stands even on a Steam-only page.
        result = match_offer(
            _offer("Neon Beats EA App Key GLOBAL"),
            self._resolver(official_platforms=("Steam",)),
        )
        self.assertIsInstance(result, Candidate)
        self.assertEqual(result.platform, "EA")

    def test_unreliable_probe_skips_distinctly(self):
        def resolver(name):
            raise AksProbeUnreliable("neon-beats -> 429")

        result = match_offer(_offer("Neon Beats - Steam"), resolver)
        self.assertIsInstance(result, SkippedOffer)
        self.assertIn("unreliable", result.reason)
        self.assertNotIn("no AKS product page", result.reason)

    def test_unreadable_aks_name_skips_distinctly(self):
        def resolver(name):
            raise AksNameUnreadable("call-of-duty-modern-warfare-3")

        result = match_offer(_offer("Neon Beats - Steam"), resolver)
        self.assertIsInstance(result, SkippedOffer)
        self.assertIn("unreadable", result.reason)

    def test_normalized_block(self):
        offer = _offer("Neon Beats - Full Version (PC) - Steam Key - GLOBAL")
        block = match_offer(offer, self._resolver()).normalized_block(1)
        self.assertIn("#1 —", block)
        self.assertIn("205027", block)
        self.assertIn("Steam GLOBAL(2), Standard(1)", block)


class DifferentProductTests(unittest.TestCase):
    def _resolver(self, aks_name):
        res = AksResolution("slug", "https://aks/x", "27577", aks_name, {"1": {"name": "Standard"}})
        return lambda name: res

    def test_extra_words_detected(self):
        extras = extra_significant_words(
            "Greedfall",
            "GreedFall - The Dying World - Deluxe Edition (Europe) (PC) - Steam - Digital Key",
        )
        self.assertIn("DYING", extras)
        self.assertIn("WORLD", extras)

    def test_the_dying_world_is_skipped(self):
        offer = _offer("GreedFall - The Dying World - Deluxe Edition (Global) (PC) - Steam - Digital Key")
        result = match_offer(offer, self._resolver("Greedfall"))
        self.assertIsInstance(result, SkippedOffer)
        self.assertIn("extra words", result.reason)

    def test_version_number_is_skipped(self):
        result = match_offer(_offer("FIFA 23 - Steam"), self._resolver("FIFA"))
        self.assertIsInstance(result, SkippedOffer)

    def test_matching_base_game_still_a_candidate(self):
        offer = _offer("Bus Simulator 27 (Global) (PC) - Steam - Digital Key")
        result = match_offer(offer, self._resolver("Bus Simulator 27"))
        self.assertIsInstance(result, Candidate)
        self.assertEqual((result.region_label, result.region_id), ("GLOBAL", "2"))

    def test_single_extra_word_is_a_different_product(self):
        # 2026-07-07: "Interdimensional" is a DLC — one significant extra word
        # is enough to skip (skill floor was ≥2, tightened; doubt → skip).
        offer = _offer("Offworld Trading Company - Interdimensional (PC) - Steam Key - EUROPE")
        result = match_offer(offer, self._resolver("Offworld Trading Company"))
        self.assertIsInstance(result, SkippedOffer)
        self.assertIn("extra words", result.reason)
        self.assertIn("INTERDIMENSIONAL", result.reason)

    def test_gog_com_key_is_not_an_extra_word(self):
        # "GOG.COM Key" tokenizes to GOG + COM; both are format noise, not a
        # different product ("Brutal Legend (PC) - GOG.COM Key - GLOBAL").
        self.assertEqual(
            extra_significant_words(
                "Brutal Legend", "Brutal Legend (PC) - GOG.COM Key - GLOBAL"),
            [])


class GiftRegionTests(unittest.TestCase):
    def test_battlenet_gift_maps_to_570(self):
        offer = _offer("Overwatch Skin Bundle (Global) (PC) - Battle.net Gift",
                       url="https://driffle.com/x-battlenet-gift-p1")
        self.assertEqual(detect_region(offer, "BATTLENET"), ("GIFT", "570", False))

    def test_steam_gift_maps_to_25(self):
        self.assertEqual(detect_region(_offer("Game Steam Gift GLOBAL"), "STEAM"), ("GIFT", "25", False))

    def test_steam_gift_eu_maps_to_259(self):
        self.assertEqual(detect_region(_offer("Game Steam Gift EU"), "STEAM"), ("GIFT EU", "259", False))


class MatchFeedTests(unittest.TestCase):
    def _feed(self, *offers):
        return NormalizedFeed(run_id="r", merchant="Test", fetched_at="t", offers=tuple(offers))

    def test_partitions_and_caps(self):
        res = AksResolution("neon-beats", "https://aks/x", "205027", "Neon Beats", {"1": {"name": "Standard"}})
        resolver = lambda name: res
        feed = self._feed(
            _offer("Neon Beats - Steam GLOBAL", oid="1"),
            _offer("Neon Beats - Steam GLOBAL", oid="2"),
            _offer("Halo Xbox", oid="3"),
        )
        candidates, skipped = match_feed(feed, resolver, max_candidates=1)
        self.assertEqual(len(candidates), 1)
        # one capped + one console skip
        self.assertEqual(len(skipped), 2)
        self.assertTrue(any("cap" in s.reason for s in skipped))


class G2ARulesTests(unittest.TestCase):
    """G2A format: 'Game (PC) - Steam Key - REGION' — region is a bare suffix,
    URLs keep ?params, and G2A.md adds merchant-specific categorical skips."""

    def _resolver(self, aks_name="Neon Beats"):
        res = AksResolution(
            slug="neon-beats", url="https://aks/buy-neon-beats", product_id="205027",
            aks_name=aks_name, editions={"1": {"name": "Standard"}},
        )
        return lambda name: res

    def test_region_from_trailing_suffix(self):
        self.assertEqual(
            detect_region(_offer("Neon Beats (PC) - Steam Key - EUROPE"), "STEAM"),
            ("EU", "9", False))
        self.assertEqual(
            detect_region(_offer("Neon Beats (PC) - Steam Key - UNITED STATES"), "STEAM"),
            ("US", "8", False))
        self.assertEqual(
            detect_region(_offer("Neon Beats (PC) - GOG Key - GLOBAL"), "GOG"),
            ("GLOBAL", "6", False))

    def test_region_from_g2a_url_path(self):
        url = ("https://www.g2a.com/runescape-pc-key-europe-i10000044281020"
               "?___currency=EUR&utm_campaign=COM_GLOBAL_PB")
        self.assertEqual(detect_region(_offer("X", url=url), "STEAM"), ("EU", "9", False))

    def test_microsoft_store_key_is_skipped(self):
        # G2A.md skip list: Microsoft Key. "Microsoft STORE Key" dodged the
        # MICROSOFT KEY substring on 2026-07-07 and surfaced as Steam US(8).
        offer = _offer(
            "Call of Duty: Modern Warfare 3 (2011) (PC) - Microsoft Store Key - UNITED STATES"
        )
        result = match_offer(offer, self._resolver())
        self.assertIsInstance(result, SkippedOffer)
        self.assertIn("skip category", result.reason)

    def test_microsoft_platform_fails_closed_but_flight_simulator_is_steam(self):
        self.assertEqual(detect_platform("X (PC) - Microsoft Store Key - GLOBAL"), "MICROSOFT")
        self.assertEqual(detect_platform("X (PC) - Microsoft Key - GLOBAL"), "MICROSOFT")
        self.assertEqual(
            detect_platform("Microsoft Flight Simulator 2024 (PC) - Steam Key - GLOBAL"),
            "STEAM",
        )

    def test_query_junk_never_sets_region(self):
        url = "https://www.g2a.com/some-game-i123?adid=x-eu-y&utm_campaign=COM_GLOBAL_PB"
        label, rid, implicit = detect_region(_offer("Some Game", url=url), "STEAM")
        self.assertEqual((label, rid), ("GLOBAL", "2"))
        self.assertTrue(implicit)

    def test_unknown_platform_fails_closed(self):
        self.assertEqual(detect_platform("GTA V (PC) - Rockstar Key - GLOBAL"), "ROCKSTAR")
        result = match_offer(
            _offer("Neon Beats (PC) - Rockstar Key - GLOBAL"), self._resolver())
        self.assertIsInstance(result, SkippedOffer)
        self.assertIn("no region id", result.reason)

    def test_g2a_categorical_skips(self):
        cases = {
            "Forza Horizon 5 (PC) - Microsoft Key - GLOBAL": "MICROSOFT KEY",
            "OMSI 2 Add-On Aachen (PC) - Steam Key - GLOBAL": "DLC",
            "Hunt: Showdown Season Pass (PC) - Steam Key - GLOBAL": "SEASON PASS",
            "CS2 AK-47 Redline (Field-Tested)": "no bundles/skins",
            "NBA 2K25: 200,000 VC (PC) - Steam Key - GLOBAL": "VC",
            "Path of Exile 100 Exalted Orbs (PC)": "ORBS",
            "Growtopia Gem Fountain - GLOBAL": "GEM",
            "Growtopia Royal Grow Pass - GLOBAL": "PASS",
            "Fallout 4 (PC) - Steam Player Trade - GLOBAL": "STEAM PLAYER TRADE",
            "Elden Ring Pre-Order Bonus (PC) - Steam Key - EUROPE": "preorder",
            "Resident Evil 4 Standard & Deluxe (PC) - Steam Key - GLOBAL": "&",
        }
        for name, expected in cases.items():
            reason = precheck_skip(_offer(name))
            self.assertIsNotNone(reason, name)
            self.assertIn(expected, reason, name)

    def test_ampersand_in_game_name_not_skipped(self):
        self.assertIsNone(precheck_skip(_offer("Sam & Max Save the World (PC) - Steam Key - GLOBAL")))

    def test_trilogy_without_aks_trilogy_is_skipped(self):
        # TRILOGY absent from the AKS name now trips the ≥1 extra-word guard
        # before the bundle-edition backstop; either way it must be skipped.
        result = match_offer(
            _offer("Neon Beats Trilogy (PC) - Steam Key - GLOBAL"), self._resolver())
        self.assertIsInstance(result, SkippedOffer)
        self.assertIn("TRILOGY", result.reason)

    def test_trilogy_product_falls_back_to_standard(self):
        # "…Trilogy" that IS the AKS product name (N. Sane style) = Standard.
        result = match_offer(
            _offer("Neon Beats Trilogy (PC) - Steam Key - GLOBAL"),
            self._resolver(aks_name="Neon Beats Trilogy"))
        self.assertIsInstance(result, Candidate)
        self.assertEqual((result.edition_label, result.edition_id), ("Standard", "1"))

    def test_edition_from_g2a_url_slug(self):
        self.assertEqual(
            detect_edition(
                "Game (PC) - Steam Key - UNITED STATES",
                "https://www.g2a.com/game-premium-edition-upgrade-pc-key-united-states-i10000?___currency=EUR",
            ),
            ("Premium", "34"),
        )

    def test_us_region_offer_not_flagged_different_product(self):
        result = match_offer(
            _offer("Neon Beats (PC) - Steam Key - UNITED STATES"), self._resolver())
        self.assertIsInstance(result, Candidate)
        self.assertEqual((result.region_label, result.region_id), ("US", "8"))


class AuditMa1TransientShadowingTests(unittest.TestCase):
    """MA1 (audit 2026-07-17): a transient/unreadable answer on a MORE
    specific slug tier must raise immediately — a 200 on a less specific tier
    can be the wrong product (deluxe title landing on the base page)."""

    def test_transient_on_specific_tier_raises_despite_base_200(self):
        def fake_http(url, timeout=8, user_agent=None):
            if "deluxe" in url:
                return HttpProbeResult(url=url, ok=False, status=429, body="")
            return HttpProbeResult(url=url, ok=True, status=200, body=AKS_PAGE)

        with self.assertRaises(AksProbeUnreliable):
            resolve_aks("Neon Beats Deluxe Edition", fake_http)

    def test_unreadable_name_on_specific_tier_raises_despite_base_200(self):
        unreadable_page = '<div data-product-id="99"></div>'  # id but no name

        def fake_http(url, timeout=8, user_agent=None):
            if "deluxe" in url:
                return HttpProbeResult(url=url, ok=True, status=200, body=unreadable_page)
            return HttpProbeResult(url=url, ok=True, status=200, body=AKS_PAGE)

        with self.assertRaises(AksNameUnreadable):
            resolve_aks("Neon Beats Deluxe Edition", fake_http)

    def test_clean_404_on_specific_tier_still_falls_through(self):
        def fake_http(url, timeout=8, user_agent=None):
            if "deluxe" in url:
                return HttpProbeResult(url=url, ok=False, status=404, body="")
            return HttpProbeResult(url=url, ok=True, status=200, body=AKS_PAGE)

        res = resolve_aks("Neon Beats Deluxe Edition", fake_http)
        self.assertIsNotNone(res)
        self.assertEqual(res.aks_name, "Neon Beats")


class AuditMa2PlatformWordBoundaryTests(unittest.TestCase):
    """MA2 (audit 2026-07-17): word-boundary platform tokens + the KEY/GIFT
    collocation as tie-breaker — a game-name word must not override the
    merchant's declaration."""

    def test_epic_chef_steam_key_is_steam(self):
        self.assertEqual(explicit_platform("Epic Chef (PC) - Steam Key - GLOBAL"), "STEAM")

    def test_gogol_word_boundary_not_gog(self):
        self.assertEqual(explicit_platform("Gogol's Quest Steam Key"), "STEAM")

    def test_single_platform_word_wins_without_collocation(self):
        self.assertEqual(explicit_platform("Epic Chef (PC) GLOBAL"), "EPIC")

    def test_ambiguous_without_key_collocation_is_none(self):
        self.assertIsNone(explicit_platform("Epic Steam Machine (PC)"))

    def test_gog_com_key_is_gog(self):
        self.assertEqual(explicit_platform("Neon Beats GOG.COM Key"), "GOG")

    def test_steam_gift_collocation_disambiguates(self):
        self.assertEqual(explicit_platform("Epic Chef Steam Gift (PC)"), "STEAM")


class AuditMa3AnniversaryDefinitiveTests(unittest.TestCase):
    """MA3 (audit 2026-07-17): ANNIVERSARY/DEFINITIVE are dangerous
    qualifiers — no stable plain catalog id exists, so a base-page entry as
    Standard(1) (the Skyrim Anniversary repro) must skip instead."""

    def test_anniversary_absent_from_aks_name_is_dangerous(self):
        self.assertEqual(
            dangerous_qualifier(
                "The Elder Scrolls V Skyrim Anniversary Edition",
                "The Elder Scrolls V: Skyrim",
            ),
            "ANNIVERSARY",
        )

    def test_definitive_absent_from_aks_name_is_dangerous(self):
        self.assertEqual(
            dangerous_qualifier("Tomb Raider Definitive Edition Key", "Tomb Raider"),
            "DEFINITIVE",
        )

    def test_dedicated_anniversary_page_is_not_flagged(self):
        self.assertIsNone(
            dangerous_qualifier("Halo Anniversary Steam Key", "Halo Anniversary")
        )


class AuditMa4GiftSegmentTests(unittest.TestCase):
    """MA4 (audit 2026-07-17): 'gift' must be its own URL segment — the bare
    substring proposed GIFT(25) for 'the-gifted-rabbit'."""

    def test_gifted_in_slug_is_not_a_gift(self):
        offer = _offer("The Gifted Rabbit (PC) Steam Key",
                       url="https://driffle.com/the-gifted-rabbit-p123")
        label, region_id, implicit = detect_region(offer, "STEAM")
        self.assertNotIn("GIFT", label)

    def test_gift_segment_still_detected(self):
        offer = _offer("Neon Beats (PC)",
                       url="https://driffle.com/neon-beats-steam-gift-eu-p1")
        label, region_id, implicit = detect_region(offer, "STEAM")
        self.assertEqual((label, region_id), ("GIFT EU", "259"))

    def test_gift_word_in_title_still_detected(self):
        offer = _offer("Neon Beats Steam GIFT (PC)", url="https://m.test/x")
        label, region_id, implicit = detect_region(offer, "STEAM")
        self.assertEqual((label, region_id), ("GIFT", "25"))


class AuditMa5StringEditionEntriesTests(unittest.TestCase):
    """MA5 (audit 2026-07-17): the R23 page-verify pool crashed with
    AttributeError on string-valued editions entries — one such page aborted
    the whole match run."""

    def _resolver(self, editions):
        def resolver(name):
            return AksResolution(
                slug="valve-complete-pack", url="https://aks/x", product_id="831",
                aks_name="Valve Complete Pack", editions=editions,
                official_platforms=("Steam",), prices=(),
            )
        return resolver

    def test_string_valued_editions_do_not_crash(self):
        offer = _offer("Valve Complete Pack (Global) (PC) - Steam Gift",
                       url="https://driffle.com/valve-complete-pack-p1")
        result = match_offer(offer, self._resolver({"1": "Standard", "92": "Complete Pack"}))
        self.assertIsInstance(result, Candidate)
        self.assertEqual((result.edition_label, result.edition_id), ("Complete Pack", "92"))


class AuditMa6MarkupDriftTests(unittest.TestCase):
    """MA6 (audit 2026-07-17): a prices block that IS present but no longer
    parses means AKS drifted its markup — loud skip, never a silent () that
    turns the R25 duplicate guard off. Absence stays a soft ()."""

    def test_present_but_unshaped_prices_raises(self):
        from src.matcher import AksPageUnparseable
        with self.assertRaises(AksPageUnparseable):
            extract_prices('<script>var x={"prices": {"not": "an array"}};</script>')

    def test_absent_prices_stays_soft(self):
        self.assertEqual(extract_prices("<html><body>nothing</body></html>"), ())

    def test_match_offer_skips_with_distinct_reason(self):
        from src.matcher import AksPageUnparseable

        def resolver(name):
            raise AksPageUnparseable("prices block unparseable: boom")

        result = match_offer(_offer("Neon Beats Steam Key"), resolver)
        self.assertIsInstance(result, SkippedOffer)
        self.assertIn("markup drifted", result.reason)


class AuditMa7GamivoEnMarkerTests(unittest.TestCase):
    """MA7 (audit 2026-07-17): Gamivo's '-en-' URL segment is an EN-only
    language lock — documented in §4.3/§4.4, never coded."""

    def test_gamivo_en_marker_skips(self):
        offer = _offer("Neon Beats (PC) Steam Key",
                       url="https://www.gamivo.com/product/neon-beats-steam-en-global")
        self.assertEqual(
            precheck_skip(offer),
            "language restriction (Gamivo '-en-' URL marker — EN-only key)",
        )

    def test_gamivo_without_marker_passes(self):
        offer = _offer("Neon Beats (PC) Steam Key",
                       url="https://www.gamivo.com/product/neon-beats-steam-global")
        self.assertIsNone(precheck_skip(offer))

    def test_other_merchants_are_not_scoped(self):
        # French title word "en" on a non-Gamivo host must not skip.
        offer = NormalizedOffer(
            offer_id="1", name="Alice en Wonderland Steam Key",
            url="https://www.kinguin.net/category/1/alice-en-wonderland",
            merchant="Kinguin",
        )
        self.assertIsNone(precheck_skip(offer))


class AuditMa8RegionTitleDefenseTests(unittest.TestCase):
    """MA8 (audit 2026-07-17): title-side region defense in depth — bare
    'EUROPE' mid-title (K4G grammar) and regions hidden in a non-first
    parenthesis."""

    def test_bare_europe_mid_title(self):
        offer = _offer("Kingdom Two Crowns EUROPE Steam CD Key",
                       url="https://www.k4g.com/product/kingdom-two-crowns")
        label, region_id, implicit = detect_region(offer, "STEAM")
        self.assertEqual((label, region_id, implicit), ("EU", "9", False))

    def test_region_in_second_parenthesis(self):
        offer = _offer("Neon Beats (PC) (Europe) - Steam Key",
                       url="https://m.test/neon-beats")
        label, region_id, implicit = detect_region(offer, "STEAM")
        self.assertEqual((label, region_id, implicit), ("EU", "9", False))

    def test_no_region_anywhere_stays_implicit_global(self):
        offer = _offer("Neon Beats (PC) - Steam Key", url="https://m.test/neon-beats")
        label, region_id, implicit = detect_region(offer, "STEAM")
        self.assertEqual((label, region_id, implicit), ("GLOBAL", "2", True))


if __name__ == "__main__":
    unittest.main()

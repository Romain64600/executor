import unittest

from src.aks_env import HttpProbeResult
from src.contracts import NormalizedFeed, NormalizedOffer
from src.matcher import (
    AksNameUnreadable,
    AksProbeUnreliable,
    AksResolution,
    Candidate,
    SkippedOffer,
    build_slug_candidates,
    dangerous_qualifier,
    detect_edition,
    detect_platform,
    detect_region,
    explicit_platform,
    extra_significant_words,
    extract_aks_name,
    extract_editions,
    extract_official_platforms,
    match_feed,
    match_offer,
    missing_aks_words,
    precheck_skip,
    resolve_aks,
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


class PrecheckSkipTests(unittest.TestCase):
    def test_console(self):
        self.assertEqual(precheck_skip(_offer("Halo Xbox Series X")), "console")

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


class ExplicitPlatformTests(unittest.TestCase):
    def test_steam_token_is_explicit(self):
        self.assertEqual(explicit_platform("Neon Beats - Steam Key - GLOBAL"), "STEAM")

    def test_no_token_is_none_but_detect_still_defaults(self):
        # R20 root cause: the STEAM default is a guess, not a detection.
        self.assertIsNone(explicit_platform("Su-27 for DCS World Key GLOBAL"))
        self.assertEqual(detect_platform("Su-27 for DCS World Key GLOBAL"), "STEAM")


class MatchOfferTests(unittest.TestCase):
    def _resolver(self, aks_name="Neon Beats", editions=None, official_platforms=("Steam",)):
        # {} must stay {} (R19 exercises a truly empty map) — only None
        # means "default Standard map". official_platforms passes through
        # untransformed for the same reason: () must stay () (R20).
        res = AksResolution(
            slug="neon-beats", url="https://aks/buy-neon-beats", product_id="205027",
            aks_name=aks_name,
            editions=editions if editions is not None else {"1": {"name": "Standard"}},
            official_platforms=official_platforms,
        )
        return lambda name: res

    def test_candidate_built(self):
        offer = _offer("Neon Beats - Full Version (PC) - Steam Key - GLOBAL")
        result = match_offer(offer, self._resolver())
        self.assertIsInstance(result, Candidate)
        self.assertEqual(result.aks_product_id, "205027")
        self.assertEqual((result.region_label, result.region_id), ("GLOBAL", "2"))
        self.assertEqual((result.edition_label, result.edition_id), ("Standard", "1"))

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

    def test_defaulted_steam_requires_steam_only_or_publisher_page(self):
        # Neither Steam-only nor publisher-direct (e.g. Steam+GoG): the
        # defaulted Steam is still unverifiable → skip stays.
        result = match_offer(
            _offer("Neon Beats Key GLOBAL"),
            self._resolver(official_platforms=("Steam", "GoG")),
        )
        self.assertIsInstance(result, SkippedOffer)
        self.assertIn("R20", result.reason)
        self.assertIn("neither Steam-only nor publisher-direct", result.reason)

    def test_defaulted_steam_passes_on_steam_only_page(self):
        result = match_offer(
            _offer("Neon Beats Key GLOBAL"), self._resolver(official_platforms=("Steam",))
        )
        self.assertIsInstance(result, Candidate)
        self.assertEqual(result.platform, "STEAM")

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


if __name__ == "__main__":
    unittest.main()

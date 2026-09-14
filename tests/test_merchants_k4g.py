"""tests for src/merchants/k4g.py — the K4G grammar file (2026-09-14, R32 / R45).

Fixtures are real rows of the 2026-09-12 batch (runs/20260912-020000-auto-k4g-s92-p1..7, 592
rows). Pipeline tests patch the registry dict (src.matcher.MERCHANT_CONFIGS) in place."""

import dataclasses
import pathlib
import re
import unittest

import src.matcher as M
from src.console_keys import classify_console
from src.matcher import (
    AksResolution,
    Candidate,
    NormalizedOffer,
    SkippedOffer,
    build_slug_candidates,
    detect_region,
    detect_region_base,
    match_offer,
    precheck_skip,
)
from src.merchant_config import MerchantConfig
from src.merchants import k4g
from src.merchants.k4g import (
    CONFIG,
    altergift_verdict,
    console_region_slot,
    console_url_families,
    drop_altergift,
    gift_delivery,
    guard_name,
    is_altergift,
    is_steam_altergift,
    parse_title,
    precheck,
    region_text,
    resolve_name,
    title_region,
    url_delivery,
)

URL = "https://k4g.com/product/x-steam-global-instant-cd-key-cd-key-AE3VLW0N"          # a CD Key slug
GIFT_URL = "https://k4g.com/product/x-steam-global-instant-altergift-alter-gift-AE3VLW0N"   # an Altergift slug
# the ONE Altergift row of the 2026-09-12 batch whose slug says cd-key (offer 101030313, p3)
TRINE_TITLE = "Trine 5: A Clockwork Conspiracy Steam Altergift"
TRINE_URL = "https://k4g.com/product/trine-5-a-clockwork-conspiracy-steam-global-instant-cd-key-48V2PFDZ"
CONFLICT_KEY = "K4G delivery conflict: title Altergift but URL says cd-key (no altergift segment) — not entered (2026-09-14)"
CONFLICT_NONE = "K4G delivery conflict: title Altergift but URL carries no altergift segment — not entered (2026-09-14)"
CONFLICT_REVERSE = "K4G delivery conflict: title CD Key but URL says altergift — not entered (2026-09-14)"
NOT_STEAM = ("K4G Altergift outside the Steam collocation (title's store phrase is not Steam) — not entered "
             "(Romain 2026-09-14: « Steam Altergift = Steam Gift »)")


def _offer(name, url=URL):
    return NormalizedOffer(offer_id="1", name=name, url=url, merchant="K4G")


class _Registry(unittest.TestCase):
    def _use(self, cfg):
        saved = M.MERCHANT_CONFIGS.get("K4G")
        if cfg is None:
            M.MERCHANT_CONFIGS.pop("K4G", None)
        else:
            M.MERCHANT_CONFIGS["K4G"] = cfg

        def restore():
            if saved is None:
                M.MERCHANT_CONFIGS.pop("K4G", None)
            else:
                M.MERCHANT_CONFIGS["K4G"] = saved

        self.addCleanup(restore)


class GrammarTests(unittest.TestCase):
    def test_real_rows(self):
        cases = {
            "Broken Sword - Shadow of the Templars: Reforged Europe Steam CD Key": ("Broken Sword - Shadow of the Templars: Reforged", "Europe", "CD Key"),
            "Monster Hunter Wilds Gold Edition Europe Steam CD Key": ("Monster Hunter Wilds Gold Edition", "Europe", "CD Key"),
            "Goblin Vyke: The Thief Tycoon Steam CD Key": ("Goblin Vyke: The Thief Tycoon", None, "CD Key"),
            "Mato Anomalies North America Steam Altergift": ("Mato Anomalies", "North America", "Altergift"),
            "Champions of Anteria United States Ubisoft Connect CD Key": ("Champions of Anteria", "United States", "CD Key"),
            "Age of Empires II: Definitive Edition - Victors and Vanquished North America Steam CD Key": ("Age of Empires II: Definitive Edition - Victors and Vanquished", "North America", "CD Key"),
            "Persona 5 Royal Canada XBOX One/PC/XBOX Series X|S CD Key": ("Persona 5 Royal", "Canada", "CD Key"),
            "Trepang2 Standard Edition Europe PC/XBOX Series X|S CD Key": ("Trepang2 Standard Edition", "Europe", "CD Key"),
            "Pokémon Scarlet Europe Nintendo Switch 2 CD Key": ("Pokémon Scarlet", "Europe", "CD Key"),
            "Borderlands 3 Ultimate Edition Europe PS4/PS5 CD Key": ("Borderlands 3 Ultimate Edition", "Europe", "CD Key"),
            "Playstation Plus CARD 365 Days United Arab Emirates PSN CD Key": ("Playstation Plus CARD 365 Days", "United Arab Emirates", "CD Key"),
            "Xbox Game Pass Essential (Core) Subscription Card 3 Months Mexico XBOX Live CD Key": ("Xbox Game Pass Essential (Core) Subscription Card 3 Months", "Mexico", "CD Key"),
            "Nintendo eShop Card 25 EUR Luxembourg Nintendo CD Key": ("Nintendo eShop Card 25 EUR", "Luxembourg", "CD Key"),
            "Wirm Steam Account": ("Wirm", None, "Account"),
            "Apex Legends 23000 Coins Ea App Manual Top-Up": ("Apex Legends 23000 Coins", None, "Manual Top-Up"),
        }
        for title, (head, region, delivery) in cases.items():
            with self.subTest(title=title):
                m = parse_title(title)
                self.assertIsNotNone(m)
                self.assertEqual((m.group("head"), m.group("region"), m.group("delivery")), (head, region, delivery))
                self.assertEqual(resolve_name(title), head)
                self.assertEqual(region_text(title), region)

    def test_vendor_titles_are_outside_the_grammar(self):
        for title in (
            "Mifinity eVoucher 100 DKK Denmark Mifinity CD Key",
            "Trend Micro Device Security Pro 3 Years / 6 Devices Trend Micro CD Key",
            "EaseUS Data Recovery Wizard Professional (Mac) 1 Month / 1 Device EaseUS CD Key",
            "Pokémon GO Coins 15500 PokemonGO Manual Top-Up",
            "Bumble Premium 1 Month Bumble Manual Top-Up",
        ):
            with self.subTest(title=title):
                self.assertIsNone(parse_title(title))
                self.assertEqual(resolve_name(title), title)
                self.assertIsNone(precheck(title, URL))
                self.assertIsNone(title_region(title))

    def test_slug_equals_the_generic_peel(self):
        # the test_matcher K4G fixtures: the peeled name yields the SAME first slug
        for title, slug in {
            "Kingdom Two Crowns Call of Olympus Europe Steam CD Key": "kingdom-two-crowns-call-of-olympus",
            "Champions of Anteria United States Ubisoft Connect CD Key": "champions-of-anteria",
            "FIFA 21 Ultimate Edition Europe Steam CD Key": "fifa-21-ultimate-edition",
            "Endless Space - Disharmony Steam CD Key": "endless-space-disharmony",
            "Assassin's Creed Origins Ubisoft Connect CD Key": "assassins-creed-origins",
        }.items():
            with self.subTest(title=title):
                self.assertEqual(build_slug_candidates(resolve_name(title))[0], slug)
                self.assertEqual(build_slug_candidates(title)[0], slug)


class HooksTests(_Registry):
    def test_title_region(self):
        for title, base in {
            "Monster Hunter Wilds Gold Edition Europe Steam CD Key": "eu",
            "Champions of Anteria United States Ubisoft Connect CD Key": "us",
            "Game United Kingdom Steam CD Key": "uk",
            "Tom Clancy's Ghost Recon Breakpoint Gold Edition Global XBOX One/Series X|S CD Key": "global",
            "Goblin Vyke: The Thief Tycoon Steam CD Key": None,
            "Mato Anomalies North America Steam Altergift": None,
        }.items():
            with self.subTest(title=title):
                self.assertEqual(title_region(title), base)

    def test_precheck_forbidden_names(self):
        for title, label in {
            "Age of Empires II: Definitive Edition - Victors and Vanquished North America Steam CD Key": "NORTH AMERICA",
            "Persona 5 Royal Canada XBOX One/PC/XBOX Series X|S CD Key": "CANADA",
            "Xbox Game Pass Essential (Core) Subscription Card 3 Months Mexico XBOX Live CD Key": "MEXICO",
            "Playstation Plus CARD 365 Days United Arab Emirates PSN CD Key": "UNITED ARAB EMIRATES",
            "Nintendo eShop Card 25 EUR Luxembourg Nintendo CD Key": "LUXEMBOURG",
            "Game Asia Steam CD Key": "ASIA",
            "Game EMEA Steam CD Key": "EMEA",
        }.items():
            with self.subTest(title=title):
                self.assertEqual(precheck(title, URL), f"forbidden region: {label}")
        self.assertIsNone(precheck("Monster Hunter Wilds Gold Edition Europe Steam CD Key", URL))

    def test_altergift_is_a_steam_gift_romain_2026_09_14(self):
        # Romain's ruling (2026-09-14): « Steam Altergift = Steam Gift on rentre sous gift tous
        # les altergifts » — no precheck skip, the merchant's own gift verdict (the slug agrees:
        # "-altergift-alter-gift-"), the word dropped from the guard and the slug (and nothing else).
        for title, guard, resolved in (
            ("Seafrog Steam Altergift", "Seafrog Steam", "Seafrog"),
            ("Thief Simulator Europe Steam Altergift", "Thief Simulator Europe Steam", "Thief Simulator"),
            ("Middle-earth: The Shadow Bundle Europe Steam Altergift", "Middle-earth: The Shadow Bundle Europe Steam", "Middle-earth: The Shadow Bundle"),
            ("Kingdom Eighties Rad Deluxe Edition Steam Altergift", "Kingdom Eighties Rad Deluxe Edition Steam", "Kingdom Eighties Rad Deluxe Edition"),
        ):
            with self.subTest(title=title):
                self.assertTrue(is_altergift(title))
                self.assertTrue(is_steam_altergift(title))
                self.assertEqual(altergift_verdict(title, GIFT_URL), "gift")
                self.assertIs(gift_delivery(title, GIFT_URL), True)
                self.assertIsNone(precheck(title, GIFT_URL))
                self.assertEqual(guard_name(title), guard)
                self.assertEqual(drop_altergift(title), guard)
                self.assertEqual(resolve_name(title), resolved)
                self.assertEqual(build_slug_candidates(resolve_name(title))[0], build_slug_candidates(resolved)[0])
        # outside the grammar and without a Steam phrase: the word still goes from the guard /
        # slug (pure text), but the row is NOT vouched for — the Steam-collocation gate (below)
        title = "Some ALTERGIFT Thing"
        self.assertTrue(is_altergift(title))
        self.assertFalse(is_steam_altergift(title))
        self.assertEqual((guard_name(title), drop_altergift(title), resolve_name(title)), ("Some Thing", "Some Thing", "Some Thing"))
        self.assertIsNone(gift_delivery(title, GIFT_URL))
        self.assertEqual(precheck(title, GIFT_URL), NOT_STEAM)
        # a forbidden region stays the precheck skip, Altergift or not
        self.assertEqual(precheck("Mato Anomalies North America Steam Altergift", GIFT_URL), "forbidden region: NORTH AMERICA")
        # the K4G region-slot rule is unchanged: "Americas" right before the store phrase is the slot
        # (fail-closed, the same outcome the 2026-09-12 run recorded for these 2 rows)
        self.assertEqual(precheck("Strategic Command: American Civil War - Wars in the Americas Steam Altergift", GIFT_URL), "forbidden region: AMERICAS")
        # not an Altergift: the generic gift read decides (None), the guard is untouched
        for title in ("Thief Simulator Europe Steam CD Key", "Game Steam Gift", "Altergifted Steam CD Key"):
            with self.subTest(title=title):
                self.assertFalse(is_altergift(title))
                self.assertIsNone(altergift_verdict(title, URL))
                self.assertIsNone(gift_delivery(title, URL))
                self.assertEqual(guard_name(title), title)
                self.assertEqual(drop_altergift(title), title)

    def test_pipeline_europe_row_enters_eu_on_the_peeled_name(self):
        page = AksResolution(slug="monster-hunter-wilds", url="https://aks/buy-monster-hunter-wilds-cd-key-compare-prices/",
                             product_id="1", aks_name="Monster Hunter Wilds",
                             editions={"1": {"name": "Standard"}, "10": {"name": "Gold"}},
                             official_platforms=("Steam",))
        offer = _offer("Monster Hunter Wilds Gold Edition Europe Steam CD Key",
                       "https://k4g.com/product/monster-hunter-wilds-steam-europe-instant-cd-key-gold-edition-cd-key-ABCDEFGH")
        asked = []

        def resolver(name, **kw):
            asked.append(name)
            return page

        self._use(None)                      # generic (no config)
        self.assertEqual(detect_region_base(offer)[:3], ("eu", "EU", False))
        self._use(CONFIG)
        self.assertEqual(detect_region_base(offer)[:3], ("eu", "EU", False))     # identical read
        r = match_offer(offer, resolver=resolver)
        self.assertIsInstance(r, Candidate, getattr(r, "reason", None))
        self.assertEqual((r.platform, r.region_label, r.region_id, r.edition_label), ("STEAM", "EU", "9", "Gold"))
        self.assertEqual(asked, ["Monster Hunter Wilds Gold Edition"])

    def test_pipeline_precheck(self):
        self._use(CONFIG)
        self.assertIsNone(precheck_skip(_offer("Seafrog Steam Altergift", GIFT_URL)))   # 2026-09-14: entered as a Steam gift
        self.assertEqual(precheck_skip(_offer("Seafrog Steam Altergift")), CONFLICT_KEY)  # …when the slug agrees (review fix)
        self.assertEqual(precheck_skip(_offer("Persona 5 Royal Canada XBOX One/PC/XBOX Series X|S CD Key",
                                              "https://k4g.com/product/persona-5-royal-pc-xbox-one-series-x-s-canada-cd-key-cd-key-IY4ZKGPV")),
                         "forbidden region: CANADA")
        self.assertEqual(precheck_skip(_offer("Wirm Steam Account")), "skip category: STEAM ACCOUNT")   # generic, unchanged
        self.assertIn("merchant-domain mismatch", precheck_skip(_offer("Game Steam CD Key", "https://www.g2a.com/x")))


class AltergiftPipelineTests(_Registry):
    """Romain 2026-09-14: « Steam Altergift = Steam Gift on rentre sous gift tous les
    altergifts ». Real rows of the 2026-09-12 batch (216 Altergift rows, never a candidate:
    149 404 slugs "…-steam-altergift", 37 "extra words: […'ALTERGIFT']", 30 NORTH AMERICA…)."""

    def _page(self, slug, name, editions=None):
        return AksResolution(slug=slug, url=f"https://aks/buy-{slug}-cd-key-compare-prices/", product_id="1",
                             aks_name=name, editions=editions or {"1": {"name": "Standard"}}, official_platforms=("Steam",))

    def test_europe_row_is_steam_gift_eu(self):
        offer = _offer("Thief Simulator Europe Steam Altergift",
                       "https://k4g.com/product/thief-simulator-steam-europe-instant-altergift-alter-gift-AAAAAAAA")
        asked = []

        def resolver(name, **kw):
            asked.append(name)
            return self._page("thief-simulator", "Thief Simulator")

        self._use(None)                                 # generic: the URL "alter-gift" segment already read gift…
        self.assertEqual(detect_region(offer, "STEAM"), ("GIFT EU", "259", False))
        r = match_offer(offer, resolver=resolver)
        self.assertIsInstance(r, SkippedOffer)          # …but the raw guard counted the word
        self.assertEqual(r.reason, "different/expanded product — extra words: ['ALTERGIFT']")
        self._use(CONFIG)
        self.assertEqual(detect_region(offer, "STEAM"), ("GIFT EU", "259", False))
        r = match_offer(offer, resolver=resolver)
        self.assertIsInstance(r, Candidate, getattr(r, "reason", None))
        self.assertEqual((r.platform, r.region_label, r.region_id, r.region_implicit, r.edition_label, r.edition_id),
                         ("STEAM", "GIFT EU", "259", False, "Standard", "1"))
        self.assertEqual(asked[-1], "Thief Simulator")

    def test_no_region_row_is_steam_gift_global(self):
        self._use(CONFIG)
        # no region anywhere (title or URL) → GIFT (25), implicit like any region-less row
        offer = _offer("Game Steam Altergift", "https://k4g.com/product/game-steam-altergift-alter-gift-AAAAAAAA")
        self.assertEqual(detect_region(offer, "STEAM"), ("GIFT", "25", True))
        r = match_offer(offer, resolver=lambda name, **kw: self._page("game", "Game"))
        self.assertIsInstance(r, Candidate, getattr(r, "reason", None))
        self.assertEqual((r.platform, r.region_label, r.region_id, r.region_implicit), ("STEAM", "GIFT", "25", True))
        # the batch's real shape: the URL carries "-steam-global-" → GIFT (25), explicit
        seafrog = _offer("Seafrog Steam Altergift", "https://k4g.com/product/seafrog-steam-global-altergift-alter-gift-QU67G9P5")
        self.assertEqual(detect_region(seafrog, "STEAM"), ("GIFT", "25", False))
        r = match_offer(seafrog, resolver=lambda name, **kw: self._page("seafrog", "Seafrog"))
        self.assertIsInstance(r, Candidate, getattr(r, "reason", None))
        self.assertEqual((r.region_label, r.region_id, r.region_implicit), ("GIFT", "25", False))
        # review fix (2026-09-14, finding [1]): the hook reads the slug too — a slug WITHOUT any
        # delivery segment is outside the K4G URL grammar → the merchant does not vouch (None →
        # the generic plain-key read) and the precheck refuses the row before that read matters
        wirm = _offer("Wirm Steam Altergift", "https://k4g.com/product/wirm-steam-global-K0SYH8QV")
        self.assertIsNone(gift_delivery(wirm.name, wirm.url))
        self.assertEqual(detect_region(wirm, "STEAM"), ("GLOBAL", "2", False))
        self.assertEqual(precheck_skip(wirm), CONFLICT_NONE)
        r = match_offer(wirm, resolver=lambda name, **kw: self._page("wirm", "Wirm"))
        self.assertIsInstance(r, SkippedOffer)
        self.assertEqual(r.reason, CONFLICT_NONE)

    def test_us_and_uk_rows_have_no_steam_gift_bucket(self):
        self._use(CONFIG)
        # REGION_IDS STEAM has gift (25) and gift_eu (259) only — a US / UK base fails closed
        for title, url, label in (
            ("Game United States Steam Altergift", "https://k4g.com/product/game-steam-united-states-altergift-alter-gift-AAAAAAAA", "GIFT US"),
            ("Game United Kingdom Steam Altergift", "https://k4g.com/product/game-steam-united-kingdom-altergift-alter-gift-AAAAAAAA", "GIFT UK"),
        ):
            with self.subTest(title=title):
                offer = _offer(title, url)
                self.assertIsNone(precheck_skip(offer))
                self.assertEqual(detect_region(offer, "STEAM"), (label, None, False))
                r = match_offer(offer, resolver=lambda name, **kw: self._page("game", "Game"))
                self.assertIsInstance(r, SkippedOffer)
                self.assertEqual(r.reason, f"no region id for STEAM/{label}")

    def test_batch_rows_sampled(self):
        # rows of runs/20260912-020000-auto-k4g-s92-p1..7 (scratchpad measure_m2.out): what each gets now
        self._use(CONFIG)
        entered = {
            # title, url → (region label, id, implicit, resolver name)
            ("Kingdom of Night Europe Steam Altergift", "https://k4g.com/product/kingdom-of-night-steam-europe-instant-altergift-alter-gift-KW9D1Y63"): ("GIFT EU", "259", False, "Kingdom of Night"),
            ("True Fear: Forsaken Souls Part 3 Steam Altergift", "https://k4g.com/product/true-fear-forsaken-souls-part-3-steam-global-instant-altergift-alter-gift-YJXNQAOB"): ("GIFT", "25", False, "True Fear: Forsaken Souls Part 3"),
            ("Mato Anomalies - Treasure from Heaven Europe Steam Altergift", "https://k4g.com/product/mato-anomalies-treasure-from-heaven-steam-europe-cd-key-alter-gift-8Z9GIX0E"): ("GIFT EU", "259", False, "Mato Anomalies - Treasure from Heaven"),
            ("Wirm Steam Altergift", "https://k4g.com/product/wirm-steam-global-altergift-alter-gift-K0SYH8QV"): ("GIFT", "25", False, "Wirm"),
        }
        for (title, url), (label, rid, implicit, name) in entered.items():
            with self.subTest(title=title):
                offer = _offer(title, url)
                self.assertIsNone(precheck_skip(offer))
                r = match_offer(offer, resolver=lambda n, **kw: self._page(build_slug_candidates(name)[0], name))
                self.assertIsInstance(r, Candidate, getattr(r, "reason", None))
                self.assertEqual((r.platform, r.region_label, r.region_id, r.region_implicit), ("STEAM", label, rid, implicit))
                self.assertEqual(build_slug_candidates(resolve_name(title))[0], build_slug_candidates(name)[0])
        # every other K4G rule is kept: forbidden regions, bundles, passes, season pass on a base page
        still_skipped = {
            ("Sonic Origins - Plus Expansion Pack North America Steam Altergift", "https://k4g.com/product/sonic-origins-plus-expansion-pack-steam-north-america-altergift-alter-gift-EDVT5Z29"): "forbidden region: NORTH AMERICA",
            ("Middle-earth: The Shadow Bundle Europe Steam Altergift", "https://k4g.com/product/middle-earth-the-shadow-bundle-steam-europe-altergift-alter-gift-AAAAAAAA"): "skip category: BUNDLE (no bundles/skins)",
            ("Far Cry 6 Game of the Year Upgrade Pass Steam Altergift", "https://k4g.com/product/far-cry-6-game-of-the-year-upgrade-pass-steam-global-altergift-alter-gift-AAAAAAAA"): "skip category: PASS (in-game/battle pass)",
        }
        for (title, url), reason in still_skipped.items():
            with self.subTest(title=title):
                self.assertEqual(precheck_skip(_offer(title, url)), reason)
        r = match_offer(_offer("Watch Dogs: Legion - Season pass Europe Steam Altergift",
                               "https://k4g.com/product/watch-dogs-legion-season-pass-steam-europe-altergift-alter-gift-AAAAAAAA"),
                        resolver=lambda n, **kw: self._page("watch-dogs-legion", "Watch Dogs: Legion"))
        self.assertIsInstance(r, SkippedOffer)
        self.assertIn("carries no DLC edition", r.reason)          # R43, unchanged


class AltergiftGatesTests(_Registry):
    """Review fixes of 2026-09-14 on Romain's Altergift ruling — fail-closed (AGENTS.md: "if
    anything is uncertain, stop"): (1) the slug must agree with the title's "Altergift";
    (4) the Steam collocation is part of the ruling (« Steam Altergift = Steam Gift »)."""

    def _page(self, slug, name, official=("Steam",)):
        return AksResolution(slug=slug, url=f"https://aks/buy-{slug}-cd-key-compare-prices/", product_id="1",
                             aks_name=name, editions={"1": {"name": "Standard"}}, official_platforms=official)

    def test_url_delivery(self):
        for url, said in {
            "https://k4g.com/product/seafrog-steam-global-altergift-alter-gift-QU67G9P5": "gift",
            "https://k4g.com/product/kingdom-of-night-steam-europe-instant-altergift-alter-gift-KW9D1Y63": "gift",
            "https://k4g.com/product/mato-anomalies-treasure-from-heaven-steam-europe-cd-key-alter-gift-8Z9GIX0E": "gift",   # both: gift wins (3 rows)
            TRINE_URL: "key",
            URL: "key",
            "https://k4g.com/product/wirm-steam-global-K0SYH8QV": None,
            "https://k4g.com/product/x-steam-global-altergift-alter-gift-AAAAAAAA?ref=cd-key": "gift",   # the query never speaks
            "": None,
        }.items():
            with self.subTest(url=url):
                self.assertEqual(url_delivery(url), said)

    def test_trine_5_title_url_delivery_conflict_is_refused(self):
        # offer 101030313 (runs/20260912-020000-auto-k4g-s92-p3): title "Steam Altergift", slug
        # "…-steam-global-instant-cd-key-48V2PFDZ" — the ONLY such row of the batch (217 / 218
        # slugs carry "-alter-gift-"). Gift (25) or key (GLOBAL 2) cannot be known from the row.
        offer = _offer(TRINE_TITLE, TRINE_URL)
        self.assertEqual(altergift_verdict(TRINE_TITLE, TRINE_URL), CONFLICT_KEY)
        self.assertIsNone(gift_delivery(TRINE_TITLE, TRINE_URL))          # the merchant does not vouch
        self._use(None)                                                    # generic: a plain key…
        self.assertEqual(detect_region(offer, "STEAM"), ("GLOBAL", "2", False))
        self._use(CONFIG)                                                  # …and the hooks never turn it into GIFT (25)
        self.assertEqual(detect_region(offer, "STEAM"), ("GLOBAL", "2", False))
        self.assertEqual(precheck_skip(offer), CONFLICT_KEY)
        self.assertEqual(precheck_skip(offer, consoles=True), CONFLICT_KEY)
        asked = []

        def resolver(name, **kw):
            asked.append(name)
            return self._page("trine-5-a-clockwork-conspiracy", "Trine 5: A Clockwork Conspiracy")

        r = match_offer(offer, resolver=resolver)
        self.assertIsInstance(r, SkippedOffer)
        self.assertEqual(r.reason, CONFLICT_KEY)
        self.assertEqual(asked, [])                                        # refused before any AKS probe
        # the same title on the batch's usual slug is the gift it says it is (unchanged class)
        agreed = _offer(TRINE_TITLE, "https://k4g.com/product/trine-5-a-clockwork-conspiracy-steam-global-instant-altergift-alter-gift-48V2PFDZ")
        self.assertIsNone(precheck_skip(agreed))
        self.assertEqual(detect_region(agreed, "STEAM"), ("GIFT", "25", False))
        r = match_offer(agreed, resolver=resolver)
        self.assertIsInstance(r, Candidate, getattr(r, "reason", None))
        self.assertEqual((r.platform, r.region_label, r.region_id), ("STEAM", "GIFT", "25"))

    def test_reverse_conflict_title_cd_key_url_altergift_is_refused(self):
        # 0 rows in the batch — the mirror of Trine 5: the generic "-gift-" segment read would
        # have filed a CD Key title under GIFT (25)
        offer = _offer("Game Steam CD Key", "https://k4g.com/product/game-steam-global-instant-cd-key-alter-gift-AAAAAAAA")
        self._use(None)
        self.assertEqual(detect_region(offer, "STEAM"), ("GIFT", "25", False))
        self._use(CONFIG)
        self.assertEqual(precheck_skip(offer), CONFLICT_REVERSE)
        r = match_offer(offer, resolver=lambda name, **kw: self._page("game", "Game"))
        self.assertIsInstance(r, SkippedOffer)
        self.assertEqual(r.reason, CONFLICT_REVERSE)
        # a "… Steam Gift" title is not the mirror (it says gift too): the generic read, unchanged
        self.assertIsNone(precheck_skip(_offer("Game Steam Gift", "https://k4g.com/product/game-steam-global-gift-AAAAAAAA")))

    def test_non_steam_altergift_is_refused_never_another_gift_bucket(self):
        # « Steam Altergift = Steam Gift »: 216 / 216 grammar rows say "Steam". A Battle.net /
        # Epic / GOG / no-platform "Altergift" is a grammar never seen → fail-closed, never
        # BATTLENET GIFT (570 / 567), never a plain key.
        self._use(CONFIG)
        for title in (
            "Seafrog Battle.net Altergift",
            "Seafrog Europe Battle.net Altergift",
            "Seafrog Epic Games Altergift",
            "Seafrog GOG Altergift",
            "Seafrog Steam / Epic Games Altergift",       # ambiguous run
            "Seafrog Altergift",                          # no store phrase at all
        ):
            with self.subTest(title=title):
                self.assertTrue(is_altergift(title))
                self.assertFalse(is_steam_altergift(title))
                self.assertEqual(altergift_verdict(title, GIFT_URL), NOT_STEAM)
                self.assertIsNone(gift_delivery(title, GIFT_URL))
                offer = _offer(title, GIFT_URL)
                self.assertEqual(precheck_skip(offer), NOT_STEAM)
                r = match_offer(offer, resolver=lambda name, **kw: self._page("seafrog", "Seafrog", ("Battle.net", "Epic Games", "GOG", "Steam")))
                self.assertIsInstance(r, SkippedOffer)
                self.assertEqual(r.reason, NOT_STEAM)
        # a console-marked Altergift is refused by the same gate in both precheck modes
        console = _offer("Seafrog Europe PS5 Altergift", "https://k4g.com/product/seafrog-playstation-5-europe-altergift-alter-gift-AAAAAAAA")
        self.assertEqual(precheck_skip(console), NOT_STEAM)
        self.assertEqual(precheck_skip(console, consoles=True), NOT_STEAM)

    def test_out_of_grammar_steam_europe_altergift_rows_still_enter(self):
        # the batch's 2 rows outside the grammar (region AFTER the store phrase): Steam is the
        # only store phrase → still a Steam gift (GIFT EU 259 from the generic " EUROPE " read)
        self._use(CONFIG)
        for title, url in (
            ("Warhammer: Chaosbane - Witch Hunter Steam Europe Altergift",
             "https://k4g.com/product/warhammer-chaosbane-witch-hunter-steam-europe-instant-altergift-alter-gift-I7P1URAW"),
            ("Life Is Strange Complete Season (Episodes 1-5) Steam Europe Altergift",
             "https://k4g.com/product/life-is-strange-complete-season-episodes-1-5-steam-europe-instant-altergift-alter-gift-ESMQ2T8D"),
        ):
            with self.subTest(title=title):
                self.assertIsNone(parse_title(title))
                self.assertTrue(is_steam_altergift(title))
                self.assertEqual(altergift_verdict(title, url), "gift")
                offer = _offer(title, url)
                self.assertIsNone(precheck_skip(offer))
                self.assertEqual(detect_region(offer, "STEAM"), ("GIFT EU", "259", False))


class ConsoleHooksTests(unittest.TestCase):
    ROWS = {
        "Icarus Console Edition Europe XBOX Series X|S CD Key": "Europe",
        "Mortal Kombat 11 Ultimate Add-On Bundle United States XBOX Series X|S CD Key": "United States",
        "Persona 5 Royal United Kingdom XBOX One/PC/XBOX Series X|S CD Key": "United Kingdom",
        "Persona 5 Royal Canada XBOX One/PC/XBOX Series X|S CD Key": "Canada",
        "Tom Clancy's Ghost Recon Breakpoint Gold Edition Global XBOX One/Series X|S CD Key": "Global",
        "Stardew Valley United States Nintendo Switch 2 CD Key": "United States",
        "Home Sweet Home Europe XBOX One/Series X|S CD Key": "Europe",
        "Far Cry 6 - Jungle Expedition SIEE PS5 CD Key": None,          # SIEE is not a region
        "Trepang2 Standard Edition PC/XBOX Series X|S CD Key": None,
    }

    def test_region_slot_verbatim_and_agrees_with_the_shared_read(self):
        for title, slot in self.ROWS.items():
            with self.subTest(title=title):
                self.assertEqual(console_region_slot(title), slot)
                sig = classify_console(title, "https://k4g.com/product/x-xbox-series-x-s-xbox-europe-cd-key-cd-key-AAAAAAAA", "K4G")
                self.assertEqual(sig.region_words[:1], (slot,) if slot else ())

    def test_url_families(self):
        cases = {
            "https://k4g.com/product/persona-5-royal-pc-xbox-one-series-x-s-canada-cd-key-cd-key-IY4ZKGPV": ("XBOX_ONE", "XBOX_SERIES"),
            "https://k4g.com/product/home-sweet-home-xbox-one-series-x-s-xbox-europe-instant-cd-key-cd-key-5ZF2STXM": ("XBOX_ONE", "XBOX_SERIES"),
            "https://k4g.com/product/company-of-heroes-3-xbox-series-x-s-xbox-europe-cd-key-standard-edition-cd-key-XR09AGQY": ("XBOX_SERIES",),
            "https://k4g.com/product/pokemon-scarlet-nintendo-switch-2-europe-cd-key-cd-key-3FWB2QK5": ("SWITCH2",),
            "https://k4g.com/product/borderlands-3-ps4-ps5-europe-instant-cd-key-ultimate-edition-cd-key-QF8DZERN": ("PS4", "PS5"),
            "https://k4g.com/product/moving-out-2-f-a-r-tastic-four-playstation-5-europe-cd-key-cd-key-W8SDTVYC": ("PS5",),
            "https://k4g.com/product/x-nintendo-switch-europe-cd-key-cd-key-AAAAAAAA": ("SWITCH",),
            # a product NAME "Nintendo Switch 2 Edition Upgrade Pack" is not a run; PC rows say nothing
            "https://k4g.com/product/x-nintendo-switch-2-edition-upgrade-pack-steam-europe-cd-key-cd-key-AAAAAAAA": None,
            "https://k4g.com/product/goblin-vyke-the-thief-tycoon-steam-global-instant-cd-key-cd-key-AE3VLW0N": None,
            "https://k4g.com/product/x-playstation-5-siee-cd-key-cd-key-AAAAAAAA": None,     # unknown region slot
        }
        for url, families in cases.items():
            with self.subTest(url=url):
                self.assertEqual(console_url_families(url), families)


class ConfigTests(unittest.TestCase):
    def test_config_declares_the_hooks(self):
        self.assertIsInstance(CONFIG, MerchantConfig)
        self.assertEqual((CONFIG.name, CONFIG.domain), ("K4G", "k4g.com"))
        self.assertIs(CONFIG.precheck, precheck)
        self.assertIs(CONFIG.title_region, title_region)
        self.assertIs(CONFIG.resolve_name, resolve_name)
        self.assertIs(CONFIG.guard_name, guard_name)            # 2026-09-14: "Altergift" is not a product word
        self.assertIs(CONFIG.gift_delivery, gift_delivery)      # 2026-09-14: Altergift = Steam gift (when the slug agrees)
        self.assertTrue(CONFIG.title_is_platform_source)
        fields = {f.name for f in dataclasses.fields(MerchantConfig)}
        if "console_region_slot" in fields:
            self.assertIs(CONFIG.console_region_slot, console_region_slot)
            self.assertIs(CONFIG.console_url_families, console_url_families)
            self.assertEqual(CONFIG.console_noise, ())
        else:
            self.assertIs(CONFIG.extra["console_hooks_pending"]["console_region_slot"], console_region_slot)

    def test_module_imports_no_generic_layer(self):
        src = pathlib.Path(k4g.__file__).read_text(encoding="utf-8")
        self.assertIsNone(re.search(r"^\s*(?:from|import)\s+src\.(?:matcher|console_keys|merchants\.registry)\b", src, re.M))


if __name__ == "__main__":
    unittest.main()

"""tests for src/merchants/kinguin.py — the Kinguin grammar file (2026-09-14, R32 / R45).

Fixtures are real rows of the 2026-09-12 batch (runs/20260912-020001-auto-kinguin-s58-p1..10,
940 rows) and the rows quoted by docs/feeds/Kinguin.md. The pipeline tests patch the
registry in place (src.matcher.MERCHANT_CONFIGS is the registry dict) so they pass whether
or not the integrator has wired "KINGUIN" → kinguin.CONFIG yet."""

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
    detect_region_base,
    extra_significant_words,
    match_offer,
    precheck_skip,
)
from src.merchant_config import MerchantConfig
from src.merchants import kinguin
from src.merchants.kinguin import (
    CONFIG,
    VALID_UNTIL_RE,
    altergift_verdict,
    console_region_slot,
    console_url_families,
    drop_altergift,
    gift_delivery,
    guard_name,
    is_account_listing,
    is_altergift,
    is_steam_altergift,
    parse_title,
    precheck,
    region_text,
    resolve_name,
    strip_valid_until,
    title_region,
    url_delivery,
)

URL = "https://www.kinguin.net/category/1/x"
GENERIC = MerchantConfig("Kinguin", domain="kinguin.net")     # the pre-2026-09-14 registry entry
ACCOUNT_SKIP = "skip category: ACCOUNT (Kinguin account / access listing — not a key)"
ALTERGIFT_CONFLICT = ("Kinguin delivery conflict: title Altergift but URL says key / account (no altergift tail) "
                      "— not entered (2026-09-14)")
ALTERGIFT_NOT_STEAM = ("Kinguin Altergift outside the Steam collocation (title's platform phrase is not Steam) "
                       "— not entered (Romain 2026-09-14: « Steam Altergift = Steam Gift »)")


def _offer(name, url=URL):
    return NormalizedOffer(offer_id="1", name=name, url=url, merchant="Kinguin")


class _Registry(unittest.TestCase):
    def _use(self, cfg):
        saved = M.MERCHANT_CONFIGS.get("KINGUIN")
        M.MERCHANT_CONFIGS["KINGUIN"] = cfg

        def restore():
            if saved is None:
                M.MERCHANT_CONFIGS.pop("KINGUIN", None)
            else:
                M.MERCHANT_CONFIGS["KINGUIN"] = saved

        self.addCleanup(restore)


class GrammarTests(unittest.TestCase):
    def test_real_rows_parse_head_region_delivery(self):
        cases = {
            "Hobo: Tough Life US Xbox One / Xbox Series X|S CD Key": ("Hobo: Tough Life", "US", "CD Key"),
            "Crusader Kings III - Royal Court DLC RoW PC Steam CD Key": ("Crusader Kings III - Royal Court DLC", "RoW", "CD Key"),
            "Call of Duty: World at War SEA PC Steam Gift": ("Call of Duty: World at War", "SEA", "Gift"),
            "Sons Of The Forest DE PC Steam Altergift": ("Sons Of The Forest", "DE", "Altergift"),
            "Rocket League UAE PC Steam Gift": ("Rocket League", "UAE", "Gift"),
            "Shardstorm PC Steam CD Key": ("Shardstorm", None, "CD Key"),
            "Microsoft Flight Simulator 2024 Aviator Edition PC Steam CD Key": ("Microsoft Flight Simulator 2024 Aviator Edition", None, "CD Key"),
            "Wrap House Simulator European Union XBOX One / Xbox Series X|S / PC CD Key": ("Wrap House Simulator", "European Union", "CD Key"),
            "Xbox Game Pass for PC - 12 Months EU PC Windows 10 CD Key": ("Xbox Game Pass for PC - 12 Months", "EU", "CD Key"),
            "Assassin's Creed Rogue NA PC Ubisoft Connect CD Key": ("Assassin's Creed Rogue", "NA", "CD Key"),
            "Grand Theft Auto V Enhanced BR PC Rockstar Digital Download CD Key": ("Grand Theft Auto V Enhanced", "BR", "Digital Download CD Key"),
            "Marathon or Mystery Steam CD Key by Digital Distribution Hub": ("Marathon or Mystery", None, "CD Key"),
            "UAD 1176 Classic FET Compressor PC/MAC CD Key": ("UAD 1176 Classic FET Compressor", None, "CD Key"),
            "Life is Strange Remastered Collection EU PS4/PS5 CD Key": ("Life is Strange Remastered Collection", "EU", "CD Key"),
            "CloverPit EU Nintendo Switch 2 CD Key": ("CloverPit", "EU", "CD Key"),
            "NHL 22 PS4 Access": ("NHL 22", None, "Access"),
            "Blocky Farm XBOX One / Xbox Series X|S Account": ("Blocky Farm", None, "Account"),
        }
        for title, (head, region, delivery) in cases.items():
            with self.subTest(title=title):
                m = parse_title(title)
                self.assertIsNotNone(m)
                self.assertEqual((m.group("head"), m.group("region"), m.group("delivery")), (head, region, delivery))
                self.assertEqual(resolve_name(title), head)
                self.assertEqual(region_text(title), region)

    def test_mixed_case_and_unknown_pairs_are_name_words(self):
        # "Us" (Among Us / The Last of Us) is never a code; "II" / "HD" / "GO" / "VR" are not
        # in the vocabulary; a Title-Case country in a game name is not a Kinguin code either
        for title, head in {
            "Among Us PC Steam CD Key": "Among Us",
            "The Last of Us Part I PC Steam CD Key": "The Last of Us Part I",
            "Heroes of Hammerwatch II EU PC Steam CD Key": "Heroes of Hammerwatch II",
            "BREAK ARTS II PC Steam CD Key (valid until May 2027)": "BREAK ARTS II",
            "Deus Ex GO PC Steam CD Key": "Deus Ex GO",
            "Trials of Mana HD PC Steam CD Key": "Trials of Mana HD",
            "Sad Virus Egypt PC Steam CD Key": "Sad Virus Egypt",
            "Death Row Xbox One CD Key": "Death Row",
        }.items():
            with self.subTest(title=title):
                self.assertEqual(resolve_name(title), head)
                self.assertIsNone(precheck(title, URL))
        self.assertEqual(region_text("Heroes of Hammerwatch II EU PC Steam CD Key"), "EU")
        self.assertIsNone(region_text("Among Us PC Steam CD Key"))
        self.assertIsNone(region_text("Sad Virus Egypt PC Steam CD Key"))

    def test_titles_outside_the_grammar_are_untouched(self):
        for title in (
            "Bitdefender Internet Security DAH Key (2 Years / 5 PCs)",
            "Tokopedia IDR 1500000 Gift Card ID",
            "Windows 11 Pro OEM Key",
            "Battlefield 1 Steam Key BRAZIL",        # the test_matcher fixture: generic BRAZIL scan
            "Mystery GOTY Xmas Box",
        ):
            with self.subTest(title=title):
                self.assertIsNone(parse_title(title))
                self.assertEqual(resolve_name(title), title)
                self.assertIsNone(precheck(title, URL))
                self.assertIsNone(title_region(title))
                self.assertIsNone(console_region_slot(title))


class RegionHooksTests(_Registry):
    def test_sellable_codes(self):
        for title, base in {
            "Metro Awakening US PC Steam CD Key": "us",
            "Warhammer 40,000: Gladius - Relics of War - Lord of Skulls DLC EU PC Steam CD Key": "eu",
            "Hades UK Xbox Series X|S CD Key": "uk",
            "Game GB PC Steam CD Key": "uk",
            "Wrap House Simulator European Union XBOX One / Xbox Series X|S / PC CD Key": "eu",
            "Shardstorm PC Steam CD Key": None,
        }.items():
            with self.subTest(title=title):
                self.assertEqual(title_region(title), base)
                self.assertIsNone(precheck(title, URL))

    def test_forbidden_codes_are_explicit_skips(self):
        # the 2026-09-12 batch: CA 85 / AU 79 / RoW 15 / TR 12 / NA 9 / SEA 7 / AR 3 / DE 2 / ZA 2 …
        cases = {
            "Puyo Puyo Tetris 2 CA Xbox One / Xbox Series X|S CD Key": "CANADA",
            "Destiny 2 - The Collection Bundle DLC AU XBOX One / Xbox Series X|S CD Key": "AUSTRALIA",
            "Crusader Kings III - Royal Court DLC RoW PC Steam CD Key": "ROW",
            "Darksiders Genesis TR PC Steam CD Key": "TURKEY",
            "Assassin's Creed Rogue NA PC Ubisoft Connect CD Key": "NORTH AMERICA",
            "Call of Duty: World at War SEA PC Steam Gift": "SOUTH EAST ASIA",
            "Bus Simulator 21 EN Language Only AR XBOX One / Xbox Series X|S CD Key": "ARGENTINA",
            "Sons Of The Forest DE PC Steam Altergift": "GERMANY",
            "Assassin's Creed Rogue ZA PC Ubisoft Connect CD Key": "SOUTH AFRICA",
            "Snufkin: Melody of Moominvalley CO Xbox Series X|S / PC CD Key": "COLOMBIA",
            "Grand Theft Auto V Enhanced BR PC Rockstar Digital Download CD Key": "BRAZIL",
            "Rocket League UAE PC Steam Gift": "UNITED ARAB EMIRATES",
            "Tom Clancy's Ghost Recon Breakpoint Ultimate Edition ANZ PC Ubisoft Connect CD Key": "ANZ",
            "Onimusha: Way of the Sword NA PS5 CD Key": "NORTH AMERICA",
            "Red Dead Redemption EU/UK PC Windows CD Key": "EU/UK",     # two buckets → no single one (fail-closed)
            "Planet Zoo - Africa Pack DLC NA PC Steam CD Key": "NORTH AMERICA",   # generic said AFRICA (the DLC name)
        }
        for title, label in cases.items():
            with self.subTest(title=title):
                self.assertEqual(precheck(title, URL), f"forbidden region: {label}")
                self.assertIsNone(title_region(title))

    def test_account_and_access_listings(self):
        rows = {
            "Blocky Farm XBOX One / Xbox Series X|S Account": "https://www.kinguin.net/category/523387/blocky-farm-xbox-one-xbox-series-x-s-account",
            "NHL 22 PS4 Access": "https://www.kinguin.net/category/366235/nhl-22-ps4-access",
            "Resident Evil 3 PS4/PS5 Access": "https://www.kinguin.net/category/363986/resident-evil-3-ps4-ps5-online-account-activation",
        }
        for title, url in rows.items():
            with self.subTest(title=title):
                self.assertTrue(is_account_listing(title, url))
                self.assertTrue(is_account_listing(title, URL))          # the title alone says it
                self.assertTrue(is_account_listing("Some Game", url))    # the URL alone says it
                self.assertEqual(precheck(title, url), ACCOUNT_SKIP)
        self.assertFalse(is_account_listing("Hades EU PS5 CD Key", URL))
        self.assertEqual(console_url_families(rows["Blocky Farm XBOX One / Xbox Series X|S Account"]),
                         "console: ACCOUNT — not a game (R45)")
        self.assertEqual(console_url_families(rows["NHL 22 PS4 Access"]), "console: ACCESS — not a game (R45)")
        self.assertEqual(console_url_families(rows["Resident Evil 3 PS4/PS5 Access"]), "console: ACCESS — not a game (R45)")

    def test_valid_until_note_is_stripped_from_the_guard_only(self):
        # Romain's ruling (2026-09-14): « Kinguin valid until juin 2027 on rentre » — the note
        # is an activation deadline, not a product word. guard_name strips it and NOTHING else.
        rows = {
            "Vampyr PC Steam CD Key (valid until March 2027)": ("Vampyr PC Steam CD Key", "Vampyr"),
            "Soulstice Deluxe Edition PC Steam CD Key (valid until June 2027)": ("Soulstice Deluxe Edition PC Steam CD Key", "Soulstice Deluxe Edition"),
            "Project MIKHAIL: A Muv-Luv War Story PC Steam CD Key (valid until May 2027)": ("Project MIKHAIL: A Muv-Luv War Story PC Steam CD Key", "Project MIKHAIL: A Muv-Luv War Story"),
            "The Invincible PC Steam CD Key (valid until May, 2027)": ("The Invincible PC Steam CD Key", "The Invincible"),    # the comma variant (5 rows)
            "Dead Cells - The Bad Seed DLC RoW PC Steam CD Key (valid until March 2027)": ("Dead Cells - The Bad Seed DLC RoW PC Steam CD Key", "Dead Cells - The Bad Seed DLC"),
            "Bitdefender Total Security Key (valid until December 2026)": ("Bitdefender Total Security Key", "Bitdefender Total Security Key"),   # outside the grammar: only the note goes
        }
        for raw, (guard, resolved) in rows.items():
            with self.subTest(raw=raw):
                self.assertEqual(guard_name(raw), guard)
                self.assertEqual(strip_valid_until(raw), guard)
                self.assertEqual(resolve_name(raw), resolved)
                self.assertIsNotNone(VALID_UNTIL_RE.search(raw))
        raw = "Project MIKHAIL: A Muv-Luv War Story PC Steam CD Key (valid until May 2027)"
        self.assertIsNone(precheck(raw, URL))
        self.assertIsNone(title_region(raw))
        self.assertEqual(build_slug_candidates(resolve_name(raw))[0], "project-mikhail-a-muv-luv-war-story")
        # the raw title still counts the note as extra words (the generic guard is untouched);
        # the guard_name hook is what removes them — and only them
        self.assertEqual(extra_significant_words("Project MIKHAIL: A Muv-Luv War Story", raw), ["VALID", "UNTIL", "MAY", "2027"])
        self.assertEqual(extra_significant_words("Project MIKHAIL: A Muv-Luv War Story", guard_name(raw)), [])
        self.assertEqual(extra_significant_words("Vampyr", guard_name("Vampyr Chronicles PC Steam CD Key (valid until March 2027)")), ["CHRONICLES"])
        # a title without the note is returned untouched; the regex is the only strip
        self.assertEqual(guard_name("Shardstorm PC Steam CD Key"), "Shardstorm PC Steam CD Key")
        self.assertEqual(guard_name("Valid Until Dawn PC Steam CD Key"), "Valid Until Dawn PC Steam CD Key")    # not the note
        # review fix (2026-09-14, finding [2]): the strip is anchored to the title END — the note
        # is trailing in 158 / 158 corpus rows; a note in the MIDDLE is a spelling never seen and
        # stays in the guard (→ the usual extra-words skip, fail-closed), never a mid-title strip
        for raw in ("Vampyr (Valid Until March 2027) PC Steam CD Key",
                    "Vampyr PC Steam CD Key (valid until March 2027) EU",
                    "(valid until March 2027) Vampyr PC Steam CD Key"):
            with self.subTest(raw=raw):
                self.assertIsNone(VALID_UNTIL_RE.search(raw))
                self.assertEqual(strip_valid_until(raw), raw)
                self.assertEqual(guard_name(raw), raw)
        self.assertEqual(guard_name("Vampyr PC Steam CD Key (valid until March 2027) "), "Vampyr PC Steam CD Key")   # trailing blank is fine
        # the same phrase is console noise now: a console row with the note resolves to the game
        self.assertEqual(CONFIG.console_noise, ("CD Key", VALID_UNTIL_RE))
        from src.console_keys import classify_console as _classify
        sig = _classify("Hades EU PS5 CD Key (valid until March 2027)",
                        "https://www.kinguin.net/category/1/hades-eu-ps5-cd-key-valid-until-march-2027", "Kinguin")
        self.assertEqual((sig.families, sig.resolve_name, sig.region_base, sig.skip_reason), (("PS5",), "Hades", "eu", None))

    def test_pipeline_valid_until_rows_are_entered(self):
        # 2026-09-12 batch: 79 rows carried the note, 69 of them skipped "different/expanded
        # product — extra words: ['VALID', 'UNTIL', '<Month>', '2027']" with the page resolved.
        vampyr = AksResolution(slug="vampyr", url="https://aks/buy-vampyr-cd-key-compare-prices/",
                               product_id="1", aks_name="Vampyr",
                               editions={"1": {"name": "Standard"}}, official_platforms=("Steam",))
        offer = _offer("Vampyr PC Steam CD Key (valid until March 2027)",
                       "https://www.kinguin.net/category/495887/vampyr-pc-steam-cd-key-valid-until-march-2027")
        asked = []

        def resolver(name, **kw):
            asked.append(name)
            return vampyr

        self._use(GENERIC)                  # the pre-2026-09-14 registry entry: the note was extra words
        r = match_offer(offer, resolver=resolver)
        self.assertIsInstance(r, SkippedOffer)
        self.assertEqual(r.reason, "different/expanded product — extra words: ['VALID', 'UNTIL', 'MARCH', '2027']")
        self._use(CONFIG)
        r = match_offer(offer, resolver=resolver)
        self.assertIsInstance(r, Candidate, getattr(r, "reason", None))
        # implicit GLOBAL, as for any Kinguin title without a region code
        self.assertEqual((r.platform, r.region_label, r.region_id, r.region_implicit, r.edition_label, r.edition_id),
                         ("STEAM", "GLOBAL", "2", True, "Standard", "1"))
        self.assertEqual(asked[-1], "Vampyr")
        # a Deluxe row reconciles its edition against the page that carries it
        soulstice = AksResolution(slug="soulstice", url="https://aks/buy-soulstice-cd-key-compare-prices/",
                                  product_id="2", aks_name="Soulstice",
                                  editions={"1": {"name": "Standard"}, "10": {"name": "Deluxe"}},
                                  official_platforms=("Steam",))
        r = match_offer(_offer("Soulstice Deluxe Edition PC Steam CD Key (valid until June 2027)",
                               "https://www.kinguin.net/category/835949/soulstice-deluxe-edition-pc-steam-cd-key-valid-until-june-2027"),
                        resolver=lambda name, **kw: soulstice)
        self.assertIsInstance(r, Candidate, getattr(r, "reason", None))
        self.assertEqual((r.platform, r.region_label, r.region_id, r.edition_label, r.edition_id), ("STEAM", "GLOBAL", "2", "Deluxe", "10"))
        # every other guard is untouched: a forbidden code, a DLC on a base page, a real extra word
        self.assertEqual(precheck_skip(_offer("Dead Cells RoW PC Steam CD Key (valid until March 2027)")), "forbidden region: ROW")
        r = match_offer(_offer("Vampyr Remastered PC Steam CD Key (valid until March 2027)"), resolver=resolver)
        self.assertIsInstance(r, SkippedOffer)
        self.assertEqual(r.reason, "dangerous qualifier absent from AKS name: REMASTERED")     # R01b
        r = match_offer(_offer("Vampyr Chronicles PC Steam CD Key (valid until March 2027)"), resolver=resolver)
        self.assertIsInstance(r, SkippedOffer)
        self.assertEqual(r.reason, "different/expanded product — extra words: ['CHRONICLES']")   # R16
        # review fix (2026-09-14, finding [2]): a mid-title note is NOT stripped — the guard reads
        # it as extra words (fail-closed), exactly the pre-ruling outcome for that spelling
        r = match_offer(_offer("Vampyr (Valid Until March 2027) PC Steam CD Key",
                               "https://www.kinguin.net/category/495887/vampyr-valid-until-march-2027-pc-steam-cd-key"),
                        resolver=resolver)
        self.assertIsInstance(r, SkippedOffer)
        self.assertEqual(r.reason, "different/expanded product — extra words: ['VALID', 'UNTIL', 'MARCH', '2027']")

    def test_pipeline_us_row_is_steam_us_on_the_game_slug(self):
        # Before: implicit GLOBAL + slug "metro-awakening-us" (404 → "no AKS product page
        # found"). After: region US (8), resolver called with the peeled name.
        page = AksResolution(slug="metro-awakening", url="https://aks/buy-metro-awakening-cd-key-compare-prices/",
                             product_id="1", aks_name="Metro Awakening",
                             editions={"1": {"name": "Standard"}}, official_platforms=("Steam",))
        offer = _offer("Metro Awakening US PC Steam CD Key",
                       "https://www.kinguin.net/category/1/metro-awakening-us-pc-steam-cd-key")
        asked = []

        def resolver(name, **kw):
            asked.append(name)
            return page

        self._use(GENERIC)
        self.assertEqual(detect_region_base(offer), ("global", "GLOBAL", True, False))
        self.assertEqual(build_slug_candidates(offer.name)[0], "metro-awakening-us")
        self._use(CONFIG)
        self.assertEqual(detect_region_base(offer), ("us", "US", False, False))
        r = match_offer(offer, resolver=resolver)
        self.assertIsInstance(r, Candidate, getattr(r, "reason", None))
        self.assertEqual((r.platform, r.region_label, r.region_id, r.region_implicit), ("STEAM", "US", "8", False))
        self.assertEqual(asked, ["Metro Awakening"])

    def test_pipeline_precheck_reasons_default_and_consoles_mode(self):
        self._use(CONFIG)
        self.assertEqual(precheck_skip(_offer("Darksiders Genesis TR PC Steam CD Key")), "forbidden region: TURKEY")
        console = _offer("Puyo Puyo Tetris 2 CA Xbox One / Xbox Series X|S CD Key",
                         "https://www.kinguin.net/category/1/puyo-puyo-tetris-2-ca-xbox-one-xbox-series-x-s-cd-key")
        self.assertEqual(precheck_skip(console), "forbidden region: CANADA")
        self.assertEqual(precheck_skip(console, consoles=True), "forbidden region: CANADA")
        self.assertEqual(precheck_skip(_offer("Blocky Farm XBOX One / Xbox Series X|S Account")), ACCOUNT_SKIP)
        # the generic vocabulary still runs after the hook (the test_matcher Kinguin fixture)
        self.assertEqual(precheck_skip(_offer("Battlefield 1 Steam Key BRAZIL", "https://www.kinguin.net/x")),
                         "forbidden region: BRAZIL")
        # the domain rule moved with the config
        self.assertIn("merchant-domain mismatch", precheck_skip(_offer("Elden Ring", "https://www.g2a.com/elden-ring")))


class AltergiftTests(_Registry):
    """Romain (2026-09-14): « Steam Altergift = Steam Gift on rentre sous gift tous les
    altergifts » — Kinguin's own "Altergift" delivery too (review fix 2026-09-14, finding
    [3]: the ruling was implemented for K4G only; a Kinguin Altergift row reached the plain
    STEAM GLOBAL (2) read and was R16-skipped "extra words: ['ALTERGIFT']"). The batch's one
    row, "Sons Of The Forest DE PC Steam Altergift", is a forbidden region anyway."""

    SONS = "Sons Of The Forest PC Steam Altergift"
    SONS_URL = "https://www.kinguin.net/category/713973/sons-of-the-forest-pc-steam-altergift"

    def _page(self, slug="sons-of-the-forest", name="Sons Of The Forest", official=("Steam",)):
        return AksResolution(slug=slug, url=f"https://aks/buy-{slug}-cd-key-compare-prices/", product_id="1",
                             aks_name=name, editions={"1": {"name": "Standard"}}, official_platforms=official)

    def test_text_hooks(self):
        for title, guard, resolved in (
            (self.SONS, "Sons Of The Forest PC Steam", "Sons Of The Forest"),
            ("Sons Of The Forest DE PC Steam Altergift", "Sons Of The Forest DE PC Steam", "Sons Of The Forest"),
            ("Sons Of The Forest EU Steam Altergift (valid until June 2027)", "Sons Of The Forest EU Steam", "Sons Of The Forest"),
            ("Some ALTERGIFT Thing", "Some Thing", "Some Thing"),           # outside the grammar: only the word goes
        ):
            with self.subTest(title=title):
                self.assertTrue(is_altergift(title))
                self.assertEqual(guard_name(title), guard)
                self.assertEqual(drop_altergift(strip_valid_until(title)), guard)
                self.assertEqual(resolve_name(title), resolved)
        for title in ("Call of Duty: World at War SEA PC Steam Gift", "F1 2013 Classic Edition Upgrade Steam Gift",
                      "Altergifted PC Steam CD Key", "Shardstorm PC Steam CD Key"):
            with self.subTest(title=title):
                self.assertFalse(is_altergift(title))
                self.assertIsNone(altergift_verdict(title, URL))
                self.assertIsNone(gift_delivery(title, URL))
                self.assertEqual(guard_name(title), title)

    def test_url_delivery(self):
        for url, said in {
            self.SONS_URL: "gift",
            "https://www.kinguin.net/category/7921/f1-2013-classic-edition-upgrade-steam-gift": "gift",
            "https://www.kinguin.net/category/1/sons-of-the-forest-pc-steam-cd-key": "key",
            "https://www.kinguin.net/category/1/sons-of-the-forest-pc-steam-key?nosalesbooster=1": "key",
            "https://www.kinguin.net/category/523387/blocky-farm-xbox-one-xbox-series-x-s-account": "key",
            "https://www.kinguin.net/category/363986/resident-evil-3-ps4-ps5-online-account-activation": "key",
            "https://www.kinguin.net/category/440591/world-of-warcraft-burning-crusade-classic-anniversary-edition-upgrade-outland-ep": None,   # truncated
            "https://www.kinguin.net/category/1/sons-of-the-forest-pc-st": None,
            URL: None,
        }.items():
            with self.subTest(url=url):
                self.assertEqual(url_delivery(url), said)

    def test_pipeline_altergift_row_is_steam_gift(self):
        offer = _offer(self.SONS, self.SONS_URL)
        asked = []

        def resolver(name, **kw):
            asked.append(name)
            return self._page()

        self._use(GENERIC)                    # before: plain key read + R16 on the word
        self.assertEqual(detect_region_base(offer)[:3], ("global", "GLOBAL", True))
        r = match_offer(offer, resolver=resolver)
        self.assertIsInstance(r, SkippedOffer)
        self.assertEqual(r.reason, "different/expanded product — extra words: ['ALTERGIFT']")
        self._use(CONFIG)
        self.assertTrue(is_steam_altergift(self.SONS))
        self.assertEqual(altergift_verdict(self.SONS, self.SONS_URL), "gift")
        self.assertIs(gift_delivery(self.SONS, self.SONS_URL), True)
        self.assertIsNone(precheck_skip(offer))
        r = match_offer(offer, resolver=resolver)
        self.assertIsInstance(r, Candidate, getattr(r, "reason", None))
        self.assertEqual((r.platform, r.region_label, r.region_id, r.region_implicit, r.edition_id),
                         ("STEAM", "GIFT", "25", True, "1"))
        self.assertEqual(asked[-1], "Sons Of The Forest")
        # the code before the platform phrase layers the Steam gift bucket: EU → GIFT EU (259);
        # US / UK have no Steam gift bucket → the fail-closed "no region id" skip (unchanged rule)
        r = match_offer(_offer("Sons Of The Forest EU PC Steam Altergift",
                               "https://www.kinguin.net/category/1/sons-of-the-forest-eu-pc-steam-altergift"), resolver=resolver)
        self.assertIsInstance(r, Candidate, getattr(r, "reason", None))
        self.assertEqual((r.region_label, r.region_id, r.region_implicit), ("GIFT EU", "259", False))
        r = match_offer(_offer("Sons Of The Forest US PC Steam Altergift",
                               "https://www.kinguin.net/category/1/sons-of-the-forest-us-pc-steam-altergift"), resolver=resolver)
        self.assertIsInstance(r, SkippedOffer)
        self.assertEqual(r.reason, "no region id for STEAM/GIFT US")
        # the batch's real row: the forbidden code wins, Altergift or not
        self.assertEqual(precheck_skip(_offer("Sons Of The Forest DE PC Steam Altergift",
                                              "https://www.kinguin.net/category/713973/sons-of-the-forest-de-pc-steam-altergift")),
                         "forbidden region: GERMANY")
        # "Steam Gift" rows are untouched: the generic " GIFT " read (hook None)
        f1 = _offer("F1 2013 Classic Edition Upgrade Steam Gift",
                    "https://www.kinguin.net/category/7921/f1-2013-classic-edition-upgrade-steam-gift")
        self.assertIsNone(gift_delivery(f1.name, f1.url))
        self.assertEqual(detect_region_base(f1), ("global", "GLOBAL", True, True))

    def test_gates_are_fail_closed(self):
        # the slug must not CONTRADICT the title (Kinguin's slug is often truncated → a silent slug
        # is accepted); a non-Steam Altergift is a grammar never seen → never another gift bucket
        self._use(CONFIG)
        conflict = _offer(self.SONS, "https://www.kinguin.net/category/1/sons-of-the-forest-pc-steam-cd-key")
        self.assertEqual(altergift_verdict(conflict.name, conflict.url), ALTERGIFT_CONFLICT)
        self.assertIsNone(gift_delivery(conflict.name, conflict.url))
        self.assertEqual(precheck_skip(conflict), ALTERGIFT_CONFLICT)
        r = match_offer(conflict, resolver=lambda name, **kw: self._page())
        self.assertIsInstance(r, SkippedOffer)
        self.assertEqual(r.reason, ALTERGIFT_CONFLICT)
        truncated = _offer(self.SONS, "https://www.kinguin.net/category/1/sons-of-the-forest-pc-st")
        self.assertEqual(altergift_verdict(truncated.name, truncated.url), "gift")
        self.assertIsNone(precheck_skip(truncated))
        # an account marker in the slug is the account skip first (unchanged order)
        self.assertEqual(precheck_skip(_offer(self.SONS, "https://www.kinguin.net/category/1/sons-of-the-forest-pc-steam-account")), ACCOUNT_SKIP)
        for title in ("Sons Of The Forest PC Epic Games Altergift", "Sons Of The Forest PC Battle.net Altergift",
                      "Sons Of The Forest GOG Altergift", "Sons Of The Forest Altergift", "Some ALTERGIFT Thing"):
            with self.subTest(title=title):
                self.assertFalse(is_steam_altergift(title))
                self.assertEqual(altergift_verdict(title, self.SONS_URL), ALTERGIFT_NOT_STEAM)
                self.assertIsNone(gift_delivery(title, self.SONS_URL))
                offer = _offer(title, self.SONS_URL)
                self.assertEqual(precheck_skip(offer), ALTERGIFT_NOT_STEAM)
                r = match_offer(offer, resolver=lambda name, **kw: self._page(official=("Steam", "Epic Games", "Battle.net", "GOG")))
                self.assertIsInstance(r, SkippedOffer)
                self.assertEqual(r.reason, ALTERGIFT_NOT_STEAM)


class ConsoleHooksTests(unittest.TestCase):
    ROWS = {
        "Hobo: Tough Life US Xbox One / Xbox Series X|S CD Key": "US",
        "Puyo Puyo Tetris 2 CA Xbox One / Xbox Series X|S CD Key": "CA",
        "MotoGP 26 AU Xbox Series X|S / PC CD Key": "AU",
        "NARUTO SHIPPUDEN: Ultimate Ninja STORM Trilogy RoW Xbox One / Xbox Series X|S CD Key": "RoW",
        "Onimusha: Way of the Sword NA PS5 CD Key": "NA",
        "EA SPORTS Madden NFL 27 NA Nintendo Switch 2 CD Key": "NA",
        "Wrap House Simulator European Union XBOX One / Xbox Series X|S / PC CD Key": "European Union",
        "Hoomanz! Xbox Series X|S / PC CD Key": None,
        "The Last of Us Part I EU PS5 CD Key": "EU",
        "NHL 27 UK Deluxe Edition Xbox Series X|S CD Key": None,       # "UK" mid-name is not the slot
    }

    def test_region_slot_is_the_code_verbatim_and_agrees_with_the_shared_read(self):
        for title, slot in self.ROWS.items():
            with self.subTest(title=title):
                self.assertEqual(console_region_slot(title), slot)
                sig = classify_console(title, URL, "Kinguin")
                self.assertEqual(sig.region_words[:1], (slot,) if slot else ())

    def test_url_families(self):
        cases = {
            "https://www.kinguin.net/category/844910/infected-cowboys-bundle-eu-xbox-one-xbox-series-x-s-cd-key": ("XBOX_ONE", "XBOX_SERIES"),
            "https://www.kinguin.net/category/841718/mechwarrior-5-mercenaries-ca-xbox-one-xbox-series-x-s-pc-cd-key": ("XBOX_ONE", "XBOX_SERIES"),
            "https://www.kinguin.net/category/808670/hoomanz-xbox-series-x-s-pc-cd-key": ("XBOX_SERIES",),
            "https://www.kinguin.net/category/141837/life-is-strange-remastered-collection-eu-ps4-ps5-cd-key": ("PS4", "PS5"),
            "https://www.kinguin.net/category/764730/cloverpit-eu-nintendo-switch-2-cd-key": ("SWITCH2",),
            "https://www.kinguin.net/category/789621/pikmin-3-deluxe-eu-nintendo-switch-cd-key": ("SWITCH",),
            "https://www.kinguin.net/category/824325/beast-of-reincarnation-pre-order-bonus-eu-ps5-cd-key": ("PS5",),
            # PC rows and truncated slugs say nothing
            "https://www.kinguin.net/category/679559/microsoft-flight-simulator-2024-aviator-edition-pc-steam-cd-key": None,
            "https://www.kinguin.net/category/440591/world-of-warcraft-burning-crusade-classic-anniversary-edition-upgrade-outland-ep": None,
            "https://www.kinguin.net/category/1/switch-galaxy-ultra-steam-cd-key": None,   # a bare "switch" is a name
        }
        for url, families in cases.items():
            with self.subTest(url=url):
                self.assertEqual(console_url_families(url), families)


class ConfigTests(unittest.TestCase):
    def test_config_declares_the_hooks(self):
        self.assertIsInstance(CONFIG, MerchantConfig)
        self.assertEqual((CONFIG.name, CONFIG.domain), ("Kinguin", "kinguin.net"))
        self.assertIs(CONFIG.precheck, precheck)
        self.assertIs(CONFIG.title_region, title_region)
        self.assertIs(CONFIG.resolve_name, resolve_name)
        self.assertIs(CONFIG.guard_name, guard_name)            # 2026-09-14: the validity note / "Altergift" are not product words
        self.assertIs(CONFIG.gift_delivery, gift_delivery)      # 2026-09-14: "PC Steam Altergift" = Steam gift; "Steam Gift" rows keep the generic read
        # platform stays title-sourced (R32b — Romain: it works today)
        self.assertTrue(CONFIG.title_is_platform_source)
        self.assertIsNone(CONFIG.url_platform)
        self.assertIsNone(CONFIG.offer_page_resolver)
        fields = {f.name for f in dataclasses.fields(MerchantConfig)}
        if "console_region_slot" in fields:
            self.assertIs(CONFIG.console_region_slot, console_region_slot)
            self.assertIs(CONFIG.console_url_families, console_url_families)
            self.assertEqual(CONFIG.console_noise, ("CD Key", VALID_UNTIL_RE))
            self.assertNotIn("console_hooks_pending", CONFIG.extra)
        else:   # the contract not landed yet: the hooks are declared under extra
            pending = CONFIG.extra["console_hooks_pending"]
            self.assertIs(pending["console_region_slot"], console_region_slot)

    def test_module_imports_no_generic_layer(self):
        src = pathlib.Path(kinguin.__file__).read_text(encoding="utf-8")
        self.assertIsNone(re.search(r"^\s*(?:from|import)\s+src\.(?:matcher|console_keys|merchants\.registry)\b", src, re.M))


if __name__ == "__main__":
    unittest.main()

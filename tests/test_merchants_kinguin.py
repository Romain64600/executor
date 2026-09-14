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
    OPEN_QUESTION_VALID_UNTIL,
    console_region_slot,
    console_url_families,
    is_account_listing,
    parse_title,
    precheck,
    region_text,
    resolve_name,
    title_region,
)

URL = "https://www.kinguin.net/category/1/x"
GENERIC = MerchantConfig("Kinguin", domain="kinguin.net")     # the pre-2026-09-14 registry entry
ACCOUNT_SKIP = "skip category: ACCOUNT (Kinguin account / access listing — not a key)"


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

    def test_valid_until_note_stays_an_extra_words_skip_until_romain_rules(self):
        raw = "Project MIKHAIL: A Muv-Luv War Story PC Steam CD Key (valid until May 2027)"
        self.assertEqual(resolve_name(raw), "Project MIKHAIL: A Muv-Luv War Story")
        self.assertEqual(resolve_name("The Invincible PC Steam CD Key (valid until May, 2027)"), "The Invincible")
        self.assertIsNone(precheck(raw, URL))
        self.assertIsNone(title_region(raw))
        # the slug is the game's …
        self.assertEqual(build_slug_candidates(resolve_name(raw))[0], "project-mikhail-a-muv-luv-war-story")
        # … but the R01b guard reads the RAW title: the note is still extra words → skip
        self.assertEqual(extra_significant_words("Project MIKHAIL: A Muv-Luv War Story", raw),
                         ["VALID", "UNTIL", "MAY", "2027"])
        # and it is deliberately NOT console noise (that would make console rows enterable)
        self.assertEqual(CONFIG.console_noise, ("CD Key",))
        self.assertIn("valid until", OPEN_QUESTION_VALID_UNTIL)

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
        # platform stays title-sourced (R32b — Romain: it works today)
        self.assertTrue(CONFIG.title_is_platform_source)
        self.assertIsNone(CONFIG.url_platform)
        self.assertIsNone(CONFIG.offer_page_resolver)
        fields = {f.name for f in dataclasses.fields(MerchantConfig)}
        if "console_region_slot" in fields:
            self.assertIs(CONFIG.console_region_slot, console_region_slot)
            self.assertIs(CONFIG.console_url_families, console_url_families)
            self.assertEqual(CONFIG.console_noise, ("CD Key",))
            self.assertNotIn("console_hooks_pending", CONFIG.extra)
        else:   # the contract not landed yet: the hooks are declared under extra
            pending = CONFIG.extra["console_hooks_pending"]
            self.assertIs(pending["console_region_slot"], console_region_slot)

    def test_module_imports_no_generic_layer(self):
        src = pathlib.Path(kinguin.__file__).read_text(encoding="utf-8")
        self.assertIsNone(re.search(r"^\s*(?:from|import)\s+src\.(?:matcher|console_keys|merchants\.registry)\b", src, re.M))


if __name__ == "__main__":
    unittest.main()

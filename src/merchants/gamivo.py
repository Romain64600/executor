"""Gamivo — region from the title tail, platform from the URL run `[R46]` (2026-09-12).

Grammar seen live on the 2026-09-12 feed (1 000 rows, ``runs/20260912-020000-auto-gamivo-*``):

* title ``<Game> [<Edition>] [<LANG>(/<LANG>)*] <Region>`` — the region is a trailing
  phrase with NO separator, optionally preceded by uppercase language codes:
  "Ravenswatch EN United Kingdom", "Tiny Tina's Wonderlands United States",
  "FIFA 23 EN/PL/CS/RU/TR EU", "KIBORG EN Colombia", "Storebound ROW". The title NEVER
  names the platform.
* URL ``gamivo.com/product/<slug>-<platform run>-<cc>[-<langs>]-<edition>`` — the
  platform run sits BETWEEN the game slug and the region code, the edition AFTER the
  code: ``tiny-tinas-wonderlands-pc-steam-us-standard``,
  ``the-sims-4-carnaval-streetwear-kit-pc-ea-app-eu-standard``,
  ``metro-exodus-pc-steam-cis-en-de-fr-it-standard``; a second form puts ``-pc`` at the
  very end: ``middle-earth-the-shadow-bundle-steam-eu-standard-pc``,
  ``…-steam-gift-global-en-october-2012-pc``. Console runs (``-xbox-…``, ``-ps-…``,
  ``-nintendo-…``) are Gamivo's own fused grammar too — declared below through the
  ``MerchantConfig`` console hooks (R32 / R45, 2026-09-14) and read by the shared
  classifier ``src/console_keys.py``, which names no merchant.

Why this module exists: the generic rules read none of that. The P2-6b trailing-slot
rule never fires (the edition token follows the code), ``detect_region`` reads no
separator-less title tail, and a platform-less title on a page listing Direct Publisher
fell to PUBLISHER (R27) — on 2026-09-11 six US-locked Steam keys were entered
Publisher (1) GLOBAL (``docs/MERCHANTS.md``). Four ``MerchantConfig`` hooks fix it, pure
functions of the feed row, no matcher import (the registry imports this module):

* ``precheck``  — a trailing region that is not sellable → ``forbidden region: <LABEL>``
  (the single router ``aks_lists.suggest_target_list`` files it); no title tail → the
  URL code decides, unknown code → fail-closed skip;
* ``title_region`` — United Kingdom / United States / EU / Global tails → uk / us / eu /
  global (authoritative, R32e);
* ``resolve_name`` — the tail peeled off before slug guessing ("Ravenswatch");
* ``url_platform`` — the URL run → STEAM / EA / UBISOFT / BATTLENET / GOG / EPIC /
  ROCKSTAR; a console run or nothing recognised → None.

Matching is CASE-SENSITIVE on purpose (like MMOGA's "<CODE> Key"): "The Last of Us" ends
with "Us", not "US"; Gamivo writes its regions Title Case ("United Kingdom", "Colombia")
or all caps ("EU", "ROW", "CIS"). A language code is only recognised from the known
ISO 639-1 list, so a trailing Roman numeral or acronym ("Final Fantasy XV Global") is not
mistaken for one. The MA7 ruling stands: an ``-en-`` URL segment / "EN" title code is a
language variant, never a skip.

Console grammar (R45, 2026-09-14 — 569/572 console rows of the 2026-09-12 batch carried
the platform in the URL only): ``…-xbox-<run>-<cc>-…`` with the fused runs
``xboxoneseries`` / ``xbox-one-series`` / ``one-series`` (Xbox One + Series),
``xboxseries`` / ``xbox-series`` / ``series``, ``xboxone`` / ``one``, each optionally
fused with ``windows`` / ``-pc`` / ``-windows`` / ``-xbox-pc`` (PC declared next to the
console: Play Anywhere candidate); ``-xbox-pc-`` alone is a PC-only Xbox Live key (skip);
``-xbox-xbox-windows-`` / ``-xbox-xboxwindows-`` is Xbox + Windows with no generation —
since P4 (Romain 2026-09-25, « Xbox sur les deux ») the hook returns
``XBOX_GENERATION_UNDECLARED`` with PC declared: the classifier reads it as Xbox One + Series
+ PC, the Play Anywhere case of P2 (before: "no declared generation");
``-ps-ps5-`` / ``-psn-ps5-`` / ``-ps-ps4-ps5-``; ``-nintendo-nintendo-switch(-2)-``. The
region is the title tail (``console_region_slot`` = ``title_tail``); the language code(s)
before it ("EN", "EN/PL/CS/RU/TR") are Gamivo's furniture (``console_noise``).
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit

from src.console_keys import SKIP_PC_ONLY, XBOX_GENERATION_UNDECLARED
from src.merchant_config import MerchantConfig

# ── title tail ───────────────────────────────────────────────────────────────────────
# Regions AKS sells → detect_region base (REGION_IDS keys).
SELLABLE_TAILS = {
    "United Kingdom": "uk", "UK": "uk",
    "United States": "us", "USA": "us", "US": "us",
    "EU": "eu", "Europe": "eu", "EUROPE": "eu",
    "Global": "global", "GLOBAL": "global", "Worldwide": "global", "WORLDWIDE": "global",
    "WW": "global",
}
# Region locks we never enter → the matcher's own FORBIDDEN_REGIONS / _URL_FORBIDDEN_CODES
# label vocabulary where one exists, so ``suggest_target_list`` files them identically
# (COLOMBIA / LATIN AMERICA / ASIA / CIS … → Blacklist, CANADA / AUSTRALIA → their list,
# the rest → garder). Observed on the 2026-09-12 feed: Colombia 310, ROW 45, Canada 18,
# Netherlands 12, Australia 8, North America 6, Turkey 6, CIS 3, Poland 3, Asia 2,
# Mexico 2, Latin America / Brazil / India / Germany / Singapore / South Africa / SEA 1.
FORBIDDEN_TAILS = {
    "Colombia": "COLOMBIA", "ROW": "ROW", "Canada": "CANADA", "Australia": "AUSTRALIA",
    "North America": "NORTH AMERICA", "Netherlands": "NETHERLANDS", "Turkey": "TURKEY",
    "Poland": "POLAND", "Asia": "ASIA", "Mexico": "MEXICO", "Latin America": "LATIN AMERICA",
    "LATAM": "LATAM", "Brazil": "BRAZIL", "India": "INDIA", "CIS": "CIS", "Germany": "GERMANY",
    "Singapore": "SINGAPORE", "South Africa": "SOUTH AFRICA", "SEA": "SOUTH EAST ASIA",
    "EMEA": "EMEA", "MENA": "MENA", "Middle East": "MIDDLE EAST", "Russia": "RUSSIA",
    "Argentina": "ARGENTINA", "China": "CHINA", "Japan": "JAPAN", "Korea": "KOREA",
    "South Korea": "KOREA", "Ukraine": "UKRAINE", "Chile": "CHILE", "Peru": "PERU",
    "Philippines": "PHILIPPINES", "Malaysia": "MALAYSIA", "Indonesia": "INDONESIA",
    "Thailand": "THAILAND", "Africa": "AFRICA", "Oceania": "OCEANIA",
    "South America": "SOUTH AMERICA", "Americas": "AMERICAS", "Eastern Europe": "EASTERN EUROPE",
    "France": "FRANCE", "Italy": "ITALY", "Spain": "SPAIN", "Hong Kong": "HONG KONG",
    "Taiwan": "TAIWAN", "New Zealand": "NEW ZEALAND", "Switzerland": "SWITZERLAND",
    "Austria": "AUSTRIA", "Romania": "ROMANIA", "Portugal": "PORTUGAL",
    "United Arab Emirates": "UNITED ARAB EMIRATES", "UAE": "UAE", "GCC": "GCC",
}
# ISO 639-1 codes Gamivo prefixes the region with ("EN", "EN/DE/FR/IT"); uppercase only.
_LANG = (
    r"(?:EN|FR|DE|ES|IT|PT|NL|PL|RU|CS|SK|HU|RO|BG|HR|SL|SV|DA|NO|FI|EL|TR|JA|KO|ZH|AR|"
    r"UK|TH|VI|ID|MS|HI|LT|LV|ET|HE|FA|UA)"
)
_REGION_ALT = "|".join(
    re.escape(k) for k in sorted({**SELLABLE_TAILS, **FORBIDDEN_TAILS}, key=len, reverse=True)
)
# "<something> [<LANGS>] <Region>$" — something must precede (a lone region is no title).
TITLE_TAIL_RE = re.compile(
    r"\s+(?:(?P<langs>" + _LANG + r"(?:/" + _LANG + r")*)\s+)?(?P<region>" + _REGION_ALT + r")\s*$"
)


def title_tail(name: str) -> str | None:
    """The trailing region phrase of a Gamivo title, verbatim ("United Kingdom", "EU",
    "Colombia"), or None when the title carries none ("Lowes Gift Card USD US $73")."""

    m = TITLE_TAIL_RE.search(name or "")
    return m.group("region") if m else None


# ── URL ──────────────────────────────────────────────────────────────────────────────
# A console run anywhere in the path → the R45 classifier owns the row: no PC platform,
# no region code read here (the title tail still speaks in precheck).
_CONSOLE_URL_TOKENS = frozenset({
    "xbox", "ps", "psn", "ps4", "ps5", "playstation", "nintendo", "meta", "oculus",
})
# The PC platform run: "[pc-]<platform>[-gift][-cd][-key][-pc]" as whole hyphen tokens.
# Longer alternatives first (epic-games before epic). A bare "ea" token is deliberately
# NOT a run (it is a slug word); only "ea-app" / "origin" declare EA.
_URL_RUN_RE = re.compile(
    r"-(?:pc-)?(?P<plat>steam|ea-app|origin|ubisoft-connect|uplay|battle-net|battlenet|"
    r"gog|epic-games|epic|rockstar)(?P<gift>-gift)?(?P<key>-cd-key|-key)?(?:-pc)?(?=-|$)"
)
_URL_RUN_PLATFORM = {
    "steam": "STEAM", "ea-app": "EA", "origin": "EA", "ubisoft-connect": "UBISOFT",
    "uplay": "UBISOFT", "battle-net": "BATTLENET", "battlenet": "BATTLENET", "gog": "GOG",
    "epic-games": "EPIC", "epic": "EPIC", "rockstar": "ROCKSTAR",
}
# The region-code slot right after the run. Sellable → base; forbidden → label (same
# vocabulary as the title tails / the matcher); multi-token names hyphenated.
SELLABLE_CODES = {
    "uk": "uk", "gb": "uk", "us": "us", "usa": "us", "eu": "eu", "europe": "eu",
    "global": "global", "ww": "global", "worldwide": "global",
}
FORBIDDEN_CODES = {
    "co": "COLOMBIA", "row": "ROW", "ca": "CANADA", "au": "AUSTRALIA", "na": "NORTH AMERICA",
    "tr": "TURKEY", "pl": "POLAND", "br": "BRAZIL", "mx": "MEXICO", "sg": "SINGAPORE",
    "za": "SOUTH AFRICA", "de": "GERMANY", "cis": "CIS", "asia": "ASIA", "in": "INDIA",
    "ru": "RUSSIA", "ar": "ARGENTINA", "cn": "CHINA", "jp": "JAPAN", "kr": "KOREA",
    "ua": "UKRAINE", "ph": "PHILIPPINES", "vn": "VIETNAM", "th": "THAILAND",
    "nl": "NETHERLANDS", "cl": "CHILE", "pe": "PERU", "my": "MALAYSIA", "id": "INDONESIA",
    "sea": "SOUTH EAST ASIA", "emea": "EMEA", "mena": "MENA", "latam": "LATAM",
    "latin-america": "LATIN AMERICA", "south-america": "SOUTH AMERICA",
    "north-america": "NORTH AMERICA", "south-africa": "SOUTH AFRICA",
    "middle-east": "MIDDLE EAST", "hk": "HONG KONG", "tw": "TAIWAN", "nz": "NEW ZEALAND",
    "ch": "SWITZERLAND", "fr": "FRANCE", "it": "ITALY", "es": "SPAIN", "at": "AUSTRIA",
    "ro": "ROMANIA", "pt": "PORTUGAL", "ae": "UNITED ARAB EMIRATES", "africa": "AFRICA",
    "oceania": "OCEANIA", "eastern-europe": "EASTERN EUROPE",
}
# 2-letter tokens that can follow a run without being a region code ("en" = the old
# "…-steam-en-global" language marker, MA7 — skipped, the next token is the code).
_NOT_A_CODE = frozenset({"en", "vr", "hd", "pc", "cd", "dl", "ed", "ep", "os"})


def _path_tokens(url: str) -> list[str]:
    seg = urlsplit(url or "").path.strip("/").rsplit("/", 1)[-1].lower()   # query ignored
    return [t for t in seg.split("-") if t]


def parse_url(url: str) -> tuple[str | None, str | None, bool]:
    """``(platform, code, console)`` read from the URL PATH: ``platform`` our token or
    None; ``code`` the region-code slot after the run ("us", "co", "global",
    "latin-america"; a 2-letter token unknown to both maps is returned AS IS — the caller
    fails closed on it), None when there is no run, no slot, or the slot holds an
    edition/other word; ``console`` True when a console run is present (both None then).

    The platform is trusted only when a region slot follows the run, or when the run
    carries the old "…-steam-key…" marker — a bare game-name platform word
    ("epic-chef-…") followed by a name word is not a run. The LAST run wins (the run
    follows the game slug), so "epic-chef-pc-steam-us-standard" reads STEAM."""

    tokens = _path_tokens(url)
    if not tokens:
        return None, None, False
    if any(t in _CONSOLE_URL_TOKENS for t in tokens):
        return None, None, True
    seg = "-" + "-".join(tokens)
    matches = list(_URL_RUN_RE.finditer(seg))
    if not matches:
        return None, None, False
    m = matches[-1]
    platform = _URL_RUN_PLATFORM[m.group("plat")]
    rest = [t for t in seg[m.end():].split("-") if t]
    if rest and rest[0] == "en":                       # "…-steam-en-global" (old grammar)
        rest = rest[1:]
    code: str | None = None
    if rest:
        two = "-".join(rest[:2])
        if two in FORBIDDEN_CODES:
            code = two
        elif rest[0] in SELLABLE_CODES or rest[0] in FORBIDDEN_CODES:
            code = rest[0]
        elif re.fullmatch(r"[a-z]{2}", rest[0]) and rest[0] not in _NOT_A_CODE:
            code = rest[0]                               # unknown 2-letter code → fail-closed
    if code is None and not m.group("key"):
        return None, None, False                         # no region slot, no key marker
    return platform, code, False


def url_platform(url: str) -> str | None:
    """The platform the URL run declares, or None (console run / nothing recognised)."""

    return parse_url(url)[0]


# ── hooks ────────────────────────────────────────────────────────────────────────────
def title_region(name: str) -> str | None:
    """"Ravenswatch EN United Kingdom" → "uk"; "FIFA 23 EN/PL/CS/RU/TR EU" → "eu";
    "Storebound ROW" → None (precheck skips it); no tail → None (generic scan)."""

    return SELLABLE_TAILS.get(title_tail(name) or "")


def precheck(name: str, url: str) -> str | None:
    """Fail-closed region gate, before the generic scans.

    1. A trailing region that is not sellable → ``forbidden region: <LABEL>``
       (Colombia, ROW, Canada, Netherlands, CIS…).
    2. A sellable title tail contradicted by the URL code (title "Global", URL "-co-") →
       the URL lock wins as a forbidden-region skip; two DIFFERENT sellable regions →
       an explicit contradiction skip — never a guess between the two.
    3. No title tail → the URL code alone: forbidden or unknown → ``forbidden region:
       <LABEL|CODE>``; ``us`` / ``uk`` → skip too (the generic URL scan cannot read a
       mid-slug code and would enter implicit GLOBAL — the 2026-09-11 failure);
       ``eu`` / ``global`` → None (the generic ``-eu`` / ``-global`` scan reads them).
    4. Neither (top-ups, cards…) → None, the generic scans decide."""

    tail = title_tail(name)
    if tail is not None and tail not in SELLABLE_TAILS:
        return f"forbidden region: {FORBIDDEN_TAILS[tail]}"
    _, code, _ = parse_url(url)
    if tail is not None:                                 # sellable tail
        if code is None or SELLABLE_CODES.get(code) == SELLABLE_TAILS[tail]:
            return None
        if code in SELLABLE_CODES:
            return (f"region contradiction: title says {tail.upper()}, URL says "
                    f"{code.upper()} — not entered (R46)")
        return f"forbidden region: {FORBIDDEN_CODES.get(code, code.upper())}"
    if code is None:
        return None
    if code in SELLABLE_CODES:
        if SELLABLE_CODES[code] in ("us", "uk"):
            return (f"region {code.upper()} declared only in the URL, title carries no "
                    f"region tail — not entered (R46)")
        return None
    return f"forbidden region: {FORBIDDEN_CODES.get(code, code.upper())}"


def resolve_name(name: str) -> str:
    """The title handed to AKS resolution: the "[<LANGS>] <Region>" tail peeled off
    ("Age of Empires II Definitive Edition United States" → "Age of Empires II Definitive
    Edition", "FIFA 23 EN/PL/CS/RU/TR EU" → "FIFA 23"); untouched when there is no tail."""

    return TITLE_TAIL_RE.sub("", name or "").rstrip() or name


# ── console hooks (R45, 2026-09-14) ──────────────────────────────────────────────────
# The fused Xbox run between the game slug and the region code (see the module docstring).
CONSOLE_XBOX_RUN_RE = re.compile(
    r"-xbox-(?:"
    r"(?P<oneseries>(?:xbox-)?one-series|xboxoneseries)(?P<pcw1>windows|-pc|-windows|-xbox-pc)?"
    r"|(?P<series>(?:xbox-)?series|xboxseries)(?P<pcw2>windows|-pc|-windows|-xbox-pc)?"
    r"|(?P<one>xboxone|one)(?P<pcw3>-pc|-windows)?"
    r"|(?P<pconly>pc)"
    r"|(?P<nogen>xbox-windows|xboxwindows)"
    r")-"
)
CONSOLE_PS_RUN_RE = re.compile(r"-(?:ps|psn)-(?P<gen>ps4-ps5|ps5|ps4)-|-(?P<gen2>ps4-ps5)-")
CONSOLE_NINTENDO_RUN_RE = re.compile(r"-nintendo-nintendo-switch(?P<two>-2)?-")
# The language code(s) Gamivo writes before the region tail ("Ravenswatch EN United
# Kingdom", "FIFA 23 EN/PL/CS/RU/TR EU") — stripped from the console resolve_name ONLY
# when a region word closes the title ("Kingdom Come Deliverance II Royal Edition EN
# Canada" keeps its "II"; "Final Fantasy XV Global" keeps "XV": only the ISO 639-1 list).
CONSOLE_LANG_TAIL_RE = re.compile(
    r"\s+(?:" + _LANG + r"(?:/" + _LANG + r")*)(?=\s+(?:" + _REGION_ALT + r")\s*$)"
)


def _console_run(url: str) -> tuple[tuple[str, ...] | str | None, bool]:
    """``(declaration, pc)`` of the console run in the LAST path segment: families, a skip
    reason, ``(XBOX_GENERATION_UNDECLARED,)`` for Xbox + Windows without a generation (P4,
    2026-09-25), or None (no console run)."""

    seg = "-" + urlsplit(url or "").path.rstrip("/").rsplit("/", 1)[-1].lower() + "-"
    m = CONSOLE_XBOX_RUN_RE.search(seg)
    if m:
        if m.group("pconly"):
            return SKIP_PC_ONLY, False
        if m.group("nogen"):
            # "xbox-xbox-windows": Xbox + Windows, no generation — P4 « Xbox sur les deux »
            return (XBOX_GENERATION_UNDECLARED,), True
        pc = bool(m.group("pcw1") or m.group("pcw2") or m.group("pcw3"))
        if m.group("oneseries"):
            return ("XBOX_ONE", "XBOX_SERIES"), pc
        if m.group("series"):
            return ("XBOX_SERIES",), pc
        return ("XBOX_ONE",), pc
    m = CONSOLE_PS_RUN_RE.search(seg)
    if m:
        gen = m.group("gen") or m.group("gen2")
        return {"ps4-ps5": ("PS4", "PS5"), "ps5": ("PS5",), "ps4": ("PS4",)}[gen], False
    m = CONSOLE_NINTENDO_RUN_RE.search(seg)
    if m:
        return (("SWITCH2",) if m.group("two") else ("SWITCH",)), False
    return None, False


def console_url_families(url: str) -> tuple[str, ...] | str | None:
    """The families the URL run declares ("…-xbox-xboxoneseries-uk-standard" → Xbox One +
    Series), "console: PC-only Xbox Live key (R45)" for "-xbox-pc-",
    ``(XBOX_GENERATION_UNDECLARED,)`` for "-xbox-xbox-windows-" / "-xbox-xboxwindows-" (P4),
    None otherwise."""

    return _console_run(url)[0]


def console_pc_declared(name: str, url: str) -> bool:
    """PC / Windows fused to the Xbox run ("xboxserieswindows", "-xbox-series-pc",
    "-one-series-windows", "-xbox-one-series-xbox-pc") — a Play Anywhere candidate."""

    return _console_run(url)[1]


def console_region_slot(name: str) -> str | None:
    """The region tail, verbatim ("United Kingdom", "EU", "Colombia", "ROW") — the
    shared classifier maps it to a base / forbidden label; None when there is no tail."""

    return title_tail(name)


CONFIG = MerchantConfig(
    "Gamivo",
    precheck=precheck,
    title_region=title_region,
    resolve_name=resolve_name,
    url_platform=url_platform,
    # console grammar (R45, 2026-09-14): fused URL runs, title-tail region, language tail
    console_url_families=console_url_families,
    console_pc_declared=console_pc_declared,
    console_region_slot=console_region_slot,
    console_noise=(CONSOLE_LANG_TAIL_RE,),
    notes="feed store id 51 (&store=51); title tail = region, URL run = platform (R46)",
)

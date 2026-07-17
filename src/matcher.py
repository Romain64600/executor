"""Read-only matcher (Sprint 3) — ports the skill's matching rules.

Consumes a :class:`~src.contracts.NormalizedFeed` and produces candidates +
skipped offers. It never submits; candidates are for Romain's validation.

Deterministic rules (see EXECUTOR_RULES §4), in order:
  1. categorical SKIP (console, forbidden region, currency/gift/sub, DLC, bundle,
     language restriction);
  2. detect platform, region (URL-first), edition;
  3. build AKS slug(s) from the merchant name and resolve them (200 +
     ``data-product-id`` + editions map) — read-only GET;
  4. R01 strict name match (every AKS-name word in the merchant title) and R01b
     dangerous-qualifier guard (remaster/DLC/HD… absent from the AKS name).
Doubt → SKIP. The whole module is pure except ``resolve_aks``, whose HTTP client
is injectable for tests.
"""

from __future__ import annotations

import html
import json
import re
import time
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Callable
from urllib.parse import quote, urlparse

from src.aks_env import AKS_STAFF_UA, http_get
from src.contracts import NormalizedFeed, NormalizedOffer

AKS_BUY_URL = "https://www.allkeyshop.com/blog/buy-{slug}-cd-key-compare-prices/"
# Staff anti-bot bypass UA for the resolve probes (2026-07-07): bulk runs with
# the plain browser UA get intermittently throttled, which silently flipped
# real product pages into "no AKS page" between two matcher runs. Restricted to
# allkeyshop.com — http_get refuses it for any other host (audit #4, 2026-07-08).
AKS_PROBE_UA = AKS_STAFF_UA
AKS_PROBE_DELAY_S = 0.3
# Politeness budget for the two plain GETs to difmark.com per page-verified
# offer (product page + its own top-offer API) — no staff UA bypass exists
# for third-party merchants, same courtesy as AKS_PROBE_DELAY_S.
DIFMARK_PROBE_DELAY_S = 0.3

# R30 (2026-07-16, Romain) — AKS's own site search, tried only when
# slug-guessing finds nothing. A WordPress `?s=` search is far heavier than a
# single product-page probe (confirmed live: ~15-20s, not the ~1s of a normal
# slug probe) — this is deliberately a last-resort fallback, not a first try.
AKS_SEARCH_URL = "https://www.allkeyshop.com/blog/"
AKS_SEARCH_TIMEOUT_S = 20
# Confirmed live (Romain, 2026-07-16): when the query has no good match, AKS
# pads the results with unrelated "top games" filler instead of an empty
# list — the search alone cannot tell a real hit from filler. Bounded to a
# handful of candidates (cost, not trust): trust comes from the SAME R01/R01b
# checks every guessed slug already goes through downstream, unchanged.
AKS_SEARCH_CANDIDATE_LIMIT = 3

# -- classification tables --------------------------------------------------
CONSOLE_TOKENS = ("XBOX", "PLAYSTATION", "PS4", "PS5", "PSN", "NINTENDO", "SWITCH")
# Bare short tokens (NA/OTHER/SEA) are deliberately excluded — they collide with
# ordinary title words (e.g. "Sea of Thieves"). Candidates are human-reviewed.
FORBIDDEN_REGIONS = (
    "ROW", "ROW ONLY", "AMERICAS", "ASIA", "NORTH AMERICA", "EMEA",
    "CIS", "TURKEY", "GERMANY", "EASTERN EUROPE", "MIDDLE EAST", "MENA",
    "LATAM", "SOUTH AMERICA", "RU ONLY", "CHINA", "JAPAN", "KOREA", "BRAZIL",
    "INDIA", "ARGENTINA", "RUSSIA", "AUSTRALIA",
)
# "OFFICE" and "VPN" moved to SOFTWARE_APP_TOKENS (R22, word-boundary): as
# substrings here they false-hit game titles ("The Office Quest", "…Officer…").
CATEGORY_SKIP = (
    "GIFT CARD", "WALLET", "CASH CARD", "SHARK CARD", "VOUCHER", "SUBSCRIPTION",
    "PREPAID", "SOFTWARE", "ANTIVIRUS", "POINTS", "CREDITS",
    "COINS", "GEMS", "DIAMONDS", "TOP-UP", "TOP UP", "MEMBERSHIP", "CURRENCY",
    "ACTIVATION LINK", "STEAM ACCOUNT", "STEAM GIFT CARD",
    "MICROSOFT KEY", "MICROSOFT STORE", "SEASON PASS", "STEAM PLAYER TRADE",
)
# Short in-game currency tokens (G2A.md): substring matching would false-hit
# ordinary words ("ORB" in "Absorber"), so these are word-boundary only.
# GEM singular: "Growtopia Gem Fountain" (2026-07-07) is a gem-currency item
# pack with its own AKS page — doubt goes to skip.
CURRENCY_TOKENS = ("ORB", "ORBS", "VC", "VP", "GEM")
DANGEROUS_QUALIFIERS = (
    "REMASTERED", "REMASTER", "REBOOT", "REMAKE", "REDUX", "SEASON PASS", "DLC",
    "UPGRADE", "SKIN", "SOUNDTRACK", "ARTBOOK", "DIGITAL BOOK", " HD",
    # Audit 2026-07-17 (MA3): ANNIVERSARY/DEFINITIVE were NOISE-whitelisted
    # with no backstop, so "Skyrim Anniversary Edition" entered the base-game
    # page as Standard(1). Same mechanism as REMASTERED: a title carrying the
    # word on an AKS page whose name doesn't = a different product tier. The
    # live master catalog has no stable plain numeric id for either (only the
    # per-product dropdown knows), so there is no safe EDITION_HINTS entry —
    # doubt goes to skip (G02); dedicated "… Anniversary/Definitive Edition"
    # AKS pages carry the word in their name and are unaffected.
    "ANNIVERSARY", "DEFINITIVE",
)
# Romain (2026-07-07, live correction): we NEVER enter bundles — not even
# single-game / cosmetic ones with their own AKS page — and never skins. This is
# categorical (word-boundary on the padded title), unlike the R01b qualifier
# guard which only fires when the word is absent from the AKS name: the
# Overwatch "Skin Bundle" candidate had a token-perfect AKS match and still must
# be skipped. EXECUTOR_RULES §4.3.
# CS-item wear levels (G2A.md) count as skins even when "skin" is absent from
# the title ("AK-47 | Redline (Field-Tested)").
BUNDLE_SKIN_TOKENS = (
    "BUNDLE", "BUNDLES", "SKIN", "SKINS",
    "FIELD TESTED", "MINIMAL WEAR", "FACTORY NEW", "BATTLE SCARRED", "WELL WORN",
)
# Romain (2026-07-08, live correction on "EaseUS Todo Backup Workstation"):
# software/applications are never candidates — games only. Same categorical
# word-boundary mechanism as BUNDLE_SKIN_TOKENS. Brand names plus multi-word
# product categories; deliberately NOT listed: "NERO" (the game N.E.R.O.
# exists), "AVG" (Japanese AVG genre tag on game titles), bare "OFFICE" /
# "WINDOWS" / "BACKUP" (common in game titles). Doubt goes to skip — a missed
# app still reaches the human gate, a skipped game shows up in skipped.json.
SOFTWARE_APP_TOKENS = (
    # brands
    "EASEUS", "AVAST", "NORTON", "MCAFEE", "KASPERSKY", "BITDEFENDER", "ESET",
    "CCLEANER", "AIDA64", "WINRAR", "ASHAMPOO", "CYBERLINK", "COREL", "AUTOCAD",
    "MALWAREBYTES", "IOBIT", "WONDERSHARE", "MOVAVI", "ADOBE", "GLARY",
    "NORDVPN", "EXPRESSVPN", "SURFSHARK", "CYBERGHOST",
    # product categories ("ANTIVIRUS" already in CATEGORY_SKIP as substring)
    "INTERNET SECURITY", "TOTAL SECURITY", "VPN",
    "TODO BACKUP", "DATA RECOVERY", "PARTITION MASTER",
    "DRIVER BOOSTER", "DRIVER UPDATER",
    "MICROSOFT OFFICE", "OFFICE HOME", "OFFICE 365", "OFFICE 2016",
    "OFFICE 2019", "OFFICE 2021", "OFFICE 2024",
    "WINDOWS 10", "WINDOWS 11", "WINDOWS SERVER",
)
# Merchant → required URL domain (EXECUTOR_RULES §11: a Kinguin candidate URL
# must contain kinguin.net). Only merchants with a written §11 domain rule are
# listed; a mapped merchant whose row URL sits on another host fails closed.
MERCHANT_DOMAINS = {"KINGUIN": "kinguin.net"}
# Merchant → URL substring(s) that are boilerplate noise, not a product
# signal — stripped before any text is derived from the URL (edition-from-
# slug, etc.). Difmark's product URLs all carry a literal "buy-console-
# account-" path segment regardless of what's actually sold; it is NOT a
# marker to skip the offer (Romain 2026-07-17, correcting an earlier attempt
# to treat it as a skip signal: "faut pas skip l'offre, juste pas prendre en
# compte cette partie de l'URL"). The stored/reported offer URL itself is
# never touched (EXECUTOR_RULES §4.6 URL hygiene) — only the local text used
# for signal derivation.
MERCHANT_URL_IGNORE_SUBSTRINGS = {"DIFMARK": ("buy-console-account-", "buy-console-account")}

# platform -> region key -> AKS region id (EXECUTOR_RULES §10; dropdown is truth)
REGION_IDS = {
    "STEAM": {"global": "2", "eu": "9", "us": "8", "uk": "71", "gift": "25", "gift_eu": "259"},
    "GOG": {"global": "6", "eu": "62", "us": "63", "uk": "64"},
    "UBISOFT": {"global": "50", "eu": "54", "us": "55", "uk": "52"},
    "EPIC": {"global": "80", "eu": "80eu"},
    "EA": {"global": "3", "eu": "3eu"},
    "BATTLENET": {"global": "45", "eu": "4", "us": "41", "uk": "47", "gift": "570", "gift_eu": "567"},
    # "Publisher (1)" is the GLOBAL bucket (the dropdown has no "Publisher
    # GLOBAL" label); ids read from the live session catalogs of 2026-07-07
    # and 2026-07-08 (identical). No gift mapping — publisher gifts fail closed.
    "PUBLISHER": {"global": "1", "eu": "12", "us": "13", "uk": "266"},
}
# Tokens that do NOT count as a "significant extra" word (platform / region /
# format / edition / stopwords). Used by the different-product guard.
NOISE_TOKENS = {
    "PC", "MAC", "STEAM", "GOG", "EPIC", "EA", "APP", "ORIGIN", "UPLAY", "UBISOFT",
    "CONNECT", "GAMES", "LAUNCHER", "STORE",  # "Ubisoft Connect" / "Epic Games Store"
    "BATTLE", "NET", "BATTLENET", "KEY", "KEYS", "CD", "CDKEY", "DIGITAL", "DOWNLOAD",
    "CODE", "GAME", "VERSION", "FULL", "PLATFORM", "WINDOWS", "ACTIVATION", "EDITION",
    "STANDARD", "GLOBAL", "WORLDWIDE", "WW", "EU", "EUROPE", "US", "USA", "UK", "ROW",
    "COM",  # "GOG.COM Key" tokenizes to GOG + COM
    "GIFT", "REGION", "FREE", "DELUXE", "ULTIMATE", "PREMIUM", "GOLD", "GOTY",
    "COMPLETE", "COLLECTION", "BUNDLE", "PACK", "DEFINITIVE", "REMASTERED", "REMASTER",
    "ANNIVERSARY", "THE", "OF", "AND", "A", "AN", "FOR", "TO", "WITH", "VS",
    "UNITED", "STATES",
}
PLATFORM_LABEL = {
    "STEAM": "Steam", "GOG": "GOG", "EPIC": "Epic", "EA": "EA App",
    "UBISOFT": "Ubisoft", "BATTLENET": "Battle.net", "PUBLISHER": "Publisher",
}
# AKS page "official platforms:" vocabulary for our platform tokens, used by
# the R20 cross-check. Observed live 2026-07-08 across all 27 created-offer
# pages: Steam, GoG, Epic Store, Direct Publisher, Xbox Play Anywhere,
# Nintendo eShop, Xbox. Tokens without an entry (EA, UBISOFT, …) get no page
# cross-check — merchant declaration only.
PAGE_PLATFORM_NAMES = {"STEAM": "Steam", "GOG": "GoG", "EPIC": "Epic Store"}
# ordered so specific hints win (Ultimate Collection before Ultimate/Collection)
EDITION_HINTS = (
    (r"\bULTIMATE COLLECTION\b", "Ultimate Collection", "348"),
    (r"\bGAME OF THE YEAR\b|\bGOTY\b", "GOTY", "9"),
    (r"\bDELUXE\b", "Deluxe", "7"),
    (r"\bGOLD\b", "Gold", "10"),
    (r"\bPREMIUM\b", "Premium", "34"),
    (r"\bCOMPLETE\b", "Complete", "91"),
    (r"\bULTIMATE\b", "Ultimate", "21"),
    (r"\bBUNDLE\b|\bPACK\b|\bTRILOGY\b", "Bundle", "8"),
    (r"\bCOLLECTION\b", "Collection", "98"),
    (r"\bDLC\b", "DLC", "16"),
)


# -- pure helpers -----------------------------------------------------------
def normalize_apostrophes(text: str) -> str:
    """NFKC-normalize, then fold curly quotes to ASCII `'`.

    NFKC first (Eneba escape, 2026-07-16): "Road to Empress Ⅱ" (U+2161, the
    single-codepoint Unicode Roman numeral "II") tokenized to just ROAD/TO/
    EMPRESS downstream — `tokenize`'s `[A-Z0-9']+` regex silently drops any
    character outside that class, so the sequel indicator vanished and the
    offer matched the unrelated base game "Road To Empress" instead (both in
    the R01/R01b identity checks AND in `build_slug_candidates`, which builds
    the AKS resolve URL from the same text — the wrong page was probed in
    the first place, not just wrongly approved after). NFKC is the
    standard-library, zero-dependency fix: it's specifically designed to
    decompose compatibility characters like Roman numerals into their plain
    ASCII form ("Ⅱ" → "II"). Curly quotes are NOT NFKC compatibility
    decompositions of `'` (they're canonically distinct punctuation), so the
    explicit replace stays after it.
    """

    return unicodedata.normalize("NFKC", text).replace("’", "'").replace("‘", "'")


def tokenize(name: str) -> list[str]:
    """Uppercase word tokens, apostrophes normalized, punctuation stripped."""

    cleaned = normalize_apostrophes(name).upper()
    return [t for t in re.findall(r"[A-Z0-9']+", cleaned) if t.strip("'")]


def missing_aks_words(aks_name: str, merchant_title: str) -> list[str]:
    """R01: AKS-name tokens absent from the merchant title (empty list = match)."""

    merchant = set(tokenize(merchant_title))
    return [w for w in tokenize(aks_name) if w not in merchant]


def extra_significant_words(aks_name: str, merchant_title: str) -> list[str]:
    """Merchant tokens absent from the AKS name and not platform/region/format noise.

    ANY of these signals a different or expanded product. The skill CORE floor is
    ≥2 ("titre a ≥2 mots absents du nom AKS → SKIP"; e.g. GreedFall "The Dying
    World"), tightened to ≥1 on 2026-07-07: "Offworld Trading Company -
    Interdimensional" (a DLC) slipped through with the single extra word
    "INTERDIMENSIONAL". Doubt goes to skip.
    """

    aks = set(tokenize(aks_name))
    extras: list[str] = []
    for token in tokenize(merchant_title):
        if token in aks or token in NOISE_TOKENS:
            continue
        extras.append(token)
    return extras


def dangerous_qualifier(merchant_title: str, aks_name: str) -> str | None:
    """R01b: a dangerous qualifier in the merchant title but not the AKS name."""

    mt = " " + merchant_title.upper() + " "
    an = " " + aks_name.upper() + " "
    for q in DANGEROUS_QUALIFIERS:
        if q in mt and q not in an:
            return q.strip()
    return None


def precheck_skip(offer: NormalizedOffer) -> str | None:
    """Categorical SKIPs from the merchant title/URL, before any AKS lookup."""

    domain = MERCHANT_DOMAINS.get(offer.merchant.upper())
    if domain:
        host = urlparse(offer.url).netloc.lower()
        if host != domain and not host.endswith("." + domain):
            return f"offer URL not on {domain} (merchant-domain mismatch)"
    # Gamivo encodes an English-only language lock as an '-en-' URL segment
    # ("…-steam-en-global") — a language restriction, documented in
    # EXECUTOR_RULES §4.3/§4.4 but never coded (audit 2026-07-17, MA7).
    # Scoped to gamivo.com like R29 is to Eneba: on other merchants '-en-'
    # can be a real title word (French "en").
    if "gamivo.com" in urlparse(offer.url).netloc.lower() and re.search(
        r"(?:^|-)en(?:-|$)", urlparse(offer.url).path.strip("/").lower()
    ):
        return "language restriction (Gamivo '-en-' URL marker — EN-only key)"
    padded = " " + re.sub(r"[^A-Z0-9]+", " ", offer.name.upper()) + " "
    if any(f" {t} " in padded for t in CONSOLE_TOKENS):
        return "console"
    for region in FORBIDDEN_REGIONS:
        if f" {region} " in padded:
            return f"forbidden region: {region}"
    upper = offer.name.upper()
    for cat in CATEGORY_SKIP:
        if cat in upper:
            return f"skip category: {cat}"
    for token in BUNDLE_SKIN_TOKENS:
        if f" {token} " in padded:
            return f"skip category: {token} (no bundles/skins)"
    for token in SOFTWARE_APP_TOKENS:
        if f" {token} " in padded:
            return f"skip category: {token} (software/app, not a game)"
    for token in CURRENCY_TOKENS:
        if f" {token} " in padded:
            return f"skip category: {token} (in-game currency)"
    if " DLC " in padded or " ADD ON " in padded or "DOWNLOADABLE CONTENT" in upper:
        return "DLC in title"
    if " PREORDER BONUS " in padded or " PRE ORDER BONUS " in padded:
        return "preorder bonus"
    # "Royal Grow Pass", "Battle Pass", "Game Pass"… — in-game passes are not
    # games ("Season Pass" is caught above as a category).
    if " PASS " in padded:
        return "skip category: PASS (in-game/battle pass)"
    if " + " in offer.name:
        return "possible multi-game bundle"
    if re.search(r"(?:DELUXE|GOLD|PREMIUM|ULTIMATE|COMPLETE|STANDARD|DEFINITIVE|GOTY)\s*&"
                 r"|&\s*(?:DELUXE|GOLD|PREMIUM|ULTIMATE|COMPLETE|STANDARD|DEFINITIVE|GOTY)", upper):
        return "two editions joined by '&'"
    if "LANGUAGES ONLY" in upper or "LANGUAGE ONLY" in upper:
        return "language restriction"
    if re.search(r"\b(EN|FR|ES|DE|IT|PT|CS|PL|RU)\s*/\s*(EN|FR|ES|DE|IT|PT|CS|PL|RU)\b", upper):
        return "language restriction"
    return None


# Single-word platform declarations, matched word-boundary only (audit
# 2026-07-17, MA2: bare substring turned "Gogol's Quest" into GOG). Multi-word
# declarations (EA APP, MICROSOFT STORE, …) stay separate collocations below.
_PLATFORM_WORDS = {
    "GOG": "GOG",
    "EPIC": "EPIC",
    "UBISOFT": "UBISOFT",
    "UPLAY": "UBISOFT",
    "ROCKSTAR": "ROCKSTAR",  # no REGION_IDS entry -> fail-closed skip, not Steam
    "STEAM": "STEAM",
}


def explicit_platform(title: str) -> str | None:
    """The platform the merchant DECLARES in the title, or None.

    None means detect_platform will default to STEAM — a guess, not a
    detection. R20 only trusts that guess when the AKS page's "official
    platforms" list is Steam-only.

    Audit 2026-07-17 (MA2): the old raw-substring, fixed-order checks let a
    game-name word override the merchant's declaration — "Epic Chef … Steam
    Key" returned EPIC (checked before STEAM), "Gogol's Quest Steam Key"
    returned GOG ("GOG" inside "GOGOL"). Single-word tokens are now
    word-boundary; when SEVERAL platform words appear, the one collocated
    with the key-type marker ("<PLATFORM> [CD ]KEY/GIFT/ALTERGIFT") is the
    declaration; still ambiguous → None, and the token-less path (URL prefix
    R29, page-verified R20/R27) decides fail-closed instead of a guess.
    """

    t = " " + normalize_apostrophes(title).upper() + " "
    # Multi-word declarations first — already collocational, unambiguous.
    if "EA APP" in t or "ORIGIN KEY" in t or "EA ORIGIN" in t or "ORIGIN CD KEY" in t:
        return "EA"  # R14: bare "Origin" in a game name is NOT the EA platform
    if "BATTLE.NET" in t or "BATTLENET" in t:
        return "BATTLENET"
    if "MICROSOFT STORE" in t or "MICROSOFT KEY" in t:
        # Key-type markers only: "Microsoft Flight Simulator … Steam Key" is a
        # Steam product. No REGION_IDS entry -> fail-closed skip (G2A.md).
        return "MICROSOFT"
    hits: dict[str, set[str]] = {}
    for word, platform in _PLATFORM_WORDS.items():
        if re.search(r"\b" + word + r"\b", t):
            hits.setdefault(platform, set()).add(word)
    if not hits:
        return None
    if len(hits) == 1:
        return next(iter(hits))
    keyed = {
        platform
        for platform, words in hits.items()
        for word in words
        if re.search(r"\b" + word + r"\b\s*(?:CD\s+)?(?:KEY|GIFT|ALTERGIFT)", t)
    }
    if len(keyed) == 1:
        return next(iter(keyed))
    return None  # ambiguous declaration — fail closed to the token-less path


# Eneba escape (2026-07-16): "Apothecarium: The Renaissance of Evil - Premium
# Edition" carries NO platform word anywhere in its title, so explicit_platform
# returned None and it fell into R27's token-less-title branch (correctly
# SKIPped there, since the AKS page never confirms Direct Publisher) — but
# it's genuinely Steam, and the merchant says so, just not in the title:
# Eneba's own URL convention is `eneba.com/<platform>-<slugified-name>`, a
# leading platform-prefix path segment present on every listing regardless of
# whether the title repeats it. Only prefixes this codebase already has a
# platform constant + region mapping for are recognized; console/currency/
# software prefixes (nintendo, xbox, psn, top, other, riot, …) are left
# unmapped — they're already caught by the console/currency/software-app
# categorical skips before platform detection runs.
ENEBA_URL_PLATFORM_PREFIXES = {
    "steam": "STEAM",
    "gog": "GOG",
    "epic": "EPIC",
    "uplay": "UBISOFT",
    "origin": "EA",
    "blizzard": "BATTLENET",
    "windows": "MICROSOFT",  # no REGION_IDS entry -> fail-closed skip, not Steam
}


def explicit_platform_from_url(url: str) -> str | None:
    """Eneba-only: the URL's leading platform-prefix path segment, or None."""

    if "eneba.com" not in url.lower():
        return None
    path = urlparse(url).path.strip("/").lower()
    prefix = path.split("-", 1)[0]
    return ENEBA_URL_PLATFORM_PREFIXES.get(prefix)


def detect_platform(title: str) -> str:
    return explicit_platform(title) or "STEAM"  # default; most PC keys are Steam


def _region_id(platform: str, key: str) -> str | None:
    # No silent fallback to Steam ids: an unknown platform must fail closed.
    return REGION_IDS.get(platform, {}).get(key)


def detect_region(offer: NormalizedOffer, platform: str) -> tuple[str, str | None, bool]:
    """Return (label, region_id, implicit). URL wins over title (rule Ga01).

    Gift is layered on top of the base region (Steam 25/259, Battle.net 570/567).
    Region may sit in the first parens (Driffle: "X (Europe) (PC) - …") or in a
    trailing " - REGION" suffix (G2A: "X (PC) - Steam Key - EUROPE").
    """

    # Query strings carry campaign junk (COM_GLOBAL_PB, ___currency=EUR…) that
    # would false-hit region tokens — only the path speaks for the product.
    url = strip_merchant_url_noise(offer.url, offer.merchant).lower().split("?", 1)[0]
    padded = " " + offer.name.upper() + " "
    # 'gift' must be its own URL segment (audit 2026-07-17, MA4): the bare
    # substring matched slug words like "the-gifted-rabbit" and proposed
    # GIFT(25) for a regular key.
    is_gift = (
        re.search(r"(?:^|[-/])gift(?:[-/]|$)", url) is not None
        or " GIFT " in padded
        or "GIFT)" in padded
    )
    tail = offer.name.rsplit(" - ", 1)[-1].strip().upper() if " - " in offer.name else ""

    base, label, implicit = "global", "GLOBAL", False
    if (
        "gift-eu" in url
        or re.search(r"-eu(?:[-/]|$)", url)
        or re.search(r"-europe(?:[-/]|$)", url)
        or " EU " in padded
        or "(EU)" in padded
        # bare "EUROPE" mid-title (K4G grammar: "X EUROPE Steam CD Key") —
        # audit 2026-07-17, MA8: title-side defense in depth, the URL carried
        # it in every recorded feed but the title check missed it.
        or " EUROPE " in padded
        or tail in ("EU", "EUROPE")
    ):
        base, label = "eu", "EU"
    elif "-global" in url or " GLOBAL " in padded or "(GLOBAL)" in padded or " WORLDWIDE " in padded:
        base, label = "global", "GLOBAL"
    elif re.search(r"-united-states(?:[-/]|$)", url) or tail in ("UNITED STATES", "US", "USA"):
        base, label = "us", "US"
    elif " UK " in padded or "(UK)" in padded or tail in ("UK", "UNITED KINGDOM"):
        base, label = "uk", "UK"
    else:
        # Scan ALL parenthesised groups, not only the first (audit
        # 2026-07-17, MA8): "X (PC) (Europe) - …" hid the region in the
        # second parens. First recognized region token wins.
        reg_found = ""
        for group in re.findall(r"\(([^)]+)\)", offer.name):
            reg = group.strip().upper()
            if reg in ("EU", "EUROPE", "GLOBAL", "WORLDWIDE", "WW",
                       "US", "USA", "UNITED STATES"):
                reg_found = reg
                break
        if reg_found in ("EU", "EUROPE"):
            base, label = "eu", "EU"
        elif reg_found in ("GLOBAL", "WORLDWIDE", "WW"):
            base, label = "global", "GLOBAL"
        elif reg_found in ("US", "USA", "UNITED STATES"):
            base, label = "us", "US"
        else:
            implicit = True  # Kinguin-style implicit GLOBAL

    if is_gift:
        if base == "eu":
            return ("GIFT EU", _region_id(platform, "gift_eu"), implicit)
        return ("GIFT", _region_id(platform, "gift"), implicit)
    return (label, _region_id(platform, base), implicit)


# Difmark region-lock vocabulary — confirmed live 2026-07-17 against the
# merchant's own per-offer "top-offer" API (offer_attributes[code=region]).
# Deliberately NOT the site-wide "regions" dropdown embedded on every Difmark
# page ({"value":1,"text":"Europe"}, ...): that is a residence/currency
# continent picker, a different vocabulary — a live check on the Rogue Loops
# example (product 166307, region_product_id=1) showed the dropdown mapping
# "1 -> Europe" while the actual per-offer attribute was "region": "Global".
# Decoding region_product_id through the dropdown would have silently been
# wrong. Any region text outside this map fails closed (G02, doubt → skip)
# instead of being guessed.
DIFMARK_REGION_TEXT_MAP = {
    "GLOBAL": ("GLOBAL", "global"),
    "EUROPE": ("EU", "eu"),
    "UNITED STATES": ("US", "us"),
    "UNITED KINGDOM": ("UK", "uk"),
}
# Difmark platform vocabulary — same source, same policy: only "Steam" is
# confirmed live so far (Romain 2026-07-17: "étends au platform aussi",
# after batch 1 showed 77% of the feed skipped on R27 for lacking a title
# platform token — Difmark titles are typically bare "<Name> Standard
# Edition"). Anything else fails closed rather than being guessed.
DIFMARK_PLATFORM_TEXT_MAP = {"STEAM": "STEAM"}
# AKS's own region dropdown carries a PARALLEL "Account" bucket for many
# platforms (Steam Account, Epic Account, Nintendo Account, PS4 Account,
# Xbox …, Windows account, …) — a legitimate, distinct region for
# account-delivery listings, NOT an un-enterable category (Romain
# 2026-07-17, correcting an initial assumption that a Difmark offer whose
# own `offer_name` says "Steam Account" should be skipped like an ordinary
# shared-credential resale: "je voulais que tu renseignes la région Steam
# Account quand tu vois Steam Account" — those offers ARE meant to be
# entered, just under this region instead of plain Steam).
# base region key -> AKS region id, Steam platform only (the only platform
# confirmed for Difmark so far via DIFMARK_PLATFORM_TEXT_MAP). No UK entry
# exists in the dropdown. Ids captured from a live dropdown snapshot
# 2026-07-08 (runs/20260708-081329-k4g/session_catalog.json, offer[region]
# select: "Steam Account (412)", "Steam EU Account (480)", "Steam Row
# Account (577)", "steam account us (578)") — per P06 "dropdown is truth",
# re-verify against a FRESH catalog fetch before Difmark's first real
# submit; ids drift over time like every other REGION_IDS entry.
DIFMARK_STEAM_ACCOUNT_REGION_IDS = {
    "global": "412",
    "eu": "480",
    "us": "578",
}
# detect_region/DIFMARK_REGION_TEXT_MAP produce a display label (GLOBAL/EU/
# US/UK); the Account-region lookup above is keyed by the same base region
# key used everywhere else — this reverses label back to that key.
_DIFMARK_REGION_LABEL_TO_BASE = {"GLOBAL": "global", "EU": "eu", "US": "us", "UK": "uk"}


class DifmarkPageUnreadable(RuntimeError):
    """The Difmark product page or its own 'top offer' API could not be read
    (network error or unexpected shape). Platform/region are unverifiable —
    fail closed, no fallback to the URL/title heuristic that was already
    ambiguous."""


def extract_difmark_top_offer_url(page_html: str) -> str | None:
    """Pull the 'top offer' API link Difmark itself embeds in the product
    page's SSR JSON blob, unescaped. None if the page shape is unrecognized."""

    match = re.search(r'"url_top_offer_with_get_params":"((?:[^"\\]|\\.)*)"', page_html)
    if not match:
        return None
    try:
        return json.loads('"' + match.group(1) + '"')
    except ValueError:
        return None


def parse_difmark_offer_attributes(body: str) -> dict[str, Any] | None:
    """{code: value} from a Difmark top-offer API JSON response, or None if
    the response isn't the expected shape."""

    try:
        data = json.loads(body)
    except ValueError:
        return None
    offer = data.get("offer") if isinstance(data, dict) else None
    attrs = offer.get("offer_attributes") if isinstance(offer, dict) else None
    if not isinstance(attrs, list):
        return None
    return {a["code"]: a["value"] for a in attrs if isinstance(a, dict) and "code" in a}


def parse_difmark_offer_name(body: str) -> str | None:
    """The offer's own display name from a Difmark top-offer API response —
    e.g. "Numina (Steam Account) / Region GLOBAL / Edition Standard". This is
    the only reliable account-vs-key signal for Difmark (Romain 2026-07-17):
    the AKS-feed title never carries it ("Numina Standard Edition", no
    "Account" word — confirmed live across all 658 batch-1 titles), and the
    URL's "steam-account" segment is boilerplate present on every listing
    regardless of delivery type (also confirmed: all 658 batch-1 URLs carry
    it). None if the response isn't the expected shape."""

    try:
        data = json.loads(body)
    except ValueError:
        return None
    offer = data.get("offer") if isinstance(data, dict) else None
    name = offer.get("offer_name") if isinstance(offer, dict) else None
    return name if isinstance(name, str) else None


@dataclass(frozen=True)
class DifmarkOfferAttributes:
    """Raw (upper-stripped) text off a Difmark offer's own top-offer API —
    "" when the API didn't carry that field. Mapping to our internal
    platform/region vocabulary (and the fail-closed decision on an
    unrecognized value) is the caller's job, so a recognized platform can
    still be used even when region text is unrecognized, and vice versa."""

    raw_platform: str
    raw_region: str
    offer_name: str


def resolve_difmark_offer(
    url: str, http_get_fn: Callable[..., Any] = http_get
) -> DifmarkOfferAttributes:
    """Fetch a Difmark offer's page-verified platform/region in ONE round-trip
    pair (Romain, 2026-07-17: "tu vas devoir ouvrir les pages marchands" /
    "les pages marchand, tu peux les curl" — plain GETs, no CDP/browser): the
    product URL itself, then the 'top offer' API link that page embeds.
    Raises DifmarkPageUnreadable if either fetch fails or the shape is
    unrecognized — never silently falls back to a guess."""

    if http_get_fn is http_get:
        time.sleep(DIFMARK_PROBE_DELAY_S)  # politeness budget for bulk runs
    page = http_get_fn(url, timeout=15)
    if not (page.ok and page.status == 200 and page.body):
        raise DifmarkPageUnreadable(f"product page unreadable: {page.status or page.error}")
    top_offer_url = extract_difmark_top_offer_url(page.body)
    if not top_offer_url:
        raise DifmarkPageUnreadable("no top-offer API link found on product page")
    if http_get_fn is http_get:
        time.sleep(DIFMARK_PROBE_DELAY_S)
    probe = http_get_fn(top_offer_url, timeout=15)
    if not (probe.ok and probe.status == 200 and probe.body):
        raise DifmarkPageUnreadable(f"top-offer API unreadable: {probe.status or probe.error}")
    attrs = parse_difmark_offer_attributes(probe.body)
    if not attrs:
        raise DifmarkPageUnreadable("top-offer API response has an unexpected shape")
    return DifmarkOfferAttributes(
        raw_platform=str(attrs.get("marketplace", "")).strip().upper(),
        raw_region=str(attrs.get("region", "")).strip().upper(),
        offer_name=parse_difmark_offer_name(probe.body) or "",
    )


def strip_merchant_url_noise(url: str, merchant: str) -> str:
    """Remove merchant-specific URL boilerplate before deriving ANY matching
    signal (region, edition) from the URL. Case-insensitive — never touches
    the stored/reported offer URL itself (EXECUTOR_RULES §4.6)."""

    cleaned = url
    for noise in MERCHANT_URL_IGNORE_SUBSTRINGS.get(merchant.upper(), ()):
        cleaned = re.sub(re.escape(noise), "", cleaned, flags=re.IGNORECASE)
    return cleaned


def slug_edition_text(url: str) -> str:
    """The Driffle URL slug as searchable text (rule: edition lives in the URL).

    Takes the last path segment, drops the trailing ``-p<digits>`` product id and
    any query string, and turns hyphens into spaces so EDITION_HINTS can match.
    """

    path = url.split("?", 1)[0].rstrip("/").rsplit("/", 1)[-1]
    path = re.sub(r"-[pi]\d+$", "", path)  # Driffle -p<id>, G2A -i<id>
    return re.sub(r"[^a-z0-9]+", " ", path.lower()).upper()


def detect_edition(title: str, url: str = "", merchant: str = "") -> tuple[str, str]:
    # Driffle carries the edition in the URL slug (Romain, 2026-07-07); it is the
    # canonical merchant identity, so it wins over the AKS-normalized feed title.
    cleaned_url = strip_merchant_url_noise(url, merchant)
    for source in (slug_edition_text(cleaned_url), title.upper()):
        if not source:
            continue
        for pattern, label, edition_id in EDITION_HINTS:
            if re.search(pattern, source):
                return (label, edition_id)
    return ("Standard", "1")


# Trailing platform/region/format phrases peeled off titles before slugging.
# K4G grammar is `<Product> [Edition] [Region] <Platform> CD Key` with no
# separators, so parens-stripping + dash-splitting alone leaves 404 slugs.
# Longest-first so "UBISOFT CONNECT" wins over "UBISOFT". Bare US/EU are
# deliberately absent ("Among Us"); word-boundary keeps ORIGINS ≠ ORIGIN.
_TRAILING_NOISE_PHRASES = tuple(sorted(
    {
        "CD KEY", "KEY", "STEAM GIFT", "STEAM", "GOG.COM", "GOG",
        "EPIC GAMES STORE", "EPIC GAMES", "EPIC", "EA APP", "EA PLAY",
        "EA ORIGIN", "ORIGIN", "UBISOFT CONNECT", "UPLAY", "UBISOFT",
        "BATTLE.NET", "BATTLENET", "ROCKSTAR GAMES LAUNCHER", "ROCKSTAR GAMES",
        "ROCKSTAR", "MICROSOFT STORE", "WINDOWS 11", "WINDOWS 10", "WINDOWS",
        "PC", "GIFT", "DIGITAL DOWNLOAD", "DIGITAL",
        "EUROPE & NORTH AMERICA", "EUROPE", "UNITED STATES", "UNITED KINGDOM",
        "GLOBAL", "WORLDWIDE", "USA", "UK",
        *FORBIDDEN_REGIONS,
    },
    key=len,
    reverse=True,
))
# Edition words stripped (trailing only) for the fallback slug variant.
# EDITION_HINTS vocabulary minus BUNDLE/PACK/TRILOGY/DLC: those name a
# different product, and bundle/DLC titles are hard-skipped upstream anyway.
_TRAILING_EDITION_PHRASES = (
    "ULTIMATE COLLECTION", "GAME OF THE YEAR", "GOTY", "DELUXE", "GOLD",
    "PREMIUM", "COMPLETE", "ULTIMATE", "COLLECTION", "STANDARD", "EDITION",
)

_SEPARATOR_CHARS = " \t-–—:,&|"


def _strip_trailing_phrases(text: str, phrases: tuple[str, ...]) -> str:
    changed = True
    while changed:
        changed = False
        text = text.rstrip(_SEPARATOR_CHARS)
        for phrase in phrases:
            pattern = r"(?<![A-Za-z0-9])" + re.escape(phrase) + r"\s*$"
            new = re.sub(pattern, "", text, flags=re.IGNORECASE)
            if new != text:
                text = new
                changed = True
                break
    return text


def cleaned_title(name: str) -> str:
    """Parens + trailing market noise stripped, apostrophes normalized.

    The shared first step for both slug-guessing (build_slug_candidates) and
    the AKS site-search fallback (search_aks_slugs, R30) — human-readable
    text, not yet hyphenated into a slug. "Endless Space - Disharmony"-style
    dashed subtitles are kept; only trailing platform/region/format noise is
    stripped ("PC", "Steam Key", "GLOBAL", …).
    """

    without_parens = re.sub(r"\([^)]*\)", " ", normalize_apostrophes(name)).strip()
    return _strip_trailing_phrases(without_parens, _TRAILING_NOISE_PHRASES)


def build_slug_candidates(name: str) -> list[str]:
    """Ordered AKS slug guesses, most specific first.

    Tier 1: full name, parens + trailing market noise stripped (keeps dashed
    subtitles like "Endless Space - Disharmony"). Tier 2: trailing edition
    words also stripped (edition-specific AKS pages exist, so tier 1 goes
    first). Tier 3: legacy dash-split head (Driffle/G2A "Name - Platform -
    Region" grammar). Over-stripping only costs a probe: a wrong-page 200 is
    caught by the R01 / extra-words guards downstream.
    """

    without_parens = re.sub(r"\([^)]*\)", " ", normalize_apostrophes(name)).strip()
    full = cleaned_title(name)
    head = re.split(r"\s[-–—]\s", without_parens)[0]
    head = _strip_trailing_phrases(head, _TRAILING_NOISE_PHRASES)
    bases = [
        full,
        _strip_trailing_phrases(full, _TRAILING_EDITION_PHRASES),
        head,
        _strip_trailing_phrases(head, _TRAILING_EDITION_PHRASES),
    ]
    out: list[str] = []
    for base in bases:
        base = base.lower()
        for variant in (
            re.sub(r"[^a-z0-9]+", "-", base.replace("'", "")).strip("-"),
            re.sub(r"[^a-z0-9]+", "-", base).strip("-"),
        ):
            variant = re.sub(r"-+", "-", variant)
            if variant and variant not in out:
                out.append(variant)
    return out


def aks_url(slug: str) -> str:
    return AKS_BUY_URL.format(slug=slug)


# -- AKS page extraction ----------------------------------------------------
def extract_product_id(body: str) -> str | None:
    match = re.search(r'data-product-id=["\']?(\d+)', body)
    return match.group(1) if match else None


def extract_aks_name(body: str) -> str | None:
    match = re.search(r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)', body)
    if not match:
        match = re.search(r"<title>([^<]+)</title>", body, re.IGNORECASE)
    if not match:
        return None
    # og:title comes in two grammars (both live 2026-07-07):
    #   "Buy <Name> CD Key Compare Prices"  and  "<Name> PC KEY Compare Prices".
    # Entities must be unescaped ("Exile&#039;s" tokenized to EXILE/039/S and
    # falsely failed R01).
    name = html.unescape(match.group(1))
    name = re.split(r"(?i)\bcd key\b", name)[0]
    name = re.split(r"(?i)\bcompare prices\b", name)[0]
    name = re.sub(r"(?i)^\s*buy\s+", "", name)
    # Only the exact "PC KEY" platform marker: a bare trailing "Key" can be a
    # real name ("The Key"), a bare trailing "PC" cannot.
    name = re.sub(r"(?i)\s+pc\s+key\s*$", "", name)
    name = re.sub(r"(?i)\s+pc\s*$", "", name)
    name = re.split(r"\s[|\-–]\s", name)[0]
    return name.strip() or None


def extract_editions(body: str) -> dict[str, Any]:
    match = re.search(r'"editions"\s*:\s*(\{(?:[^{}]|\{[^{}]*\})*\})', body)
    if not match:
        return {}
    try:
        return json.loads(match.group(1))
    except ValueError:
        return {}


class AksPageUnparseable(Exception):
    """A structure the page DOES carry failed to parse (markup drift).

    Distinct from absence: an absent block stays a soft () so page variants
    don't mass-abort, but a present-yet-unparseable one means AKS changed its
    serialization and every guard reading it (R25 duplicate check) would
    silently disable itself — fail closed, distinctly (audit 2026-07-17,
    MA6)."""


def extract_prices(body: str) -> tuple[dict[str, Any], ...]:
    """The AKS page's own current-offers list (its price-comparison table) —
    each entry carries ``merchantName``, ``edition``, ``region`` (R25,
    2026-07-15). This is what lets a candidate be checked against what AKS
    ALREADY shows for this exact merchant, not just against the merchant's own
    feed. Balanced-bracket regex mirrors ``extract_editions``'s balanced-brace
    one; entries are flat (no nested arrays observed) — if AKS ever nests
    them, the capture truncates and json.loads fails: that now raises
    :class:`AksPageUnparseable` instead of silently returning () and turning
    the R25 duplicate guard off (audit 2026-07-17, MA6)."""

    match = re.search(r'"prices"\s*:\s*(\[(?:[^\[\]]|\[[^\[\]]*\])*\])', body)
    if not match:
        if '"prices"' in body:
            raise AksPageUnparseable(
                "prices block present but did not match the extraction shape"
            )
        return ()
    try:
        parsed = json.loads(match.group(1))
    except ValueError as exc:
        raise AksPageUnparseable(f"prices block unparseable: {exc}") from exc
    return tuple(p for p in parsed if isinstance(p, dict))


def extract_official_platforms(body: str) -> tuple[str, ...]:
    """The AKS page's "official platforms:" list, () when absent.

    Names are page-side vocabulary ("Steam", "GoG", "Direct Publisher", …),
    comma-separated; capture stops at sentence/markup boundaries. Verified
    live 2026-07-08: present on 27/27 created-offer pages, stubs included.
    """

    match = re.search(r'official platforms?:\s*([^.<"]+)', body, re.IGNORECASE)
    if not match:
        return ()
    return tuple(p.strip() for p in match.group(1).split(",") if p.strip())


@dataclass(frozen=True)
class AksResolution:
    slug: str
    url: str
    product_id: str
    aks_name: str
    editions: dict[str, Any] = field(default_factory=dict)
    official_platforms: tuple[str, ...] = ()
    prices: tuple[dict[str, Any], ...] = ()


class AksProbeUnreliable(Exception):
    """A slug probe failed with something other than a clean 404.

    403/429/5xx/timeouts under bulk load are transient throttling, not proof
    that the product page does not exist — treating them as "no AKS page"
    makes candidate lists flap between runs. Fail closed, distinctly.
    """


class AksNameUnreadable(Exception):
    """An AKS page answered 200 with a product id but no extractable name.

    R01 (name verification) cannot run without it. Falling back to the offer
    title made every name check compare the title to itself (2026-07-07: a
    "Microsoft Store Key - UNITED STATES" offer sailed through as a
    candidate). Fail closed, distinctly.
    """


def _resolution_from_body(slug: str, url: str, body: str) -> AksResolution | None:
    """Shared extraction step for a 200 response — used by both the
    slug-guess loop and the search-fallback loop below."""

    product_id = extract_product_id(body)
    if not product_id:
        return None
    aks_name = extract_aks_name(body)
    if not aks_name:
        return None
    return AksResolution(
        slug=slug,
        url=url,
        product_id=product_id,
        aks_name=aks_name,
        editions=extract_editions(body),
        official_platforms=extract_official_platforms(body),
        prices=extract_prices(body),
    )


def search_aks_slugs(
    name: str, http_get_fn: Callable[..., Any] = http_get, limit: int = AKS_SEARCH_CANDIDATE_LIMIT
) -> list[str]:
    """AKS's own WP site search (`?s=`), as a candidate source of last resort.

    Read-only, returns SLUGS ONLY — unverified. The caller (resolve_aks) runs
    the exact same extraction as a guessed slug, and match_offer's R01/R01b
    checks are what actually decide, exactly like a guessed slug: search can
    return unrelated "top games" filler when it has no good match (confirmed
    live, Romain 2026-07-16), so a search hit is never trusted on its own.
    """

    query = cleaned_title(name)
    if not query:
        return []
    url = f"{AKS_SEARCH_URL}?s={quote(query)}"
    probe = http_get_fn(url, timeout=AKS_SEARCH_TIMEOUT_S, user_agent=AKS_PROBE_UA)
    if not (probe.ok and probe.status == 200 and probe.body):
        return []
    slugs: list[str] = []
    for slug in re.findall(r"/blog/buy-([a-z0-9-]+)-cd-key-compare-prices/", probe.body):
        if slug not in slugs:
            slugs.append(slug)
        if len(slugs) >= limit:
            break
    return slugs


def resolve_aks(name: str, http_get_fn: Callable[..., Any] = http_get) -> AksResolution | None:
    """Try each candidate slug read-only; return the first real product page.

    Falls back to search_aks_slugs (R30) only when every guessed slug comes
    back cleanly 404/410 — a transient or unreadable signal from a *guessed*
    slug still fails closed immediately, same as before; the fallback is
    "try harder before giving up", not a new correctness gate.
    """

    # Audit 2026-07-17 (MA1): the raise must be IMMEDIATE, not collected for
    # an end-of-loop check — slug tiers go from most to least specific, so a
    # throttled/unreadable answer on "some-game-deluxe-edition" shadowed by a
    # 200 on "some-game" silently resolves the wrong product tier. That is
    # exactly what the docstring always promised ("fails closed immediately")
    # and what the old collect-then-maybe-raise code did not do.
    for slug in build_slug_candidates(name):
        url = aks_url(slug)
        if http_get_fn is http_get:
            time.sleep(AKS_PROBE_DELAY_S)  # politeness budget for bulk AKS runs
        probe = http_get_fn(url, timeout=8, user_agent=AKS_PROBE_UA)
        if not (probe.ok and probe.status == 200 and probe.body):
            if probe.status not in (404, 410):
                raise AksProbeUnreliable(f"{slug} -> {probe.status or probe.error}")
            continue
        resolution = _resolution_from_body(slug, url, probe.body)
        if resolution is None:
            if not extract_product_id(probe.body):
                continue
            # Never fall back to the offer title: name checks would compare
            # the title to itself and pass anything (fail-open).
            raise AksNameUnreadable(slug)
        return resolution

    for slug in search_aks_slugs(name, http_get_fn):
        url = aks_url(slug)
        if http_get_fn is http_get:
            time.sleep(AKS_PROBE_DELAY_S)
        probe = http_get_fn(url, timeout=8, user_agent=AKS_PROBE_UA)
        if not (probe.ok and probe.status == 200 and probe.body):
            continue
        resolution = _resolution_from_body(slug, url, probe.body)
        if resolution is not None:
            return resolution
    return None


# -- results ----------------------------------------------------------------
@dataclass(frozen=True)
class Candidate:
    """One matcher-approved offer, serialized to ``candidates.json``.

    ``platform`` is one of the ``REGION_IDS`` keys — STEAM, GOG, UBISOFT,
    EPIC, EA, BATTLENET, or **PUBLISHER** (R20 revision: a token-less title
    whose AKS page lists `Direct Publisher` is a publisher key, region
    "Publisher (1)" = the GLOBAL bucket). Operators reading reports should
    expect PUBLISHER alongside the classic store platforms.
    """

    offer: NormalizedOffer
    aks_product_id: str
    aks_url: str
    aks_name: str
    platform: str
    region_label: str
    region_id: str
    edition_label: str
    edition_id: str
    region_implicit: bool = False

    @property
    def fingerprint(self) -> str:
        """Exact submission identity — a stale approval fails if any part changes."""

        return f"{self.offer.offer_id}|{self.aks_product_id}|{self.region_id}|{self.edition_id}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "fingerprint": self.fingerprint,
            "offer": self.offer.to_dict(),
            "aks_product_id": self.aks_product_id,
            "aks_url": self.aks_url,
            "aks_name": self.aks_name,
            "platform": self.platform,
            "region": {"label": self.region_label, "id": self.region_id, "implicit": self.region_implicit},
            "edition": {"label": self.edition_label, "id": self.edition_id},
        }

    def normalized_block(self, index: int) -> str:
        platform = PLATFORM_LABEL.get(self.platform, self.platform)
        implicit = " [region implicit]" if self.region_implicit else ""
        return (
            f"#{index} — {self.offer.name}\n"
            f"\U0001F3AF {self.aks_product_id} — {self.aks_name}\n"
            f"\U0001F517 {self.offer.url}\n"
            f"\U0001F3AF {self.aks_url}\n"
            f"{platform} {self.region_label}({self.region_id}), "
            f"{self.edition_label}({self.edition_id}){implicit}"
        )


def _edition_entry_name(value: Any) -> str:
    """An editions-map entry's display name — tolerates both observed shapes
    ({"name": "Deluxe", …} and a bare string)."""

    return str(value.get("name", "")) if isinstance(value, dict) else str(value)


def _dlc_edition_on_page(editions: dict[str, Any]) -> str:
    """The DLC bucket of an AKS editions map, or "" (id 16 is canonical today,
    the name match is the seatbelt if ids ever move). A truthy value means the
    product ITSELF is a DLC — its edition, regardless of any title hint."""

    for key, value in editions.items():
        name = value.get("name") if isinstance(value, dict) else str(value)
        if key == "16" or (isinstance(name, str) and name.strip().upper() == "DLC"):
            return f"{key}: {name}"
    return ""


@dataclass(frozen=True)
class SkippedOffer:
    offer: NormalizedOffer
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {"offer": self.offer.to_dict(), "reason": self.reason}


def match_offer(
    offer: NormalizedOffer,
    resolver: Callable[[str], AksResolution | None] = resolve_aks,
    difmark_offer_resolver: Callable[[str], DifmarkOfferAttributes] = resolve_difmark_offer,
) -> Candidate | SkippedOffer:
    reason = precheck_skip(offer)
    if reason:
        return SkippedOffer(offer, reason)

    is_difmark = offer.merchant.strip().upper() == "DIFMARK"
    declared_platform = explicit_platform(offer.name) or explicit_platform_from_url(offer.url)
    difmark_attrs: DifmarkOfferAttributes | None = None
    difmark_platform_verified = False
    difmark_is_account = False

    if is_difmark:
        # Romain (2026-07-17, live escape): batch 1's "candidates" were ALL
        # genuine STEAM ACCOUNT sales (full login credentials — "Account
        # Delivery: you will receive all the necessary login credentials",
        # confirmed on every sampled offer's own page) despite reporting as
        # plain "Steam". The AKS-feed title never carries the word ("Numina
        # Standard Edition") and the URL's "steam-account" segment is
        # boilerplate on every listing regardless of type — the ONLY place
        # the distinction shows up is the merchant's own per-offer
        # `offer_name` ("Numina (Steam Account) / Region GLOBAL / Edition
        # Standard"). So the page is fetched unconditionally for every
        # Difmark offer, not just when title/URL are ambiguous — it also
        # still doubles as the platform/region source in that case (batch 1
        # showed 77% of the feed skipped on R27 for lacking any title
        # platform token at all, and some Steam EUROPE offers carry no
        # region signal either).
        try:
            difmark_attrs = difmark_offer_resolver(offer.url)
        except DifmarkPageUnreadable as exc:
            return SkippedOffer(offer, f"Difmark merchant page unverifiable: {exc}")
        difmark_is_account = "ACCOUNT" in difmark_attrs.offer_name.upper()
        if declared_platform is None:
            mapped_platform = DIFMARK_PLATFORM_TEXT_MAP.get(difmark_attrs.raw_platform)
            if mapped_platform is None:
                return SkippedOffer(
                    offer, f"Difmark page platform unrecognized: {difmark_attrs.raw_platform!r}"
                )
            declared_platform = mapped_platform
            difmark_platform_verified = True

    platform = declared_platform or "STEAM"  # default — R20 verifies it below
    region_label, region_id, implicit = detect_region(offer, platform)
    if implicit and is_difmark:
        # Some Steam EUROPE offers carry no region signal in the URL or
        # title at all. Doubt still goes to skip (G02): a page/API that
        # can't be read is NOT treated as GLOBAL.
        mapped_region = DIFMARK_REGION_TEXT_MAP.get(difmark_attrs.raw_region)
        if mapped_region is None:
            return SkippedOffer(
                offer, f"Difmark page region unrecognized: {difmark_attrs.raw_region!r}"
            )
        region_label, base = mapped_region
        region_id = _region_id(platform, base)
    if is_difmark and difmark_is_account:
        # AKS's region dropdown carries a PARALLEL "Account" bucket
        # (Romain 2026-07-17: "je voulais que tu renseignes la région Steam
        # Account quand tu vois Steam Account" — enter it under THAT region,
        # never skip). Only confirmed for Steam so far, and no UK variant
        # exists in the dropdown — anything else fails closed (G02).
        base = _DIFMARK_REGION_LABEL_TO_BASE.get(region_label)
        account_region_id = (
            DIFMARK_STEAM_ACCOUNT_REGION_IDS.get(base) if platform == "STEAM" and base else None
        )
        if account_region_id is None:
            return SkippedOffer(
                offer,
                f"Difmark Account region unconfirmed for {platform}/{region_label}"
                f" (offer_name: {difmark_attrs.offer_name!r})",
            )
        region_label, region_id = f"{region_label} ACCOUNT", account_region_id
    if region_id is None:
        return SkippedOffer(offer, f"no region id for {platform}/{region_label}")

    try:
        resolution = resolver(offer.name)
    except AksProbeUnreliable as exc:
        return SkippedOffer(offer, f"AKS probe unreliable (throttled?): {exc}")
    except AksNameUnreadable as exc:
        return SkippedOffer(offer, f"AKS page name unreadable — cannot verify product (R01): {exc}")
    except AksPageUnparseable as exc:
        return SkippedOffer(
            offer, f"AKS page markup drifted — guard input unreadable (MA6): {exc}"
        )
    if resolution is None:
        return SkippedOffer(offer, "no AKS product page found (slug not 200)")

    missing = missing_aks_words(resolution.aks_name, offer.name)
    if missing:
        return SkippedOffer(offer, f"name mismatch, missing AKS words: {missing}")

    extras = extra_significant_words(resolution.aks_name, offer.name)
    if extras:
        return SkippedOffer(offer, f"different/expanded product — extra words: {extras}")

    qualifier = dangerous_qualifier(offer.name, resolution.aks_name)
    if qualifier:
        return SkippedOffer(offer, f"dangerous qualifier absent from AKS name: {qualifier}")

    # R19 (2026-07-08, DCS A-10C Warthog escape): an AKS page with an EMPTY
    # editions map is a stub record — "merchants":[],"editions":[],"prices":[],
    # "regions":[] in the page blob, zero offers. Such a page can vouch for no
    # edition at all, and it can hide a DLC: A-10C (empty map) was entered
    # Standard(1) and Romain had to fix the DB by hand, while sibling DCS
    # P-51D Mustang (populated map, DLC bucket) was correctly entered DLC(16)
    # by R18 the same run. Neither the feed row nor the page carries any other
    # deterministic edition signal → fail closed, skip with a distinct reason.
    if not resolution.editions:
        return SkippedOffer(
            offer, "AKS page carries no editions map — edition unverifiable (R19)"
        )

    # R20 (2026-07-08, Su-27 for DCS World escape): detect_platform's STEAM is
    # a DEFAULT, not a detection. "Su-27 … Key GLOBAL" carries no platform
    # token; it went in as Steam GLOBAL(2) although its AKS page says
    # "official platforms: Steam, Direct Publisher" and the key is an Eagle
    # Dynamics (publisher) key. The page's official-platforms line is the only
    # deterministic signal:
    #   - a DEFAULTED Steam is trusted only when the page is Steam-only;
    #   - revision same day (Romain: "Rentrons les en publisher"): when the
    #     page instead offers Direct Publisher, the token-less key is a
    #     publisher key — enter it as PUBLISHER (Su-27 was corrected in DB to
    #     publisher, not dropped);
    #   - an EXPLICIT title token is the merchant's declaration of what it
    #     sells (multi-platform pages are normal — Osmos: Steam+GoG page,
    #     Steam key), but when we know the page vocabulary for that token its
    #     total absence from the page is a contradiction → fail closed.
    page_platforms = {p.upper() for p in resolution.official_platforms}
    if declared_platform is None:
        if not page_platforms:
            return SkippedOffer(
                offer,
                "no platform in title and AKS page lists no official platforms"
                " — platform unverifiable (R20)",
            )
        # R27 (2026-07-15, Romain — Gameboost escape, same day as R26):
        # R26 made a token-less title default to PUBLISHER whenever the page
        # had ANY platform signal, even a Steam-only one — based on the DCS
        # P-51D Mustang / A-10C Warthog escape (Kinguin). Hours later,
        # Gameboost proved the opposite failure mode: token-less titles that
        # are genuinely Steam got defaulted to Publisher too. Romain: "il y a
        # des offres steam qu'on détecte en publisher, ça c'est seulement
        # renseigné sur la page marchand" — the merchant's own product page
        # is the only place that states the truth, and it isn't fetchable
        # (Gameboost sits behind Cloudflare — see the merchant's own notes).
        # Neither a Steam default nor a Publisher default is safe for a
        # Steam-only AKS page + a token-less title: DCS and Gameboost are the
        # same page-signal shape with opposite ground truth. The only
        # deterministic, non-guessing signal left is a page that explicitly
        # confirms Direct Publisher — anything short of that now SKIPs,
        # including the Steam-only case R26 defaulted to Publisher. DCS
        # itself reverts to skip (no signal strong enough to auto-resolve
        # it); a human enters cases like it deliberately.
        if "DIRECT PUBLISHER" not in page_platforms:
            return SkippedOffer(
                offer,
                "no platform in title and AKS page does not confirm Direct"
                " Publisher — platform unverifiable, not defaulted (R27)",
            )
        platform = "PUBLISHER"
        region_label, region_id, implicit = detect_region(offer, platform)
        if region_id is None:
            return SkippedOffer(offer, f"no region id for {platform}/{region_label}")
    else:
        page_name = PAGE_PLATFORM_NAMES.get(declared_platform)
        if page_name and page_platforms and page_name.upper() not in page_platforms:
            source = "Difmark merchant page" if difmark_platform_verified else "title"
            return SkippedOffer(
                offer,
                f"{source} says {page_name} but AKS official platforms exclude it (R20)",
            )

    # R18 as revised by Romain (2026-07-08, replacing the 07-07 skip): a title
    # can hide its DLC nature ("Exoplanets Pack" — no "DLC" word), but the
    # resolved AKS page's editions map tells the truth. DLC bucket present →
    # the product IS a DLC → enter it with the DLC edition, even when a
    # Standard bucket coexists (Brotato: Abyssal Terrors). The page overrides
    # every title hint, so the E05 fallback and the bundle-resolution guard
    # below don't apply ("Pack" in a DLC's own name is identity, not a bundle).
    if _dlc_edition_on_page(resolution.editions):
        edition_label, edition_id = "DLC", "16"
    else:
        edition_label, edition_id = detect_edition(offer.name, offer.url, offer.merchant)
        # CORE rule 4 / E05: an edition word that is part of the AKS game name is not
        # an edition — fall back to Standard. Label match alone misses hint synonyms
        # ("Trilogy" resolves to label "Bundle"), so also compare via re-detection on
        # the AKS name: same edition id there = the word is product identity.
        if edition_id != "1" and (
            edition_label.upper() in resolution.aks_name.upper()
            or detect_edition(resolution.aks_name)[1] == edition_id
        ):
            # R23 (2026-07-13, Valve Complete Pack escape): the E05 identity
            # heuristic assumes a name-embedded edition word can't be a real
            # edition, but some products genuinely sell Standard AND a
            # same-worded tier (AKS 831 "Valve Complete Pack" page carries
            # both Standard(1) and Complete Pack(92) — the generic EDITION_HINTS
            # id for "Complete" (91) isn't even this page's own id). The page's
            # own editions map is the authoritative source (already in hand,
            # zero extra requests): if it has a non-Standard entry whose name
            # contains the detected label, trust that page-verified id/label
            # over the identity collapse. No match on the page → Standard(1)
            # as before.
            #
            # Two P2 fixes on the above (2026-07-13, Romain's review of R23):
            #  - never page-verify a "Bundle" label: "we never enter bundles,
            #    ever" is absolute, so there is no legitimate page-verified
            #    Bundle tier to resurrect here. Without this guard, a page's
            #    own Bundle-named entry could either surface as a Candidate
            #    under a non-"8" page id (invisible to the `edition_id == "8"`
            #    skip below) or get skipped where the offer used to pass
            #    through as Standard pre-R23 — a silent behavior change
            #    either way, on a title that just happens to carry
            #    "Bundle"/"Pack"/"Trilogy" as part of its own product name.
            #  - pick deterministically, not by page/dict order: prefer an
            #    EXACT (case-insensitive) name match; if none, accept a
            #    substring match only when it is the SOLE one. Multiple
            #    distinct non-Standard entries tied at the same specificity
            #    is a guess, not a page-verified pick — fail closed (doubt
            #    goes to skip, G02) instead of silently taking whichever the
            #    page happened to list first.
            page_edition = None
            if edition_label != "Bundle":
                # _edition_entry_name tolerates string-valued entries the same
                # way _dlc_edition_on_page always did — a page serializing
                # {"1": "Standard"} used to crash this comprehension with
                # AttributeError and abort the whole match run (audit
                # 2026-07-17, MA5).
                on_page = [
                    (eid, _edition_entry_name(data))
                    for eid, data in resolution.editions.items()
                    if _edition_entry_name(data).strip().upper() != "STANDARD"
                    and edition_label.upper() in _edition_entry_name(data).upper()
                ]
                exact = [c for c in on_page if c[1].strip().upper() == edition_label.upper()]
                pool = exact or on_page
                if len(pool) > 1:
                    return SkippedOffer(
                        offer,
                        f"ambiguous page-verified edition for {edition_label!r}: "
                        f"{[name for _, name in pool]} (R23 P2)",
                    )
                if pool:
                    page_edition = pool[0]
            if page_edition:
                edition_id, edition_label = page_edition
            else:
                edition_label, edition_id = "Standard", "1"
        # Hard rule (Romain 2026-07-07): we NEVER enter bundles. A title that still
        # resolves to the Bundle edition after E05 (Pack/Trilogy/…) is a bundle.
        if edition_id == "8":
            return SkippedOffer(offer, "bundle edition resolved — no bundles ever")

    # R25 (2026-07-15, Romain — Kinguin/Darkwood escape): the AKS page's own
    # price-comparison table already lists every merchant currently selling
    # this exact region/edition. A candidate's own matcher run only proves
    # the offer is still live on the MERCHANT's feed; it says nothing about
    # whether AKS already has a price for it — from an earlier run, a human
    # operator working the same feed in parallel, or any other source. Check
    # the page's own current listing (already in hand, zero extra requests)
    # before ever proposing a duplicate as a "new" candidate.
    duplicate = next(
        (
            p for p in resolution.prices
            if str(p.get("merchantName", "")).strip().upper() == offer.merchant.strip().upper()
            and str(p.get("edition", "")) == edition_id
            and str(p.get("region", "")) == region_id
        ),
        None,
    )
    if duplicate is not None:
        return SkippedOffer(
            offer,
            f"{offer.merchant} already lists a price for this region/edition on AKS (R25)",
        )

    return Candidate(
        offer=offer,
        aks_product_id=resolution.product_id,
        aks_url=resolution.url,
        aks_name=resolution.aks_name,
        platform=platform,
        region_label=region_label,
        region_id=region_id,
        edition_label=edition_label,
        edition_id=edition_id,
        region_implicit=implicit,
    )


def match_feed(
    feed: NormalizedFeed,
    resolver: Callable[[str], AksResolution | None] = resolve_aks,
    difmark_offer_resolver: Callable[[str], DifmarkOfferAttributes] = resolve_difmark_offer,
    *,
    max_candidates: int = 100,
) -> tuple[list[Candidate], list[SkippedOffer]]:
    candidates: list[Candidate] = []
    skipped: list[SkippedOffer] = []
    for offer in feed.offers:
        result = match_offer(offer, resolver, difmark_offer_resolver)
        if isinstance(result, Candidate):
            if len(candidates) < max_candidates:
                candidates.append(result)
            else:
                skipped.append(SkippedOffer(offer, "candidate cap reached (max 100)"))
        else:
            skipped.append(result)
    return candidates, skipped

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
from dataclasses import dataclass, field
from typing import Any, Callable
from urllib.parse import urlparse

from src.aks_env import AKS_STAFF_UA, http_get
from src.contracts import NormalizedFeed, NormalizedOffer

AKS_BUY_URL = "https://www.allkeyshop.com/blog/buy-{slug}-cd-key-compare-prices/"
# Staff anti-bot bypass UA for the resolve probes (2026-07-07): bulk runs with
# the plain browser UA get intermittently throttled, which silently flipped
# real product pages into "no AKS page" between two matcher runs. Restricted to
# allkeyshop.com — http_get refuses it for any other host (audit #4, 2026-07-08).
AKS_PROBE_UA = AKS_STAFF_UA
AKS_PROBE_DELAY_S = 0.3

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
CATEGORY_SKIP = (
    "GIFT CARD", "WALLET", "CASH CARD", "SHARK CARD", "VOUCHER", "SUBSCRIPTION",
    "PREPAID", "SOFTWARE", "ANTIVIRUS", "OFFICE", "VPN", "POINTS", "CREDITS",
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
# Merchant → required URL domain (EXECUTOR_RULES §11: a Kinguin candidate URL
# must contain kinguin.net). Only merchants with a written §11 domain rule are
# listed; a mapped merchant whose row URL sits on another host fails closed.
MERCHANT_DOMAINS = {"KINGUIN": "kinguin.net"}

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
    return text.replace("’", "'").replace("‘", "'")


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


def explicit_platform(title: str) -> str | None:
    """The platform the merchant DECLARES in the title, or None.

    None means detect_platform will default to STEAM — a guess, not a
    detection. R20 only trusts that guess when the AKS page's "official
    platforms" list is Steam-only.
    """

    t = title.upper()
    if "GOG" in t:
        return "GOG"
    if "EPIC" in t:
        return "EPIC"
    if "UBISOFT" in t or "UPLAY" in t:
        return "UBISOFT"
    if "EA APP" in t or "ORIGIN KEY" in t or "EA ORIGIN" in t or "ORIGIN CD KEY" in t:
        return "EA"  # R14: bare "Origin" in a game name is NOT the EA platform
    if "BATTLE.NET" in t or "BATTLENET" in t:
        return "BATTLENET"
    if "ROCKSTAR" in t:
        return "ROCKSTAR"  # no REGION_IDS entry -> fail-closed skip, not Steam
    if "MICROSOFT STORE" in t or "MICROSOFT KEY" in t:
        # Key-type markers only: "Microsoft Flight Simulator … Steam Key" is a
        # Steam product. No REGION_IDS entry -> fail-closed skip (G2A.md).
        return "MICROSOFT"
    if "STEAM" in t:
        return "STEAM"
    return None


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
    url = offer.url.lower().split("?", 1)[0]
    padded = " " + offer.name.upper() + " "
    is_gift = "gift-" in url or "-gift" in url or " GIFT " in padded or "GIFT)" in padded
    tail = offer.name.rsplit(" - ", 1)[-1].strip().upper() if " - " in offer.name else ""

    base, label, implicit = "global", "GLOBAL", False
    if (
        "gift-eu" in url
        or re.search(r"-eu(?:[-/]|$)", url)
        or re.search(r"-europe(?:[-/]|$)", url)
        or " EU " in padded
        or "(EU)" in padded
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
        match = re.match(r"^[^(]*\(([^)]+)\)", offer.name)
        reg = match.group(1).strip().upper() if match else ""
        if reg in ("EU", "EUROPE"):
            base, label = "eu", "EU"
        elif reg in ("GLOBAL", "WORLDWIDE", "WW"):
            base, label = "global", "GLOBAL"
        elif reg in ("US", "USA", "UNITED STATES"):
            base, label = "us", "US"
        else:
            implicit = True  # Kinguin-style implicit GLOBAL

    if is_gift:
        if base == "eu":
            return ("GIFT EU", _region_id(platform, "gift_eu"), implicit)
        return ("GIFT", _region_id(platform, "gift"), implicit)
    return (label, _region_id(platform, base), implicit)


def slug_edition_text(url: str) -> str:
    """The Driffle URL slug as searchable text (rule: edition lives in the URL).

    Takes the last path segment, drops the trailing ``-p<digits>`` product id and
    any query string, and turns hyphens into spaces so EDITION_HINTS can match.
    """

    path = url.split("?", 1)[0].rstrip("/").rsplit("/", 1)[-1]
    path = re.sub(r"-[pi]\d+$", "", path)  # Driffle -p<id>, G2A -i<id>
    return re.sub(r"[^a-z0-9]+", " ", path.lower()).upper()


def detect_edition(title: str, url: str = "") -> tuple[str, str]:
    # Driffle carries the edition in the URL slug (Romain, 2026-07-07); it is the
    # canonical merchant identity, so it wins over the AKS-normalized feed title.
    for source in (slug_edition_text(url), title.upper()):
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
    full = _strip_trailing_phrases(without_parens, _TRAILING_NOISE_PHRASES)
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


def resolve_aks(name: str, http_get_fn: Callable[..., Any] = http_get) -> AksResolution | None:
    """Try each candidate slug read-only; return the first real product page."""

    transient: list[str] = []
    unreadable: list[str] = []
    for slug in build_slug_candidates(name):
        url = aks_url(slug)
        if http_get_fn is http_get:
            time.sleep(AKS_PROBE_DELAY_S)  # politeness budget for bulk AKS runs
        probe = http_get_fn(url, timeout=8, user_agent=AKS_PROBE_UA)
        if not (probe.ok and probe.status == 200 and probe.body):
            if probe.status not in (404, 410):
                transient.append(f"{slug} -> {probe.status or probe.error}")
            continue
        product_id = extract_product_id(probe.body)
        if not product_id:
            continue
        aks_name = extract_aks_name(probe.body)
        if not aks_name:
            # Never fall back to the offer title: name checks would compare
            # the title to itself and pass anything (fail-open).
            unreadable.append(slug)
            continue
        return AksResolution(
            slug=slug,
            url=url,
            product_id=product_id,
            aks_name=aks_name,
            editions=extract_editions(probe.body),
            official_platforms=extract_official_platforms(probe.body),
        )
    if unreadable:
        raise AksNameUnreadable("; ".join(unreadable))
    if transient:
        raise AksProbeUnreliable("; ".join(transient))
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
) -> Candidate | SkippedOffer:
    reason = precheck_skip(offer)
    if reason:
        return SkippedOffer(offer, reason)

    declared_platform = explicit_platform(offer.name)
    platform = declared_platform or "STEAM"  # default — R20 verifies it below
    region_label, region_id, implicit = detect_region(offer, platform)
    if region_id is None:
        return SkippedOffer(offer, f"no region id for {platform}/{region_label}")

    try:
        resolution = resolver(offer.name)
    except AksProbeUnreliable as exc:
        return SkippedOffer(offer, f"AKS probe unreliable (throttled?): {exc}")
    except AksNameUnreadable as exc:
        return SkippedOffer(offer, f"AKS page name unreadable — cannot verify product (R01): {exc}")
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
                " — Steam default unverifiable (R20)",
            )
        if page_platforms != {"STEAM"}:
            if "DIRECT PUBLISHER" not in page_platforms:
                return SkippedOffer(
                    offer,
                    "no platform in title and AKS page is neither Steam-only"
                    " nor publisher-direct — Steam default unverified (R20)",
                )
            platform = "PUBLISHER"
            region_label, region_id, implicit = detect_region(offer, platform)
            if region_id is None:
                return SkippedOffer(offer, f"no region id for {platform}/{region_label}")
    else:
        page_name = PAGE_PLATFORM_NAMES.get(declared_platform)
        if page_name and page_platforms and page_name.upper() not in page_platforms:
            return SkippedOffer(
                offer,
                f"title says {page_name} but AKS official platforms exclude it (R20)",
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
        edition_label, edition_id = detect_edition(offer.name, offer.url)
        # CORE rule 4 / E05: an edition word that is part of the AKS game name is not
        # an edition — fall back to Standard. Label match alone misses hint synonyms
        # ("Trilogy" resolves to label "Bundle"), so also compare via re-detection on
        # the AKS name: same edition id there = the word is product identity.
        if edition_id != "1" and (
            edition_label.upper() in resolution.aks_name.upper()
            or detect_edition(resolution.aks_name)[1] == edition_id
        ):
            edition_label, edition_id = "Standard", "1"
        # Hard rule (Romain 2026-07-07): we NEVER enter bundles. A title that still
        # resolves to the Bundle edition after E05 (Pack/Trilogy/…) is a bundle.
        if edition_id == "8":
            return SkippedOffer(offer, "bundle edition resolved — no bundles ever")

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
    *,
    max_candidates: int = 100,
) -> tuple[list[Candidate], list[SkippedOffer]]:
    candidates: list[Candidate] = []
    skipped: list[SkippedOffer] = []
    for offer in feed.offers:
        result = match_offer(offer, resolver)
        if isinstance(result, Candidate):
            if len(candidates) < max_candidates:
                candidates.append(result)
            else:
                skipped.append(SkippedOffer(offer, "candidate cap reached (max 100)"))
        else:
            skipped.append(result)
    return candidates, skipped

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
import datetime
import inspect
import json
import os
import re
import time
import unicodedata
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote, urlparse

from src.aks_env import AKS_STAFF_UA, REQUIRED_USER_AGENT, http_get
from src import candidate_contract
# [R45] (2026-09-12) console keys — the pure classifier / page grammar lives in its own
# module (no matcher import there); the matcher only wires it in (design §3).
from src.console_keys import (
    CONSOLE_PAGE_KIND,
    CONSOLE_PAGE_KINDS,
    CONSOLE_PLATFORM_LABEL,
    CONSOLE_REGION_IDS,
    CONSOLE_REGION_LABELS,
    ConsoleSignal,
    account_signal,
    classify_console,
    console_marker_in_url,
    console_page_identity,
    distinct_region_bases,
    page_platform_family,
    extract_console_pages,
    extract_page_platform,
    is_account_listing,
)
from src.contracts import NormalizedFeed, NormalizedOffer
from src.merchant_config import MerchantConfig, MerchantOfferSignals
from src.merchants.instant_gaming import (  # noqa: F401 — re-exported for tests/back-compat
    IG_PLATFORM_TEXT_MAP,
    IG_REGION_TEXT_MAP,
    IgOfferAttributes,
    IgPageUnreadable,
    extract_ig_platform,
    extract_ig_region,
    ig_offer_signals,
    resolve_ig_offer,
)
from src.merchants.difmark import (  # noqa: F401 — re-exported for tests/back-compat
    DIFMARK_ACCOUNT_PAGE_KINDS,
    DIFMARK_ACCOUNT_PLATFORMS_PENDING,
    url_account_platform as difmark_url_account_platform,
    DIFMARK_PLATFORM_TEXT_MAP,
    DIFMARK_PROBE_DELAY_S,
    DIFMARK_REGION_TEXT_MAP,
    DIFMARK_STEAM_ACCOUNT_REGION_IDS,
    DifmarkOfferAttributes,
    DifmarkPageUnreadable,
    _DIFMARK_REGION_LABEL_TO_BASE,
    difmark_product_id,
    extract_difmark_top_offer_url,
    parse_difmark_offer_attributes,
    parse_difmark_offer_name,
    resolve_difmark_offer,
)
from src.merchants import (  # noqa: F401
    difmark as _difmark,
    eneba as _eneba,
    g2a as _g2a,
    gamivo as _gamivo,
    instant_gaming as _ig,
    mmoga as _mmoga,
)
# The merchant registry moved to src/merchants/registry.py (2026-09-14, R32 / R45): the
# shared console classifier consults the merchant hooks through it, without importing the
# matcher. Re-exported here — same dict object, same function — so every caller and every
# test patching ``src.matcher.MERCHANT_CONFIGS`` in place keeps working.
from src.merchants.registry import MERCHANT_CONFIGS, merchant_config  # noqa: F401

AKS_BUY_URL = "https://www.allkeyshop.com/blog/buy-{slug}-cd-key-compare-prices/"
# Legacy page shape (pages created around 2021 — "Minecraft" & co, Romain 2026-09-10):
AKS_LEGACY_URL = "https://www.allkeyshop.com/blog/compare-and-buy-cd-key-for-digital-download-{slug}/"
# Slugs that already end with a year never get the "new" year-suffixed variants.
_SLUG_YEAR_SUFFIX_RE = re.compile(r"-(?:19|20)\d\d$")
# AKS product pages come in "kinds": the ordinary key page (`…-cd-key-…`) and,
# for account-delivery listings, a SEPARATE dedicated page per platform
# (`…-steam-account-…`, `…-ps5-account-…`, …) — a distinct AKS product with its
# own id, editions and price list (Romain 2026-07-18: "pour les offres Account,
# tu dois proposer la page Account, pas la page du jeu"; verified live —
# "Final Knight Steam Account" is product 187974, "Final Knight" the key page
# is 171000). `{kind}` is the segment between the slug and `compare-prices`.
AKS_COMPARE_URL = "https://www.allkeyshop.com/blog/buy-{slug}-{kind}-compare-prices/"
# Staff anti-bot bypass UA for the resolve probes (2026-07-07): bulk runs with
# the plain browser UA get intermittently throttled, which silently flipped
# real product pages into "no AKS page" between two matcher runs. Restricted to
# allkeyshop.com — http_get refuses it for any other host (audit #4, 2026-07-08).
AKS_PROBE_UA = AKS_STAFF_UA
# Per-probe politeness budget for bulk AKS resolves. 0.3 → 0.15 (Romain 2026-09-08): the
# serial 0.3s sleep DOMINATED match wall-clock (~69% of each 0.434s request; measured RPM
# ~138). Halving it ~doubles the resolve rate (measured ~255 RPM, ~330 theoretical with HTTP
# keep-alive) — still serial, no concurrency, so the rate rise is bounded. This IS the one
# change that raised the request rate (keep-alive alone did not); the 2026-08-28 IP ban
# is attributed by src/invariants.py to bot-like plain-Chrome health probes run before every
# stage, not to staff-UA probe rate. Runtime backstop (audit 2026-09-09): a 429 or a run of unreliable
# probes aborts the match stage fail-closed (AksThrottled) — raise the delay back if AKS
# pushes back.
AKS_PROBE_DELAY_S = 0.15
# Politeness budget for the two plain GETs to difmark.com per page-verified
# offer (product page + its own top-offer API) — no staff UA bypass exists
# for third-party merchants, same courtesy as AKS_PROBE_DELAY_S.

# R30 (2026-07-16, Romain) — AKS's own site search, tried only when
# slug-guessing finds nothing. A WordPress `?s=` search is far heavier than a
# single product-page probe (confirmed live: ~15-20s, not the ~1s of a normal
# slug probe) — this is deliberately a last-resort fallback, not a first try.
AKS_SEARCH_URL = "https://www.allkeyshop.com/blog/"
# 20 → 8 s (Romain GO 2026-09-10, "gagner du temps"): the site search answered in 22-28 s
# with an EMPTY 200 body on the new VPS — a slow answer is never a useful one, so waiting
# 20 s per attempt only fed the circuit breaker 3 × 20 s per page.
AKS_SEARCH_TIMEOUT_S = 8
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
    # §4.3 promised this since v1; never coded until DO6 (audit 2026-07-17).
    # The precheck normalizes punctuation to spaces, so "EU-NA" matches here.
    "EU NA",
    # Fable re-audit 2026-09-06 (P1): the vocabulary lagged aks_lists'
    # _BLACKLIST_REGION_KEYWORDS + _REGION_LIST, so a lock encoded only as a
    # merchant slug (…-steam-key-philippines, …-latin-america) escaped BOTH the
    # title and URL scans and detect_region fell to implicit GLOBAL — a
    # region-locked key entered worldwide, auto-approved in safe-auto sweeps.
    # The routing labels stay in phase: LATIN AMERICA / PHILIPPINES / MALAYSIA /
    # INDONESIA / THAILAND / MEXICO / CHILE / COLOMBIA / PERU / POLAND / UKRAINE
    # → Blacklist (8) via _BLACKLIST_REGION_KEYWORDS; CANADA / AFRICA → their
    # dedicated _REGION_LIST (33 / 35), exactly like AUSTRALIA above; OCEANIA has
    # no list → garder. VIETNAM is deliberately NOT here — it collides with legit
    # war-game titles ("Rising Storm 2: Vietnam", "Men of War: Vietnam"); it is
    # caught URL-slot-only via _URL_ONLY_FORBIDDEN_REGIONS below.
    "LATIN AMERICA", "PHILIPPINES", "MALAYSIA", "INDONESIA", "THAILAND",
    "MEXICO", "CHILE", "COLOMBIA", "PERU", "POLAND", "UKRAINE",
    "CANADA", "AFRICA", "OCEANIA",
    # ROW écrit en toutes lettres (2026-09-24). Le scan ne connaissait que le sigle « ROW » :
    # « Gray Zone Warfare - Tactical Edition Upgrade Steam Key: Rest of World » (CJS, scan
    # du 21/09, 7 lignes de ce type) passait le precheck et se lisait GLOBAL(2) implicite —
    # une clé ROW saisie comme mondiale. Aucune n'a été écrite (aucun approved.json ne la
    # contient). Romain, même jour : une ROW n'entre que si on prouve qu'elle s'active en
    # Europe — ce que ni le titre ni l'URL ne prouvent. Routage : comme ROW, « garder ».
    "REST OF WORLD", "REST OF THE WORLD",
)

# Forbidden regions matched ONLY in the merchant URL slot, NEVER the title — the
# name would over-skip legit games that carry the word as a theme, not a lock
# (Fable re-audit 2026-09-06). VIETNAM is the clear case: a "…-steam-key-vietnam"
# slug is a region lock, but "Rising Storm 2: Vietnam" is a game we sell.
_URL_ONLY_FORBIDDEN_REGIONS = ("VIETNAM",)

# Country-restricted gifts (§4.3 "Country Gift (CZ/RU/TR/BR/AR/IN/CN)" —
# promised since v1, never coded until DO6, audit 2026-07-17). The code must
# be ADJACENT to the GIFT word: a bare word check would false-hit English
# ("Alice IN Wonderland Steam Gift"). Runs on the padded, punctuation-
# normalized title.
_COUNTRY_GIFT_RE = re.compile(
    r" (?:CZ|RU|TR|BR|AR|IN|CN) GIFT | GIFT (?:CZ|RU|TR|BR|AR|IN|CN) "
)

# Region encoded as a BARE 2-letter code in a merchant slug (P2-6b + the "-us" base,
# audit 2026-09-02). Matched ONLY in a "region slot": immediately after a region-
# context marker (key/gift/platform) AND trailing — end of the path, optionally a
# merchant product-id suffix (G2A "-i123", Driffle "-p123"). This excludes the
# English-word collisions where the code is NOT marker-preceded ("among-us",
# "lost-in-random") or NOT trailing ("the-key-in-the-lock-steam-key"). Distinctive
# markers only — no generic "games"/"net" that would hit "The Hunger Games".
_URL_REGION_MARKER = (
    r"key|gift|code|digital|account|pc|mac|linux|steam|epic|gog|origin|uplay|"
    r"ubisoft|rockstar|windows|xbox|psn|switch"
)


def _url_region_code(url: str, code: str) -> bool:
    """True if a bare region ``code`` (e.g. 'us', 'ru') sits in a trailing region
    slot of the (lowercased, query-stripped) ``url``. See ``_URL_REGION_MARKER``."""

    return re.search(
        r"-(?:" + _URL_REGION_MARKER + r")-" + re.escape(code) + r"(?:-[ip]\d+)?/?$",
        url,
    ) is not None


# Forbidden regions that also appear as bare 2-letter slug codes → skip. "IN"
# (India) is DELIBERATELY excluded — even gated it is too collision-heavy; the full
# "-india" form is caught by the name / URL FORBIDDEN_REGIONS scan. Labels reuse the
# FORBIDDEN_REGIONS full names so suggest_target_list routes them identically.
_URL_FORBIDDEN_CODES = (
    ("ru", "RUSSIA"), ("tr", "TURKEY"), ("br", "BRAZIL"), ("ar", "ARGENTINA"),
    ("cn", "CHINA"), ("kr", "KOREA"), ("jp", "JAPAN"),
    # Fable re-audit 2026-09-06 (P1): the bare-code set lagged the full-name set.
    # Only LOW-collision country codes in a trailing region SLOT (see
    # _url_region_code) — "pl/ua/mx/ph/vn/th" are not English words in a
    # "-<marker>-<code>" slot. Skipped as too collision-heavy even when gated:
    # "id" (Indonesia vs "id"), "my" (Malaysia vs "my"), "co"/"cl"/"pe"
    # (Colombia/Chile/Peru vs common fragments) — their full-name slugs still
    # catch via the FORBIDDEN_REGIONS URL scan. "in" (India) stays excluded (v1).
    ("pl", "POLAND"), ("ua", "UKRAINE"), ("mx", "MEXICO"),
    ("ph", "PHILIPPINES"), ("vn", "VIETNAM"), ("th", "THAILAND"),
)

# "OFFICE" and "VPN" moved to SOFTWARE_APP_TOKENS (R22, word-boundary): as
# substrings here they false-hit game titles ("The Office Quest", "…Officer…").
# P2-7 (audit 2026-09-02): "SOFTWARE" dropped — a title literally containing the
# word "software" must NOT be hard-skipped here: that jumped the R31 software path
# (is_software + page-driven licence edition/region), losing software AKS actually
# sells. Software is now classified by SOFTWARE_APP_TOKENS / is_software, never this
# list. "TOP-UP" dropped as redundant (the word-boundary matcher normalizes
# punctuation, so "TOP UP" already catches "Top-Up").
CATEGORY_SKIP = (
    "GIFT CARD", "WALLET", "CASH CARD", "SHARK CARD", "VOUCHER", "SUBSCRIPTION",
    "PREPAID", "ANTIVIRUS", "POINTS", "CREDITS",
    "COINS", "MINECOINS", "GEMS", "DIAMONDS", "TOP UP", "MEMBERSHIP", "CURRENCY",
    "ACTIVATION LINK", "STEAM ACCOUNT", "STEAM GIFT CARD",
    "MICROSOFT STORE ACCOUNT", "MICROSOFT ACCOUNT", "STEAM PLAYER TRADE",
)
# [R52] (2026-09-16, audit de Romain) — "MICROSOFT KEY" / "MICROSOFT STORE" ONT QUITTÉ cette
# liste. Elles y étaient pour une raison qui n'existe plus : §4.5 disait « MICROSOFT platform
# has no region mapping → fail-closed » (`[R17]`), or `[R50]` a mappé la famille Windows 10
# (Global 246 / EU 244 / US 245 / UK 249) le matin même sur l'arbitrage de Romain (« Windows 10
# pour les jeux, microsoft software pour les logiciels »). Une clé de JEU du Microsoft Store
# n'a donc plus de motif d'être pré-refusée. Mesuré sur tous les runs sauvegardés : 164 lignes
# (34 distinctes) étaient bloquées là, dont des Call of Duty, GTA V Enhanced, Skyrim AE,
# Fallout 76, Rise of the Tomb Raider… CE QUI RESTE REFUSÉ, et pourquoi les trois entrées
# ci-dessus ont été ajoutées en échange (Romain : « en conservant les refus des cartes cadeaux,
# abonnements et recharges ») : les COMPTES ("Mafia: Definitive Edition … - Microsoft Store
# Account - GLOBAL" — le mot ACCOUNT seul n'est pas un marqueur ici, d'où les deux entrées
# explicites, sur le modèle de "STEAM ACCOUNT") et la MONNAIE de jeu ("Minecraft - 1720
# Minecoins …" — "COINS" ne matche pas le mot composé MINECOINS, les bornes de mot l'en
# empêchent). Les bundles ("… x4 Bundle", "Project + Visio Pack Bundle") restaient déjà pris
# par BUNDLE, et les logiciels Microsoft (Visual Studio, Project, Windows Enterprise) partent
# sur le chemin LOGICIEL `[R31]`, page-dirigé.
# ("SEASON PASS" left this list 2026-09-11 — it is a DLC marker now, see [R43].)


# [R43] DLC-announcing title markers (Romain GO 2026-09-11, "apprendre à ajouter les
# DLC … inclus les Season Pass"). Until now "DLC in title" / "SEASON PASS" were
# categorical pre-skips, so a DLC that ANNOUNCES itself never reached AKS resolution,
# while a DLC that hides it ("Exoplanets Pack") was entered via the page's DLC bucket
# [R18]. Measured 2026-09-11 on 12 MMOGA "(DLC)" titles: 9 resolve, by plain slug
# guessing once the marker is stripped, to their OWN AKS page and all 9 carry the DLC
# bucket (id 16); 3 have no page. So the marker is a CLASSIFIER now: the title is
# resolved with the marker stripped (strip_dlc_marker — SEASON/EXPANSION PASS stay,
# they ARE the AKS slug: hearts-of-iron-iv-expansion-pass-2), and the resolved page
# MUST carry the DLC bucket, else the offer is skipped (base game / wrong product —
# the fail-closed guard; R16 extra-words is the second net). Entered as DLC(16).
DLC_TITLE_MARKERS = ("SEASON PASS", "EXPANSION PASS", "DOWNLOADABLE CONTENT",
                     "ADD ON", "ADDON", "DLC")
# The marker words that are NOT part of an AKS product name/slug — removed before
# slug building and ignored by the extra-words guard. (SEASON/EXPANSION PASS are.)
_DLC_MARKER_STRIP_RE = re.compile(
    r"\(\s*DLCS?\s*\)|(?<![A-Za-z0-9])(?:DLCS?|ADD[- ]?ONS?|DOWNLOADABLE[- ]CONTENTS?)(?![A-Za-z0-9])",
    re.IGNORECASE,
)
_DLC_MARKER_TOKENS = frozenset({"DLC", "DLCS", "ADDON", "ADDONS"})
# The passes that ARE DLC products (own AKS page) even without a DLC tag. Any other
# "<x> Pass" ("Year 1 Pass", "Extra Pass", "X Games Pass", "Ultimate Pass") is a DLC only
# when the merchant tags it (DLC / Add-On) — measured 2026-09-11: 5 such MMOGA rows
# resolve to their own DLC-bucket page. "Battle Pass" / "Game Pass" / "Grow Pass" are
# in-game or subscription passes and stay the PASS category skip even when tagged.
_DLC_PASS_MARKERS = frozenset({"SEASON PASS", "EXPANSION PASS"})
_INGAME_PASS_RE = re.compile(r"\b(?:BATTLE|GAME|GROW|MONTHLY|WEEKLY|PREMIUM BATTLE)\s+PASS(?:ES)?\b")


def dlc_title_marker(name: str) -> str | None:
    """The DLC marker a merchant title announces ("SEASON PASS", "EXPANSION PASS",
    "DOWNLOADABLE CONTENT", "ADD ON", "ADDON", "DLC"), or None. Word-boundary on the
    padded upper title ("(DLC)", "Add-On", "Season Passes" all count); a game word
    merely containing the letters ("Addonis") does not. NFKC-normalised first, like
    ``tokenize`` (adversarial review 2026-09-11: a fullwidth "ＤＬＣ" must classify
    exactly as the token it becomes, else the R16 waiver and the R43 guard disagree)."""

    padded = " " + re.sub(r"[^A-Z0-9]+", " ", fold_accents(normalize_apostrophes(name)).upper()) + " "
    if padded.startswith(" DLC ") and not padded.startswith(" DLC PACK ") and " DLC " not in padded[5:]:
        return None      # a LEADING "DLC" is a name ("DLC Quest", a real game), not a marker
    for marker in DLC_TITLE_MARKERS:
        if f" {marker} " in padded or f" {marker}S " in padded or f" {marker}ES " in padded:
            return marker
    return None


def title_dlc_marker(offer: "NormalizedOffer", cfg: Any = None) -> str | None:
    """Le marqueur DLC d'une ligne : celui de la GRAMMAIRE du marchand d'abord
    (`MerchantConfig.dlc_marker`, [R55b] — GOG « Expansion - … »), puis les marqueurs
    génériques. Un seul point de lecture, pour que la résolution (R43), l'identité et
    l'édition (R18) voient la MÊME chose : si l'une lisait le marqueur du marchand et
    l'autre non, un DLC serait cherché comme un DLC puis rangé comme un jeu."""

    if cfg is not None and getattr(cfg, "dlc_marker", None):
        marque = cfg.dlc_marker(offer.name)
        if marque:
            return marque
    return dlc_title_marker(offer.name)


def resolution_name(offer: "NormalizedOffer", cfg: Any = None) -> str:
    """Le nom qu'on donne à la résolution AKS pour cette ligne — UNE seule définition.

    Le crochet `resolve_name` du marchand d'abord (GameSeal retire « <Store> <Delivery> -
    <RÉGION> », MMOGA la queue « <CODE> Key », Wyrel son gabarit « (PC) Standard Global »,
    GOG le préfixe « Expansion - »), puis le marqueur DLC, qui n'est pas dans le slug AKS.

    REVUE DE ROMAIN (2026-09-23) : « export SQL sans nettoyage propre au marchand —
    Zombies Invasion (PC) Steam Gift- EU part en page à créer alors que le nettoyage GameSeal
    retrouve la page ». Exact : l'export vers la liste 22 confrontait au sitemap le titre
    BRUT, pendant que le matcher cherchait le titre NETTOYÉ. Deux lectures du même nom, et
    celle qui décidait d'un déplacement sans retour était la plus pauvre. Mesuré sur les deux
    fichiers livrés le 2026-09-22 : 204 lignes dont la page existe une fois le nom nettoyé
    (Wyrel 157, Gamivo 21, Kinguin 10, GOG 7…). Le matcher et l'export lisent désormais
    CETTE fonction, et ne peuvent plus diverger."""

    if cfg is None:
        cfg = merchant_config(offer.merchant)
    nom = cfg.resolve_name(offer.name) if cfg is not None and cfg.resolve_name else offer.name
    if title_dlc_marker(offer, cfg) is not None:
        nom = strip_dlc_marker(nom)
    return nom or offer.name


# [R43] explicit DLC COLLECTIONS are bundles of DLCs — "we NEVER enter bundles" (§4.3):
# "<Game> - DLC Pack / DLC Collection / DLC Bundle", "All DLC", "Complete DLC", "DLCs".
# Direction matters: "World's Fair Pack (DLC)" is ONE content pack (PACK before DLC) and
# stays a DLC; "DLC Pack" (DLC before PACK) is a collection.
_DLC_COLLECTION_RE = re.compile(
    r"\b(?:ALL|COMPLETE|EVERY|FULL)\s+DLCS?\b|\bDLCS?\s+(?:PACK|COLLECTION|BUNDLE|SET)S?\b|\bDLCS\b"
)


def dlc_collection_marker(name: str) -> str | None:
    padded = re.sub(r"[^A-Z0-9]+", " ", fold_accents(normalize_apostrophes(name)).upper())
    m = _DLC_COLLECTION_RE.search(padded)
    return m.group(0).strip() if m else None


def strip_dlc_marker(name: str) -> str:
    """The title with its DLC / Add-On / Downloadable Content marker removed — the text
    handed to AKS resolution ("Northgard - Svardilfari Clan of the Horse (DLC)" →
    "Northgard - Svardilfari Clan of the Horse"). Season/Expansion Pass words are kept
    (they name the AKS page). Dangling separators left by the removal are trimmed;
    the identity checks keep using the raw title. NFKC-normalised like the classifier."""

    if dlc_title_marker(name) is None:
        return name                                   # nothing to strip ("DLC Quest")
    text = _DLC_MARKER_STRIP_RE.sub(" ", normalize_apostrophes(name))
    text = re.sub(r"\(\s*\)", " ", text)                       # "( )" left by "(DLC)"
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\s*[-–—:|]\s*(?=$|\s*[-–—:|])", " ", text)   # "… - - Steam" / trailing " -"
    text = re.sub(r"\s+", " ", text).strip(" -–—:|")
    return text or name


def _category_skip_pattern(cat: str) -> "re.Pattern[str]":
    """A word-boundary matcher for a CATEGORY_SKIP token (P2-7, audit 2026-09-02).

    A raw substring over-skipped valid games ("Stratagems"→GEMS, "Checkpoints"→
    POINTS, "Laptop Upgrade"→TOP UP). This matches the token as whole words —
    internal spaces accept any punctuation ("Gift-Card" ≡ "Gift Card"), and an
    OPTIONAL trailing plural ("S"/"ES") keeps plural offers caught ("Vouchers",
    "Gift Cards", "Season Passes", "Antiviruses"), which a bare word boundary would
    have regressed.

    The word boundary is LETTER-only (`[A-Z]`), NOT alphanumeric: a token glued to a
    DIGIT stays a skip ("5000Gems"/"Wallet100" — a digit adjacency is a currency
    AMOUNT, the strongest 'this is currency' signal), while a token glued to a LETTER
    is a game word and passes ("Stratagems", "Gemstone"). NB a bare currency word
    that is genuinely a game's leading word ("Gems of War") stays a fail-SAFE skip
    (doubt → skip; the "games only / no currency" hard rule forbids the reverse).

    This precheck is DEFENSE-IN-DEPTH, NOT the leak-proof games-only net (re-audit
    2026-09-05): the same LETTER boundary that keeps "Stratagems" also lets a currency/
    gift token glued to a lowercase BRAND prefix escape ("Amazon eGift Card", "Garena
    eCoins", "Free Fire eDiamonds") — precheck returns None for these. The AUTHORITATIVE
    non-game filter downstream still catches them: they resolve no AKS game page ("no
    AKS product page found") or fail R01 / the extra-words guard, so none is entered
    (verified live). Do NOT tighten this with a brand-prefix heuristic — it cannot be
    distinguished from an embedded game word ("Strata|gems") without re-breaking games."""

    core = r"[^A-Z0-9]+".join(re.escape(w) for w in re.split(r"[^A-Z0-9]+", cat) if w)
    return re.compile(r"(?<![A-Z])" + core + r"(?:E?S)?(?![A-Z])")


_CATEGORY_SKIP_RES = tuple((cat, _category_skip_pattern(cat)) for cat in CATEGORY_SKIP)
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
    "BUNDLE", "BUNDLES",
    "FIELD TESTED", "MINIMAL WEAR", "FACTORY NEW", "BATTLE SCARRED", "WELL WORN",
)
# A CS/Dota cosmetic reads "<weapon/hero> Skin(s)" — SKIN as a *noun modified by
# what it decorates*. The same word is an ordinary noun in a real game's title,
# recognisable structurally (Romain 2026-07-23, "Blacksad: Under the Skin"): SKIN
# governed by a determiner/possessive ("Under the Skin", "Second Skin", "Save
# Your Skin") is a noun phrase, not a cosmetic. ("Skinwalker" is already excluded
# by the word boundary.)
# P3-2 (audit 2026-09-02): the old leading branch `^\s*SKINS?\b` whitelisted ANY
# title starting with SKIN/SKINS — so a cosmetic pack "Skins Pack" / "Skin Pack"
# bypassed the categorical SKIN skip. Narrowed to the ONE documented SKIN-leading
# GAME ("Skin Deep"); every other "Skins …" title falls through to the skip
# (fail-closed → Blacklist; a rare other SKIN-leading game is a fail-safe over-skip).
_SKIN_NOUN_DETERMINERS = ("THE", "YOUR", "MY", "HIS", "HER", "OUR", "ITS", "OWN", "SECOND")
_SKIN_TOKEN_RE = re.compile(r"\bSKINS?\b")
_SKIN_TITLE_PHRASE_RE = re.compile(
    r"\b(?:" + "|".join(_SKIN_NOUN_DETERMINERS) + r")\s+SKINS?\b|^\s*SKIN\s+DEEP\b"
)
# Romain (2026-07-23): soundtracks / artbooks / digital books are non-game add-on
# content — never a game, routed to Blacklist. Word-boundary (same mechanism as
# BUNDLE_SKIN_TOKENS): "OST" only as a standalone word (never "Ghost"/"Frost");
# "SOUNDTRACK"/"ARTBOOK" don't collide with game words. A game bundling a
# soundtrack is already caught upstream as a bundle.
NON_GAME_CONTENT_TOKENS = (
    "SOUNDTRACK", "OST", "ARTBOOK", "ART BOOK", "DIGITAL ARTBOOK", "DIGITAL BOOK",
)
# Random/lootbox keys & items (Romain 2026-07-23, examples). The tell is
# grammatical: a lootbox uses RANDOM as an *adjective on a generic delivery noun*
# — a word that names "a thing dispensed", never a specific game's identity —
# whereas a real game uses "Random" as a *proper noun* ("Lost in Random", "Random
# Heroes"). So we fire only when RANDOM modifies a delivery noun, or is a
# quantified draw ("1x Random …"):
#   - COMMON delivery nouns (GAME/KEY/ITEM) also occur on ordinary offers, so they
#     count only *directly* after RANDOM ("Random Key"), never at a distance —
#     this is what keeps "Random Heroes Steam Key" and "Lost in Random Steam Key"
#     out (a platform word sits between Random and Key there).
#   - STRONG delivery nouns (CASE/CRATE/DROP/SPINNER/LOOT/BUNDLE/MYSTERY/BOX/GACHA)
#     are rare in normal offers, so RANDOM…<strong noun> may span a couple of
#     adjectives ("RANDOM INDIE STEAM CASE", "RANDOM VIP STEAM CASE").
# "Random … Skin" lootboxes are caught downstream by the SKIN cosmetic rule.
_LOOT_NOUN_COMMON = r"GAMES?|KEYS?|ITEMS?"
_LOOT_NOUN_STRONG = r"CASES?|CRATES?|DROPS?|SPINNERS?|LOOT|BUNDLES?|GACHA|MYSTERY|BOX(?:ES)?"
# [R45] review fix (2026-09-14): ONE console platform word may sit between RANDOM and the
# common noun — Driffle "1 Random Xbox Game (Global) (Xbox One / Xbox Series X|S) …" escaped
# the scan (under --consoles it reached resolution as "1 Random Game"). Console words ONLY:
# never STEAM / PC — "Lost in Random Steam Key" is a real game (test pinned).
_LOOT_CONSOLE_WORD = r"XBOX|PLAYSTATION|PSN|NINTENDO|SWITCH|PS4|PS5"
_RANDOM_LOOT_RE = re.compile(
    rf"\bRANDOM\s+(?:{_LOOT_NOUN_COMMON})\b"                         # Random <common noun>
    rf"|\bRANDOM\s+(?:{_LOOT_CONSOLE_WORD})\s+(?:{_LOOT_NOUN_COMMON})\b"  # Random Xbox Game (R45)
    rf"|\bRANDOM\b(?:\s+\w+){{0,2}}\s+(?:{_LOOT_NOUN_STRONG})\b"     # Random [adj adj] <strong noun>
    rf"|\b\d+\s*[xX]\s*(?:PREMIUM\s+)?RANDOM\b"                      # <N>x Random …
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
    "WINDOWS SERVER",
    "BIGASOFT", "VIDEO CONVERTER", "SCREEN RECORDER",  # media tools (R31)
)
# R31 (2026-08-11): software is NO LONGER a hard skip. SOFTWARE_APP_TOKENS is now
# a CLASSIFIER — a title match routes the offer to the SOFTWARE PATH (page-driven
# edition/region resolution, skip when unresolvable), so software AKS actually
# sells is entered with the CORRECT licence edition, never a guessed Standard.
# Page-side markers below catch software whose brand isn't listed (Romain: "va
# visiter la page AKS pour voir les régions/éditions"). Edition labels only ever
# seen on software pages — a game page never lists these.
_SOFTWARE_PAGE_EDITION_MARKERS = (
    "OEM", "RETAIL", "LTSC", "LIFETIME LICENSE", "N EDITION",
    "MICROSOFT ACCOUNT BIND", "PHONE ACTIVATION",
)
# "Windows 10/11" is software only as an OS LICENCE ("Windows 11 Pro OEM Key",
# "Windows 10 Home"); on a game key it is just a platform/compat marker and must
# NOT be filed as software (audit 2026-07-23: "Destiny 2 … Windows 10 Store Key",
# "Fallout 76 … Windows 10/11 CD Key", "Mahjong 3 … Windows 10 Store" were wrongly
# routed to Softwares). So require an OS edition/licence word directly after the
# version — never fire on the "10/11" both-versions compat form (normalises to
# "10 11") or the "… Store" Microsoft-Store delivery form.
_WINDOWS_OS_RE = re.compile(
    # A real OS licence names an edition (Pro/Home/Enterprise/…/OEM/N). Bare
    # "Windows 10 Key" is NOT an OS licence — it's a game's Microsoft-Store
    # delivery form ("Sea of Thieves Windows 10 Key") — so KEY is deliberately
    # absent from the alternation (R31 audit 2026-08-11, game-regression finding).
    r"\bWINDOWS (?:10|11)\s+(?:PRO|HOME|ENTERPRISE|EDUCATION|PROFESSIONAL|OEM|N|LICEN[CS]E)\b"
)
def is_account_offer(name: str, url: str = "", merchant: str = "") -> bool:
    """True when an explicit signal says the listing is an ACCOUNT — the merchant's own
    ``account_row`` grammar, the whole word ACCOUNT in the title, or ``account`` as a
    standalone token of the URL path (see ``console_keys.account_signal`` for the
    precedence). It is THE detector: the sort (account list 30, Romain 2026-07-23), the
    precheck, the Difmark account branch and the submitter's last guard all ask it.

    2026-09-25 : it read the TITLE only. A Gamivo account titled « Hitman 2 Global », whose
    URL alone says so (``…-xbox-one-series-account-global-standard``), was entered as an
    « Xbox One Game Code » key — and eight Difmark « [Steam/Global][OFFLINE] » accounts as
    Steam keys (the Difmark branch trusted a page wording that never says ACCOUNT)."""

    return is_account_listing(name, url, merchant)
# Merchant-specific rules (required URL domain, URL boilerplate to ignore, offer-
# page platform resolver, …) live in ONE place — the `MERCHANT_CONFIGS` registry
# below, read via `merchant_config()` (R32, 2026-08-11). Notably:
#   - Kinguin `domain=kinguin.net` (EXECUTOR_RULES §11): a candidate URL must be on
#     that host; another host fails closed.
#   - Difmark `url_ignore_substrings=("buy-console-account-",)`: the literal path
#     segment every Difmark URL carries is boilerplate, stripped before deriving
#     URL signals — NOT a skip marker (Romain 2026-07-17). The stored/reported URL
#     itself is never touched (§4.6 URL hygiene); only the local derivation text is.

# platform -> region key -> AKS region id (EXECUTOR_RULES §10; dropdown is truth)
# ``gmg_gift`` / ``gmg_gift_eu`` / ``gmg_gift_us`` (R32c, ids from Romain 2026-08-28):
# the per-platform "GMG Green Gift" region — a Green Man Gaming gift, NOT a plain gift.
# A green-gift resolves to REGION_IDS[platform][gmg_gift…]; a platform with no gmg_gift
# key (or a green-gift whose base region has no variant) fails closed. The submitter
# re-resolves these ids against the live catalog (label), so drift is handled there.
# Region buckets per platform, {base: modal option id}. The ids are read from the LIVE
# session catalog (`catalog.json`, 867 options) and verified identical across the 11 catalogs
# saved between 2026-09-10 and 2026-09-15. A base a platform lacks is ABSENT on purpose — the
# matcher then fails closed ("no region id for <PLATFORM>/<BASE>") rather than guess a
# neighbouring bucket. Audit 2026-09-16 (Romain: « verifie mieux ») closed three FALSE
# refusals where the bucket did exist but was never mapped: ROCKSTAR (global / eu / us / uk),
# EPIC (us / uk), EA (us / uk).
REGION_IDS = {
    "STEAM": {"global": "2", "eu": "9", "us": "8", "uk": "71",
              "gift": "25", "gift_eu": "259", "gift_us": "2577", "gift_uk": "2572",
              "gmg_gift": "386", "gmg_gift_eu": "387"},
    "GOG": {"global": "6", "eu": "62", "us": "63", "uk": "64"},
    "UBISOFT": {"global": "50", "eu": "54", "us": "55", "uk": "52",
                "gift": "501", "gift_eu": "504", "gift_us": "505",
                "gmg_gift": "60", "gmg_gift_eu": "58", "gmg_gift_us": "59"},
    "EPIC": {"global": "80", "eu": "80eu", "us": "80us", "uk": "805",
             "gmg_gift": "633", "gmg_gift_us": "635"},
    "EA": {"global": "3", "eu": "3eu", "us": "3us", "uk": "3uk",
           "gmg_gift": "35", "gmg_gift_eu": "36", "gmg_gift_us": "37"},
    # Rockstar: the PLAIN "Rockstar (15)" option is the GLOBAL bucket — same shape as
    # "Publisher (1)", the dropdown carries no "Rockstar GLOBAL" label (Romain 2026-09-16:
    # « pour les regions Rockstar on a toutes les regions dont tu as besoin meme la globale,
    # verifie mieux »). Before this the table held the GMG gift alone and 35 rows of the
    # saved runs fail-closed on "no region id for ROCKSTAR/GLOBAL|UK|EU" — a FALSE refusal,
    # the bucket existed all along. Locks (APAC 157, ASIA 155, EMEA 153, LATAM 154, ROW 156,
    # FRANCE 335, Germany 336, Netherlands 337, MIDDLE EAST 338) stay out: they are
    # forbidden regions, not bases.
    "ROCKSTAR": {"global": "15", "eu": "152", "us": "151", "uk": "158", "gmg_gift": "159"},
    "BATTLENET": {"global": "45", "eu": "4", "us": "41", "uk": "47",
                  "gift": "570", "gift_eu": "567", "gift_us": "568",
                  "gmg_gift": "630", "gmg_gift_eu": "631", "gmg_gift_us": "632"},
    # "Publisher (1)" is the GLOBAL bucket (the dropdown has no "Publisher
    # GLOBAL" label); ids read from the live session catalogs of 2026-07-07
    # and 2026-07-08 (identical). No gift mapping — publisher gifts fail closed.
    "PUBLISHER": {"global": "1", "eu": "12", "us": "13", "uk": "266"},
    # Microsoft Store: the dropdown carries TWO families and Romain ruled between them
    # (2026-09-16): « Windows 10 pour les jeux, microsoft software pour les logiciels ».
    # GAMES take the "Windows 10 …" family here (Global 246 / EU 244 / US 245 / UK 249;
    # locks EMEA 248, ROW 247, FR 404, WINDOWS DE 356, Windows CANADA 663 stay out).
    # SOFTWARE never reads this table: the R31 software path resolves its region from the
    # AKS PAGE's own options (``resolve_software_region``), which is where the "microsoft
    # software …" family (global 532 / eu 533 / us 534 / uk 548) already lives — so the
    # second half of the ruling needs no mapping, only this comment.
    "MICROSOFT": {"global": "246", "eu": "244", "us": "245", "uk": "249"},
}
# [R45] (2026-09-12) console FAMILIES are platforms like the PC ones: XBOX_ONE /
# XBOX_SERIES / XBOX_PC (Play Anywhere) / PS4 / PS5 / SWITCH → {base: modal bucket id}
# (catalog.json, 867 entries, identical on 9 catalogs 10-12/09 — design §0). A base a
# family lacks (PS5 has GLOBAL only) is absent → the usual "no region id" fail-closed skip.
# Merged here so validation_io / the console /api/meta accept the families automatically.
REGION_IDS.update(CONSOLE_REGION_IDS)
# Tokens that do NOT count as a "significant extra" word (platform / region /
# format / edition / stopwords). Used by the different-product guard.
NOISE_TOKENS = {
    "PC", "MAC", "STEAM", "GOG", "EPIC", "EA", "APP", "ORIGIN", "UPLAY", "UBISOFT",
    "CONNECT", "GAMES", "LAUNCHER", "STORE",  # "Ubisoft Connect" / "Epic Games Store"
    "BATTLE", "NET", "BATTLENET", "ROCKSTAR",   # ROCKSTAR added 2026-09-16, see below
    "MICROSOFT",                                # MICROSOFT added 2026-09-18, same story
    "KEY", "KEYS", "CD", "CDKEY", "DIGITAL", "DOWNLOAD",
    "CODE", "GAME", "VERSION", "FULL", "PLATFORM", "WINDOWS", "ACTIVATION", "EDITION",
    "STANDARD", "GLOBAL", "WORLDWIDE", "WW", "EU", "EUROPE", "US", "USA", "UK", "ROW",
    "COM",  # "GOG.COM Key" tokenizes to GOG + COM
    "GIFT", "REGION", "FREE", "DELUXE", "ULTIMATE", "PREMIUM", "GOLD", "GOTY",
    "COMPLETE", "COLLECTION", "BUNDLE", "PACK", "DEFINITIVE", "REMASTERED", "REMASTER",
    "ANNIVERSARY", "THE", "OF", "AND", "A", "AN", "FOR", "TO", "WITH", "VS",
    "UNITED", "STATES",
}
# ROCKSTAR (2026-09-16): every other store word was already noise here, and ROCKSTAR was
# already a trailing noise PHRASE for slug building (_TRAILING_NOISE_PHRASES) — but not a
# noise TOKEN, so the identity guard read it as a product word. It never showed because the
# region gate fired first ("no region id for ROCKSTAR/…"); mapping the Rockstar buckets the
# same day moved every Rockstar row one step further, onto "different/expanded product —
# extra words: ['ROCKSTAR']". The two fixes are one fix: without this line the region
# mapping delivers nothing. Safe on the saved corpora — no AKS product name contains the
# word (0 of every candidates.json / skipped.json of the runs kept).
# MICROSOFT (2026-09-18, audit complet) : exactement la même histoire, deux ans plus tard.
# Les seaux MICROSOFT sont mappés depuis [R50] (voir REGION_IDS ci-dessus), donc les lignes
# « (Microsoft Store) » passent la garde de région et viennent mourir un cran plus loin, sur
# « different/expanded product — extra words: ['MICROSOFT'] ». Reproduit sur Gamerall, qui
# écrit la boutique dans le titre. Même contrôle de sûreté que pour ROCKSTAR : aucun nom de
# produit AKS des corpus sauvegardés ne contient le mot (0 sur tous les candidates.json).
# ISO 639-1 language codes. A store's language marker ("Hard Bullet VR Gift EN
# Global", "… FR", …) is NOT a product differentiator (Romain 2026-09-01: "EN =
# english only … enter every language variant as the SAME product"). But a code is
# treated as noise ONLY once EVERY AKS-name token has been covered before it (see
# extra_significant_words), never while any of the game name remains after it —
# otherwise "En Garde"/"The En Garde"/"Legend En Garde" would match "Garde"-family
# names and "No Man's Sky"/"A No Man's Sky" would match "Man's Sky" (Romain audit).
# Position after the FULL game name is the signal.
LANGUAGE_TOKENS = frozenset({
    "EN", "FR", "DE", "ES", "IT", "PT", "NL", "PL", "RU", "SV", "DA", "NO", "FI",
    "CS", "SK", "HU", "RO", "BG", "HR", "SL", "ET", "LV", "LT", "EL", "TR", "UK",
    "JA", "KO", "ZH", "AR", "HE", "TH", "VI", "ID", "MS", "HI", "FA", "UA",
})
# Codes that are ALSO classic gray-market region-lock suffixes (Russia/Turkey/
# Argentina/Poland/Ukraine). A trailing bare one is AMBIGUOUS — language variant vs
# region lock — so it must NOT be swallowed as language noise (Fable re-audit
# 2026-09-06): a region-locked key would otherwise become a GLOBAL(2)/GIFT candidate
# that safe-auto auto-approves. Kept as a significant extra → the "different/expanded
# product — extra words" fail-closed skip (doubt → skip), mirroring the P2-6b URL
# decision that already rules the SAME trailing code a forbidden region.
# AUDIT DU 2026-09-18 : TH manquait. Le commentaire ci-dessus revendique de MIROITER la
# décision P2-6b (« the SAME trailing code a forbidden region ») — or `_URL_FORBIDDEN_CODES`
# porte ("th", "THAILAND") depuis le 2026-09-06 sans que celui-ci suive : le même code
# était verrou dans l'URL et langue dans le titre. Le miroir est désormais VÉRIFIÉ par
# test (LANGUAGE_TOKENS ∩ codes URL ⊆ cet ensemble), pour qu'il ne puisse plus dériver
# quand on ajoutera un code. Les autres codes de langue qui nomment aussi un pays (DE, IT,
# ES…) ne sont PAS ajoutés : le dépôt porte le faux positif documenté « (Without DE) »
# (docs/MERCHANTS.md) et « id » a été écarté comme trop collisionnel — ce sont des
# décisions prises, pas des oublis.
_REGION_LOCK_LANG_CODES = frozenset({"RU", "TR", "AR", "PL", "TH", "UA"})
PLATFORM_LABEL = {
    "STEAM": "Steam", "GOG": "GOG", "EPIC": "Epic", "EA": "EA App",
    "UBISOFT": "Ubisoft", "BATTLENET": "Battle.net", "PUBLISHER": "Publisher",
}
PLATFORM_LABEL.update(CONSOLE_PLATFORM_LABEL)     # [R45] console families (report labels)
# AKS page "official platforms:" vocabulary for our platform tokens, used by
# the R20 cross-check. Observed live 2026-07-08 across all 27 created-offer
# pages: Steam, GoG, Epic Store, Direct Publisher, Xbox Play Anywhere,
# Nintendo eShop, Xbox. Tokens without an entry (EA, UBISOFT, …) get no page
# cross-check — merchant declaration only.
# R32 (2026-08-13): extended to Ubisoft/EA/Battle.net so a merchant/page-resolved
# platform for these is cross-checked against the AKS page too (was Steam/GoG/Epic
# only → Instant Gaming Ubisoft/EA/Battle.net offers entered without page
# confirmation). AKS page vocabulary verified live: "Ubisoft Connect", "EA app",
# "Battle.net". A page that doesn't list the platform → fail-closed skip.
PAGE_PLATFORM_NAMES = {
    "STEAM": "Steam", "GOG": "GoG", "EPIC": "Epic Store",
    "UBISOFT": "Ubisoft Connect", "EA": "EA app", "BATTLENET": "Battle.net",
}
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
# Trademark / legal / abbreviation symbols stripped to a space BEFORE NFKC in
# normalize_apostrophes, so EVERY caller is covered (tokenize / cleaned_title /
# build_slug_candidates), not just tokenize. Two families (audit 2026-09-09 wording): ™ ℠
# № ℡ decompose to a LETTER sequence ("TM", "SM", "No", "TEL") that NFKC glues onto the
# adjacent word and breaks identity checks ("Company™" → "COMPANYTM"; Eneba escape +
# adversarial verify 2026-09-08); ℅ ℀ ℁ ℆ decompose to letter+slash forms ("c/o", "a/c")
# that leave stray letters behind; © ® ℗ have NO decomposition (the token regex already
# dropped them) and are stripped only so cleaned_title / the R30 search query stay clean.
# Deliberately NOT the letterlike MATH symbols (ℂ ℝ ℋ, Å U+212B) which decompose to a single
# legitimate letter, nor Roman numerals (Ⅱ U+2161 → "II", kept). № is therefore dropped, not
# read as "No" — a title spelling "№ 5" against an AKS "No. 5" would skip (R01), by design.
_NFKC_LETTER_SYMBOL_RE = re.compile(
    "[©®℀℁℅℆№℗℠℡™]")


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

    text = _NFKC_LETTER_SYMBOL_RE.sub(" ", text)
    # AUDIT DU 2026-09-18. Le repli d'accents du 2026-09-16 s'était arrêté aux scans
    # CATÉGORIELS (`fold_accents` dans `precheck_skip` / `_norm_tokens`) : ni l'identité
    # (`tokenize`, donc R01/R01b) ni le slug (`cleaned_title` → `build_slug_candidates`) ne
    # repliaient quoi que ce soit, alors que la regex `[A-Z0-9']+` de `tokenize` JETTE
    # silencieusement tout caractère hors de sa classe. « Kādomon » perdait donc son « ā » :
    # le mot devenait « K DOMON », l'identité ne matchait plus et le slug sondait la mauvaise
    # page — exactement le mode d'échec que la normalisation « Ⅱ » de 2026-07-16 avait
    # corrigé pour les numéraux. NFKD **remplace** NFKC ici : c'est un sur-ensemble strict
    # (même décomposition de compatibilité — « Ⅱ »→II, « ＤＬＣ »→DLC, « ﬁ »→fi, exigée
    # par [R28]) auquel s'ajoute la décomposition canonique, dont on retire ensuite les
    # marques combinantes. L'ordre compte : le strip des symboles reste AVANT, sinon
    # « Company™ » devient « COMPANYTM ».
    decomposed = unicodedata.normalize("NFKD", text)
    folded = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return folded.replace("’", "'").replace("‘", "'")


# [R42] Roman numerals ≡ digits (2026-09-10, MMOGA "Crusader Kings III" vs the AKS page
# "Crusader Kings 3"): a sequel number is the SAME word whichever way it is written, so
# identity checks canonicalise standalone II–XV tokens to digits and slug guessing /
# feed searches try both spellings. Deliberately NOT I, V, X, L, C, D, M — single-letter
# numerals are real title words ("V Rising", "Mega Man X", "I Am Alive"), fail-closed.
_ROMAN_TO_DIGIT = {
    "II": "2", "III": "3", "IV": "4", "VI": "6", "VII": "7", "VIII": "8", "IX": "9",
    "XI": "11", "XII": "12", "XIII": "13", "XIV": "14", "XV": "15",
}
_DIGIT_TO_ROMAN = {v: k for k, v in _ROMAN_TO_DIGIT.items()}
_NUMERAL_TOKEN_RE = re.compile(r"(?<![A-Za-z0-9])(?:II|III|IV|VI|VII|VIII|IX|XI|XII|XIII|XIV|XV|"
                               r"2|3|4|6|7|8|9|11|12|13|14|15)(?![A-Za-z0-9])", re.IGNORECASE)


def swap_numerals(text: str) -> str:
    """The same text with every standalone Roman numeral II–XV written as a digit and
    every standalone digit 2–15 written as a Roman numeral (case preserved for lowercase
    slugs). "Crusader Kings III" ↔ "Crusader Kings 3"; "Fable 2026" unchanged."""

    lower = text == text.lower()

    def _swap(m: "re.Match[str]") -> str:
        tok = m.group(0).upper()
        if tok in _ROMAN_TO_DIGIT:
            return _ROMAN_TO_DIGIT[tok]
        rom = _DIGIT_TO_ROMAN.get(tok, m.group(0))
        return rom.lower() if lower else rom

    return _NUMERAL_TOKEN_RE.sub(_swap, text)


# Les orthographes de FRANCHISE qu'AKS et les marchands écrivent différemment. Une seule
# aujourd'hui, LUE SUR SIX PAGES VIVANTES le 2026-09-20 (`warhammer-40k-darktide`,
# `…-space-marine-2`, `…-boltgun`, `…-rogue-trader`, `…-gladius-relics-of-war`,
# `…-battlesector`) : AKS écrit « Warhammer 40K », jamais « 40000 » ni « 40-000 », quand les
# marchands écrivent « Warhammer 40,000 ». Sans ce repli, la ligne échouait DEUX fois — le
# slug sondé (`warhammer-40-000-battlesector`, 404) puis, même avec la bonne page, la garde
# d'identité R01 (« missing AKS words: ['40K'] »). 12 offres du seul balayage GameSeal du
# 19/09. Comme le repli d'apostrophe, il ne peut faire matcher que des noms qui SIGNIFIENT
# la même chose : « 40,000 » et « 40K » sont deux graphies du même nombre, des deux côtés de
# la comparaison. N'y ajoute pas de règle de nombre GÉNÉRIQUE (« 10,000 » → « 10K ») sans la
# même vérification en ligne : AKS ne l'applique pas partout.
_FRANCHISE_SPELLINGS = ((re.compile(r"\b40[\s,]?000\b"), "40K"),)


def fold_franchise_spellings(text: str) -> str:
    """« Warhammer 40,000 » → « Warhammer 40K » (l'orthographe d'AKS), des DEUX côtés."""

    for pattern, canonical in _FRANCHISE_SPELLINGS:
        text = pattern.sub(canonical, text or "")
    return text


def tokenize(name: str) -> list[str]:
    """Uppercase word tokens, apostrophes normalized, punctuation stripped; standalone
    Roman numerals II–XV canonicalised to digits ([R42])."""

    # Trademark/legal symbols (™ ® © ℠ ℡ №…) are stripped inside normalize_apostrophes,
    # BEFORE its NFKC — else NFKC glues them into letters ("Company™" → "COMPANYTM").
    # AUDIT DU 2026-09-18 : l'apostrophe est REPLIÉE, comme `_identity_tokens` le fait déjà
    # pour les pages console depuis le 2026-09-14 et comme `_slug_variants` sonde déjà les
    # deux orthographes. R01 l'exigeait au caractère près, si bien qu'« Assassins Creed » ne
    # couvrait pas « Assassin's Creed » : un faux refus, jamais une fausse saisie — mais le
    # repli ne peut faire matcher que des noms qui SIGNIFIENT la même chose (même argument
    # que `fold_accents`). Les deux replis sont maintenant identiques, ils ne peuvent plus
    # diverger. La moitié « mots-outils » du constat (THE / OF / AND retirés du côté requis)
    # est volontairement ABANDONNÉE : elle, elle relâcherait l'identité.
    cleaned = fold_franchise_spellings(normalize_apostrophes(name).upper())
    out = []
    for t in re.findall(r"[A-Z0-9']+", cleaned):
        t = t.replace("'", "")
        if t:
            out.append(_ROMAN_TO_DIGIT.get(t, t))
    return out


def missing_aks_words(aks_name: str, merchant_title: str) -> list[str]:
    """R01: AKS-name tokens absent from the merchant title (empty list = match)."""

    merchant = set(tokenize(merchant_title))
    return [w for w in tokenize(aks_name) if w not in merchant]


def extra_significant_words(aks_name: str, merchant_title: str, *, dlc_page: bool = False) -> list[str]:
    """Merchant tokens absent from the AKS name and not platform/region/format noise.
    ``dlc_page`` ([R43]: the resolved page carries the DLC bucket) waives the DLC marker
    words only; by default (any other caller) they count as extras, exactly as before.

    ANY of these signals a different or expanded product. The skill CORE floor is
    ≥2 ("titre a ≥2 mots absents du nom AKS → SKIP"; e.g. GreedFall "The Dying
    World"), tightened to ≥1 on 2026-07-07: "Offworld Trading Company -
    Interdimensional" (a DLC) slipped through with the single extra word
    "INTERDIMENSIONAL". Doubt goes to skip.
    """

    aks = set(tokenize(aks_name))
    toks = tokenize(merchant_title)
    extras: list[str] = []
    aks_seen: set[str] = set()
    for i, token in enumerate(toks):
        if token in aks:
            aks_seen.add(token)
            continue
        if token in NOISE_TOKENS:
            continue
        # [R43] the DLC marker ("DLC", "Add-On", "Downloadable Content") announces the
        # product's nature, it is not a product word — waived ONLY when the caller
        # proved the resolved page IS a DLC (dlc_page: DLC bucket, match_offer), so the
        # AKS name legitimately lacks the word ("Northgard Svardilfari Clan of the
        # Horse" for "… Clan of the Horse (DLC)"). Phrase-level for the two-word forms.
        # Never unconditional (adversarial review 2026-09-11): without the proof the
        # marker stays an extra word, i.e. the pre-R43 "extra words: ['DLC']" skip.
        if dlc_page:
            if token in _DLC_MARKER_TOKENS:
                continue
            if token == "ADD" and i + 1 < len(toks) and toks[i + 1] in ("ON", "ONS"):
                continue
            if token in ("ON", "ONS") and i > 0 and toks[i - 1] == "ADD":
                continue
            if token == "DOWNLOADABLE" and i + 1 < len(toks) and toks[i + 1] in ("CONTENT", "CONTENTS"):
                continue
            if token in ("CONTENT", "CONTENTS") and i > 0 and toks[i - 1] == "DOWNLOADABLE":
                continue
        # A language code (EN/FR/…) is a language MARKER only once EVERY AKS-name token
        # has ALREADY been covered — nothing of the game name remains after it. A
        # leading article/common word is NOT enough (Romain audit 2026-09-01): "The En
        # Garde" still has GARDE to match, "Legend En Garde" still has GARDE, "A No
        # Man's Sky" still has MAN'S/SKY — so EN/NO stay significant title words, else
        # they'd falsely match "The Garde"/"Legend Garde"/"A Man's Sky". "Hard Bullet
        # VR Gift EN Global"/"Neon Beats FR Global" DO strip their trailing EN/FR
        # because all of the game name is already seen. Position AFTER the full name is
        # the signal (the earlier `seen_head` armed on the first common/noise token —
        # THE/A are NOISE — which an article could trip).
        if token in LANGUAGE_TOKENS and token not in _REGION_LOCK_LANG_CODES and aks_seen == aks:
            continue
        # [R46] (2026-09-12, Gamivo "Ravenswatch EN United Kingdom"): UNITED and STATES are
        # NOISE, KINGDOM is not — it is a game-name word ("Kingdom Come Deliverance",
        # "Total War Three Kingdoms"). It is the region phrase ONLY in the same trailing
        # position as a language code: every AKS-name token already covered AND directly
        # preceded by UNITED. A leading "United Kingdom …" with name words still to come
        # stays a significant extra (different product), exactly like a leading code.
        if token == "KINGDOM" and aks_seen == aks and i > 0 and toks[i - 1] == "UNITED":
            continue
        # "Green Gift" is G2A's Steam-gift delivery label (Romain 2026-08-27), NOT a
        # product differentiator — GIFT is already noise, so drop the GREEN that forms
        # the phrase (only when it directly precedes GIFT, so a real "…Green…" name
        # word elsewhere is still counted). Keeps a valid G2A "Green Gift Key GLOBAL"
        # from false-skipping as "extra words: ['GREEN']".
        if token == "GREEN" and i + 1 < len(toks) and toks[i + 1] == "GIFT":
            continue
        # "EA Play" is the EA app storefront/brand, not a product word — drop PLAY
        # ONLY in that exact collocation (immediately after EA). A standalone "Play"
        # elsewhere stays significant (R38 revision 2026-09-01, Romain review: PLAY
        # is no longer universal NOISE).
        if token == "PLAY" and i > 0 and toks[i - 1] == "EA":
            continue
        # "Pre-Order" / "Preorder" is a release-TIMING status, not a product word: the
        # same game/edition sold as a pre-order is the SAME product (Romain 2026-09-08,
        # Phantom Blade Zero — K4G "Digital Deluxe Edition PRE-ORDER" false-skipped
        # "extra words: ['PRE','ORDER']" while it is just the Deluxe edition pre-ordered,
        # and K4G had no Deluxe/GLOBAL nor Deluxe/EU price on the page yet). Strip the
        # "PRE ORDER" collocation and the "PREORDER" token — but NEVER when "BONUS"
        # follows: "PREORDER BONUS" is a distinct CONTENT edition, hard-skipped upstream
        # (precheck_skip, matcher.py:652). Phrase-level, not bare-token NOISE, so a real
        # "Pre"/"Order" name word elsewhere ("Order of War") stays significant.
        if token == "PREORDER" and not (i + 1 < len(toks) and toks[i + 1] == "BONUS"):
            continue
        if token == "PRE" and i + 1 < len(toks) and toks[i + 1] == "ORDER" \
                and not (i + 2 < len(toks) and toks[i + 2] == "BONUS"):
            continue
        if token == "ORDER" and i > 0 and toks[i - 1] == "PRE" \
                and not (i + 1 < len(toks) and toks[i + 1] == "BONUS"):
            continue
        extras.append(token)
    return extras


# [R44] (R43 dry-run 2026-09-11): a REGION phrase that is part of the AKS PRODUCT NAME
# is identity, not a lock — "Age of Empires III Definitive Edition - United States
# Civilization (DLC)" carries "-united-states-" in its merchant slug and detect_region
# read it as US (a GLOBAL DLC would have been entered US-locked). The title/URL scan
# cannot know the product name; match_offer re-checks the detected label against the
# resolved page name and SKIPS (fail-closed, never a guessed region) — unless the
# merchant's own title grammar declared the region (MMOGA "… US Key" is authoritative).
# "GLOBAL" is not listed: a "Worldwide" name word yields the default anyway.
_REGION_IDENTITY_PHRASES = {
    "US": ("UNITED STATES", "USA"),
    "UK": ("UNITED KINGDOM",),
    "EU": ("EUROPE",),
}


def region_phrase_in_aks_name(region_label: str, aks_name: str) -> str | None:
    """The region phrase of ``region_label`` that also appears, as whole words, in the
    AKS product name — or None (the common case)."""

    padded = " " + re.sub(r"[^A-Z0-9]+", " ", fold_accents(aks_name).upper()) + " "
    for phrase in _REGION_IDENTITY_PHRASES.get(region_label, ()):
        if f" {phrase} " in padded:
            return phrase
    return None


# [R43] qualifiers whose "absent from the AKS name" alarm is answered by the PAGE's
# nature: a DLC-bucket page IS the DLC / season pass the title announces, even when
# its name omits the word ("Northgard Svardilfari Clan of the Horse").
_DLC_PAGE_QUALIFIERS = frozenset({"SEASON PASS", "DLC"})


def dangerous_qualifier(merchant_title: str, aks_name: str, *, dlc_page: bool = False) -> str | None:
    """R01b: a dangerous qualifier in the merchant title but not the AKS name.
    ``dlc_page`` (the resolved page carries the DLC bucket, [R43]) waives the DLC /
    SEASON PASS qualifiers only — a remaster/HD/anniversary word stays a skip."""

    mt = " " + merchant_title.upper() + " "
    an = " " + aks_name.upper() + " "
    for q in DANGEROUS_QUALIFIERS:
        if dlc_page and q in _DLC_PAGE_QUALIFIERS:
            continue
        if q in mt and q not in an:
            return q.strip()
    return None


# Marqueurs de région VENDABLE, tels qu'un marchand les écrit dans son créneau. Servent au
# départage ci-dessous ; volontairement courts — on ne cherche pas à LIRE la région ici,
# seulement à savoir qu'une région vendable a été déclarée APRÈS un nom de pays.
_SELLABLE_REGION_WORDS = (
    "GLOBAL", "WORLDWIDE", "WW", "EUROPE", "EU", "USA", "US", "UK",
    "UNITED STATES", "UNITED KINGDOM",
)


def _forbidden_region_in(padded: str) -> str | None:
    """Le nom de pays qui VERROUILLE ce texte, ou None.

    AUDIT DU 2026-09-18 (P1). Le balayage était ``if f" {region} " in padded`` sur le texte
    ENTIER : tout jeu dont le NOM contient China / India / Japan / Ukraine / Poland… était
    refusé « forbidden region: <PAYS> », puis routé par ``suggest_target_list`` vers la
    Blacklist (8). Reproduit sur cinq lignes G2A réelles, toutes GLOBAL dans le titre ET dans
    l'URL : « Assassin's Creed Chronicles: China … GLOBAL », « Crusader Kings II: Rajas of
    India … GLOBAL », « Cities: Skylines … Modern Japan … GLOBAL », « Ukraine War Stories …
    GLOBAL », « Civilization VI - Poland Civilization and Scenario Pack … GLOBAL ». Dans un
    sweep ``--triage --move-execute``, chaque page s'auto-autorise ([R36], §14) et
    ``is_blacklist_label`` fait sauter la vérification présent-sur-cible : des jeux vendables
    sortaient physiquement du feed de travail vers la Blacklist, sans revue et sans preuve.

    Le départage est celui que les marchands écrivent réellement : **la région est la DERNIÈRE
    chose déclarée**. Un nom de pays suivi, plus loin dans le même texte, d'un marqueur
    vendable est donc du NOM DE PRODUIT. Ce qui reste refusé, et doit l'être : « … Steam Key
    BRAZIL », « Hades RUSSIA PC Steam CD Key », et — c'est le point qui protège le P1 du
    2026-09-06 — « Cyberpunk 2077 Global Steam Key BRAZIL », où le verrou vient APRÈS le mot
    vendable. On ne retire AUCUN pays de FORBIDDEN_REGIONS : le verrou dans le slug reste
    attrapé, et les deux scans (titre et URL) gardent leur défense en profondeur."""

    # La DERNIÈRE occurrence, pas la première (Romain, 2026-09-19). Avec `find`, un verrou
    # RÉPÉTÉ disparaissait : « Assassin's Creed Chronicles China Global Steam Key CHINA »
    # s'arrêtait au CHINA du NOM DU JEU, voyait GLOBAL après lui, et concluait « nom de
    # produit » — alors que le second CHINA, lui, est bien le créneau de région. Une clé
    # verrouillée Chine entrait en GLOBAL(2) chez Kinguin comme chez Gamivo. La règle dit
    # « la région est la dernière chose déclarée » : il faut donc partir de la dernière.
    best_region, best_at = None, -1
    for region in FORBIDDEN_REGIONS:
        at = padded.rfind(f" {region} ")
        if at > best_at:
            best_region, best_at = region, at
    if best_region is None:
        return None
    after = best_at + len(best_region)
    for word in _SELLABLE_REGION_WORDS:
        if padded.find(f" {word} ", after) >= 0:
            return None             # un marqueur vendable SUIT le pays → nom de produit
    return best_region


def precheck_skip(offer: NormalizedOffer, *, consoles: bool = False) -> str | None:
    """Categorical SKIPs from the merchant title/URL, before any AKS lookup.

    ``consoles`` ([R45], 2026-09-12): False (default, every existing caller) keeps the
    historical behaviour — any console marker → ``"console"``; True routes a console-
    marked row through :func:`classify_console` — its fail-closed ``skip_reason`` is
    returned as is, otherwise the row CONTINUES through the remaining scans (forbidden
    regions, categories, bundles, skins…) exactly like a PC row, and :func:`match_offer`
    takes the console branch."""

    cfg = merchant_config(offer.merchant)
    domain = cfg.domain if cfg else None
    if domain:
        host = urlparse(offer.url).netloc.lower()
        if host != domain and not host.endswith("." + domain):
            return f"offer URL not on {domain} (merchant-domain mismatch)"
    # Merchant-config override hook (R32e, 2026-09-10): the merchant's own categorical
    # skip, before the generic scans (MMOGA "<Product> <CODE> Key" locks).
    if cfg is not None and cfg.precheck is not None:
        hook_reason = cfg.precheck(offer.name, offer.url)
        if hook_reason:
            return hook_reason
    # (MA7 retired 2026-09-01, Romain: "EN = english only … enterrable") — a
    # Gamivo '-en-' URL segment used to skip as an EN-only language restriction;
    # a language variant is now entered as the same product (see LANGUAGE_TOKENS).
    padded = " " + re.sub(r"[^A-Z0-9]+", " ", fold_accents(offer.name).upper()) + " "
    # [R45] (2026-09-12) the console scan reads the TITLE tokens (unchanged) OR the URL
    # PATH (console_marker_in_url) — the Gamivo leak fix: Gamivo (569/572 console rows)
    # and Eneba carry the platform in the URL only, so "Riders Republic Premium Edition
    # United States" (gamivo …/riders-republic-xbox-xbox-one-series-us-premium) escaped
    # the title-only scan and was entered on the PC page (run 20260911-162100, AKS
    # 50562). Active even with consoles=False (→ the historical "console" skip).
    # AIGUILLAGE COMPTE (Romain, 2026-09-21) : une ligne que le marchand déclare COMPTE ne
    # passe pas par le scan console — ni ici, ni au dispatch de `match_offer`. Le compte est
    # le produit vendu ; la branche compte exigera sa page « <plateforme> Account » et son
    # seau, donc un compte ne peut toujours pas entrer comme une clé.
    _account_row = bool(
        cfg is not None and cfg.account_row is not None
        and cfg.account_row(offer.name, offer.url))
    if _account_row:
        # La ligne part vers la branche compte — mais les marqueurs NON-JEU du classifieur
        # restent dus : une « PSN Card 20 EUR (Account) » ou un « Game Pass (Account) » sont
        # refusés comme partout ailleurs. SEUL le motif « ACCOUNT — not a game » est ignoré,
        # puisque c'est exactement la classification que Romain a renversée le 2026-09-21.
        # (Correctif de mon propre correctif, même jour : la première version sautait TOUS
        # les scans suivants — régions interdites et cartes cadeaux comprises.)
        _sig_account = classify_console(offer.name, offer.url, offer.merchant)
        _reason_account = _sig_account.skip_reason if _sig_account is not None else None
        if _reason_account and "ACCOUNT — not a game" not in _reason_account:
            return _reason_account
    elif (any(f" {t} " in padded for t in CONSOLE_TOKENS) or console_marker_in_url(offer.url)):
        if not consoles:
            return "console"
        sig = classify_console(offer.name, offer.url, offer.merchant)
        if sig is None:
            # A marker we saw but the classifier did not — grammar disagreement, never a
            # PC entry: the historical skip (fail-closed).
            return "console"
        if sig.skip_reason:
            return sig.skip_reason
        # [R45] review fix (2026-09-14): the region SLOT of the merchant's console grammar
        # (Kinguin / K4G "<Game> CA Xbox One …", Driffle "(Hong Kong)", Gamivo "EN
        # Singapore") names a region AKS does not sell → the same "forbidden region" path
        # as PC, BEFORE any resolution. Before this fix 150 Kinguin CA / AU console rows
        # passed the precheck and read an implicit GLOBAL.
        if sig.region_label:
            return f"forbidden region: {sig.region_label}"
        # A classified console row keeps going through the remaining categorical scans.
    _locked = _forbidden_region_in(padded)
    if _locked:
        return f"forbidden region: {_locked}"
    # P2-6 (audit 2026-09-02): a forbidden region encoded ONLY in the merchant URL
    # (e.g. Gamivo ".../cyberpunk-2077-steam-key-brazil") escaped this title-only scan
    # and reached detect_region, which recognizes ONLY sellable buckets
    # (eu/global/us/uk) → an implicit GLOBAL, entering a region-locked key worldwide
    # (the R33 page-region rescue needs a merchant page config Gamivo doesn't have).
    # Scan the URL PATH the same way — normalized, word-boundary, query stripped and
    # merchant noise removed (the stored/reported URL is never mutated). SAME reason
    # string as the title path so the one router (suggest_target_list) sends
    # BRAZIL/LATAM/… → Blacklist and NA/ROW/… → garder, identically.
    url_path = urlparse(strip_merchant_url_noise(offer.url, offer.merchant)).path
    url_padded = " " + re.sub(r"[^A-Z0-9]+", " ", fold_accents(url_path).upper()) + " "
    _locked_url = _forbidden_region_in(url_padded)
    if _locked_url:
        return f"forbidden region: {_locked_url}"
    # P2-6b (audit 2026-09-02): forbidden regions also appear as bare 2-letter slug
    # codes ("…-steam-key-ru") — caught only in a trailing region slot (see
    # _url_region_code) so English words ("lost-in-random", "among-us") don't skip.
    url_lower = url_path.lower()
    for code, label in _URL_FORBIDDEN_CODES:
        if _url_region_code(url_lower, code):
            return f"forbidden region: {label}"
    # Fable re-audit 2026-09-06 (P1): URL-slot-only forbidden regions (VIETNAM) — a
    # lock in the slug, but too title-collision-heavy for BOTH the name AND a plain
    # URL word-boundary scan: "rising-storm-2-vietnam-steam-key" carries "vietnam"
    # as the GAME NAME. So gate it to the trailing region SLOT exactly like the
    # 2-letter codes — only "-<marker>-vietnam" (a lock) matches, never a mid-slug
    # game name. (The bare "vn" code above already covers the abbreviated slug.)
    for region in _URL_ONLY_FORBIDDEN_REGIONS:
        if _url_region_code(url_lower, region.lower()):
            return f"forbidden region: {region}"
    if _COUNTRY_GIFT_RE.search(padded):
        return "country gift (region-locked gift, §4.3)"
    # Random/lootbox keys & items (_RANDOM_LOOT_RE, see its definition). Checked
    # BEFORE the category loops so it primes over an incidental GIFT CARD / SKIN /
    # BUNDLE token in the same title ("…RANDOM CASE GIFT CARD…", "Random Bundle").
    if _RANDOM_LOOT_RE.search(padded):
        return "skip category: RANDOM (random/lootbox, not a game)"
    # accents folded (2026-09-16): CATEGORY_SKIP is ASCII English, so "CRÉDITS" had to
    # become "CREDITS" to meet the entry that was already there. See fold_accents.
    upper = fold_accents(offer.name).upper()
    for cat, pat in _CATEGORY_SKIP_RES:      # word-boundary, not raw substring (P2-7)
        if pat.search(upper):
            return f"skip category: {cat}"
    for token in BUNDLE_SKIN_TOKENS:
        if f" {token} " in padded:
            return f"skip category: {token} (no bundles/skins)"
    if _SKIN_TOKEN_RE.search(padded) and not _SKIN_TITLE_PHRASE_RE.search(padded):
        return "skip category: SKIN (no bundles/skins)"
    for token in NON_GAME_CONTENT_TOKENS:
        if f" {token} " in padded:
            # A game bundled with its OST/artbook is NOT standalone non-game content,
            # so it must not auto-route to Blacklist as a soundtrack (audit 2026-07-23:
            # "Sinless + OST", "Lost Records … Soundtrack Edition" were wrongly
            # Blacklisted). The two forms then diverge (P3-3, audit 2026-09-02 —
            # the `continue` is load-bearing, NOT dead):
            #   • "… <token> EDITION" (no " + ") → falls through, ENTERS the base game;
            #   • "<game> + OST" → falls through to the " + " multi-game-bundle skip
            #     below → "possible multi-game bundle" → garder (None), a fail-closed
            #     OVER-skip (we NEVER enter bundles), NOT a base-game entry.
            # Do NOT "fix" this to enter the " + " base game (fail-open bundle entry)
            # nor to drop the " + " branch (reintroduces the wrong-Blacklist bug).
            if " + " in offer.name or f" {token} EDITION " in padded:
                continue
            return f"skip category: {token} (non-game content)"
    # R31 (2026-08-11): software is NO LONGER pre-skipped here. It falls through
    # to the AKS lookup and the SOFTWARE PATH in match_offer (is_software +
    # page-driven edition/region); software AKS doesn't sell still gets caught by
    # the "no AKS product page found" gate. SOFTWARE_APP_TOKENS / _WINDOWS_OS_RE
    # are now CLASSIFIERS (is_software), not skips.
    for token in CURRENCY_TOKENS:
        if f" {token} " in padded:
            return f"skip category: {token} (in-game currency)"
    # [R43] (2026-09-11): a "DLC" / "Add-On" / "Season Pass" title is NO LONGER a
    # pre-skip — it is resolved (marker stripped) and must land on an AKS page carrying
    # the DLC bucket (match_offer), entered as DLC(16). See dlc_title_marker. A DLC
    # COLLECTION ("DLC Pack", "All DLC", "DLCs") is a bundle of DLCs → never entered.
    collection = dlc_collection_marker(offer.name)
    if collection:
        return f"skip category: {collection} (DLC collection — no bundles)"
    if " PREORDER BONUS " in padded or " PRE ORDER BONUS " in padded:
        return "preorder bonus"
    # "Royal Grow Pass", "Battle Pass", "Game Pass"… — in-game passes are not
    # games. A SEASON / EXPANSION pass is a DLC product with its own AKS page ([R43])
    # and falls through to resolution instead.
    if " PASS " in padded and (dlc_title_marker(offer.name) is None or _INGAME_PASS_RE.search(padded)):
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
    # ACCOUNT (2026-09-25) — LAST, so every existing reason keeps its label ("skip category:
    # STEAM ACCOUNT", "console: ACCOUNT — not a game (R45)", a merchant hook's own refusal).
    # A merchant that DECLARES its accounts (`account_row`, Difmark) sends them to the
    # account branch instead — never here. Everyone else: an account is never a key, and no
    # generic account page flow exists for them, so it is refused and routed to the account
    # list (30) by `aks_lists.suggest_target_list` — the manual-review queue. Before, a
    # PC listing whose URL alone said account (title silent) was refused NOWHERE.
    if not _account_row:
        signal = account_signal(offer.name, offer.url, offer.merchant)
        if signal is not None:
            return (f"skip category: ACCOUNT (account listing — the {signal} says account; "
                    "never entered as a key)")
    return None


# Single-word platform declarations, matched word-boundary only (audit
# 2026-07-17, MA2: bare substring turned "Gogol's Quest" into GOG). Multi-word
# declarations (EA APP, MICROSOFT STORE, …) stay separate collocations below.
_PLATFORM_WORDS = {
    "GOG": "GOG",
    "EPIC": "EPIC",
    "UBISOFT": "UBISOFT",
    "UPLAY": "UBISOFT",
    "ROCKSTAR": "ROCKSTAR",  # seaux Rockstar mappés depuis [R50] — la ligne ENTRE
    "STEAM": "STEAM",
}

# [37] Fable re-audit 2026-09-06: the URL slug scan needs MORE platform words than the
# title scan (which handles EA / Origin / Battle.net specially, above), but adding them
# to the shared _PLATFORM_WORDS would leak into the title scan (collisions like a game
# named "…Battle…"). URL-scan-only superset — the "key" collocation gate below keeps it
# safe. "battle" → BATTLENET matches "…-battle-net-key" / "…-battle-key" only.
_URL_PLATFORM_WORDS = {
    **_PLATFORM_WORDS,
    "EA": "EA", "ORIGIN": "EA",
    "BATTLENET": "BATTLENET", "BATTLE": "BATTLENET",
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
    # Word-boundary collocations (NOT raw substring): "EA Player"/"EA Playground"
    # must NOT read as EA (R38 revision 2026-09-01, Romain review). "EA Play" is the
    # EA app storefront/brand (region ids under EA) — a key sold on it is an
    # EA-platform product, like "EA App"/"EA Origin"; bare "Origin" in a game name is
    # NOT the EA platform (R14).
    if (re.search(r"\bEA (?:APP|PLAY|ORIGIN)\b", t)
            or re.search(r"\bORIGIN (?:CD )?KEY\b", t)):
        return "EA"
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


def _url_platform_scan(path: str) -> str | None:
    """The platform token collocated with the key marker in a merchant URL PATH
    ("…-steam-key-…", "…-ubisoft-connect-key-…", "…-rockstar-key-…"), or None.

    Collocation with "key" is what makes a WHOLE-path scan safe: a game-name platform
    word ("epic-chef-…-key") is NOT read as EPIC (it is not adjacent to the key
    marker), and a token-less delivery slug ("…-green-gift-key-…", the G2A GMG gift)
    yields None → fail-closed. Zero or >1 distinct platforms → None (ambiguous)."""

    words = "|".join(sorted((w.lower() for w in _URL_PLATFORM_WORDS), key=len, reverse=True))
    # Trailing boundary is a zero-width LOOKAHEAD, not a consuming class: two adjacent
    # collocations share one hyphen ("…-steam-key-epic-key-…"), and a consuming boundary
    # would eat the '-' the second token needs, so non-overlapping finditer would miss it
    # and return ONE platform instead of failing closed on the ambiguous >1 (2026-08-27
    # review). The lookahead keeps the delimiter so both collocations match → None.
    # [37] Fable re-audit 2026-09-06: allow a platform-suffix segment between the word and
    # the key marker — "gog-com-key", "epic-games-key", "ea-app-key", "battle-net-key" —
    # else those slugs read no platform and a locked key fell to implicit STEAM/None.
    hits = {
        _URL_PLATFORM_WORDS[m.group(1).upper()]
        for m in re.finditer(
            r"[-/](" + words + r")(?:-(?:connect|com|games|app|net))?-(?:cd-)?keys?(?=[-/]|$)",
            path)
    }
    return next(iter(hits)) if len(hits) == 1 else None


def explicit_platform_from_url(url: str, merchant: str = "") -> str | None:
    """The platform declared in a merchant's URL, per that merchant's MerchantConfig
    (R32b, 2026-08-27 — was Eneba-only). Two per-merchant modes: ``url_platform_prefixes``
    → the URL's LEADING path segment maps to a platform (Eneba, ``eneba.com/steam-…``);
    ``url_platform_scan`` → the platform token collocated with the key marker anywhere in
    the path (G2A, ``…-steam-key-…``; a token-less ``…-green-gift-key-…`` → None). A
    merchant with neither knob (or no config) → None, unchanged.
    [R46] (2026-09-12): a merchant's ``url_platform`` hook — its own URL grammar — is
    consulted FIRST; its non-None answer wins, None falls through to the two modes
    (Gamivo "…-pc-steam-us-standard": the run sits mid-slug, after the game slug)."""

    cfg = merchant_config(merchant)
    if cfg is None:
        return None
    if cfg.url_platform is not None:
        hooked = cfg.url_platform(url)
        if hooked is not None:
            return hooked
    path = urlparse(url).path.strip("/").lower()
    if cfg.url_platform_prefixes:
        return cfg.url_platform_prefixes.get(path.split("-", 1)[0])
    if cfg.url_platform_scan:
        return _url_platform_scan(path)
    return None


def detect_platform(title: str) -> str:
    return explicit_platform(title) or "STEAM"  # default; most PC keys are Steam


def _region_id(platform: str, key: str) -> str | None:
    # No silent fallback to Steam ids: an unknown platform must fail closed.
    return REGION_IDS.get(platform, {}).get(key)


def is_green_gift(name: str, url: str) -> bool:
    """A Green Man Gaming ("Green Gift") delivery, or False (R32c, 2026-08-28 — Romain:
    "Green Gift = Greenmangaming gift, != Steam"). GREEN adjacent to GIFT in the title,
    or a ``green-gift`` URL segment. A GMG gift maps to the per-platform gmg_gift region,
    not the plain Steam-gift region; only the "Green Gift" phrase counts (a bare "Green"
    or plain "Gift" does not)."""

    if re.search(r"(?:^|[-/])green-gift(?:[-/]|$)", (url or "").lower()):
        return True
    return re.search(r"\bGREEN[\s-]+GIFT\b", (name or "").upper()) is not None


def _detect_region_parts(offer: NormalizedOffer) -> tuple[str, str, bool, bool, bool]:
    """The region scan shared by :func:`detect_region` and :func:`detect_region_base`
    ([R45] extraction, 2026-09-12 — behaviour byte-identical to the pre-R45 detect_region
    body): ``(base, label, implicit, is_gift, is_green_gift)``. ``base`` ∈ global/eu/us/uk,
    ``label`` its uppercase label, ``implicit`` the Kinguin-style default, the two gift
    flags the plain-gift / Green-Man-Gaming-gift signals the platform-specific layering
    in detect_region needs."""

    # Query strings carry campaign junk (COM_GLOBAL_PB, ___currency=EUR…) that
    # would false-hit region tokens — only the path speaks for the product.
    url = strip_merchant_url_noise(offer.url, offer.merchant).lower().split("?", 1)[0]
    padded = " " + offer.name.upper() + " "
    cfg = merchant_config(offer.merchant)
    # Merchant-config override hook (R32e, 2026-09-14 — Romain: « Steam Altergift = Steam
    # Gift on rentre sous gift tous les altergifts »): the merchant's OWN gift-delivery
    # verdict (K4G "… Steam Altergift" → True) wins over the generic read; None → generic.
    hook_gift = cfg.gift_delivery(offer.name, offer.url) if cfg is not None and cfg.gift_delivery else None
    if hook_gift is not None:
        is_gift = bool(hook_gift)
    else:
        # 'gift' must be its own URL segment (audit 2026-07-17, MA4): the bare
        # substring matched slug words like "the-gifted-rabbit" and proposed
        # GIFT(25) for a regular key.
        is_gift = (
            re.search(r"(?:^|[-/])gift(?:[-/]|$)", url) is not None
            or " GIFT " in padded
            or "GIFT)" in padded
        )
    tail = offer.name.rsplit(" - ", 1)[-1].strip().upper() if " - " in offer.name else ""
    # Merchant-config override hook (R32e, 2026-09-10): the region the merchant's title
    # grammar declares wins over the generic title/URL scan below (MMOGA "… US Key").
    hook_base = cfg.title_region(offer.name) if cfg is not None and cfg.title_region else None

    base, label, implicit = "global", "GLOBAL", False
    if hook_base is not None:
        # The merchant's grammar is authoritative when it speaks (its URL is derived from
        # the same title, so the generic URL scan cannot know better).
        base, label = hook_base, ("GLOBAL" if hook_base == "global" else hook_base.upper())
    elif (
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
    # AUDIT DU 2026-09-18. La branche GLOBAL était testée AVANT US et UK, et elle lit
    # « -global » en SOUS-CHAÎNE NUE plus « GLOBAL » en plein milieu du titre. Un produit dont
    # le NOM PROPRE contient le mot (Counter-Strike: Global Offensive, Global Agenda…) faisait
    # donc gagner GLOBAL(2) contre un verrou US/UK pourtant écrit dans le CRÉNEAU de l'URL ou
    # en queue de titre : une clé verrouillée publiée mondiale.
    #
    # On ne touche NI l'ordre général NI la lecture de « -global » : le « -global » en milieu
    # de slug est la grammaire NORMALE de Driffle, K4G (altergift) et Gamivo, et le passer en
    # implicite casserait des décisions documentées. On fait seulement perdre GLOBAL face à un
    # verrou US/UK **terminal**, c'est-à-dire écrit là où un créneau de région s'écrit : slot
    # de fin d'URL (`_url_region_code`, déjà ancré), chemin finissant par `-united-states` /
    # `-united-kingdom`, ou QUEUE de titre. Les lectures FAIBLES (« USA » ou « (UK) » en plein
    # milieu du titre, `-united-states-` en milieu de slug) restent où elles étaient, APRÈS
    # GLOBAL : sans quoi le cas fondateur de [R44] — « Age of Empires III: United States
    # Civilization … - Steam Key GLOBAL » — basculerait de GLOBAL (correct) vers US.
    #
    # Quand les deux sont explicites (queue de titre GLOBAL + slot d'URL US, la paire Eneba),
    # le VERROU gagne : c'est le sens sûr, une clé verrouillée ne doit jamais s'élargir.
    elif (re.search(r"-united-states/?$", url) or _url_region_code(url, "us")
          or _url_region_code(url, "usa") or tail in ("UNITED STATES", "US", "USA")):
        base, label = "us", "US"
    elif (re.search(r"-united-kingdom/?$", url) or _url_region_code(url, "uk")
          or _url_region_code(url, "gb") or tail in ("UK", "UNITED KINGDOM")):
        base, label = "uk", "UK"
    elif "-global" in url or " GLOBAL " in padded or "(GLOBAL)" in padded or " WORLDWIDE " in padded:
        base, label = "global", "GLOBAL"
    elif (re.search(r"-united-states(?:[-/]|$)", url) or _url_region_code(url, "us")
          or _url_region_code(url, "usa")
          or " USA " in padded or "(USA)" in padded
          or tail in ("UNITED STATES", "US", "USA")):
        # "-us"/"-usa" only in a trailing region slot ("…-steam-key-us"), never a bare
        # "among-us" (P2-6b gate) — before, a "-us" slug fell to implicit GLOBAL,
        # entering a US-locked key worldwide (and a US green gift missed gmg_gift_us).
        # [9] (Fable re-audit 2026-09-06): also the "-usa" slug spelling + a bare
        # mid-title " USA " / "(USA)" (the tail-only check missed both).
        base, label = "us", "US"
    elif (re.search(r"-united-kingdom(?:[-/]|$)", url)
          or _url_region_code(url, "uk") or _url_region_code(url, "gb")
          or " UK " in padded or "(UK)" in padded or tail in ("UK", "UNITED KINGDOM")):
        # Fable re-audit 2026-09-06: mirror the P2-6b "-us" slot detection for "-uk"
        # (and the "-gb" spelling) — a "…-steam-key-uk" slug used to fall to implicit
        # GLOBAL (a UK-locked key sold worldwide, and a UK gift missing gift_uk/
        # gmg_gift_uk). Gated to the trailing region slot so "uk"/"gb" is never matched
        # mid-slug.
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
    return base, label, implicit, is_gift, is_green_gift(offer.name, offer.url)


def detect_region_base(offer: NormalizedOffer) -> tuple[str, str, bool, bool]:
    """[R45] (2026-09-12) the platform-INDEPENDENT region read of a merchant row:
    ``(base, label, implicit, gift)`` — ``base`` ∈ global/eu/us/uk, ``label`` its label,
    ``implicit`` when nothing declared it, ``gift`` when the row is a (green-)gift
    delivery. The console branch maps ``base`` per declared family (``REGION_IDS[fam]``)
    and refuses gifts (no console gift bucket exists); :func:`detect_region` is the
    PC path layering the per-platform gift buckets on top of the same read."""

    base, label, implicit, is_gift, green = _detect_region_parts(offer)
    return base, label, implicit, (is_gift or green)


def detect_region(offer: NormalizedOffer, platform: str) -> tuple[str, str | None, bool]:
    """Return (label, region_id, implicit). URL wins over title (rule Ga01).

    Gift is layered on top of the base region (Steam 25/259, Battle.net 570/567).
    Region may sit in the first parens (Driffle: "X (Europe) (PC) - …") or in a
    trailing " - REGION" suffix (G2A: "X (PC) - Steam Key - EUROPE").
    ([R45] 2026-09-12: the scan itself moved to ``_detect_region_parts`` so the console
    branch can read the base region without a platform — output unchanged.)
    """

    base, label, implicit, is_gift, green = _detect_region_parts(offer)
    # A Green Man Gaming ("Green Gift") delivery is NOT a plain (Steam) gift — it maps to
    # the platform's dedicated gmg_gift region (R32c). Checked BEFORE and INDEPENDENT of
    # the plain is_gift branch: is_gift's title test is the space-delimited " GIFT ", but a
    # green gift can be a hyphen-compound "GREEN-GIFT" which is_green_gift accepts — gating
    # the gmg branch on is_gift would leak that form to the plain region (2026-08-28
    # review).
    # P2-8 (audit 2026-09-02): resolve the EXACT per-base gmg_gift bucket — NO silent
    # fallback to the GLOBAL gmg_gift id. STEAM has gmg_gift+gmg_gift_eu (no _us), EPIC has
    # gmg_gift+gmg_gift_us (no _eu); the old `or gmg_gift` returned the GLOBAL id while the
    # label still said "US"/"EU", contradicting the id (a mislabel that widened the region
    # and defeated the validation gate — a US-restricted key entered worldwide). A base the
    # platform lacks → gid None → fail-closed skip downstream (label and id can never
    # disagree; same fail-closed stance as GOG plain gift → None).
    # Fable re-audit 2026-09-06: BOTH gift branches resolve the EXACT per-base bucket with
    # NO silent default for a locked base — a US/UK-locked (green-)gift must NOT widen to
    # the platform-global gift bucket under a region-less label (the P2-8 mislabel, which
    # was only fixed for the gmg 'us'/'eu' cases). A base the platform lacks a bucket for
    # → gid None → the existing "no region id" fail-closed skip, and the label carries the
    # base so id and label agree.
    # Audit 2026-09-16 (Romain: « si ça existe le fichier marchand ne devrait pas affirmer le
    # contraire, fix la config marchand »): the tables above USED to claim "gift_us / gift_uk
    # exist on no platform". False — the live dropdown has Steam Gift US (2577) / Steam Gift
    # UK (2572), Battlenet Gift US (568) and the whole Ubisoft Gift family (501 / EU 504 /
    # US 505), all now mapped. The SAFETY property is unchanged: a locked gift still resolves
    # its OWN per-base bucket and never widens to the platform-global one. Still absent for
    # real, and still fail-closed: ``gmg_gift_uk`` (no platform has it), a Battle.net gift UK,
    # an EA / EPIC / GOG / PUBLISHER / ROCKSTAR plain gift.
    if green:
        key = {"eu": "gmg_gift_eu", "us": "gmg_gift_us", "uk": "gmg_gift_uk"}.get(base, "gmg_gift")
        gid = _region_id(platform, key)
        return ("GMG GIFT" + {"eu": " EU", "us": " US", "uk": " UK"}.get(base, ""), gid, implicit)
    if is_gift:
        key = {"eu": "gift_eu", "us": "gift_us", "uk": "gift_uk"}.get(base, "gift")
        return ("GIFT" + {"eu": " EU", "us": " US", "uk": " UK"}.get(base, ""),
                _region_id(platform, key), implicit)
    return (label, _region_id(platform, base), implicit)


def account_identity(aks_name: str, page_kind: str) -> str | None:
    """The game-identity portion of an AKS account page's name, or None when
    the page is not actually an account page for ``page_kind``.

    An account page's name ends with the page-kind words — "Final Knight
    **Steam Account**", "007 First Light **PS5 Account**". Those words are
    page-TYPE metadata, not product identity, and the merchant feed title
    never carries them ("Final Knight Standard Edition"), so R01 must compare
    against the stripped identity ("Final Knight") — otherwise every account
    match false-fails on the missing "Account"/platform words. Returning None
    when the suffix is absent is a fail-closed guard: an account-URL 200 whose
    name is not "<game> <platform> account" is not the page we think it is."""

    words = page_kind.upper().split("-")  # "steam-account" -> ["STEAM", "ACCOUNT"]
    pattern = r"\s+" + r"\s+".join(re.escape(w) for w in words) + r"\s*$"
    stripped = re.sub(pattern, "", aks_name, flags=re.IGNORECASE).strip()
    if stripped == aks_name.strip() or not stripped:
        return None
    return stripped


# ── Per-merchant configuration registry (R32, 2026-08-11) ────────────────────
# The pipeline "starts from the merchant config": match_offer reads
# merchant_config(offer.merchant) and applies its rules. A merchant with no
# config keeps the generic behaviour. The registry itself (``MERCHANT_CONFIGS`` /
# ``merchant_config``) lives in src/merchants/registry.py since 2026-09-14 and is
# re-exported above; register a new merchant module THERE.


def strip_merchant_url_noise(url: str, merchant: str) -> str:
    """Remove merchant-specific URL boilerplate before deriving ANY matching
    signal (region, edition) from the URL. Case-insensitive — never touches
    the stored/reported offer URL itself (EXECUTOR_RULES §4.6)."""

    cleaned = url
    cfg = merchant_config(merchant)
    for noise in (cfg.url_ignore_substrings if cfg else ()):
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
# Le MÊME jeu de phrases, sans les noms de pays. AUDIT DU 2026-09-18, troisième site du même
# défaut : le strip est ITÉRATIF, donc après avoir retiré « GLOBAL », « KEY » et « STEAM » de
# « Crusader Kings II: Rajas of India - Steam Key - GLOBAL », « INDIA » se retrouvait en queue
# et était amputé à son tour → slug « crusader-kings-ii-rajas-of », mauvaise page sondée même
# une fois le precheck corrigé. Idem « Modern Japan » → « Modern ». Un nom de pays n'est retiré
# que si la ligne est RÉELLEMENT verrouillée par lui, selon la même règle que les deux scans
# (`_forbidden_region_in` : la région est la dernière chose déclarée).
_TRAILING_NOISE_PHRASES_KEEP_COUNTRY = tuple(
    ph for ph in _TRAILING_NOISE_PHRASES if ph not in FORBIDDEN_REGIONS
)
# Edition words stripped (trailing only) for the fallback slug variant.
# EDITION_HINTS vocabulary minus BUNDLE/PACK/TRILOGY/DLC: those name a
# different product (bundle titles are hard-skipped upstream; a DLC title has its
# marker stripped by strip_dlc_marker before slug building, [R43]).
_TRAILING_EDITION_PHRASES = (
    "ULTIMATE COLLECTION", "GAME OF THE YEAR", "GOTY", "DELUXE", "GOLD",
    "PREMIUM", "COMPLETE", "ULTIMATE", "COLLECTION", "STANDARD", "EDITION",
    # AUDIT DU 2026-09-20 : « DIGITAL » manquait, et il précède presque toujours un palier
    # déjà listé (« Alien: Isolation Digital Deluxe Edition » → le repli s'arrêtait sur
    # `alien-isolation-digital`, `alien-isolation` n'était JAMAIS sondé : 6 offres perdues
    # sur le balayage GameSeal). DIGITAL n'est pas un produit, c'est un format.
    # NE PAS y ajouter DEFINITIVE / REMASTERED / ANNIVERSARY : eux n'ont AUCUN seau dans
    # EDITION_HINTS, donc atteindre la page de base leur donnerait Standard(1) sur un AUTRE
    # produit — 15 lignes justes du même balayage résolvent leur page dédiée
    # (`buy-age-of-empires-3-definitive-edition-`, `buy-starcraft-remastered-`…).
    "DIGITAL",
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
    padded = " " + re.sub(r"[^A-Z0-9]+", " ", fold_accents(name).upper()) + " "
    phrases = (_TRAILING_NOISE_PHRASES if _forbidden_region_in(padded)
               else _TRAILING_NOISE_PHRASES_KEEP_COUNTRY)
    return _strip_trailing_phrases(without_parens, phrases)


def build_slug_candidates(name: str) -> list[str]:
    """Ordered AKS slug guesses, most specific first.

    Tier 1: full name, parens + trailing market noise stripped (keeps dashed
    subtitles like "Endless Space - Disharmony"). Tier 2: trailing edition
    words also stripped (edition-specific AKS pages exist, so tier 1 goes
    first). Tier 3: legacy dash-split head (Driffle/G2A "Name - Platform -
    Region" grammar). Over-stripping only costs a probe: a wrong-page 200 is
    caught by the R01 / extra-words guards downstream.
    """

    name = fold_franchise_spellings(name)   # « Warhammer 40,000 » → le `40k` d'AKS
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
        for variant in _slug_variants(base):
            if variant not in out:
                out.append(variant)
    return out


def _slug_variants(base: str) -> list[str]:
    """The slug spellings of ONE base text: apostrophes dropped / kept as a dash, and
    [R42] the numeral-swapped spelling right after each ("crusader-kings-iii" then
    "crusader-kings-3") — same tier, one extra probe only when a numeral exists."""

    base = base.lower()
    out: list[str] = []
    for text in (base, swap_numerals(base)):
        for variant in (
            re.sub(r"[^a-z0-9]+", "-", text.replace("'", "")).strip("-"),
            re.sub(r"[^a-z0-9]+", "-", text).strip("-"),
        ):
            variant = re.sub(r"-+", "-", variant)
            if variant and variant not in out:
                out.append(variant)
    return out


def own_page_slugs(name: str) -> list[str]:
    """Tier 1 only — the slugs of the FULL cleaned name. [R43]: a title that announces a
    DLC may only be accepted on the page of its own full name; a resolution reached
    through the less specific tiers (edition words stripped, the dash-split base-game
    head) is NOT the DLC's page (adversarial review 2026-09-11: a base-game page can
    carry a DLC bucket, so the bucket alone does not prove the page is THIS DLC)."""

    return _slug_variants(cleaned_title(name))


def resolved_on_own_page(slug: str, name: str) -> bool:
    """True iff ``slug`` (the resolved variant — current, year-suffixed or legacy shape)
    is one of :func:`own_page_slugs` of ``name``."""

    own = own_page_slugs(name)
    return slug in own or re.sub(r"-\d{4}$", "", slug) in own


def aks_url(slug: str, page_kind: str = "cd-key") -> str:
    return AKS_COMPARE_URL.format(slug=slug, kind=page_kind)


_SITEMAP_CACHE: list[Any] = []          # [] = pas encore chargé, [None] = pas d'index


def sitemap_index(path: str | None = None) -> Any:
    """L'index des pages publiées par AKS, chargé UNE fois par processus, ou ``None``.

    Il ne remplace aucune garde : il dit seulement quelles URL existent, pour qu'on sonde
    celles-là au lieu de deviner. Un index absent, illisible ou périmé rend ``None`` et le
    matcher se comporte exactement comme avant (voir `src/aks_sitemap.py`)."""

    if path is not None or not _SITEMAP_CACHE:
        from src import aks_sitemap
        chemin = path or os.environ.get("AKS_SITEMAP_PATH") or str(
            Path(__file__).resolve().parents[1] / aks_sitemap.DEFAULT_PATH)
        index = aks_sitemap.SitemapIndex.load(chemin)
        if index is not None and (index.incomplete or not index.fresh()):
            index = None          # un catalogue troué ou vieux ne fait pas autorité
        if path is not None:
            return index
        _SITEMAP_CACHE.append(index)
    return _SITEMAP_CACHE[0]


def set_sitemap_index(index: Any) -> None:
    """Pose l'index pour ce processus (tests, et 03_match qui le charge une fois)."""

    _SITEMAP_CACHE.clear()
    _SITEMAP_CACHE.append(index)


def sitemap_is_authoritative() -> bool:
    return sitemap_index() is not None


# Ce que le filtre « sitemap d'abord » a évité ou laissé passer, pour ce processus : 03_match
# le recopie dans match_meta.json (une page = un processus), l'audit y lit ce que le mode a
# coûté ou épargné. Remis à zéro par `reset_sitemap_first_stats`.
SITEMAP_FIRST_STATS: dict[str, int] = {"probes_skipped": 0, "valve_unconfirmed": 0}


def reset_sitemap_first_stats() -> None:
    for cle in SITEMAP_FIRST_STATS:
        SITEMAP_FIRST_STATS[cle] = 0


def sitemap_first_probes(probes: list[tuple[str, str]],
                         page_kind: str = "cd-key") -> list[tuple[str, str]]:
    """Les sondes des passes 1-2 que l'index sitemap CONFIRME — sitemap d'abord (2026-09-24).

    Romain : « go pour le matching sitemap d'abord », après l'audit du parallélisme du 23/09 :
    35 % des offres n'ont aucune page AKS et chacune coûtait ~4,7 sondes aveugles (slug complet,
    slug sans édition, tête de titre, variantes année et ancienne forme) qui répondaient 404 —
    ~164 requêtes perdues par page de 100 lignes, sur le budget par IP qui borne tout le reste.
    Vérifié avant : 99,8 % des ~9 000 pages résolues depuis le 15/09 sont dans l'index.

    * Index absent ou périmé → les sondes telles quelles : rien ne change sans index frais.
    * Forme courante ou année (`buy-<slug>-<gabarit>-compare-prices/`) → gardée ssi
      ``has_page(<slug>-<gabarit>)``.
    * Forme ancienne (`compare-and-buy-…-<slug>/`) → gardée ssi ``has_legacy(slug)`` ; un
      index qui n'a pas cherché les pages anciennes (``None``) la garde, faute de savoir.
    * **La soupape** : la TOUTE PREMIÈRE sonde (tier 1, forme courante) part toujours, même
      non confirmée. Le sitemap est une photo et il a des trous — ``buy-the-front-cd-key``
      répondait 200 le 24/09 sans figurer dans l'index du 23. Une page neuve porte presque
      toujours le nom complet du jeu : c'est la sonde qui la trouve. Coût : une requête par
      offre sans page, au lieu de ~4,7.

    L'ordre est conservé, donc MA1 aussi : les tiers restent du plus au moins précis, et une
    réponse douteuse sur une sonde gardée lève toujours immédiatement."""

    index = sitemap_index()
    if index is None or not probes:
        return list(probes)
    gardees: list[tuple[str, str]] = []
    for rang, (variant, url) in enumerate(probes):
        if url == AKS_LEGACY_URL.format(slug=variant):
            connue = index.has_legacy(variant)
            confirmee = connue is None or connue
        else:
            confirmee = index.has_page(f"{variant}-{page_kind}")
        if confirmee:
            gardees.append((variant, url))
        elif rang == 0:
            gardees.append((variant, url))
            SITEMAP_FIRST_STATS["valve_unconfirmed"] += 1
        else:
            SITEMAP_FIRST_STATS["probes_skipped"] += 1
    return gardees


# Les SEULS gabarits que la passe 3 accepte comme équivalents d'une page `cd-key` : d'autres
# façons d'écrire « une clé pour ce jeu ». Volontairement étroit.
#   * PAS les pages COMPTE (`-steam-account`…) : un compte n'est pas une clé, c'est un autre
#     produit — la branche compte (Difmark, R32) le dit déjà, et 246 des lignes rattrapables
#     du balayage de nuit sont de ce genre. Les rattraper ICI les ferait entrer sous le
#     mauvais produit ; elles ressortent donc toujours « pas de page », et l'export de tri
#     les RETIENT au lieu de les déplacer (c'est exactement son rôle).
#   * PAS les pages CONSOLE : elles ont leur propre branche (R45, `_console_plan`), avec ses
#     règles de plateformes déclarées.
SITEMAP_KEY_KINDS: tuple[str, ...] = ("key", "game-code", "download-code")


def sitemap_shapes(slugs: list[str], page_kind: str = "cd-key") -> list[tuple[str, str]]:
    """Les ``(slug, url)`` que l'index CONFIRME et que les passes 1-2 n'ont pas déjà sondés.

    Rend une liste vide sans index — la passe 3 disparaît alors purement et simplement — et
    vide aussi pour tout ``page_kind`` autre que ``cd-key`` : on ne rouvre pas la porte des
    clés à une page compte."""

    index = sitemap_index()
    if index is None or not slugs or page_kind != "cd-key":
        return []
    autres = tuple(k for k in SITEMAP_KEY_KINDS if k != page_kind)
    out: list[tuple[str, str]] = []
    vus: set[str] = set()
    for slug in slugs:
        # (slug tel qu'AKS l'écrit, gabarit) — le slug rendu doit rester NU : il devient
        # `AksResolution.slug`, que R43 compare aux slugs du titre (`own_page_slugs`).
        paires: list[tuple[str, str]] = [(slug, k) for k in index.kinds_for(slug, autres)]
        # …et la même question à la ponctuation près. Trouvé par la vérification du
        # 2026-09-22 : « Hyperdimension Neptunia Re;Birth3 » cherche `…re-birth3…` quand AKS
        # écrit `…rebirth3…`, « House of 1,000 Doors » cherche `…1-000-doors…` contre
        # `…1000-doors…`, « MotoGP24 » contre `motogp-24`. Le produit est le même, seule
        # l'écriture diffère. L'URL proposée est ensuite RÉELLEMENT téléchargée et passe les
        # gardes de nom R01 : un homonyme aplati est refusé là, comme n'importe quel autre.
        for kind in (page_kind,) + autres:
            plat = index.flat_page(f"{slug}-{kind}")
            if plat and plat.endswith("-" + kind):
                paire = (plat[: -len(kind) - 1], kind)
                if paire not in paires:
                    paires.append(paire)
        for nu, kind in paires:
            url = AKS_COMPARE_URL.format(slug=nu, kind=kind)
            if url not in vus:
                vus.add(url)
                out.append((nu, url))
    return out


# [R57] (Romain, 2026-09-23 : « tu peux pas faire comme pour les autres marchands, et si on
# a déjà des offres DLC on ajoute en DLC ? »). Le séparateur de sous-titre d'un nom de
# produit : « Crusader Kings II: Holy Fury », « Talisman - The City Expansion ».
_SUBTITLE_SPLIT_RE = re.compile(r"\s*:\s+|\s+[-–—|]\s+")


def derived_dlc_page(title: str, title_tier: str, marker: str | None,
                     resolution: "AksResolution") -> bool:
    """[R57] Un titre SANS marqueur est-il un DLC, d'après sa page ET la page de son jeu ?

    La demande de Romain, telle quelle — « si on a déjà des offres DLC, on ajoute en DLC » —
    rouvrirait exactement l'erreur que R18 a durcie le 17/09 : la page du JEU DE BASE
    « Grand Theft Auto Vice City » portait un seau DLC à côté du Standard, et le jeu est
    entré en DLC. Cette branche ne s'ouvre donc que si QUATRE faits sont réunis :

    1. le titre ne porte ni marqueur DLC ni mot d'édition (il se lit « Standard ») ;
    2. la page ne vend AUCUN seau Standard — c'est ce qui protège le cas Vice City : là où
       un Standard existe, un titre « Standard » y est rangé, comme avant ;
    3. la ligne est résolue sur la page À SON PROPRE NOM (`resolved_on_own_page`) ;
    4. la page d'un JEU PARENT existe aussi, distincte : « Europa Universalis IV: Muslim
       Advisor Portraits » a sa page ET `europa-universalis-iv` existe. C'est ce qui sépare
       un DLC d'un jeu de base : un jeu de base n'a pas, au-dessus de lui, une autre page
       dont son nom est le prolongement.

    Le seau DLC lui-même est vérifié par l'appelant (`_dlc_edition_on_page`).

    Mesuré avant d'être écrit, sur ~17 000 offres des balayages récents de TOUS les
    marchands : 41 refus E06 portaient sur une page à seau DLC ; la règle en récupère 19 —
    GOG 15, K4G 4, zéro chez les quatorze autres, qui marquent leurs DLC dans le titre — et
    les 19 sont bien des DLC, relus un par un. Générique pour cette raison.

    Fail-closed : sans index sitemap frais (condition 4 invérifiable), la branche reste
    fermée et la ligne est refusée comme avant."""

    if marker is not None or title_tier != "1":
        return False
    for bucket_id, entree in (resolution.editions or {}).items():
        if bucket_id == "1" or "STANDARD" in _edition_entry_name(entree).upper():
            return False
    index = sitemap_index()
    if index is None:
        return False
    if not resolved_on_own_page(resolution.slug, title):
        return False
    nom = cleaned_title(title).strip()
    tete = _SUBTITLE_SPLIT_RE.split(nom, maxsplit=1)[0].strip()
    if not tete or tete == nom:
        return False
    for candidat in build_slug_candidates(tete):
        if candidat == resolution.slug:
            continue
        if index.has_page(f"{candidat}-cd-key") or index.flat_page(f"{candidat}-cd-key"):
            return True
    return False


def aks_page_urls(slug: str, page_kind: str = "cd-key", *,
                  years: tuple[int, ...] | None = None) -> list[tuple[str, str]]:
    """The ordered ``(slug_variant, url)`` shapes to probe for ONE guessed slug (Romain
    2026-09-10 — "essaie le current, puis le nouveau, puis l'ancien"):

    1. current  ``buy-<slug>-cd-key-compare-prices/``
    2. new      ``buy-<slug>-<year>-cd-key-compare-prices/`` — pages AKS creates since
                2026 carry the release year (``buy-fable-2026-…``); tried for this year
                and next year, unless the slug already ends with a year;
    3. legacy   ``compare-and-buy-cd-key-for-digital-download-<slug>/`` (≈2021 pages).

    Account kinds keep their single current shape. ``years`` is injectable for tests
    (default: today's year, +1). :func:`resolve_aks` probes shape 1 for every slug tier
    first and shapes 2-3 for the most specific slug only — probing all shapes of every
    tier (×5) drove ~300 req/min and AKS answered with 503 bursts (run 2026-09-10 10:22)."""

    shapes = [(slug, AKS_COMPARE_URL.format(slug=slug, kind=page_kind))]
    if page_kind != "cd-key":
        return shapes
    if not _SLUG_YEAR_SUFFIX_RE.search(slug):
        if years is None:
            y = datetime.date.today().year
            years = (y, y + 1)
        for year in years:
            variant = f"{slug}-{year}"
            shapes.append((variant, AKS_COMPARE_URL.format(slug=variant, kind=page_kind)))
    shapes.append((slug, AKS_LEGACY_URL.format(slug=slug)))
    return shapes


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
    # og:title comes in several live grammars — always "<Name>" followed by page
    # furniture that is NEVER part of the game name:
    #   "Buy <Name> CD Key Compare Prices", "<Name> PC KEY Compare Prices" (2026-07-07),
    #   "Buy <Name> Steam Key Prices" (2026-08-25 — platform marker + "Key Prices", no
    #   "Compare"), "Buy <Name> Steam Key Compare Prices - AllKeyShop.com" and
    #   "Buy <Name> Steam Key at best Price (PC) - Allkeyshop.com" (2026-09-07 — the site
    #   suffix and the "at best Price (PC)" tail; the old $-anchored strips failed on the
    #   " - AllKeyShop.com" suffix and left "Steam Key"/"…Price (PC)" in the name, so R01
    #   demanded STEAM/KEY/PRICE/PC in merchant titles → false-skips, e.g. GTA 5 / BG3 /
    #   Helldivers 2). Entities must be unescaped ("Exile&#039;s" → EXILE/039/S false-R01).
    name = html.unescape(match.group(1))
    name = re.sub(r"(?i)^\s*buy\s+", "", name)
    # Strip the trailing " - AllKeyShop.com" site suffix FIRST, so the furniture cut below
    # is never blocked by it (og:title comes both with and without the suffix).
    name = re.sub(r"(?i)\s*[-–|]\s*allkeyshop(?:\.com)?\s*$", "", name)
    # Cut at the FIRST furniture marker — everything after it is furniture. A bare
    # trailing "Key" is NOT a marker (a real name can end in "Key" — "The Key"/"Skeleton
    # Key"): every "…Key" marker REQUIRES a "cd"/platform word before it, so the name
    # keeps its own "Key". "pc" is a platform here so "PC KEY" is furniture.
    name = re.split(
        r"(?i)\s+(?:"
        r"cd\s+keys?"
        r"|(?:steam|epic(?:\s+games)?|gog|uplay|ubisoft(?:\s+connect)?|origin|ea(?:\s+app)?|"
        r"rockstar|bethesda|windows|xbox|playstation|psn|switch|nintendo|pc)\s+keys?"
        r"|at\s+best\s+prices?"
        r"|compare\s+prices?"
        r")\b",
        name, maxsplit=1)[0]
    # A trailing "(PC)" tag or a bare trailing "PC" left over is furniture, never the name.
    name = re.sub(r"(?i)\s*\(pc\)\s*$", "", name)
    name = re.sub(r"(?i)\s+pc\s*$", "", name)
    return name.strip() or None


def _strip_furniture_key(name: str, slug: str) -> str:
    """A bare trailing "Key"/"Keys" in the AKS name is DELIVERY furniture, not identity,
    UNLESS the URL slug carries it too — the slug is the canonical product identity.

    ``extract_aks_name`` deliberately keeps a bare trailing "Key" because a real name can
    end in one ("The Key", "Skeleton Key") and the og:title alone can't tell furniture
    from identity. The slug can: "Minecraft Key" comes from slug ``minecraft`` (no "key")
    → the "Key" is furniture → "Minecraft"; "The Key" / "Skeleton Key" come from slug
    ``the-key`` / ``skeleton-key`` (carry "key") → the "Key" stays.

    Romain 2026-09-08: the bare "Key" made R01 demand KEY in the merchant title, so
    legitimate Minecraft Java/Bedrock/US offers (no "Key" in their name) were false-skipped
    as "missing AKS words: ['KEY']". Slug-gated so "The Key"/"Skeleton Key" are untouched."""

    if not name or not slug:
        return name
    slug_tokens = {t for t in re.split(r"[^a-z0-9]+", slug.lower()) if t}
    if "key" in slug_tokens or "keys" in slug_tokens:
        return name
    stripped = re.sub(r"(?i)\s+keys?\s*$", "", name).strip()
    # Only strip when a real name word survives — never reduce the name to empty.
    return stripped if stripped else name


def extract_editions(body: str) -> dict[str, Any]:
    match = re.search(r'"editions"\s*:\s*(\{(?:[^{}]|\{[^{}]*\})*\})', body)
    if not match:
        return {}
    try:
        return json.loads(match.group(1))
    except ValueError:
        return {}


def extract_regions(body: str) -> dict[str, str]:
    """The AKS page's region dropdown as ``{region_id: filter_name}`` — the real
    regions this product is sold under (R31, software entry 2026-08-11). Software
    pages use software-specific regions (GLOBAL id 532 "Microsoft Software",
    "PUBLISHER GLOBAL", "PHONE ACTIVATION") whose ids differ from the generic
    per-platform region ids, so software must map its region against THIS map, not
    guess. Pairs are pulled directly (id + filter_name) rather than full-JSON
    parsed: the region entries embed long HTML descriptions with braces/quotes
    that defeat a balanced-brace capture."""

    block = re.search(r'"regions"\s*:\s*\{(.*?)\}\s*,\s*"(?:editions|prices|merchants)"',
                      body, re.DOTALL)
    scope = block.group(1) if block else body
    out: dict[str, str] = {}
    for rid, fname in re.findall(r'"([^"]+)"\s*:\s*\{[^{}]*?"filter_name"\s*:\s*"([^"]+)"', scope):
        out.setdefault(rid, fname)
    return out


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

    # Capture the comma-separated list up to the SENTENCE-ending period (". " —
    # "official platforms: …. Depending on the store, …") or markup/quote — NOT
    # the first "." (which truncated "Battle.net" → "Battle" and lost everything
    # after it, R32 audit 2026-08-13). Internal dots (Battle.net) are kept.
    match = re.search(r'official platforms?:\s*(.+?)(?:\.(?=\s|<|$)|<|"|$)', body, re.IGNORECASE)
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
    regions: dict[str, str] = field(default_factory=dict)
    official_platforms: tuple[str, ...] = ()
    prices: tuple[dict[str, Any], ...] = ()
    # [R45] (2026-09-12) the page's platform tab bar (`<ul class="aks-offer-tabulations">`):
    # {kind: url} for every platform page of the game (kind ∈ CONSOLE_PAGE_KINDS — ps4 /
    # ps5 / xbox-one / xbox-series / nintendo-switch / nintendo-switch-2 / cd-key). A tab
    # may point to ANOTHER product (Elden Ring → "Elden Ring Tarnished Edition Nintendo
    # Switch 2"), so every target page is re-read and identity-checked before use.
    console_pages: dict[str, str] = field(default_factory=dict)
    # `<meta data-itemprop="platform" content="PC">` of the active tab ("" when absent).
    page_platform: str = ""


class AksProbeUnreliable(Exception):
    """A slug probe failed with something other than a clean 404.

    403/429/5xx/timeouts under bulk load are transient throttling, not proof
    that the product page does not exist — treating them as "no AKS page"
    makes candidate lists flap between runs. Fail closed, distinctly.
    ``status`` carries the HTTP status (None for a transport failure) so the
    match-level throttle guard can react to an explicit 429.
    """

    def __init__(self, message: str, status: int | None = None, slug: str | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.slug = slug        # which AKS page failed (the throttle guard dedupes on it)


# Audit 2026-09-09 (critic): with 0.15 s pacing + keep-alive, a 429/503 window used to
# turn EVERY offer into one probe → one 'AKS probe unreliable' skip at ~400 req/min on
# one staff-UA connection, 03_match exited 0 and a safe-auto sweep plowed on, page after
# page. The only safeguard was the human 'watched on a small batch'. Now deterministic:
THROTTLE_MAX_CONSECUTIVE_UNRELIABLE = 5
# Grace before aborting on a burst of NON-429 unreliable answers (a 4-second 503 hiccup killed
# a whole sweep on 2026-09-09): wait, retry the offer ONCE, abort only if it still fails.
# Never for a 429 (explicit rate limit = stop now). At most THROTTLE_MAX_GRACES per run.
THROTTLE_GRACE_S = 30.0
THROTTLE_MAX_GRACES = 2
# R30 site-search circuit breaker (Romain 2026-09-10): after this many CONSECUTIVE search
# failures (timeout / empty body / 5xx) in one run the endpoint is considered down for the
# rest of the run — no more 20 s timeouts per deep offer (59 × 20 s on one Kinguin page).
# Search failures never count toward the throttle abort: they say nothing about the
# product pages, which are what AKS throttles.
SEARCH_CIRCUIT_BREAKER_FAILURES = 3
SEARCH_SLUG_KEY = "site-search"
# One same-URL retry after a short pause on a 5xx / transport failure of a guessed-slug probe
# (never on 429 — explicit rate limit). MA1 is intact: the SAME tier is retried, never a lower
# one. Under an injected test http_get the retry happens without the pause.
PROBE_TRANSIENT_RETRY_WAIT_S = 2.0


class AksThrottled(Exception):
    """AKS is pushing back — a 429, or THROTTLE_MAX_CONSECUTIVE_UNRELIABLE offers in a row
    whose probe was unreliable. The match stage must STOP fail-closed (03_match exits 2 →
    a safe-auto sweep halts) instead of hammering AKS and silently false-skipping every
    remaining offer of the page."""


class _ThrottleGuard:
    """Wraps the resolver handed to :func:`match_feed` (one instance per run):

    * counts consecutive :class:`AksProbeUnreliable` outcomes on DISTINCT product pages
      (reset by any clean resolution) and raises :class:`AksThrottled` — which
      :func:`match_offer` does NOT catch — on a 429 immediately, or at the consecutive
      limit after ONE grace (sleep THROTTLE_GRACE_S, retry the offer once; at most
      THROTTLE_MAX_GRACES graces per run);
    * R30 circuit breaker: SEARCH_CIRCUIT_BREAKER_FAILURES consecutive site-search
      failures open the circuit — the resolver is then called with ``search=False`` for
      the rest of the run (only when it accepts that keyword, i.e. :func:`resolve_aks`).
      Search failures never count toward the throttle abort.

    ``stats`` (dict) is filled for match_meta: probe_unreliable, search_failures,
    search_circuit_open_offers, throttle_graces.

    ``shared`` ([R45] review fix, 2026-09-14): this guard DELEGATES its throttle state
    (consecutive count, last failed page, graces, limit, ``stats``) to another guard, so
    the anchor probes (main guard) and the console tab-page reads (page guard) of one
    run form ONE stream of probes — the sweep aborts after
    THROTTLE_MAX_CONSECUTIVE_UNRELIABLE unreliable probes across BOTH resolvers, not 2×
    (two independent guards doubled the budget and the graces). The R30 search breaker
    stays per instance (page reads never hit the search endpoint)."""

    def __init__(self, resolver: Callable[..., AksResolution | None],
                 limit: int = THROTTLE_MAX_CONSECUTIVE_UNRELIABLE, *,
                 sleep: Callable[[float], None] = time.sleep,
                 grace_s: float = THROTTLE_GRACE_S, max_graces: int = THROTTLE_MAX_GRACES,
                 search_breaker: int = SEARCH_CIRCUIT_BREAKER_FAILURES,
                 search_open: bool = False,
                 on_resolution: Callable[[Any, dict[str, Any]], None] | None = None,
                 shared: "_ThrottleGuard | None" = None) -> None:
        self._resolver = resolver
        # REVUE DE ROMAIN (2026-09-22) : « le catalogue désactive des protections contre le
        # throttling — l'enveloppe change l'IDENTITÉ du résolveur, utilisée par match_feed
        # pour activer les gardes console/compte. Un 429 sur une page PS5 devient un simple
        # skip. Cela arrive même sans catalogue activé. » Exact, et c'était le plus grave :
        # `match_feed` décide de TROIS choses par `resolver is resolve_aks` (sommeil réel,
        # résolveur de compte gardé, et surtout garde de throttle sur les pages console).
        # Mon `recorder.wrap()` rendait une NOUVELLE fonction — donc `is` faux, donc les
        # lectures de page console tournaient SANS garde, et ce depuis le commit, catalogue
        # actif ou non. Le catalogue ÉCOUTE désormais ici, au lieu d'envelopper : l'identité
        # du résolveur reste intacte et toutes les gardes se rallument.
        self._on_resolution = on_resolution
        self._sleep = sleep
        self._search_breaker = search_breaker
        self._accepts_search = _accepts_kwarg(resolver, "search")
        self.search_failures_consecutive = 0
        # A sweep may START with the circuit open (persisted from the previous page,
        # Romain GO 2026-09-10) — no 3 × timeout tax on every page while AKS search is down.
        self.search_open = bool(search_open)
        self.shared = shared
        if shared is not None:
            # One throttle state for the run: limits and counters are the shared guard's.
            self._limit = shared._limit
            self._grace_s = shared._grace_s
            self._max_graces = shared._max_graces
            self.stats = shared.stats
            return
        self._limit = limit
        self._grace_s = grace_s
        self._max_graces = max_graces
        self._consecutive = 0
        self._graces = 0
        self._last_failed_key: str | None = None
        self.stats: dict[str, int] = {"probe_unreliable": 0, "search_failures": 0,
                                      "search_circuit_open_offers": 0, "throttle_graces": 0,
                                      "search_circuit_preopened": int(bool(search_open))}

    # Throttle state — the shared guard's when delegated, else this instance's.
    @property
    def consecutive(self) -> int:
        return self.shared.consecutive if self.shared is not None else self._consecutive

    @consecutive.setter
    def consecutive(self, value: int) -> None:
        if self.shared is not None:
            self.shared.consecutive = value
        else:
            self._consecutive = value

    @property
    def graces(self) -> int:
        return self.shared.graces if self.shared is not None else self._graces

    @graces.setter
    def graces(self, value: int) -> None:
        if self.shared is not None:
            self.shared.graces = value
        else:
            self._graces = value

    @property
    def _last_failed(self) -> str | None:
        return self.shared._last_failed if self.shared is not None else self._last_failed_key

    @_last_failed.setter
    def _last_failed(self, value: str | None) -> None:
        if self.shared is not None:
            self.shared._last_failed = value
        else:
            self._last_failed_key = value

    def _call(self, name: str, kwargs: dict[str, Any]) -> AksResolution | None:
        if self.search_open and self._accepts_search:
            self.stats["search_circuit_open_offers"] += 1
            return self._resolver(name, search=False, **kwargs)
        return self._resolver(name, **kwargs)

    def __call__(self, name: str, **kwargs: Any) -> AksResolution | None:
        try:
            result = self._call(name, kwargs)
        except AksProbeUnreliable as exc:
            self.stats["probe_unreliable"] += 1
            status = getattr(exc, "status", None)
            if status == 429:
                raise AksThrottled(f"AKS answered 429 (rate limited): {exc}") from exc
            if getattr(exc, "slug", None) == SEARCH_SLUG_KEY:
                # R30 endpoint failing: not product-page throttling. Trip the breaker.
                self.stats["search_failures"] += 1
                self.search_failures_consecutive += 1
                if self.search_failures_consecutive >= self._search_breaker:
                    self.search_open = True
                raise
            # One persistently broken AKS page (a 500 on the slug shared by consecutive
            # variants of one title) is NOT throttling: a repeat of the SAME failing page
            # does not advance the count (review 2026-09-09) — only distinct pages do.
            key = getattr(exc, "slug", None) or str(exc)
            if key != self._last_failed:
                self.consecutive += 1
                self._last_failed = key
            if self.consecutive < self._limit:
                raise
            # At the limit: one grace (Romain 2026-09-10) — a short burst of 503s must not
            # kill a whole sweep, but a persistent one must still stop it fail-closed.
            if self.graces < self._max_graces:
                self.graces += 1
                self.stats["throttle_graces"] += 1
                self._sleep(self._grace_s)
                try:
                    result = self._call(name, kwargs)
                except AksProbeUnreliable as exc2:
                    raise AksThrottled(
                        f"{self.consecutive} consecutive unreliable AKS probes on distinct pages, "
                        f"still failing after a {self._grace_s:.0f}s grace (last: {exc2})"
                    ) from exc2
            else:
                raise AksThrottled(
                    f"{self.consecutive} consecutive unreliable AKS probes on distinct pages "
                    f"({self.graces} grace(s) already spent; last: {exc})"
                ) from exc
        self.consecutive = 0
        self._last_failed = None
        self.search_failures_consecutive = 0
        if result is not None and self._on_resolution is not None:
            try:
                self._on_resolution(result, kwargs)
            except Exception:                 # noqa: BLE001
                pass                          # un observateur ne casse jamais une résolution
        return result


def _accepts_kwarg(fn: Callable[..., Any], kw: str) -> bool:
    """True if ``fn`` can be called with ``kw=...`` (a keyword or **kwargs parameter)."""

    try:
        params = inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return False
    if kw in params and params[kw].kind in (inspect.Parameter.KEYWORD_ONLY,
                                             inspect.Parameter.POSITIONAL_OR_KEYWORD):
        return True
    return any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values())


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
    aks_name = _strip_furniture_key(aks_name, slug)
    return AksResolution(
        slug=slug,
        url=url,
        product_id=product_id,
        aks_name=aks_name,
        editions=extract_editions(body),
        regions=extract_regions(body),
        official_platforms=extract_official_platforms(body),
        prices=extract_prices(body),
        console_pages=extract_console_pages(body),      # [R45] platform tab bar
        page_platform=extract_page_platform(body),      # [R45] active tab platform
    )


# [R45] the slug of a KNOWN AKS page URL (a tab-bar link): `buy-<slug>-<kind>-compare-prices/`.
_AKS_PAGE_URL_RE = re.compile(
    r"/blog/buy-(.+?)-(?:" + "|".join(re.escape(k) for k in CONSOLE_PAGE_KINDS) + r")-compare-prices/?$"
)


def resolve_aks_url(url: str, http_get_fn: Callable[..., Any] = http_get) -> AksResolution | None:
    """[R45] (2026-09-12) read ONE known AKS product page by URL — a console page linked
    from the anchor page's tab bar — with the same pacing / retry / fail-closed reading as
    a guessed slug (:func:`_probe_guessed_page`): a clean 404/410 → None, anything else
    non-200 → :class:`AksProbeUnreliable`, a 200 with a product id but no readable name →
    :class:`AksNameUnreadable`. No slug guessing, no site search: the URL IS the page. A
    URL outside the known page grammar (``buy-<slug>-<kind>-compare-prices/``) → None
    (fail-closed: not a page we know how to read)."""

    match = _AKS_PAGE_URL_RE.search(url.split("?", 1)[0])
    if not match:
        return None
    slug = match.group(1)
    probe = _probe_guessed_page(url, http_get_fn)
    if probe is None:
        return None                                    # clean 404/410
    if not (probe.ok and probe.status == 200 and probe.body):
        raise AksProbeUnreliable(f"{slug} -> {probe.status or probe.error}",
                                 status=probe.status, slug=slug)
    resolution = _resolution_from_body(slug, url, probe.body)
    if resolution is None:
        if not extract_product_id(probe.body):
            return None                                # a 200 that is not a product page
        raise AksNameUnreadable(slug)                  # never fall back to the offer title
    return resolution


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
        if probe.status in (404, 410):
            return []      # clean absence, same reading as a slug probe
        # Review 2026-09-09: a throttled / failing site search used to soft-fail to [] →
        # "no AKS product page found", which masked a 429/5xx from the throttle guard and
        # even RESET its counter. Anything but 200/404/410 is unreliable, not "no result".
        raise AksProbeUnreliable(f"site search -> {probe.status or probe.error}",
                                 status=probe.status, slug=SEARCH_SLUG_KEY)
    slugs: list[str] = []
    # P3-1 (audit 2026-09-02): AKS serves BOTH the ordinary `-cd-key-` page and a
    # bare `-key-` page (e.g. buy-the-green-light-key-compare-prices/, id 216255).
    # Recognize both. The slug capture is NON-GREEDY (`+?`) so a `-cd-key-` link does
    # NOT mis-capture a trailing `-cd` ("road-to-empress-cd"); `(?:cd-)?` still cannot
    # match a `-<platform>-account-` page, so the account-page exclusion is preserved.
    for slug in re.findall(r"/blog/buy-([a-z0-9-]+?)-(?:cd-)?key-compare-prices/", probe.body):
        if slug not in slugs:
            slugs.append(slug)
        if len(slugs) >= limit:
            break
    return slugs


def _probe_guessed_page(url: str, http_get_fn: Callable[..., Any]) -> Any:
    """Paced GET of one guessed AKS page. Returns ``None`` on a clean 404/410, the probe on
    200, or — after ONE same-URL retry on a 5xx / transport failure (PROBE_TRANSIENT_RETRY_WAIT_S,
    no pause under an injected http_get) — the last failing probe for the caller to raise on.
    A 429 is never retried."""

    probe = None
    for attempt in (1, 2):
        if http_get_fn is http_get:
            time.sleep(AKS_PROBE_DELAY_S)  # politeness budget for bulk AKS runs
        probe = http_get_fn(url, timeout=8, user_agent=AKS_PROBE_UA)
        if probe.ok and probe.status == 200 and probe.body:
            return probe
        if probe.status in (404, 410):
            return None
        transient = probe.status is None or probe.status >= 500
        if attempt == 1 and transient:
            if http_get_fn is http_get:
                time.sleep(PROBE_TRANSIENT_RETRY_WAIT_S)
            continue
        break
    return probe


def resolve_aks(
    name: str, http_get_fn: Callable[..., Any] = http_get, *, page_kind: str = "cd-key",
    search: bool = True,
) -> AksResolution | None:
    """Try each candidate slug read-only; return the first real product page.

    ``page_kind`` selects the AKS page family (``cd-key`` default, or an
    account kind like ``steam-account`` — Romain 2026-07-18). Falls back to
    search_aks_slugs (R30) only when every guessed slug comes back cleanly
    404/410 AND ``page_kind`` is ``cd-key`` — the site-search result regex
    recognizes `-cd-key-` AND bare `-key-` slugs (P3-1), but never an account
    page, so there is no search fallback for account pages; they rely on
    slug-guessing alone (each fallback slug is probed as both `cd-key` and bare
    `key`). A transient or unreadable
    signal from a *guessed* slug still fails closed immediately, same as
    before; the fallback is "try harder before giving up", not a new
    correctness gate.
    """

    # Audit 2026-07-17 (MA1): the raise must be IMMEDIATE, not collected for
    # an end-of-loop check — slug tiers go from most to least specific, so a
    # throttled/unreadable answer on "some-game-deluxe-edition" shadowed by a
    # 200 on "some-game" silently resolves the wrong product tier. That is
    # exactly what the docstring always promised ("fails closed immediately")
    # and what the old collect-then-maybe-raise code did not do.
    slugs = build_slug_candidates(name)
    # Pass 1 — the current URL shape for every slug tier (most → least specific): the
    # common case, unchanged cost. Pass 2 (cd-key only) — the alternate shapes of the MOST
    # specific slug: year-suffixed (new AKS pages, e.g. buy-fable-2026-…) then legacy
    # (compare-and-buy-…, ≈2021 pages) — Romain 2026-09-10, bounded to +3 probes per
    # unresolvable offer. MA1 holds: a transient answer raises at once, never a lower tier.
    probes: list[tuple[str, str]] = [(slug, aks_url(slug, page_kind)) for slug in slugs]
    if page_kind == "cd-key" and slugs:
        probes += aks_page_urls(slugs[0], page_kind)[1:]
    # Sitemap d'abord (2026-09-24) : avec un index frais, on ne sonde que les formes qu'AKS
    # publie, plus la soupape du tier 1 — voir `sitemap_first_probes`.
    probes = sitemap_first_probes(probes, page_kind)
    sondees: set[str] = set()
    for variant, url in probes:
        sondees.add(url)
        probe = _probe_guessed_page(url, http_get_fn)
        if probe is None:
            continue                                   # clean 404/410 → next shape/tier
        if not (probe.ok and probe.status == 200 and probe.body):
            raise AksProbeUnreliable(f"{variant} -> {probe.status or probe.error}",
                                     status=probe.status, slug=variant)
        resolution = _resolution_from_body(variant, url, probe.body)
        if resolution is None:
            if not extract_product_id(probe.body):
                continue
            # Never fall back to the offer title: name checks would compare
            # the title to itself and pass anything (fail-open).
            raise AksNameUnreadable(variant)
        return resolution

    # Pass 3 (2026-09-22, Romain : « n'oublie pas le gabarit -key et l'index sitemap ») —
    # l'INDEX SITEMAP. Aucun slug deviné n'a répondu ; avant de rendre None, on demande à la
    # liste des pages qu'AKS publie lui-même si l'une d'elles porte un de nos slugs sous un
    # gabarit qu'on ne sonde pas : `-key` (404 lignes du balayage de nuit), `-steam-account`
    # (246), et le reste. Le coût est NUL quand l'index ne connaît rien — c'est une lecture
    # locale, pas une requête — ce qui est exactement la leçon du 2026-09-10 : sonder plus de
    # formes à l'aveugle avait poussé ~300 req/min et AKS répondait en 503.
    for variant, url in sitemap_shapes(slugs, page_kind):
        if url in sondees:
            # Déjà sondée en passe 1-2 : l'aplatissement de la passe 3 retombe sur la même
            # URL quand le slug exact est dans l'index. La même question aurait la même
            # réponse — une requête de moins, rien d'autre.
            continue
        probe = _probe_guessed_page(url, http_get_fn)
        if probe is None:
            # Le sitemap est une PHOTO : une page publiée hier peut avoir été retirée. Un
            # 404 propre sur une page annoncée n'est donc pas une anomalie — on continue.
            continue
        if not (probe.ok and probe.status == 200 and probe.body):
            # …en revanche un 429 / 5xx est AKS qui pousse, et doit atteindre la garde de
            # throttle comme n'importe quelle autre sonde (MA1 : immédiatement).
            raise AksProbeUnreliable(f"{variant} -> {probe.status or probe.error}",
                                     status=probe.status, slug=variant)
        resolution = _resolution_from_body(variant, url, probe.body)
        if resolution is not None:
            return resolution

    if page_kind != "cd-key" or not search:
        # no site-search fallback for account pages (see docstring), nor once the R30
        # circuit breaker is open for this run (_ThrottleGuard, 2026-09-10)
        return None
    if sitemap_is_authoritative():
        # R30 n'est pas retirée — la décision de Romain du 2026-07-16 tient — mais la
        # recherche interne d'AKS est MORTE : mesurée le 2026-09-22 depuis les DEUX VPS, elle
        # répond `HTTP 200` avec `Content-Length: 0`, vite ou lentement, avec ou sans
        # `Accept`. Elle était ouverte en disjoncteur sur 253 des 259 pages du balayage de
        # nuit. Quand l'index sitemap est frais, il répond à la même question (« cette page
        # existe-t-elle ? ») de façon complète et hors ligne : on ne paie plus 3 × 8 s pour
        # un corps vide. Index absent ou périmé → on retombe sur la recherche, inchangée.
        return None
    for slug in search_aks_slugs(name, http_get_fn):
        # P3-1: a fallback slug may live at the bare `-key-` page, not `-cd-key-`.
        # Probe both kinds (cd-key first — the common shape); the loop still soft-
        # continues on any non-200 EXCEPT an explicit 429, which is AKS pushing back and
        # must reach the throttle guard (review 2026-09-09).
        for kind in ("cd-key", "key"):
            url = aks_url(slug, kind)
            if http_get_fn is http_get:
                time.sleep(AKS_PROBE_DELAY_S)
            probe = http_get_fn(url, timeout=8, user_agent=AKS_PROBE_UA)
            if not (probe.ok and probe.status == 200 and probe.body):
                if probe.status == 429:
                    raise AksProbeUnreliable(f"{slug} -> 429", status=429, slug=slug)
                continue
            resolution = _resolution_from_body(slug, url, probe.body)
            if resolution is not None:
                return resolution
    return None


# -- results ----------------------------------------------------------------
@dataclass(frozen=True)
class Target:
    """[R45] (2026-09-12) ONE entry of a candidate: a (family, AKS product page, region
    bucket, edition) tuple. A PC candidate has exactly one (synthesized from its primary
    fields); a console candidate has one per declared platform page ("PS4 / PS5" → the PS5
    page + the PS4 page; Play Anywhere → the Xbox page(s) + the PC page under the XBOX/PC
    buckets). The submitter enters ALL of them or NONE (a consumed feed row loses its
    second platform) — until the per-target modal is observed it fails closed on > 1."""

    platform: str
    aks_product_id: str
    aks_url: str
    aks_name: str
    region_label: str
    region_id: str
    edition_label: str
    edition_id: str

    def to_dict(self) -> dict[str, Any]:
        """The nested ``candidates.json`` entry — the shape is defined ONCE in
        ``src/candidate_contract.py`` (Lot 2, 2026-09-15); the dataclass fields ARE the
        canonical flat target (``candidate_contract.TARGET_KEYS``)."""

        return candidate_contract.to_nested_target(asdict(self))


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
    # [R45] every entry of this candidate, primary first. () (the PC default) means the
    # single target synthesized from the primary fields — see ``all_targets``.
    targets: tuple[Target, ...] = ()

    @property
    def all_targets(self) -> tuple[Target, ...]:
        """The targets, never empty: the explicit ones, or the one synthesized from the
        primary fields (every PC candidate, and any console candidate with one page)."""

        if self.targets:
            return self.targets
        return (Target(self.platform, self.aks_product_id, self.aks_url, self.aks_name,
                       self.region_label, self.region_id, self.edition_label, self.edition_id),)

    def _identity_dict(self) -> dict[str, Any]:
        """``to_dict()`` without the ``fingerprint`` key — the candidate dict the shared
        contract (``src/candidate_contract.py``) fingerprints and normalises."""

        return {
            "offer": self.offer.to_dict(),
            "aks_product_id": self.aks_product_id,
            "aks_url": self.aks_url,
            "aks_name": self.aks_name,
            "platform": self.platform,
            "region": {"label": self.region_label, "id": self.region_id, "implicit": self.region_implicit},
            "edition": {"label": self.edition_label, "id": self.edition_id},
            # [R45] ALWAYS present (one synthesized target for a PC candidate) so the
            # submitter / validation read one shape for every candidates.json.
            "targets": [t.to_dict() for t in self.all_targets],
        }

    @property
    def fingerprint(self) -> str:
        """Exact submission identity — a stale approval fails if any part changes.
        [R45]: unchanged for one target; extra targets append ``|+<pid>:<region>:<edition>``
        per target. ONE definition since Lot 2 (2026-09-15): ``candidate_contract.fingerprint``
        over the serialized dict — validation, the submitter and app.js read the same
        module (or its verified port), never a second copy of the formula."""

        return candidate_contract.fingerprint(self._identity_dict())

    def to_dict(self) -> dict[str, Any]:
        return {"fingerprint": self.fingerprint, **self._identity_dict()}

    def normalized_block(self, index: int) -> str:
        platform = PLATFORM_LABEL.get(self.platform, self.platform)
        implicit = " [region implicit]" if self.region_implicit else ""
        block = (
            f"#{index} — {self.offer.name}\n"
            f"\U0001F3AF {self.aks_product_id} — {self.aks_name}\n"
            f"\U0001F517 {self.offer.url}\n"
            f"\U0001F3AF {self.aks_url}\n"
            f"{platform} {self.region_label}({self.region_id}), "
            f"{self.edition_label}({self.edition_id}){implicit}"
        )
        # [R45] one line per EXTRA target: "↳ PS4 85104 — Hades PS4 · Playstation Game Code GLOBAL(88)"
        for t in self.all_targets[1:]:
            block += (f"\n\u21B3 {t.platform} {t.aks_product_id} — {t.aks_name} · "
                      f"{t.region_label}({t.region_id})")
        return block


def _edition_entry_name(value: Any) -> str:
    """An editions-map entry's display name — tolerates both observed shapes
    ({"name": "Deluxe", …} and a bare string)."""

    return str(value.get("name", "")) if isinstance(value, dict) else str(value)


# Edition-label reconciliation (P1-1/P1-2, adversarial review 2026-09-02). Comparing a
# guessed hint label to a page label needs neither bare equality (over-skips the common
# suffixed page labels "Deluxe Edition"/"Complete Pack") nor raw substring (wrongly
# adopts a tier SUPERSET or a sub-word: "Gold"⊂"Marigold Edition", "Deluxe"⊂"Deluxe Plus
# Edition"). The safe match is TOKEN-SET EQUALITY modulo pure format noise: strip only
# "Edition"/"Pack" and stopwords, so a residual DISTINCTIVE token (PLUS/ULTIMATE/…)
# breaks the match. GOTY is expanded so its abbreviation matches "Game of the Year …".
# "Edition"/"Pack" + stopwords + pure delivery-format qualifiers ("Digital", "Version")
# — none is a distinctive tier word, so stripping them can never collapse two real tiers
# ("Digital Deluxe Edition" == "Deluxe"; adversarial review 2026-09-02, a near-universal
# premium-edition naming on AKS). Distinctive words (PLUS/ULTIMATE/GOLD/…) are NOT here.
_EDITION_FORMAT_NOISE = frozenset({
    "EDITION", "PACK", "DIGITAL", "VERSION", "OF", "THE", "AND", "A", "FOR"})
# Distinctive edition-TIER tokens: their presence in a residue means a DIFFERENT tier, so
# they must fail the sole-compatible rescue closed (never silently upgrade "Knights" →
# "Knights Deluxe"). Everything else in NOISE_TOKENS (format + PLATFORM + region words) is
# safe residue noise.
_EDITION_TIER_TOKENS = frozenset({
    "DELUXE", "ULTIMATE", "GOLD", "GOTY", "PREMIUM", "COMPLETE", "DEFINITIVE",
    "ANNIVERSARY", "REMASTER", "REMASTERED", "COLLECTION", "BUNDLE", "TRILOGY"})
# The residue a sole-compatible edition may carry over the wanted extras and still be the
# SAME tier (match_extras_to_page_edition). = the matcher's canonical noise MINUS the tier
# tokens, plus AKS's "Editon" typo. Using NOISE_TOKENS (not just the format-noise set) is
# what lets a PLATFORM word in an edition NAME be residue noise: extra_significant_words
# strips "Windows" from a "Minecraft Windows 10 Edition" offer (extras → {10}) but the
# page edition keeps it ({WINDOWS,10,EDITION}), so the residue {WINDOWS,EDITION} must be
# noise for the offer to adopt edition "Windows 10 Edition" (Romain audit 2026-09-08). A
# distinctive TIER word in the residue still fails closed (kept out of the noise set).
_EDITION_RESIDUE_NOISE = (NOISE_TOKENS - _EDITION_TIER_TOKENS) | frozenset({"EDITON"})
_EDITION_LABEL_ALIASES = (("GOTY", "GAME OF THE YEAR"),)


def expand_edition_aliases(label: str) -> str:
    """"GOTY" → "GAME OF THE YEAR" (the page and the merchant spell the same tier two
    ways). Shared by ``_edition_key`` and by the extras rescue, qui le lisait en tokens
    BRUTS : une offre « Game of the Year Edition » (extras {YEAR}) ne reconnaissait pas le
    seau « GOTY » de la page ({GOTY}) et sortait « extra words: [\'YEAR\'] » — 3 refus sur
    le balayage GameSeal du 19/09, alors que son jumeau « Fallout 4 GOTY Edition » entrait
    sur le MÊME produit en GOTY(9) (audit du 2026-09-20)."""

    up = " " + (label or "").strip().upper() + " "
    for abbr, expanded in _EDITION_LABEL_ALIASES:
        up = re.sub(r"\b" + abbr + r"\b", expanded, up)
    return up.strip()


def _edition_key(label: str) -> frozenset[str]:
    """The distinctive-token signature of an edition label (format noise + stopwords
    removed, GOTY expanded). Two labels name the same edition tier iff their keys are
    equal — never a substring/superset."""

    return frozenset(t for t in re.findall(r"[A-Z0-9]+", " " + expand_edition_aliases(label) + " ")
                     if t not in _EDITION_FORMAT_NOISE)


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


def fold_accents(text: str) -> str:
    """Strip diacritics: "CRÉDITS" → "CREDITS", "Abonnés" → "Abonnes".

    NFKD decomposes an accented letter into its base letter + a combining mark, and the
    marks are then dropped. Added 2026-09-16 after an adversarial review of a FRENCH
    storefront (GamesPlanet FR): every categorical skip vocabulary here is ASCII English
    (`CATEGORY_SKIP`, `CURRENCY_TOKENS`…) and `_norm_tokens` replaced any non-ASCII letter
    by a SPACE, so "CRÉDITS" became the two junk tokens "CR" and "DITS" and the `CREDITS`
    entry that already existed never matched. Folding can only make a vocabulary word
    match text that means it — it never invents a new word (an accented word whose folded
    form is NOT in the vocabulary still does not match)."""

    return "".join(c for c in unicodedata.normalize("NFKD", text or "")
                   if not unicodedata.combining(c))


def _norm_tokens(s: str) -> str:
    """Uppercase, ACCENTS FOLDED, non-alphanumerics → single spaces, trimmed — the shared
    shape for word-boundary substring matching (padded with spaces at the call site)."""
    return re.sub(r"[^A-Z0-9]+", " ", fold_accents(s or "").upper()).strip()


def is_software_title(offer: NormalizedOffer) -> bool:
    """Title-only software signal: a curated brand/category token
    (SOFTWARE_APP_TOKENS) or the OS-licence regex. Used by the SORT to group
    software under the Softwares list WITHOUT fetching the AKS page (R31); the
    entry classifier :func:`is_software` layers the page markers on top."""

    padded = " " + _norm_tokens(offer.name) + " "
    if any(f" {t} " in padded for t in SOFTWARE_APP_TOKENS):
        return True
    return bool(_WINDOWS_OS_RE.search(offer.name.upper()))


def is_software(offer: NormalizedOffer, resolution: AksResolution) -> bool:
    """True when the offer is software/app (R31) → routed to the SOFTWARE PATH
    (page-driven edition/region, skip-on-ambiguity) instead of the game path.
    Two precise signals, either suffices:
      - a curated software token in the merchant TITLE (see is_software_title), or
      - the resolved AKS PAGE carrying an edition/region label only software ever
        uses (OEM / RETAIL / LTSC / N EDITION / PHONE ACTIVATION …).
    A game never carries a software brand name nor an OEM/RETAIL edition, so a
    game is never misrouted — game behaviour is untouched (Romain: software-only,
    zero game regression)."""

    if is_software_title(offer):
        return True
    # Word-boundary, PER LABEL: a marker must be a whole token/phrase in one
    # edition/region label. Raw substring scanning of a concatenated blob wrongly
    # fired "N EDITION" inside a game's "ChampioN EDITION" (R31 audit 2026-08-11).
    labels = [_edition_entry_name(v) for v in resolution.editions.values()]
    labels += list(resolution.regions.values())
    for label in labels:
        padded = " " + _norm_tokens(label) + " "
        if any(f" {m} " in padded for m in _SOFTWARE_PAGE_EDITION_MARKERS):
            return True
    return False


def resolve_software_edition(
    offer: NormalizedOffer, editions: dict[str, Any]
) -> tuple[str, str] | None:
    """Map a software offer to ONE edition ON THE PAGE (R31), or None → skip.
    Software editions are licence types (OEM / Retail / 1 PC / Lifetime / 1 Month)
    taken from the page itself — never the game 'Standard' default (Adobe has no
    Standard at all). Rule:
      - a page edition LABEL that appears in the merchant title, longest wins;
      - exactly one longest match → take it;
      - a tie at the longest length → ambiguous → skip;
      - no label in the title → take it ONLY if the page lists a single edition;
        with ≥2 editions and no title signal we do NOT guess → skip."""

    padded = " " + _norm_tokens(offer.name) + " "
    matches: list[tuple[str, str, str]] = []  # (norm, edition_id, label)
    for eid, value in editions.items():
        label = _edition_entry_name(value)
        norm = _norm_tokens(label)
        if norm and f" {norm} " in padded:
            matches.append((norm, eid, label))
    if matches:
        winner = max(matches, key=lambda m: len(m[0]))
        # Every OTHER match must be NESTED in the winner (same licence dimension:
        # "Retail 5 PC" contains "Retail"/"5 PC"). Two INDEPENDENT dimensions both
        # in the title with no combined SKU ("Retail" + "1 PC", no "Retail 1 PC"
        # edition) would be decided by raw string length — a guess → skip (R31
        # audit 2026-08-11). This also subsumes the equal-length tie (not nested).
        w = " " + winner[0] + " "
        if any(m is not winner and f" {m[0]} " not in w for m in matches):
            return None
        return (winner[1], winner[2])
    # Nothing in the title → take a SINGLE edition, but NEVER a lone generic
    # "Standard": that is the guessed-Standard R31 forbids (Adobe has no Standard;
    # software's real edition is a licence type). ≥2 editions with no signal → skip.
    if len(editions) == 1:
        (eid, value), = editions.items()
        if _norm_tokens(_edition_entry_name(value)) == "STANDARD":
            return None
        # [25] Fable re-audit 2026-09-06: we only reach here with NO page-edition label in
        # the title. If the title still carries a licence/duration SIGNAL (it just didn't
        # match this lone edition — e.g. a "1 Year" offer on a lone "Lifetime" page),
        # auto-taking the lone edition enters the WRONG licence. Any unmatched licence
        # token → fail-closed skip, never guess (mirror EXECUTOR_RULES §4.9).
        if _SOFTWARE_LICENCE_SIGNAL_RE.search(padded):
            return None
        return (eid, _edition_entry_name(value))
    return None


# Licence / duration signals in a software title (uppercased, space-normalised form).
_SOFTWARE_LICENCE_SIGNAL_RE = re.compile(
    r" (?:LIFETIME|OEM|RETAIL|LTSC|\d+\s*(?:PC|DEVICES?|MONTHS?|YEARS?)) ")


def match_extras_to_page_edition(
    extras: list[str], editions: dict[str, Any]
) -> tuple[str, str] | None:
    """Page-verified rescue for the different-product guard: when EVERY merchant
    "extra" token (a word absent from the AKS game name and not format/region/edition
    noise) is contained in a page edition's OWN name, those tokens NAME that edition —
    not a different product. "Legends of Eisenwald - Knight's Edition" (URL
    ``…-knights-edition-…``) → the page's "Knights Editon" (id 2723): the shared
    signal is the token KNIGHTS, apostrophe-folded, NOT the "Edition"/"Editon" suffix
    (AKS typos it; the merchant apostrophizes it).

    Resolution is DETERMINISTIC and fail-closed (Romain review 2026-09-01) — never a
    guess by token count or dict order:
      - exactly ONE compatible edition → resolve to it;
      - ≥2 compatible editions → the title carries no signal to choose between them
        ("KNIGHTS" fits both "Knights Edition" and "Knights Deluxe Edition", with no
        DELUXE in the title) → None UNLESS a SINGLE edition's distinctive tokens (its
        name minus format/edition NOISE) EXACTLY equal the wanted tokens;
      - anything else (extra split across editions, an extra in NO edition — a
        distinguishing subtitle like "… Valhalla Edition" on a page with no Valhalla
        edition, a Standard/Bundle-only match) → None → stays a SKIP.
    Bundles are never rescued (absolute)."""

    want = {t.replace("'", "") for t in extras}
    if not want:
        return None
    compatible: list[tuple[str, str, set[str]]] = []
    for eid, value in editions.items():
        # L'alias est appliqué AVANT la tokenisation (2026-09-20) : le seau « GOTY » de la
        # page doit se comparer aux extras d'un titre « Game of the Year Edition ».
        etoks = {t.replace("'", "") for t in tokenize(expand_edition_aliases(_edition_entry_name(value)))}
        if not etoks or etoks == {"STANDARD"}:
            continue
        if etoks & {"BUNDLE", "PACK", "TRILOGY"}:
            continue                       # never enter bundles (absolute)
        if want <= etoks:
            compatible.append((eid, _edition_entry_name(value), etoks))
    if len(compatible) == 1:
        # Fable re-audit 2026-09-06: adopt the sole compatible edition ONLY when its
        # residue (tokens minus the wanted extras) is pure edition-FORMAT noise — NEVER a
        # distinctive TIER word. `want <= etoks` (subset) alone upgraded a plain offer to
        # the page's higher tier (want={KNIGHTS} ⊆ {KNIGHTS,DELUXE,EDITION}: DELUXE is
        # stripped from `want` as noise, so the subset test passes) — a wrong-tier write
        # that safe-auto auto-approves. Residue of pure format noise (incl. the "Editon"
        # typo) keeps the endorsed Eisenwald "Knights Editon"(2723) rescue resolving.
        if (compatible[0][2] - want) <= _EDITION_RESIDUE_NOISE:
            return (compatible[0][0], compatible[0][1])
        return None
    if not compatible:
        return None
    # ≥2 compatible: only a UNIQUE exact match (distinctive tokens == wanted) may win;
    # ties (or several exacts) are ambiguous → fail-closed skip. Order-independent.
    exact = [c for c in compatible
             if {t for t in c[2] if t not in NOISE_TOKENS} == want]
    if len(exact) == 1:
        return (exact[0][0], exact[0][1])
    return None


def resolve_software_region(
    region_label: str, regions: dict[str, str]
) -> tuple[str, str] | None:
    """Map the offer's region to ONE region id ON THE PAGE (R31), or None → skip.
    Software regions are page-specific (GLOBAL id 532 "Microsoft Software",
    "PUBLISHER GLOBAL" id 1, "PHONE ACTIVATION") — the generic per-platform region
    id never matches. Exact filter-name match wins; else a unique substring match
    (offer GLOBAL inside page "PUBLISHER GLOBAL"); else a single page region is
    taken unambiguously; anything ambiguous → skip."""

    want = _norm_tokens(region_label)
    if not regions:
        return None
    exact = [(rid, fname) for rid, fname in regions.items() if _norm_tokens(fname) == want]
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        return None
    sub = [
        (rid, fname) for rid, fname in regions.items()
        if want and f" {want} " in f" {_norm_tokens(fname)} "
    ]
    if len(sub) == 1:
        return sub[0]
    if len(sub) > 1:
        return None
    if len(regions) == 1:
        (rid, fname), = regions.items()
        norm = _norm_tokens(fname)
        # Take the lone region only when it is a GLOBAL/PUBLISHER type, or the
        # offer carries no concrete region — NEVER file a GLOBAL offer under a lone
        # country region (R31 audit: {"7":"TURKEY"} + a GLOBAL offer must skip).
        # NB (Fable re-audit 2026-09-06, finding [7] — DECLINED by Romain 2026-09-07):
        # the auditor flagged that a US/EU-locked software offer is also filed under a
        # lone GLOBAL/PUBLISHER page here. That DIRECTLY contradicts the Romain-reviewed
        # R31 catch-all ("a lone GLOBAL/PUBLISHER region is still taken for an unknown
        # label", 2026-08-11) — software licences are global, the merchant region label
        # is usually noise. Romain reviewed the finding and decided KEEP AS-IS ("laisse
        # [7] tel quel, ne durcis pas"). Do NOT re-tighten — this is a deliberate call,
        # not an oversight, and re-audits will re-flag it.
        if not want or "GLOBAL" in norm or "PUBLISHER" in norm:
            return (rid, fname)
        return None
    return None



@dataclass(frozen=True)
class _Plan:
    """[R45] (2026-09-12) what the resolution step hands to the common guard / edition
    flow of :func:`match_offer` — produced by :func:`_pc_plan` (the historical PC / account
    / software path, unchanged) or :func:`_console_plan` (the console branch)."""

    resolution: AksResolution
    platform: str
    region_label: str
    region_id: str
    implicit: bool
    declared_platform: str | None
    difmark_platform_verified: bool
    dlc_page: bool
    identity_name: str
    # The merchant text the R01 / R16 / R01b guards and detect_edition read: the raw
    # title for PC (unchanged), the console classifier's resolve_name (platform / store /
    # region markers removed, edition words kept) for a console row.
    guard_name: str
    # Console only: (family, page, bucket label, bucket id) per declared platform page,
    # primary first (the page `resolution` IS). () for PC.
    console_targets: tuple[tuple[str, AksResolution, str, str], ...] = ()
    # Console only ([R45] review fix, 2026-09-14): the BASE region label ("US" / "EU" /
    # "UK" / "GLOBAL") the buckets were derived from — `region_label` is the bucket text
    # ("Xbox Game Code US"), which R44 cannot look up. None for PC (region_label is the
    # base label there already).
    base_label: str | None = None

    @property
    def console(self) -> bool:
        return bool(self.console_targets)


def r43_dlc_page_refusal(dlc_marker: str, resolution: AksResolution, resolve_name: str,
                         title: str, stamp: str = "R43") -> str | None:
    """[R43] — THE check that a title announcing a DLC / season pass (``dlc_marker``) sits on
    the DLC's OWN AKS page; the refusal reason, or None. ONE implementation, read by the PC
    path (:func:`_pc_plan`) and, since P5 (Romain 2026-09-25, « P5 A »), by the console branch
    for EVERY target page (:func:`_console_plan`, ``stamp="R43, R45"``). Three facts, in order:

    1. the page's editions map carries the DLC bucket — that page IS a DLC (the same truth R18
       reads for hidden DLCs); any other page (the base game reached through a less specific
       slug tier, an empty stub map, a wrong product) is refused;
    2. AUDIT DU 2026-09-18 — a DLC marker with NO DLC name of its own (no subtitle in
       ``title``: "<Game> (DLC)") on a page that also sells a bucket OTHER than DLC is
       indistinguishable from the base game's own page carrying a DLC bucket (live
       2026-09-11: Stray Blade, Aliens Dark Descent, Dragon Quest III HD-2D Remake base pages
       all carry bucket 16) → refused. The guard used to test Standard by the LITERAL key
       « 1 »; a multi-bucket page whose Standard is « Standard + DLC » (id 518) opened it. The
       spec says « a DLC-only page ({16} without Standard) still enters », implemented
       literally: any bucket other than DLC fires it. Season / Expansion passes are exempt
       (they name their page);
    3. the page was reached under the title's OWN full name (:func:`resolved_on_own_page`,
       tier 1), never via the edition-stripped or dash-split base-game tiers — the DLC bucket
       alone is not proof the page is THIS DLC. Measured 2026-09-11: 204/205 dry-run DLC
       candidates resolve at tier 1. A console page's ``slug`` is the bare game slug (the
       capture before ``-<kind>-compare-prices``), so the same comparison holds there.

    ``resolve_name`` is the marker-stripped name the page was resolved from; ``title`` the
    text whose subtitle check (2) reads — the raw title on PC (unchanged), the console
    classifier's ``resolve_name`` on a console row (the raw console title always carries a
    " - " of platform / region furniture, which would silence the check)."""

    if not _dlc_edition_on_page(resolution.editions):
        return (f"{dlc_marker} in title but AKS page {resolution.slug!r} carries no DLC "
                f"edition — base game or wrong product, not entered ({stamp})")
    _non_dlc_buckets = [k for k, v in resolution.editions.items()
                        if k != "16" and _edition_entry_name(v).strip().upper() != "DLC"]
    if (dlc_marker not in _DLC_PASS_MARKERS and _non_dlc_buckets
            and not re.search(r"\s[-–—:|]\s|:\s", cleaned_title(strip_dlc_marker(title)))):
        return (f"{dlc_marker} in title without a DLC name of its own, on a page that also "
                f"sells a non-DLC edition ({resolution.slug!r}) — base game or unnamed DLC, "
                f"not entered ({stamp})")
    if not resolved_on_own_page(resolution.slug, resolve_name):
        return (f"{dlc_marker} in title resolved through a less specific slug tier "
                f"({resolution.slug!r} is not the page of {resolve_name!r}) — not the DLC's "
                f"own page, not entered ({stamp})")
    return None


def _pc_plan(
    offer: NormalizedOffer,
    resolver: Callable[..., AksResolution | None],
    difmark_offer_resolver: Callable[[str], DifmarkOfferAttributes],
    account_resolver: Callable[..., AksResolution | None],
) -> _Plan | SkippedOffer:
    """The PC / account / software resolution path of :func:`match_offer` — platform,
    region, AKS page ([R43] DLC checks included) and the identity name the guards compare
    against. Moved out of match_offer verbatim for [R45] (2026-09-12) so the console
    branch (:func:`_console_plan`) can share the guard / edition flow that follows;
    behaviour unchanged."""

    is_difmark = offer.merchant.strip().upper() == "DIFMARK"
    _cfg = merchant_config(offer.merchant)
    # Platform source is per-merchant (R32b, 2026-08-27 — Romain: "ça dépend du
    # marchand"): the TITLE by default, but a merchant whose titles are unreliable for
    # the platform (G2A) reads it from the URL instead (title_is_platform_source=False).
    # The URL fallback runs for every merchant, so a title-sourced merchant that simply
    # omitted the token still picks up a URL-declared platform when one is present.
    _title_src = _cfg is None or _cfg.title_is_platform_source
    declared_platform = (explicit_platform(offer.name) if _title_src else None) \
        or explicit_platform_from_url(offer.url, offer.merchant)
    # R32 (2026-08-11): merchant config — when the platform is not in the title,
    # read it from the merchant's OWN offer page (Instant Gaming: token-less titles
    # hide a Steam key; a whole IG sweep wrongly defaulted to Publisher). Fail
    # closed if the page is unreadable or names an unrecognized platform — never
    # guess. Games from merchants without a config are unchanged.
    _page_region_resolved = False             # R33: the offer page gave a region
    _page_region_base: str | None = None      #      → ENTER with this base, or
    _page_region_label = ""                   #      → forbidden region: <label> skip
    # A merchant whose signals live on its OWN offer page (Instant Gaming) is
    # resolved EVEN when the feed title already carries a platform token: the region
    # is NEVER in an IG title, so gating this on `declared_platform is None` would let
    # a region-locked "…Steam…" title default to implicit GLOBAL — R33's exact bug
    # class (region-safety must not depend on platform-resolution). The page platform
    # only OVERRIDES when the title gave none. Fail closed: unreadable page or an
    # unrecognized page platform → skip, never a guess.
    if _cfg is not None and _cfg.offer_page_resolver is not None:
        try:
            # Le titre est passé au résolveur : certains marchands y écrivent ce que
            # l'URL tait, et le lire évite d'ouvrir la page (Romain 2026-09-18).
            _sig = _cfg.offer_page_resolver(offer.url, offer.name)
        except Exception as exc:  # noqa: BLE001 — page unreadable → fail closed
            return SkippedOffer(
                offer, f"{offer.merchant} offer page unreadable — unverifiable (R32): {exc}")
        if _sig.platform is None:
            return SkippedOffer(
                offer, f"{offer.merchant} offer page names an unrecognized platform — not entered (R32)")
        if declared_platform is None:
            declared_platform = _sig.platform
        elif _sig.platform != declared_platform:
            # Audit #1 (Romain 2026-08-14): the title declared one platform, the
            # offer page (authoritative for THIS listing) another. Do not blindly
            # trust the title — a conflict is a fail-closed skip.
            return SkippedOffer(
                offer,
                f"{offer.merchant} platform conflict: title={declared_platform} "
                f"vs offer page={_sig.platform} — not entered (audit #1)")
        _page_region_resolved = _sig.region_resolved
        _page_region_base = _sig.region_base
        _page_region_label = _sig.region_label
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
        # 2026-09-25 : the page wording decided ALONE, and silence meant KEY — « ACCOUNT » in
        # `offer_name`, else the key page. Real wordings are « ⭐️ Stellaris +14 Games
        # [Steam/Global][OFFLINE] », « Beasts of Bermuda [STEAM/GLOBAL][OFFLINE] » (OFFLINE =
        # a shared offline account): eight rows of the ACCOUNT list (30) went to the Steam KEY
        # page under GLOBAL(2) on 2026-09-23. The page now has to SAY which it is:
        #   - ACCOUNT or OFFLINE in `offer_name`, or ACCOUNT in the title → account;
        #   - the 2026-07-17 key wording « <Game> (<platform>) … » (the API platform alone in
        #     parentheses, e.g. « (Steam) »), or the word KEY → key — the reviewed « vraie clé
        #     Difmark » of 2026-09-21 keeps passing (the URL's « account » is template here);
        #   - anything else (« [Steam/Global] » with no OFFLINE…) → refused, never a key by
        #     default.
        _name_up = difmark_attrs.offer_name.upper()
        difmark_is_account = (
            re.search(r"\b(?:ACCOUNT|OFFLINE)\b", _name_up) is not None
            or account_signal(offer.name, "", offer.merchant) == "title")
        _explicit_key = (
            re.search(r"\bKEY\b", _name_up) is not None
            or (bool(difmark_attrs.raw_platform)
                and f"({difmark_attrs.raw_platform.strip().upper()})" in _name_up.replace("( ", "(").replace(" )", ")")))
        if not difmark_is_account and not _explicit_key and (difmark_attrs.offer_name or "").strip():
            return SkippedOffer(
                offer,
                f"Difmark : la page ne dit ni compte ni clé ({difmark_attrs.offer_name!r}) — "
                "type invérifiable, jamais entré comme clé par défaut")
        # REVUE DE ROMAIN (2026-09-21, e596cd3 → 5d163e1) : « la branche compte peut encore
        # produire une CLÉ. Reproduit avec une URL ps5-account, un titre sans (Account), une
        # API indiquant STEAM et un offer_name VIDE : candidat sur la page de clé, région
        # GLOBAL(2). Cette ligne était refusée avant le pull ; le nouvel aiguillage doit
        # imposer une preuve du type de compte. » Exact, et c'est MA régression : en retirant
        # ces lignes au classifieur console, j'ai retiré le refus qui les protégeait.
        #
        # La réponse n'est PAS de refuser toute ligne dont l'URL dit « account » : chez
        # Difmark ce segment est du GABARIT, présent sur toutes les annonces quel que soit le
        # type (docs/MERCHANTS.md) — de vraies clés passent par là. La réponse est d'exiger
        # que la page PARLE, et qu'elle ne se contredise pas :
        #   (a) `offer_name` vide ⇒ on ne sait pas ⇒ refus (c'est le cas de la reproduction) ;
        #   (b) la famille que l'URL déclare (ps5-account, xb1, epic-games-account…) doit
        #       s'accorder avec la plateforme que la page annonce — « URL PS5 + page STEAM »
        #       est une contradiction, pas un candidat.
        if not (difmark_attrs.offer_name or "").strip():
            return SkippedOffer(
                offer,
                "Difmark : la page ne nomme pas l'offre (offer_name vide) — type de compte "
                "invérifiable, jamais entré comme clé")
        _url_family = difmark_url_account_platform(offer.url)
        _page_family = DIFMARK_PLATFORM_TEXT_MAP.get(difmark_attrs.raw_platform) or (
            DIFMARK_ACCOUNT_PLATFORMS_PENDING.get(difmark_attrs.raw_platform))
        if _url_family and _page_family and _url_family != _page_family:
            return SkippedOffer(
                offer,
                f"Difmark : l'URL déclare {_url_family} et la page {_page_family} "
                f"({difmark_attrs.raw_platform!r}) — déclaration contradictoire, non entré")
        if declared_platform is None:
            mapped_platform = DIFMARK_PLATFORM_TEXT_MAP.get(difmark_attrs.raw_platform)
            if mapped_platform is None:
                # Le TYPE de compte est lu, mais AKS n'a pas encore (pour ce catalogue) la
                # page « <plateforme> Account » ni le seau correspondant — 50 titres réels
                # sondés le 2026-09-21 sur six gabarits : 0 page. Le refus le DIT, au lieu
                # de prétendre que la plateforme est inconnue : le jour où l'on en trouve
                # une, la plateforme passe dans DIFMARK_ACCOUNT_PAGE_KINDS (Romain :
                # « quand tu trouveras du Epic account, tu ajouteras l'Epic account »).
                pending = DIFMARK_ACCOUNT_PLATFORMS_PENDING.get(difmark_attrs.raw_platform)
                if pending and difmark_is_account:
                    return SkippedOffer(
                        offer,
                        f"compte {pending} — pas encore de page ni de seau AKS confirmés "
                        f"pour ce type de compte (Steam seul aujourd'hui)")
                return SkippedOffer(
                    offer, f"Difmark page platform unrecognized: {difmark_attrs.raw_platform!r}"
                )
            declared_platform = mapped_platform
            difmark_platform_verified = True

    # A green gift's REAL platform (→ which gmg_gift region) is not in a token-less
    # G2A slug; it lives on the merchant offer page. For a merchant whose page we can't
    # open yet (R32c: G2A hard-blocks fetches with 403), the platform is UNVERIFIABLE →
    # fail-closed skip with a clear, specific reason (not the generic R27), and flagged
    # as pending the browser page-read work. When the platform IS known (readable page,
    # or a URL that declares it) the green gift resolves its gmg_gift region below.
    if declared_platform is None and _cfg is not None and not _cfg.offer_page_readable \
            and is_green_gift(offer.name, offer.url):
        return SkippedOffer(
            offer,
            f"{offer.merchant} green gift — real platform is only on the merchant offer "
            "page, not openable yet (R32c); pending browser page-read")
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

    # R33 (2026-08-13): the merchant offer page's REGION overrides the title/URL
    # default (Instant Gaming feed titles carry no region, so detect_region always
    # said implicit GLOBAL — a whole IG sweep entered 32/54 region-locked offers as
    # GLOBAL). Two outcomes (Romain's region policy 2026-08-13):
    #   - a sellable base (worldwide→GLOBAL, Europe→EU, US, UK) → ENTER with it;
    #   - otherwise → a ``forbidden region: <label>`` skip, using the SAME reason
    #     format as the generic title/URL path so the ONE central router
    #     (aks_lists.suggest_target_list) routes it: LATAM / Brazil / Asia / Russia →
    #     Blacklist, everything else (ROW / North America / …) → garder.
    if _page_region_resolved:
        if _page_region_base is not None:
            _rid = _region_id(platform, _page_region_base)
            if _rid is None:
                return SkippedOffer(offer, f"region {_page_region_base!r} unavailable for {platform} (R33)")
            region_label = {"global": "GLOBAL", "eu": "EU", "us": "US", "uk": "UK"}[_page_region_base]
            region_id, implicit = _rid, False
        else:
            return SkippedOffer(offer, f"forbidden region: {_page_region_label}")

    # Account offers resolve AKS's dedicated account PAGE, not the game key
    # page (Romain 2026-07-18). The account page is a distinct product (own id
    # / editions / prices), and its name ends with the page-kind words
    # ("<game> Steam Account") — page-type metadata the merchant feed title
    # never carries, so R01 compares against the stripped identity below.
    account_page_kind: str | None = None
    if is_difmark and difmark_is_account:
        account_page_kind = DIFMARK_ACCOUNT_PAGE_KINDS.get(platform)
        if account_page_kind is None:
            return SkippedOffer(
                offer, f"Difmark account page kind unknown for platform {platform!r}"
            )

    # Merchant-config override hook (R32e, 2026-09-10): the merchant may rewrite the text
    # handed to AKS resolution (MMOGA peels the "<CODE> Key" tail → slug "borderlands-2",
    # not the 404 "borderlands-2-eu"). The identity checks keep using the raw title.
    # [R43] the DLC marker is not part of the AKS slug ("… Clan of the Horse (DLC)" →
    # northgard-svardilfari-clan-of-the-horse); Season/Expansion Pass words are kept.
    dlc_marker = title_dlc_marker(offer, _cfg)
    resolve_name = resolution_name(offer, _cfg)
    try:
        if account_page_kind is not None:
            resolution = account_resolver(resolve_name, page_kind=account_page_kind)
        else:
            resolution = resolver(resolve_name)
    except AksProbeUnreliable as exc:
        return SkippedOffer(offer, f"AKS probe unreliable (throttled?): {exc}")
    except AksNameUnreadable as exc:
        return SkippedOffer(offer, f"AKS page name unreadable — cannot verify product (R01): {exc}")
    except AksPageUnparseable as exc:
        return SkippedOffer(
            offer, f"AKS page markup drifted — guard input unreadable (MA6): {exc}"
        )
    if resolution is None:
        kind_note = f" {account_page_kind}" if account_page_kind else ""
        return SkippedOffer(offer, f"no AKS{kind_note} product page found (slug not 200)")

    # [R43] (Romain GO 2026-09-11): a title that ANNOUNCES a DLC / season pass must land
    # on the DLC's OWN AKS page, carrying the DLC bucket — see :func:`r43_dlc_page_refusal`
    # (shared with the console branch since P5, 2026-09-25). BEFORE the name guards so the
    # reason is explicit. R16 (the DLC's own words absent from a base-game name) stays the
    # second net behind it.
    dlc_page = bool(_dlc_edition_on_page(resolution.editions))
    if dlc_marker is not None:
        refusal = r43_dlc_page_refusal(dlc_marker, resolution, resolve_name, offer.name)
        if refusal is not None:
            return SkippedOffer(offer, refusal)

    # R01 / different-product guards compare against the game-identity name.
    # For an account page that means stripping the "<platform> Account" suffix;
    # a suffix-less account page (None) is a fail-closed "not really an account
    # page" skip.
    if account_page_kind is not None:
        identity_name = account_identity(resolution.aks_name, account_page_kind)
        if identity_name is None:
            return SkippedOffer(
                offer,
                f"resolved {account_page_kind} page name {resolution.aks_name!r} "
                "is not an account page (suffix absent) — fail closed",
            )
    else:
        identity_name = resolution.aks_name

    # Merchant-config override hook (R32e, 2026-09-14 — Romain: « Kinguin valid until juin
    # 2027 on rentre », « Steam Altergift = Steam Gift on rentre »): the merchant may hand
    # the identity guards (R01 / R16 / R01b) and detect_edition its title with its own
    # NON-PRODUCT note stripped — and only that (Kinguin "(valid until <Month> <Year>)",
    # K4G "Altergift"). The raw title for every merchant without the hook (unchanged); an
    # empty answer falls back to the raw title (the stricter read — never an empty guard).
    guard_name = (_cfg.guard_name(offer.name) if _cfg is not None and _cfg.guard_name else "") or offer.name

    return _Plan(
        resolution=resolution,
        platform=platform,
        region_label=region_label,
        region_id=region_id,
        implicit=implicit,
        declared_platform=declared_platform,
        difmark_platform_verified=difmark_platform_verified,
        dlc_page=dlc_page,
        identity_name=identity_name,
        guard_name=guard_name,
    )


def match_offer(
    offer: NormalizedOffer,
    resolver: Callable[..., AksResolution | None] = resolve_aks,
    difmark_offer_resolver: Callable[[str], DifmarkOfferAttributes] = resolve_difmark_offer,
    account_resolver: Callable[..., AksResolution | None] = resolve_aks,
    *,
    page_resolver: Callable[[str], AksResolution | None] = resolve_aks_url,
    consoles: bool = False,
) -> Candidate | SkippedOffer:
    reason = precheck_skip(offer, consoles=consoles)
    if reason:
        return SkippedOffer(offer, reason)

    # [R45] (2026-09-12) console branch: a classified console row (consoles=True, no
    # skip_reason — precheck_skip already returned one otherwise) resolves its platform
    # PAGES and buckets in _console_plan; every other row takes the historical PC path.
    # Both rejoin the common flow below (R44 → R01/R16/R01b → R19 → platform → edition).
    # AIGUILLAGE COMPTE (Romain, 2026-09-21 : « elle ne doit pas continuer à passer par la
    # branche console, elle doit être routée vers une branche compte. Elle utilisera la
    # branche jeu ou la branche console selon le type d'account »). Un marchand qui déclare
    # `account_row` dit que CETTE ligne vend un COMPTE : le compte est le produit, pas un
    # marqueur non-jeu. Elle prend donc la branche compte (`_pc_plan`, qui lit la page
    # marchande et exige une PAGE AKS « <plateforme> Account » + un SEAU « Account »), et
    # jamais le chemin des clés console — c'est cet aiguillage, et non le refus « ACCOUNT —
    # not a game » du 14/09, qui empêche désormais un compte d'être entré comme une clé.
    _account_cfg = merchant_config(offer.merchant)
    _is_account_row = bool(
        _account_cfg is not None and _account_cfg.account_row
        and _account_cfg.account_row(offer.name, offer.url))
    console_sig = (classify_console(offer.name, offer.url, offer.merchant)
                   if consoles and not _is_account_row else None)
    if console_sig is not None:
        plan = _console_plan(offer, console_sig, resolver, page_resolver)
    else:
        plan = _pc_plan(offer, resolver, difmark_offer_resolver, account_resolver)
    if isinstance(plan, SkippedOffer):
        return plan
    _cfg = merchant_config(offer.merchant)
    resolution, platform = plan.resolution, plan.platform
    region_label, region_id, implicit = plan.region_label, plan.region_id, plan.implicit
    declared_platform, difmark_platform_verified = plan.declared_platform, plan.difmark_platform_verified
    dlc_page, identity_name, guard_name = plan.dlc_page, plan.identity_name, plan.guard_name

    # [R44] a region phrase that is part of the resolved product name is identity, not
    # a lock (see _REGION_IDENTITY_PHRASES) — fail-closed skip unless the merchant's
    # title grammar itself declared the region (hook = authoritative, R32e).
    hook_region = _cfg.title_region(offer.name) if _cfg is not None and _cfg.title_region else None
    # [R45] review fix (2026-09-14): a console plan's region_label is the BUCKET text
    # ("Xbox Game Code US"), which R44 cannot look up — it reads the BASE label the plan
    # kept (plan.base_label, "US") against the page IDENTITY (platform suffix removed:
    # "Air Force United States Pacific Xbox One" → "… Pacific"); the console grammar's own
    # region slot (sig.region_base) is authoritative like a merchant hook. PC rows: the
    # same call as before (base label = region_label, raw page name).
    r44_label = plan.base_label or region_label
    r44_name = identity_name if plan.console else resolution.aks_name
    grammar_region = hook_region is not None or (
        console_sig is not None and console_sig.region_base is not None)
    identity_phrase = region_phrase_in_aks_name(r44_label, r44_name)
    if identity_phrase is not None and not grammar_region:
        return SkippedOffer(
            offer,
            f"region {r44_label} read from {identity_phrase!r}, which is part of the AKS "
            f"product name {resolution.aks_name!r} — region ambiguous, not entered (R44)",
        )

    # R31: is this a software/app? (page + title classifier — see is_software).
    # Software still gets the STRICT missing-words gate (the offer must contain the
    # AKS product name → no wrong-product match), but NOT the game-tuned
    # extra-words / dangerous-qualifier gates: a software title legitimately adds
    # version + licence words the concise AKS name omits ("Windows 11 Pro OEM Key"
    # vs page "Windows 11 Pro"), which those gates read as a "different product".
    # [R45] never for a console row (design §3.5.h: sw=False — a console game page carries
    # no software licence labels, and the software path has no console buckets).
    sw = False if plan.console else is_software(offer, resolution)

    # [R45] the guards read ``guard_name``: the raw title for PC (unchanged), the console
    # classifier's resolve_name (platform / store / region markers removed) for consoles.
    missing = missing_aks_words(identity_name, guard_name)
    if missing:
        return SkippedOffer(offer, f"name mismatch, missing AKS words: {missing}")

    edition_from_extras: tuple[str, str] | None = None
    if not sw:
        extras = extra_significant_words(identity_name, guard_name, dlc_page=dlc_page)
        if extras:
            # Page-verified rescue: extras that ALL name one page edition are that
            # edition's qualifier ("Knight's Edition" → page "Knights Editon" 2723),
            # not a different product — carry the resolved edition to §edition below.
            edition_from_extras = match_extras_to_page_edition(extras, resolution.editions)
            if edition_from_extras is None:
                return SkippedOffer(offer, f"different/expanded product — extra words: {extras}")
            # AUDIT DU 2026-09-18. Ce sauvetage COURT-CIRCUITE `detect_edition` (branche `elif`
            # du bloc édition). Or les mots de PALIER — DELUXE, ULTIMATE, GOLD, GOTY… — sont
            # dans NOISE_TOKENS, donc ils n'entrent jamais dans `extras` : un titre « <Jeu>
            # Deluxe <qualificatif> » pouvait être adopté sous le seau du qualificatif, palier
            # perdu, c'est-à-dire une écriture de MAUVAISE ÉDITION. On exige que le seau adopté
            # porte les paliers que le MARCHAND ajoute — ceux du titre moins ceux du nom AKS,
            # sinon « Ultimate Admiral: Age of Sail » ou « Homeworld Remastered Collection »
            # seraient refusés à tort (le mot est DANS le nom du produit). La comparaison passe
            # par `_edition_key`, pour que l'alias GOTY ↔ « Game of the Year » ne fasse pas
            # rater une adoption correcte.
            _tiers = ((set(tokenize(guard_name)) & _EDITION_TIER_TOKENS)
                      - set(tokenize(identity_name)))
            if _tiers and not _tiers <= _edition_key(edition_from_extras[1]):
                return SkippedOffer(
                    offer,
                    f"les extras nomment l'édition {edition_from_extras[1]!r} mais le titre "
                    f"déclare le palier {sorted(_tiers)} — non entré (R39)",
                )

        qualifier = dangerous_qualifier(guard_name, resolution.aks_name, dlc_page=dlc_page)
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

    # R31 (2026-08-11, Romain — software entry): software AKS actually sells is
    # entered with the correct LICENCE edition read from the page (OEM / Retail /
    # 1 PC / 1 Month …), never a guessed 'Standard' (Adobe has no Standard at
    # all), and its region mapped to the page's own dropdown. It BYPASSES the
    # game platform gate (R20/R27 below): a software key carries no Steam/Publisher
    # token and software pages often list no official_platforms. Fail closed when
    # the edition or region can't be pinned to THIS page — no guessing. Games are
    # untouched (is_software is precise: brand tokens + software-only page labels).
    if sw:
        sw_edition = resolve_software_edition(offer, resolution.editions)
        if sw_edition is None:
            return SkippedOffer(
                offer,
                f"software edition unresolved on the AKS page "
                f"({len(resolution.editions)} editions, none in title) — not guessed (R31)",
            )
        sw_region = resolve_software_region(region_label, resolution.regions)
        if sw_region is None:
            return SkippedOffer(
                offer,
                f"software region unresolved on the AKS page for {region_label!r}"
                " — not guessed (R31)",
            )
        edition_id, edition_label = sw_edition
        region_id, region_label = sw_region
        # R25 duplicate guard RETIRED here too (Romain 2026-09-08) — see the main-path
        # note below; a PENDING offer is to be added regardless of the page's price table.
        return Candidate(
            offer=offer,
            aks_product_id=resolution.product_id,
            aks_url=resolution.url,
            aks_name=resolution.aks_name,
            platform="SOFTWARE",
            region_label=region_label,
            region_id=region_id,
            edition_label=edition_label,
            edition_id=edition_id,
            region_implicit=implicit,
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
        # [R58] (Romain, 2026-09-24, Wyrel SEULEMENT, dans sa config marchand) : une ligne
        # que la grammaire du marchand déclare « clé PC » sans boutique entre STEAM quand la
        # page AKS ne déclare QUE Steam — « si on voit qu'il y a du Epic, du Ubisoft, du EA…
        # on skip » : la moindre autre plateforme officielle laisse le refus R27 / [R51]
        # ci-dessous. Égalité STRICTE avec {STEAM}, jamais « Steam parmi d'autres ».
        _pc_sans_boutique = (_cfg is not None and _cfg.pc_key_without_store is not None
                             and _cfg.pc_key_without_store(offer.name, offer.url))
        if _pc_sans_boutique and page_platforms == {"STEAM"}:
            platform = "STEAM"
            region_label, region_id, implicit = detect_region(offer, platform)
            if region_id is None:
                return SkippedOffer(offer, f"no region id for {platform}/{region_label}")
        else:
            if "DIRECT PUBLISHER" not in page_platforms:
                return SkippedOffer(
                    offer,
                    "no platform in title and AKS page does not confirm Direct"
                    " Publisher — platform unverifiable, not defaulted (R27)",
                )
            # [R51] (2026-09-16) — « Direct Publisher » on the AKS page is NOT a statement
            # about THIS merchant's key. Romain, after two Electronicfirst rows were entered
            # PUBLISHER while the merchant sells Steam, and a Gamivo row (« Resident Evil
            # Raccoon City Edition », steam global) reproduced it live: « avant de decider si
            # publisher ou non on doit ouvrir la page marchant … si on arrive pas a ouvrir la
            # page marchant on skip l'offre … on devrait ajouter cette securite par defaut pour
            # tous les marchants ». The AKS line describes the GAME (the game also exists as a
            # publisher key); the only place that says what the MERCHANT sells is its own product
            # page. A merchant declares that it reads it with
            # `MerchantConfig.publisher_from_merchant_page`; the default is False, so the safety
            # is on for every merchant, config or not. Measured cost on every saved run: 13
            # distinct candidates (MMOGA 5, Gamivo 6, Electronicfirst 2) — some of them, like
            # `Minecraft - Java & Bedrock Edition`, are plausibly REAL publisher keys and will be
            # recoverable when a merchant page reader lands (MMOGA's page answers 200).
            # Merchants whose real platform is only on their offer page (Instant
            # Gaming) never reach here token-less: their MerchantConfig resolver set
            # `declared_platform` from the page above, or already failed closed (R32).
            if _cfg is None or not _cfg.publisher_from_merchant_page:
                return SkippedOffer(
                    offer,
                    "no platform in title or URL — the AKS page's 'Direct Publisher' describes"
                    " the game, not this merchant's key, and the merchant page is not read"
                    " (R51)",
                )
            platform = "PUBLISHER"
            region_label, region_id, implicit = detect_region(offer, platform)
            if region_id is None:
                return SkippedOffer(offer, f"no region id for {platform}/{region_label}")
    else:
        page_name = PAGE_PLATFORM_NAMES.get(declared_platform)
        # [R56] un marchand mono-plateforme (GOG) peut lever ce contrôle : sa plateforme
        # vient de son domaine, pas d'une lecture de titre, donc la liste de la page ne la
        # contredit pas — elle est seulement incomplète.
        #
        # CORRECTION DU 2026-09-23 (Romain : « pour GOG, c'est GOG la plateforme, il n'y en
        # a pas d'autres, donc je ne vois pas pourquoi tu cherches une plateforme »). J'avais
        # remplacé R20 par un contrôle du SEAU de région : la page doit porter le seau 6.
        # C'était faux, et sur le mauvais signal. `extract_regions` rend « les régions sous
        # lesquelles ce produit EST DÉJÀ VENDU » — une liste de filtre —, pas ce que le
        # formulaire de saisie propose. Le menu déroulant des régions est un CATALOGUE
        # GLOBAL, identique pour tous les produits, et le soumetteur en résout l'identifiant
        # EN DIRECT à l'ouverture de la modale (`src/submitter.py`, « Both dropdowns are a
        # global catalog »). Une page dont les offres actuelles sont toutes Steam accepte
        # donc parfaitement une offre GOG. Le contrôle refusait 136 lignes sur 250 pour une
        # case qui existe. Il est retiré.
        _exige_page = _cfg is None or _cfg.require_page_platform
        if _exige_page and page_name and page_platforms and page_name.upper() not in page_platforms:
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
    # DURCI le 2026-09-17 sur GO de Romain (« go pour le durcissement, seul seau DLC
    # decide »). Avant, la seule PRÉSENCE d'un seau DLC décidait, même avec un Standard à
    # côté — c'est ainsi qu'une clé Rockstar de JEU DE BASE, "Grand Theft Auto Vice City",
    # titre sans le moindre marqueur, est entrée en DLC(16) ce jour-là. Désormais, pour un
    # titre SANS marqueur, le seau DLC ne décide que s'il est le SEUL que la page propose :
    # un vrai DLC caché ("Exoplanets Pack") garde sa page mono-seau et entre juste, un jeu de
    # base dont la page offre aussi Standard repart en Standard. Un titre MARQUÉ reste
    # gouverné par R43 (own-page, DLC anonyme) et garde l'ancien comportement.
    # NB : "Standard + DLC" est un AUTRE seau (518) que "DLC" (16) et n'a jamais déclenché
    # R18 — vérifié sur le catalogue vivant du 2026-09-17.
    # [R18b] AUDIT DU 2026-09-20, sur GO de Romain (« le correctif que tu veux »). R18 est
    # le seul juge du seau DLC et le reste ; il se RETIRE d'un seul cas, mesuré en
    # production : le titre marchand annonce un PALIER (Deluxe / Ultimate / Gold / Complete)
    # que la page AKS ne nomme pas — le marchand vend alors un SKU plus large que ce que la
    # page propose. « Call of Duty: Black Ops III Zombies Chronicles Deluxe Edition » (offre
    # 100700366, balayage du 19/09) est entrée DLC(16) sur `…-zombies-chronicles`, la page du
    # DLC seul : `detect_edition` lisait bien Deluxe(7), mais R18 s'exécutait avant et
    # l'écrasait. Sans R18 la ligne part en `else` → la vérification de page (P1-1) refuse
    # « edition 'Deluxe'(7) not sold on the resolved AKS page » : un refus, pas une écriture
    # fausse. Le DLC caché SANS palier (« Exoplanets Pack ») est intact, et un palier que la
    # page nomme AUSSI garde R18 (« Wortox Deluxe Chest » sur la page du même nom, « All
    # Nauts pack » sur `…-all-nauts-pack`). Mesure avant/après sur 1 818 lignes écrites
    # (GameSeal + le crible de 728) : 43 en DLC(16), 10 sans marqueur, UNE SEULE bascule —
    # celle qui était fausse.
    _title_tier = detect_edition(guard_name, offer.url, offer.merchant)[1]
    _marker = title_dlc_marker(offer, _cfg)
    _tier_the_page_does_not_name = (
        _marker is None
        and _title_tier != "1"
        and _title_tier != detect_edition(resolution.aks_name or "")[1]
    )
    if _dlc_edition_on_page(resolution.editions) and not _tier_the_page_does_not_name and (
            _marker is not None or len(resolution.editions) == 1
            or derived_dlc_page(guard_name, _title_tier, _marker, resolution)):
        edition_label, edition_id = "DLC", "16"
    # AUDIT DU 2026-09-18 : le durcissement ci-dessus ne fermait qu'UNE porte sur trois.
    # Deux autres producteurs adoptaient le seau DLC par simple égalité de libellé, sans
    # marqueur et sans la condition « seul seau » : la vérification de page E05/R23 et la
    # réconciliation P1-1, plus bas. Reproduit : « DLC Quest » — un vrai JEU DE BASE que
    # EXECUTOR_RULES §4.3 (f) nomme explicitement — sur une page {1: Standard, 16: DLC}
    # ressortait en DLC(16), exactement la classe d'erreur « Vice City » du 17/09. Les deux
    # portes écartent désormais le seau DLC : après ce bloc, DLC(16) n'est atteignable QUE
    # par [R18]. Invariant verrouillé par test_r18_is_the_sole_authority_on_the_dlc_bucket.
    elif edition_from_extras is not None:
        # A page-verified edition named by the merchant's "extra" tokens, rescued
        # above from the different-product guard (e.g. Knights Editon 2723).
        edition_id, edition_label = edition_from_extras
    else:
        edition_label, edition_id = detect_edition(guard_name, offer.url, offer.merchant)
        # CORE rule 4 / E05: an edition word that is part of the AKS game name is not
        # an edition — fall back to Standard. Label match alone misses hint synonyms
        # ("Trilogy" resolves to label "Bundle"), so also compare via re-detection on
        # the AKS name: same edition id there = the word is product identity.
        e05_page_verified = edition_id != "1" and (
            edition_label.upper() in resolution.aks_name.upper()
            or detect_edition(resolution.aks_name)[1] == edition_id
        )
        if e05_page_verified:
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
                # [6] Fable re-audit 2026-09-06: match by _edition_key TOKEN-SET
                # equality (format noise stripped, GOTY expanded) as the R40/P1-1
                # reconciliation already does — NEVER a raw substring. The old
                # `label in name` adopted a page's SUPERSET tier ("Complete" →
                # "Complete Plus"/"Complete Deluxe") or, worse, its own BUNDLE-named
                # tier under a non-"8" id (invisible to the `edition_id == "8"` skip
                # below) → a bundle entered, breaking the absolute no-bundles rule.
                # Bundle/Trilogy entries are excluded outright; exact-name preference is
                # kept, so "Complete Pack"(92) — key {COMPLETE}, PACK being format noise
                # — remains the endorsed page-verified adoption.
                want_key = _edition_key(edition_label)
                on_page = []
                for eid, data in resolution.editions.items():
                    ename = _edition_entry_name(data)
                    if ename.strip().upper() == "STANDARD":
                        continue
                    ekey = _edition_key(ename)
                    if ekey & {"BUNDLE", "TRILOGY"}:
                        continue                       # never resurrect a bundle tier
                    if eid == "16" or ekey == {"DLC"}:
                        continue                       # [R18] seul juge du seau DLC — voir ci-dessous
                    if ekey == want_key:
                        on_page.append((eid, ename))
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
        # P1-1/P1-2 (audit 2026-09-02): a GUESSED non-Standard game edition MUST be
        # RECONCILED against the resolved AKS page's own editions map. detect_edition
        # returns a generic hardcoded id (Deluxe→7, Gold→10, GOTY→9, …) from the merchant
        # TITLE or the URL SLUG; the E05/R23 page-verification just above only runs when
        # the edition word is IN the AKS name — the OPPOSITE of the common case (edition
        # in the merchant title/slug, not the AKS name), leaving the guessed id emitted
        # with NO proof the page sells it → a wrong-edition write that survives human
        # validation ("Sniper Elite 4 Deluxe" → base page → Deluxe(7); a slug-parasite
        # "…-complete-edition" → 91). Every OTHER edition producer already binds to the
        # map (DLC via _dlc_edition_on_page, extras via match_extras_to_page_edition,
        # software via resolve_software_edition) — the game path was the sole gap.
        # Reconcile a non-Standard guessed edition ENTIRELY against the page's own map,
        # by _edition_key TOKEN-SET EQUALITY modulo format noise (so "Deluxe"=="Deluxe
        # Edition" and "GOTY"=="Game of the Year Edition", but "Gold"≠"Marigold Edition",
        # "Deluxe"≠"Deluxe Plus Edition" — neither over-skip nor wrong-tier adoption,
        # adversarial review 2026-09-02). We do NOT trust the guessed id even when it
        # happens to be a page key: a page could list that id under a DIFFERENT tier
        # ("Winter Pack" at id 7), and entering it under the guessed "Deluxe" label would
        # be a wrong-edition write — so the id must EARN its place via a label match.
        # >1 match is a guess → skip; 0 match → skip. A "Bundle"(8) guess already returned
        # above; Standard(1) is the safe canonical fallback and stays untouched. Runs ONLY
        # when E05 did NOT already page-verify the edition (E05 leaves a real map id or
        # Standard(1)); re-running on an E05-resolved id would false-flag ambiguity.
        if edition_id != "1" and not e05_page_verified:
            want_key = _edition_key(edition_label)
            if want_key == {"DLC"}:
                # [R18] est le SEUL juge du seau DLC (durcissement du 2026-09-17). Sans ce
                # refus, le motif générique plus bas dirait « not sold on the resolved AKS
                # page » alors que la page le vend — un motif faux, et qui alimente le
                # routeur de tri des listes.
                return SkippedOffer(
                    offer,
                    f"edition {edition_label!r}({edition_id}) : seul [R18] décide du seau DLC "
                    "— titre sans marqueur ou page multi-seaux, non entré",
                )
            pool = [(eid, _edition_entry_name(v))
                    for eid, v in resolution.editions.items()
                    if _edition_entry_name(v).strip().upper() != "STANDARD"
                    and want_key and _edition_key(_edition_entry_name(v)) == want_key
                    and eid != "16"]
            if len(pool) == 1:
                edition_id, edition_label = pool[0]          # adopt the page's real id
            elif len(pool) > 1:
                return SkippedOffer(
                    offer,
                    f"ambiguous page edition for {edition_label!r}: "
                    f"{[n for _, n in pool]} — not guessed (audit P1-1)",
                )
            else:
                return SkippedOffer(
                    offer,
                    f"edition {edition_label!r}({edition_id}) not sold on the resolved "
                    f"AKS page — guessed edition unverified (audit P1-1)",
                )

    # [E06] L'ÉDITION RETENUE DOIT ÊTRE VENDUE PAR LA PAGE — STANDARD COMPRIS (Romain,
    # 2026-09-21 : « normalement tu es censé aller voir la page AKS comme pour les jeux
    # normaux, voir si on est en standard ou en DLC sur cette page »).
    #
    # La page était DÉJÀ lue et sa carte d'éditions en main : le trou n'était pas qu'on ne
    # regardait pas, c'est que Standard était EXEMPTÉ du contrôle — la réconciliation P1-1
    # ci-dessus ne s'exécute que `if edition_id != "1"` (« Standard(1) is the safe canonical
    # fallback and stays untouched »). Un titre sans marqueur sortait donc en Standard(1)
    # même sur une page qui ne vend pas Standard. Mesuré le jour même sur la 1re saisie
    # Difmark : 5 des 10 offres créées — « Diablo IV Lord of Hatred » sur une page
    # {16 DLC, 7 Deluxe, 21 Ultimate}, et quatre jeux en accès anticipé sur des pages
    # {5: Early Access}. Sur un marchand classique le défaut est rare mais réel : 1 page sur
    # 60 tirées au sort chez GameSeal (« TurboMania Fog Racers », Early Access).
    #
    # La branche console applique déjà exactement cette règle à ses pages cibles depuis le
    # 12/09 (« edition … not sold on the <fam> page ») ; c'est la page PRIMAIRE qui y
    # échappait. Trois issues, dans cet ordre :
    #   - l'édition est au catalogue de la page → rien ne change ;
    #   - la page n'a qu'UN seau → c'est lui (le cas « Early Access » de Romain : sur ces
    #     pages toutes les offres entrent en accès anticipé). R18 garde la main sur le seau
    #     DLC : une page mono-seau DLC a déjà été tranchée par lui plus haut ;
    #   - plusieurs seaux et aucun qui corresponde → REFUS fail-closed, on ne devine pas
    #     (le cas Diablo : DLC + Deluxe + Ultimate, sans Standard).
    # Le seau DLC est HORS de ce contrôle : [R18] en est le seul juge (AGENTS.md), et il
    # émet l'id canonique 16 même quand la page liste son DLC sous un autre id — un garde-fou
    # délibéré, verrouillé par test_dlc_bucket_matched_by_name_when_id_moves.
    if resolution.editions and edition_id not in resolution.editions and edition_id != "16":
        if len(resolution.editions) == 1:
            _sole_id, _sole_value = next(iter(resolution.editions.items()))
            _sole_name = _edition_entry_name(_sole_value)
            # REVUE DE ROMAIN (2026-09-21, e596cd3 → 5d163e1) : « E06 peut accepter un
            # bundle interdit — une offre Standard face à une page {8: Bundle} devient un
            # candidat Bundle. L'adoption du seul seau intervient après le contrôle
            # anti-bundle et le contourne. » Exact, et c'est la règle la plus absolue du
            # projet (Romain 2026-07-07 : « on n'entre JAMAIS de bundle »). L'adoption du
            # seau unique s'arrête donc net sur un bundle — la page ne vend que ça, il n'y a
            # rien à écrire ici.
            # Jetons BRUTS, comme la garde anti-bundle de `match_extras_to_page_edition` :
            # `_edition_key` traite « Pack » comme du bruit de format, ce qui laisserait
            # passer un seau « Deluxe Pack ». Adopter un seau que l'offre n'a pas demandé est
            # déjà une supposition ; si ce seau sent le bundle, la règle absolue tranche.
            if _sole_id == "8" or set(tokenize(_sole_name)) & {"BUNDLE", "PACK", "TRILOGY"}:
                return SkippedOffer(
                    offer,
                    f"la page ne vend que {_sole_name!r} — bundle, jamais entré (E06)",
                )
            edition_id, edition_label = _sole_id, _sole_name
        else:
            return SkippedOffer(
                offer,
                f"edition {edition_label!r}({edition_id}) not sold on the resolved AKS page "
                f"— page sells {sorted(_edition_entry_name(v) for v in resolution.editions.values())} "
                "(E06)",
            )

    # [R45] (2026-09-12) console targets — after the edition block so every page enters
    # the ONE edition the primary page resolved (P1-1 reconciled it against the primary's
    # own map). Every target page must sell that edition id, else the WHOLE offer skips:
    # never a partial entry (a consumed feed row loses its second platform, design §4).
    # P5 (DÉCIDÉ Romain 2026-09-25) : le refus en bloc de l'édition DLC(16) est retiré. Un
    # titre MARQUÉ a déjà passé R43 sur chaque page (_console_plan) ; un titre SANS marqueur
    # n'atteint DLC(16) que par R18, avec ses verrous PC (seau DLC seul de la page, R18b,
    # R57) — la règle des DLC PC appliquée aux consoles, pas un second système. Le contrôle
    # ci-dessous (chaque page vend l'édition) reste le filet « tout ou rien ».
    targets: tuple[Target, ...] = ()
    if plan.console:
        built: list[Target] = []
        for fam, page, bucket_label, bucket_id in plan.console_targets:
            if edition_id not in page.editions:
                return SkippedOffer(
                    offer,
                    f"edition {edition_label}({edition_id}) not sold on the {fam} page (R45)",
                )
            built.append(Target(
                platform=fam, aks_product_id=page.product_id, aks_url=page.url,
                aks_name=page.aks_name, region_label=bucket_label, region_id=bucket_id,
                edition_label=edition_label, edition_id=edition_id,
            ))
        targets = tuple(built)

    # R25 duplicate guard RETIRED (Romain 2026-09-08). It was added 2026-07-15
    # (Kinguin/Darkwood escape) to skip a candidate whose merchant already had a price
    # on the AKS page for this exact region/edition — the concern was a STALE matched
    # batch re-submitted after the offer had since been entered. Romain's ruling: an
    # offer that is still in the PENDING feed is TO BE ADDED, period — we do not second-
    # guess it against the page's price table. Two reasons the old guard was wrong: (1)
    # it matched by merchantName, but the page price can come from another channel /
    # AKS auto-sync (the page merchant id ≠ the operator's feed store_id — e.g. Phantom
    # Blade Zero: page "Kinguin" id 47 vs feed store 58), so it false-skipped genuinely
    # new offers; (2) staleness is now handled by the STABLE pending feed (offers are
    # kept, ids no longer rotate) + submit-time prove-gone, not this page check. Do NOT
    # re-add — see AGENTS.md "Reviewed decisions". ``prices`` is still extracted (price
    # routing / diagnostics), just no longer a skip source.
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
        targets=targets,
    )


def _identity_tokens(name: str) -> list[str]:
    """[R45] review fix (2026-09-14): the per-page identity comparison folds apostrophes.
    AKS names a console page without them ("DreamWorks Spirit Luckys Big Adventure
    Nintendo Switch") while the PC page keeps "Lucky's" — a real false skip of the MMOGA
    dry-run of 2026-09-12. ``tokenize`` already folds curly quotes to "'"
    (normalize_apostrophes); the ASCII apostrophe is removed here, empty tokens dropped."""

    return [t for t in (tok.replace("'", "") for tok in tokenize(name)) if t]


def _console_plan(
    offer: NormalizedOffer,
    sig: ConsoleSignal,
    resolver: Callable[..., AksResolution | None],
    page_resolver: Callable[[str], AksResolution | None],
) -> _Plan | SkippedOffer:
    """[R45] (2026-09-12) the CONSOLE resolution branch of :func:`match_offer` — Romain
    2026-09-12: the AKS feed tool overwrites the region/PLATFORM per target page, so a
    console key is entered on EVERY platform page the merchant declares AND AKS has
    (policy P1 "merchant declaration ∧ AKS page" — never partial):

    a. ``families`` = the merchant-declared platforms (classifier), ``guard_name`` = the
       title without platform / store / region markers (edition kept) — the text the
       R01 / R16 / R01b guards and detect_edition read, AND the slug source;
    b. a DLC / season-pass title (P5, DÉCIDÉ Romain 2026-09-25 — « P5 A », the PC rule
       [R43] applied to consoles): resolved with its marker stripped, and EVERY target page
       (Play Anywhere PC page included) must be the DLC's own page carrying the DLC bucket
       — :func:`r43_dlc_page_refusal`, one page missing = the whole row refused (§6);
    c. the base region → one bucket per family (REGION_IDS[fam]) — review fix
       2026-09-14: the merchant grammar's region slot (``sig.region_base``, read by the
       classifier: Kinguin / K4G "<Game> US Xbox One …", Driffle "(Europe)") is
       authoritative; the generic title/URL scan (detect_region_base, which carries the
       R46 Gamivo ``title_region`` hook: "Ravenswatch EN United Kingdom" → uk) speaks
       only when NOT implicit; the two must agree (else skip); region words naming MORE
       THAN ONE sellable base are refused right after that slot — above the merchant's
       ``offer_page_resolver``, so a contradictory title never costs a page fetch
       (2026-09-19, Romain: "Gamerall accepte des régions contradictoires"); an implicit
       read while the classifier removed a region word (``sig.region_words``) is refused — a
       region-locked console key is NEVER filed under an implicit GLOBAL (Gamivo 254/264
       and Kinguin 37 real rows did before); a gift → skip (no console gift bucket); a
       missing bucket → skip (PS5 EU / US / UK take 88eu / 88us / 88uk since P3, Romain
       2026-09-25);
    d. the ANCHOR page: the PC page when it exists (slug tiers + R30 search, unchanged),
       else the console page of the primary family by slug (``page_kind``, no search —
       like account pages); none → skip;
    e. ``identity_name`` = the anchor name without its platform suffix ("Hades PS5" →
       "Hades") — R01 / R16 / R01b compare guard_name against it (common flow);
    f. Play Anywhere (P2) = the PC page's ``official platforms`` lists "Xbox Play
       Anywhere" OR (DÉCIDÉ Romain 2026-09-25, « on le considère Play Anywhere ») the
       merchant declares Xbox + PC/Windows: every Xbox target then takes the XBOX/PC bucket
       and the PC page becomes an extra target; "PC + a NON-Xbox family" stays a
       contradictory-delivery skip; Xbox + PC with no AKS PC page → skip (the PC target is
       unverifiable, never a partial entry);
    g. one target page per declared family from the anchor's tab bar (the console anchor
       is its own page); no tab → skip; the page is re-read (``page_resolver``) and its
       identity must equal the anchor's (a tab can point to another product — Elden Ring
       → "Tarnished Edition Nintendo Switch 2") else skip; an empty editions map → R19;
    h. the primary family's page / bucket become the plan's resolution / region — the
       common flow (R44 → guards → R19 → edition block, untouched) runs on them, then
       match_offer builds one :class:`Target` per page (edition checked on each)."""

    families = tuple(sig.families)
    if not families:
        return SkippedOffer(offer, "console: no declared generation (R45)")
    for fam in families:
        if fam == "XBOX_PC" or fam not in CONSOLE_PAGE_KIND or fam not in REGION_IDS:
            # XBOX_PC is a BUCKET family (Play Anywhere target), never a declared one.
            return SkippedOffer(offer, f"console: unknown platform family {fam!r} — not entered (R45)")
    guard_name = (sig.resolve_name or "").strip()
    if not guard_name:
        return SkippedOffer(
            offer, "console: no product name left once the platform markers are removed (R45)")

    # (b) P5 — DÉCIDÉ Romain 2026-09-25 (« P5 A ») : un DLC / season pass console suit la
    # règle des DLC PC [R43]. Le marqueur est lu sur le nom que le classifieur a nettoyé
    # (plateforme / boutique / région retirées) et retiré pour la résolution, comme sur PC
    # (`resolution_name`) : « Battlefield 4 Premium (DLC) (Xbox One) Xbox Live Key - EU » →
    # page « battlefield-4-premium ». Chaque page cible est vérifiée plus bas, en (g).
    # Avant : refus « console: DLC / season pass on console — not entered yet (R45) ».
    # Le marqueur est lu comme R18 le lira dans `match_offer` (`title_dlc_marker`, titre brut
    # + grammaire du marchand), puis sur le nom nettoyé : si les deux lectures divergeaient,
    # un DLC pourrait sauter R43 ici et être rangé DLC(16) par R18 plus loin.
    _cfg_console = merchant_config(offer.merchant)
    dlc_marker = title_dlc_marker(offer, _cfg_console) or dlc_title_marker(guard_name)
    slug_name = strip_dlc_marker(guard_name) if dlc_marker is not None else guard_name

    # (c) region: the platform-independent base, then one bucket per declared family.
    # [R45] review fix (2026-09-14) — never an implicit GLOBAL for a region word the
    # merchant wrote (see the docstring): grammar slot > non-implicit generic read >
    # refusal when a region word was seen but not mapped > implicit GLOBAL (no region
    # word at all, the Kinguin-style default).
    generic_base, generic_label, generic_implicit, gift = detect_region_base(offer)
    if gift:
        return SkippedOffer(offer, "console: gift delivery has no console bucket (R45)")
    # Le marchand dont la région vit sur SA PROPRE PAGE ([R33] Instant Gaming, [R54] Gamerall)
    # est consulté AVANT le balayage générique, et son résolveur est la lecture ORDONNÉE
    # complète du marchand : titre, puis URL, puis page.
    #
    # 2026-09-18, audit : il n'était pas consulté du tout ici — la branche console tombait sur
    # le GLOBAL implicite sans jamais ouvrir la page.
    # 2026-09-19, Romain : la garde ajoutée la veille arrivait TROP TARD. Elle vivait dans le
    # dernier `else`, donc le balayage GÉNÉRIQUE la précédait — et ce balayage lit les mots du
    # NOM DU JEU. « 51 Worldwide Games (Nintendo Switch) », sans région dans l'URL, donnait un
    # GLOBAL *explicite* sur le seul mot « Worldwide » du titre : la page n'était jamais
    # ouverte, même simulée indisponible. On ne lit ici QUE la région — la plateforme vient du
    # classifieur console, et la confronter au jeton PC du résolveur produirait un faux
    # conflit (PSN / NINTENDO ne sont pas des familles PC).
    _page_resolver = _cfg_console.offer_page_resolver if _cfg_console is not None else None
    grammar_base = sig.region_base
    if grammar_base is not None:
        if not generic_implicit and generic_base != grammar_base:
            return SkippedOffer(
                offer, "console: region contradiction (title/grammar vs URL) — not entered (R45)")
        base, implicit = grammar_base, False
        label = "GLOBAL" if grammar_base == "global" else str(grammar_base).upper()
    elif len(distinct_region_bases(sig.region_words)) > 1:
        # Romain, 2026-09-19 : « Gamerall accepte des régions contradictoires ». Le contrat
        # de :class:`ConsoleSignal` le dit déjà — des mots de région qui ne désignent PAS une
        # base vendable unique sont un refus — mais le déplacement du résolveur marchand
        # au-dessus (même jour, correctif « 51 Worldwide Games ») l'avait court-circuité :
        # « Hades (Nintendo Switch) GLOBAL US » descendait au résolveur, qui prenait la
        # PREMIÈRE région du titre et entrait la clé en GLOBAL(99) ; « EUROPE USA » en
        # EU(99eu). La garde est donc AU-DESSUS du résolveur, et un titre contradictoire ne
        # coûte pas une requête de page.
        #
        # Le prédicat est `sig.region_words`, PAS un désaccord avec le balayage générique :
        # le générique lit les mots du NOM DU JEU et se tromperait sur « 51 Worldwide Games
        # (Nintendo Switch) » (générique GLOBAL explicite, page Europe — un faux conflit).
        # `region_words` ne rapporte que les mots retirés À CÔTÉ de la phrase de plateforme —
        # mesuré `()` sur ce titre-là, `('GLOBAL', 'US')` sur celui de Romain.
        return SkippedOffer(
            offer,
            f"console: merchant region contradiction {' / '.join(sig.region_words)} — "
            "no single sellable base, not entered (R45)")
    elif _page_resolver is not None:
        try:
            _psig = _page_resolver(offer.url, offer.name)
        except Exception as exc:  # noqa: BLE001 — page illisible → fail closed
            return SkippedOffer(
                offer,
                f"console: {offer.merchant} offer page unreadable — unverifiable "
                f"(R32/R45): {exc}")
        if not _psig.region_resolved:
            return SkippedOffer(
                offer,
                f"console: {offer.merchant} offer page gives no region — "
                "never an implicit GLOBAL for this merchant (R32/R45)")
        if _psig.region_base is None:
            return SkippedOffer(offer, f"forbidden region: {_psig.region_label}")
        base, implicit = _psig.region_base, False
        label = "GLOBAL" if _psig.region_base == "global" else str(_psig.region_base).upper()
    elif not generic_implicit:
        base, label, implicit = generic_base, generic_label, False
    elif sig.region_words:
        return SkippedOffer(
            offer,
            f"console: merchant region {sig.region_words[0]!r} not mapped to a sellable base "
            "— not entered (R45)",
        )
    else:
        base, label, implicit = "global", "GLOBAL", True
    for fam in families:
        if REGION_IDS.get(fam, {}).get(base) is None:
            return SkippedOffer(offer, f"no region id for {fam}/{label} (R45)")

    # (d) anchor page — the PC page first (existing resolution: slug tiers + R30 search),
    # else the console page of the primary family (slug only, like account pages).
    primary = families[0]
    anchor_kind = "cd-key"
    try:
        pc_res = resolver(slug_name)
        anchor = pc_res
        if anchor is None:
            anchor_kind = CONSOLE_PAGE_KIND[primary]
            anchor = resolver(slug_name, page_kind=anchor_kind)
    except AksProbeUnreliable as exc:
        return SkippedOffer(offer, f"AKS probe unreliable (throttled?): {exc}")
    except AksNameUnreadable as exc:
        return SkippedOffer(offer, f"AKS page name unreadable — cannot verify product (R01): {exc}")
    except AksPageUnparseable as exc:
        return SkippedOffer(offer, f"AKS page markup drifted — guard input unreadable (MA6): {exc}")
    if anchor is None:
        return SkippedOffer(offer, "no AKS product page found (console) (R45)")

    # (e) identity = the anchor name without its platform suffix.
    identity_name = console_page_identity(anchor.aks_name).strip()
    if not identity_name:
        return SkippedOffer(
            offer, f"console: AKS page name {anchor.aks_name!r} has no product identity (R45)")

    # (f) Play Anywhere is the PC page's truth (P2).
    pa = pc_res is not None and "XBOX PLAY ANYWHERE" in {p.upper() for p in pc_res.official_platforms}
    xbox_declared = any(f in ("XBOX_ONE", "XBOX_SERIES") for f in families)
    # AUDIT DU 2026-09-20 : la garde Play Anywhere se déclenchait pour N'IMPORTE quelle
    # famille dès que « PC » était déclaré à côté, alors que Xbox Play Anywhere n'existe ni
    # sur Nintendo ni sur PlayStation (docs/EXECUTOR_RULES.md §4.12 P2 : « next to an Xbox
    # family »). « FINAL FANTASY VIII - REMASTERED (PC) (Nintendo Switch) Nintendo Key - EU »
    # (offre 100703022) était refusée 22 fois avec un motif qui affirmait un Xbox absent du
    # titre. Le refus RESTE (une clé eShop ne s'active pas sur PC : la déclaration marchande
    # se contredit, on ne devine pas laquelle est vraie) — c'est le motif qui devient vrai,
    # et la garde Play Anywhere retrouve son domaine.
    if sig.pc_declared and not xbox_declared:
        return SkippedOffer(
            offer,
            "console: merchant declares PC next to "
            f"{'/'.join(families) or 'a console'} — contradictory delivery, not entered (R45)",
        )
    # P2 — DÉCIDÉ Romain 2026-09-25 (« P2 saisir sur les xbox déclarées et sur PC, on le
    # considère Play Anywhere »). Xbox + PC/Windows déclarés par le marchand SANS que la page
    # PC d'AKS liste « Xbox Play Anywhere » : ce n'est plus un refus « contradiction », la
    # clé est traitée EXACTEMENT comme une clé Play Anywhere — les pages Xbox déclarées + la
    # page PC, toutes dans la case XBOX/PC (306 / 241 / 242 / 240). ~100 lignes refusées avant
    # (« PAC-MAN MUSEUM+ EU XBOX One / Xbox Series X|S / PC CD Key », « RIOT- Civil Unrest PC
    # EU XBOX One / Xbox Series X|S CD Key »). Sans page PC chez AKS, la cible PC n'existe pas :
    # refus, jamais une saisie partielle (§6).
    if sig.pc_declared and pc_res is None:
        return SkippedOffer(
            offer,
            f"console: merchant declares Xbox + PC but AKS has no PC page for "
            f"'{identity_name}' — Play Anywhere target unverifiable, not entered (R45)",
        )
    pa_targets = xbox_declared and (pa or sig.pc_declared)

    def _bucket(fam: str) -> tuple[str, str] | SkippedOffer:
        bucket_family = "XBOX_PC" if pa_targets and fam in ("XBOX_ONE", "XBOX_SERIES") else fam
        rid = REGION_IDS.get(bucket_family, {}).get(base)
        if rid is None:
            return SkippedOffer(offer, f"no region id for {bucket_family}/{label} (R45)")
        return CONSOLE_REGION_LABELS.get(rid, label), rid

    # (g) one page per declared family, identity-checked; every page or nothing.
    pages: list[tuple[str, AksResolution, str, str]] = []
    for fam in families:
        kind = CONSOLE_PAGE_KIND[fam]
        if anchor_kind == kind:
            page = anchor
        else:
            url = anchor.console_pages.get(kind)
            if not url:
                return SkippedOffer(
                    offer,
                    f"console: AKS has no {fam} page for '{identity_name}' — declared platform "
                    "unverifiable (R45)",
                )
            try:
                page = page_resolver(url)
            except AksProbeUnreliable as exc:
                return SkippedOffer(offer, f"AKS probe unreliable (throttled?): {exc}")
            except AksNameUnreadable as exc:
                return SkippedOffer(
                    offer, f"AKS page name unreadable — cannot verify product (R01): {exc}")
            except AksPageUnparseable as exc:
                return SkippedOffer(
                    offer, f"AKS page markup drifted — guard input unreadable (MA6): {exc}")
            if page is None:
                return SkippedOffer(
                    offer,
                    f"console: AKS {fam} page {url} not found (404) — declared platform "
                    "unverifiable (R45)",
                )
        if _identity_tokens(console_page_identity(page.aks_name)) != _identity_tokens(identity_name):
            return SkippedOffer(
                offer, f"console page '{page.aks_name}' is not '{identity_name}' (R45)")
        # AUDIT DU 2026-09-18 : la comparaison de noms ci-dessus ne distingue PAS les
        # générations — `console_page_identity` retire justement le suffixe de plateforme, si
        # bien que « Hades PS4 » et « Hades PS5 » sont tous deux « Hades ». La méta de la page
        # le dit, elle, et elle était extraite puis jetée. Prudence : une méta absente ou d'un
        # vocabulaire inconnu ne prouve rien et ne refuse rien ; seule une méta qui nomme
        # explicitement une AUTRE famille fait échouer la cible.
        _meta_fam = page_platform_family(getattr(page, "page_platform", "") or "")
        if _meta_fam is not None and _meta_fam != fam:
            return SkippedOffer(
                offer,
                f"console: la page {page.url} se déclare {_meta_fam}, pas {fam} — "
                "onglet vers une autre génération, non entré (R45)")
        if not page.editions:
            # "(R19, R45)": feed_status files the console branch's R19 under consoles.
            return SkippedOffer(
                offer, f"AKS {fam} page carries no editions map — edition unverifiable (R19, R45)")
        bucket = _bucket(fam)
        if isinstance(bucket, SkippedOffer):
            return bucket
        pages.append((fam, page, bucket[0], bucket[1]))
    if pa_targets:
        # The PC page is an extra Play Anywhere target under the XBOX/PC bucket (the
        # anchor IS the PC page here, so its identity is the identity by construction).
        if not pc_res.editions:
            return SkippedOffer(
                offer, "AKS XBOX_PC page carries no editions map — edition unverifiable (R19, R45)")
        bucket = _bucket("XBOX_PC")
        if isinstance(bucket, SkippedOffer):
            return bucket
        pages.append(("XBOX_PC", pc_res, bucket[0], bucket[1]))

    # (b, suite) P5 — la règle R43 sur CHAQUE page cible, page PC Play Anywhere comprise :
    # la page du DLC lui-même (slug du nom complet), avec le seau DLC (16). Une seule page qui
    # manque et la ligne entière est refusée — on ne perd pas une plateforme en silence (§6).
    if dlc_marker is not None:
        for fam, page, _label, _rid in pages:
            refusal = r43_dlc_page_refusal(dlc_marker, page, slug_name, guard_name,
                                           stamp="R43, R45")
            if refusal is not None:
                return SkippedOffer(offer, f"console: {fam} — {refusal}")

    # (h) the primary page is the plan's resolution; the common flow runs on it.
    fam0, page0, label0, rid0 = pages[0]
    return _Plan(
        resolution=page0,
        platform=fam0,
        region_label=label0,
        region_id=rid0,
        implicit=implicit,
        declared_platform=fam0,          # no PAGE_PLATFORM_NAMES entry → no R20/R27 check
        difmark_platform_verified=False,
        # P5 : toutes les pages portent le seau DLC (vérifié ci-dessus) → le marqueur DLC du
        # titre n'est plus un mot « en trop » pour R16 / R01b, exactement comme sur PC.
        dlc_page=dlc_marker is not None,
        identity_name=identity_name,
        guard_name=guard_name,
        console_targets=tuple(pages),
        base_label=label,
    )


def match_feed(
    feed: NormalizedFeed,
    resolver: Callable[[str], AksResolution | None] = resolve_aks,
    difmark_offer_resolver: Callable[[str], DifmarkOfferAttributes] = resolve_difmark_offer,
    *,
    max_candidates: int = 100,
    on_progress: Callable[[dict[str, int]], None] | None = None,
    progress_every: int = 5,
    stats: dict[str, int] | None = None,
    search_circuit_open: bool = False,
    page_resolver: Callable[[str], AksResolution | None] = resolve_aks_url,
    consoles: bool = False,
    on_resolution: Callable[[Any, dict[str, Any]], None] | None = None,
) -> tuple[list[Candidate], list[SkippedOffer]]:
    """Match every offer. ``on_progress`` (2026-07-20), when given, is called
    every ``progress_every`` offers and once at the end with
    ``{done, total, candidates, skipped}`` — the admin logs these as
    ``match_progress`` events so the operator sees live progression instead of
    a silent panel (the stage does no per-offer logging of its own).

    Raises :class:`AksThrottled` (fail-closed STOP for the whole stage) on a 429 or
    on THROTTLE_MAX_CONSECUTIVE_UNRELIABLE consecutive unreliable probes (audit
    2026-09-09, one 30 s grace first) — a per-offer unreliable probe below that stays a
    SkippedOffer. ``stats`` (optional dict) receives the guard's counters
    (probe_unreliable, search_failures, search_circuit_open_offers, throttle_graces).

    [R45] ``consoles`` (default off) routes classified console rows through the console
    branch; ``page_resolver`` reads the console target pages by URL — under the production
    resolver it is wrapped in a throttle guard that SHARES the main guard's state (review
    fix 2026-09-14: one consecutive-unreliable count, one grace budget and one ``stats``
    across both resolvers), an injected one is used as is."""

    candidates: list[Candidate] = []
    skipped: list[SkippedOffer] = []
    total = len(feed.offers)
    # No real sleep under an injected test resolver (same identity rule as the pacing).
    guard = _ThrottleGuard(resolver, sleep=time.sleep if resolver is resolve_aks else (lambda s: None),
                           search_open=search_circuit_open, on_resolution=on_resolution)
    # Account-page resolutions (Difmark accounts) go through the same guard when the
    # production resolver is in use; an injected test resolver keeps the default.
    account_resolver = guard if resolver is resolve_aks else resolve_aks
    # [R45] console page reads: production → a guard sharing the main guard's throttle
    # state (same fail-closed abort, ONE consecutive count across both), else as is.
    page_guard: Callable[[str], AksResolution | None] = page_resolver
    if resolver is resolve_aks:
        page_guard = _ThrottleGuard(
            page_resolver,
            sleep=time.sleep if page_resolver is resolve_aks_url else (lambda s: None),
            on_resolution=on_resolution, shared=guard)
    for i, offer in enumerate(feed.offers, 1):
        result = match_offer(offer, guard, difmark_offer_resolver, account_resolver=account_resolver,
                             page_resolver=page_guard, consoles=consoles)
        if isinstance(result, Candidate):
            if len(candidates) < max_candidates:
                candidates.append(result)
            else:
                skipped.append(SkippedOffer(offer, f"candidate cap reached (max {max_candidates})"))
        else:
            skipped.append(result)
        if on_progress is not None and (i % progress_every == 0 or i == total):
            on_progress({"done": i, "total": total,
                         "candidates": len(candidates), "skipped": len(skipped)})
    if stats is not None:
        stats.update(guard.stats)          # [R45] the page guard shares this very dict
    return candidates, skipped

"""MMOGA — platform from the URL category segment, region from the "<CODE> Key" title tail
(Romain 2026-09-10: « notre executor doit apprendre à ajouter les offres mmoga »).

Grammar seen live (``mmoga.com/<Platform>-Games/<Product>[-<REGION>-Key].html?ref=<affid>``):

* ``https://www.mmoga.com/Steam-Games/Borderlands-2-EU-Key.html?ref=615``
  → title "Borderlands 2 EU Key" — platform STEAM (URL), region EU (title tail)
* ``https://www.mmoga.com/Steam-Games/Company-of-Heroes-2.html?ref=615``
  → title "Company of Heroes 2" — STEAM, no region token → generic implicit GLOBAL
* ``https://www.mmoga.com/EA-Games/Battlefield-4-Premium.html?ref=615``
  → title "Battlefield 4 Premium" — EA (URL), edition Premium (generic title rule)

This module OVERRIDES three generic behaviours through the ``MerchantConfig`` hooks
(``precheck`` / ``title_region`` / ``resolve_name``) — the matcher itself knows nothing
about MMOGA — plus, since [R63] (2026-09-28), ``english_only_name``: the whole delivery
bracket around an « English only » mention, dropped from the slug of an EA English-only key
the matcher ENTERS (never from ``resolve_name``). The region code is an UPPERCASE 2-letter code right before the trailing
"Key": case-SENSITIVE on purpose — "Among Us Key" (Us) is a global key, "Borderlands 2
US Key" (US) is US-locked. A code that maps to no AKS bucket (DE, FR, …) fails CLOSED
(skip "forbidden region: <code>"), never an implicit worldwide entry; the price of that
safety is a rare false skip on a title ending with an uppercase acronym + Key ("Deus Ex GO
Key"). ``?ref=`` is affiliate noise: kept verbatim in artifacts (R21), ignored by every
matching signal. No matcher import (the registry imports this module).

Console grammar (R32 / R45, 2026-09-14 — Romain: « un fichier de config par marchand »):
the platform is the URL CATEGORY segment (``/Xbox-Live/Xbox-One-Game-Keys/``,
``/Xbox-Live/Xbox-Series-XS-Game-Keys/``, ``/Playstation-Network/Playstation-5-Game-Keys/``,
``/Nintendo/Switch/``; ``/Xbox-Live/Xbox-360-Game-Keys/`` → skip; the card / subscription
categories ``/PSN-Cards-<CC>/``, ``/Nintendo-eShop-Cards/``, ``/Playstation-Plus/``,
``/Xbox-Live-Cards/``, ``/Xbox-Live-Gold/`` → non-game skip) — read by the shared
classifier ONLY when the title phrase ("(Xbox One / Series X|S Download Code)") declares
no generation (a cross-gen title filed under Xbox-One-Game-Keys: the title wins). The
region next to the platform phrase is the same "<CODE> Key" / "[EU]" / "(… Key EU)"
grammar as the PC rows (``console_region_slot``); the " - EU" dash tail is the shared
read. "Download Code" is MMOGA's delivery phrase (``console_noise``). Declared through
the ``MerchantConfig`` console hooks — ``src/console_keys.py`` names no merchant.
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit

from src.console_keys import SKIP_XBOX_360, skip_not_a_game
from src.merchant_config import MerchantConfig
from src.merchants.common import english_only_mark

# URL category segment (lowercased, before the first "-") → platform token. Only prefixes
# with a REGION_IDS entry are mapped; console / software / gift-card categories stay
# unmapped → console/software categorical skips or a fail-closed platform skip, never a
# Steam guess.
MMOGA_URL_PLATFORM_PREFIXES = {
    "steam": "STEAM",        # /Steam-Games/…
    "ea": "EA",              # /EA-Games/… (EA app / Origin keys)
    "origin": "EA",
    "gog": "GOG",
    "epic": "EPIC",
    "ubisoft": "UBISOFT",
    "uplay": "UBISOFT",
    "rockstar": "ROCKSTAR",  # seaux Rockstar mappés depuis [R50] — la ligne ENTRE
    "battle.net": "BATTLENET",
    "blizzard": "BATTLENET",
    "windows": "MICROSOFT",  # seaux Windows mappés depuis [R50] — la ligne ENTRE si la page
                             # AKS liste « Microsoft Windows » ([R62], matcher)
}

# "<Product> <CODE> Key" / "<Product> <CODE> CD Key" — uppercase code, raw title case.
REGION_CODE_KEY_RE = re.compile(r"(?:^|\s)([A-Z]{2})\s+(?:CD\s+)?[Kk][Ee][Yy]\s*$")
# Second MMOGA grammar (adversarial review 2026-09-11 — 9 of 1 060 created offers carried it
# and were entered GLOBAL): the code sits AFTER the key word inside a trailing bracket:
# "WWE 2K24 - Deluxe Edition (Steam Key EU)", "Marvel's Midnight Suns - Epic Games Store
# Key [EU]", "Wild West Dynasty - Ultimate Edition [EU]", "The Sims 4 - For Rent DLC (EA App
# Key EU)". Same 2-letter vocabulary, same SELLABLE / FORBIDDEN routing.
REGION_CODE_TAIL_RE = re.compile(
    r"(?:\s*\((?:[A-Za-z][A-Za-z .]*\s)?(?:CD\s+)?[Kk][Ee][Yy]\s+([A-Z]{2})\)"
    r"|\s*\[([A-Z]{2})\]"
    r"|\s*\(([A-Z]{2})\))\s*$"
)
# Codes with an AKS region bucket (matcher REGION_IDS keys).
SELLABLE_CODES = {"EU": "eu", "US": "us", "UK": "uk", "GB": "uk"}
# Forbidden locks — the SAME labels as the matcher's FORBIDDEN_REGIONS / _URL_FORBIDDEN_CODES
# so the one router (aks_lists.suggest_target_list) files them identically.
FORBIDDEN_CODES = {
    "RU": "RUSSIA", "TR": "TURKEY", "BR": "BRAZIL", "AR": "ARGENTINA", "CN": "CHINA",
    "KR": "KOREA", "JP": "JAPAN", "PL": "POLAND", "UA": "UKRAINE", "MX": "MEXICO",
    "PH": "PHILIPPINES", "VN": "VIETNAM", "TH": "THAILAND",
}


# ── crochets de LIVRAISON (2026-09-29 — [R32f] + proposition 6 de l'audit du 2026-09-28) ──
# Romain, 2026-09-29 : « Oui pour etendre Altergift a MMOGA et a tous marchant existant et
# futur ». MMOGA écrit sa livraison entre crochets : « Firewatch [EU Steam Altergift] »,
# « Borderlands 2 [EU Key] », « Ghost of Tsushima - Director's Cut [PC Version - Steam Key EU] »,
# « Planet Coaster 2 [Steam Game Card EU] », « The Last of Us : Part I [PC] [Steam] ». Le crochet
# restait dans le slug (« firewatch-eu-steam-altergift » : 404) — proposition 6 : il en sort.
# Mais le crochet porte aussi la RÉGION, et la lecture générique ne la voit pas (« EU] » n'est
# pas « EU », « -eu.html » n'est pas un créneau) : sortir le crochet du slug SANS lire son code
# ferait entrer une clé EU en GLOBAL implicite. C'est déjà arrivé, le crochet ne bloquait pas
# tout : « Horizon Forbidden West - Complete Edition [Steam PC Key EU] » (101040244) et
# « Marvel's Spider-Man Remastered [PC - Steam Key EU] » (101039968), créées STEAM GLOBAL(2)
# le 2026-09-11. Le code du crochet est donc lu ici, comme le « (… Key EU) » entre parenthèses.
#
# Un crochet de livraison : chaque mot est du vocabulaire de livraison ci-dessous OU un code
# de deux capitales, avec AU MOINS un mot de livraison — « [VR] », « [Remake] », « [2014] »,
# « [DLC] », « [Banjo & Kazooie] » sont des mots de PRODUIT et restent (« Silent Hill 2
# [Remake] » n'est pas « Silent Hill 2 »). Jamais un crochet console (« [Xbox One / Series X|S
# Download Code] » : la branche console a sa propre lecture, inchangée), jamais un crochet qui
# porte la mention « English only » ou le code EN ([R63] : la mention ne sort du slug que sur sa
# route, par ``english_only_name``, et EN n'est jamais un code de région).
_BRACKET_RE = re.compile(r"\[([^\[\]]*)\]")
_BRACKET_TOKEN_SPLIT_RE = re.compile(r"[\s/,|\-]+")
DELIVERY_BRACKET_WORDS = frozenset({
    "KEY", "CD", "STEAM", "ALTERGIFT", "GAMECARD", "GAME", "CARD", "PC", "VERSION", "EA", "APP",
    "ORIGIN", "EPIC", "GAMES", "STORE", "OFFICIAL", "GREENCODE", "UBISOFT", "CONNECT", "GOG",
    "ROCKSTAR",
})
# Deux capitales qui ne sont PAS une région : la plateforme (PC, EA) et la langue (EN, [R63]).
_NOT_REGION_CODES = frozenset({"PC", "EA", "EN"})
_CODE_TOKEN_RE = re.compile(r"[A-Z]{2}")
# « … [<crochet de livraison>] - DE » : le créneau de région écrit juste APRÈS le crochet
# (« EA Sports FC 25 [PC Version / EA Gamecard] - DE », « Immortals of Aveum [PC Version, EA App
# Key] - EU »), ancré en fin de titre.
_BRACKET_DASH_CODE_RE = re.compile(r"\[(?P<content>[^\[\]]*)\]\s+-\s+(?P<code>[A-Z]{2})\s*$")


def _bracket_tokens(content: str) -> list[str]:
    return [t for t in _BRACKET_TOKEN_SPLIT_RE.split(content or "") if t]


def is_delivery_bracket(content: str) -> bool:
    """Le CONTENU d'un crochet (sans les crochets) est de la livraison MMOGA — « EU Steam
    Altergift », « EU Key », « PC Version - Steam Key EU », « Steam Game Card », « PC » — et pas
    un mot de produit (« Remake », « VR », « 2014 »), une plateforme console, ni la mention
    English only / le code EN ([R63])."""

    if english_only_mark(content or "") is not None:
        return False
    tokens = _bracket_tokens(content)
    words = 0
    for tok in tokens:
        if tok == "EN":
            return False
        if tok.upper() in DELIVERY_BRACKET_WORDS:
            words += 1
        elif not _CODE_TOKEN_RE.fullmatch(tok):
            return False
    return words > 0


def delivery_bracket_codes(name: str) -> tuple[str, ...]:
    """Les codes de région écrits DANS les crochets de livraison du titre, puis dans le
    créneau « ] - XX » qui suit l'un d'eux — distincts, dans l'ordre : « Firewatch [EU Steam
    Altergift] » → ("EU",) ; « … [PC Version - Steam Key EU] » → ("EU",) ; « … [PC Version /
    EA Gamecard] - DE » → ("DE",) ; « Returnal [PC - Steam Key] » → () ; « … [PC - Origin EN
    Key] » → () (EN n'est pas une région, et le crochet reste à [R63])."""

    codes: list[str] = []
    for m in _BRACKET_RE.finditer(name or ""):
        content = m.group(1)
        if not is_delivery_bracket(content):
            continue
        for tok in _bracket_tokens(content):
            if _CODE_TOKEN_RE.fullmatch(tok) and tok not in _NOT_REGION_CODES and tok not in codes:
                codes.append(tok)
    tail = _BRACKET_DASH_CODE_RE.search(name or "")
    if tail and is_delivery_bracket(tail.group("content")):
        code = tail.group("code")
        if code not in _NOT_REGION_CODES and code not in codes:
            codes.append(code)
    return tuple(codes)


def _tail_region_code(name: str) -> str | None:
    """Les deux lectures historiques (2026-09-10 / 2026-09-11) : « <CODE> Key » en fin de
    titre, puis « (… Key XX) » / « [XX] » / « (XX) » en fin de titre."""

    m = REGION_CODE_KEY_RE.search(name or "")
    if m:
        return m.group(1)
    m = REGION_CODE_TAIL_RE.search(name or "")
    if not m:
        return None
    key_code, bracket_code, paren_code = m.groups()
    if key_code:
        return key_code                      # "(… Key XX)": a region slot — any code, unmapped → skip
    code = bracket_code or paren_code        # bare "[XX]" / "(XX)": only a KNOWN region code
    return code if code in SELLABLE_CODES or code in FORBIDDEN_CODES else None


def region_codes(name: str) -> tuple[str, ...]:
    """Tous les codes de région que la grammaire MMOGA lit dans le titre, distincts : la queue
    historique d'abord, puis les crochets de livraison (2026-09-29). Plus d'un code → la ligne
    se contredit, ``precheck`` la refuse (jamais un choix entre deux verrous)."""

    codes: list[str] = []
    first = _tail_region_code(name)
    if first:
        codes.append(first)
    for code in delivery_bracket_codes(name):
        if code not in codes:
            codes.append(code)
    return tuple(codes)


def region_code(name: str) -> str | None:
    """The one region code the MMOGA grammar reads, or None ("Among Us Key" → None; two
    different codes → None here, and ``precheck`` refuses the row)."""

    codes = region_codes(name)
    return codes[0] if len(codes) == 1 else None


def precheck(name: str, url: str) -> str | None:
    """A forbidden or unmapped region code before Key is a lock we must never enter
    worldwide → categorical skip (fail-closed). Sellable codes pass (title_region maps them).
    Two different codes in the same title (2026-09-29) → refused, never one of the two."""

    codes = region_codes(name)
    if len(codes) > 1:
        return (f"MMOGA region conflict: {' / '.join(codes)} written in the same title — not "
                "entered (2026-09-29)")
    code = codes[0] if codes else None
    if code is None or code in SELLABLE_CODES:
        return None
    return f"forbidden region: {FORBIDDEN_CODES.get(code, code)}"


def title_region(name: str) -> str | None:
    """"Borderlands 2 US Key" → "us"; "Borderlands 2 EU Key" → "eu"; "Firewatch [EU Steam
    Altergift]" → "eu" (2026-09-29); no code → None (generic)."""

    return SELLABLE_CODES.get(region_code(name) or "")


def strip_delivery_brackets(name: str) -> str:
    """``name`` sans ses crochets de LIVRAISON — et le créneau « - XX » qui en suit un en fin de
    titre — rien d'autre (proposition 6 de l'audit du 2026-09-28, 2026-09-29) : « Firewatch [EU
    Steam Altergift] » → « Firewatch » ; « The Last of Us : Part I [PC] [Steam] » → « The Last of
    Us : Part I » ; « EA Sports FC 25 [PC Version / Steam Gamecard] - EU » → « EA Sports FC 25 » ;
    « Silent Hill 2 [Remake] », « Metro Awakening [VR] - Deluxe Edition », « GRID Legends [EN
    Key - English Only] » inchangés. Pour le SLUG seulement : les gardes lisent le titre brut
    (un « [Steam Game Card] » ou un « [Official Key] » y reste un mot en trop)."""

    text = name or ""
    if not any(is_delivery_bracket(m.group(1)) for m in _BRACKET_RE.finditer(text)):
        return name                          # no delivery bracket: byte-identical
    tail = _BRACKET_DASH_CODE_RE.search(text)
    if tail and is_delivery_bracket(tail.group("content")):
        text = text[:tail.start()] + "[" + tail.group("content") + "]"
    out = _BRACKET_RE.sub(lambda m: " " if is_delivery_bracket(m.group(1)) else m.group(0), text)
    return re.sub(r"\s+", " ", out).strip(" -–—:,/").strip() or name


def resolve_name(name: str) -> str:
    """The title handed to AKS resolution: the "<CODE> Key" tail peeled off, so the slug is
    "borderlands-2", not the 404 "borderlands-2-eu"; and, since 2026-09-29, the DELIVERY
    brackets (``strip_delivery_brackets`` — "firewatch", not "firewatch-eu-steam-altergift").
    Untouched when there is neither."""

    out = name
    if _tail_region_code(name):
        out = REGION_CODE_TAIL_RE.sub("", REGION_CODE_KEY_RE.sub("", name)).rstrip()
    return strip_delivery_brackets(out) or name


# [R63] (Romain, 2026-09-28 : « go pour les clés EA English only en case 31 »). MMOGA écrit la
# mention DANS son crochet de livraison — « GRID Legends [EN Key - English Only] », « EA Sports
# FC 25 [PC Version / EA App EN Key - English only] », « A Way Out [EA App Key EN - English
# Only] - EU » — ou à côté d'un crochet de livraison — « FIFA 23 - Ultimate Edition [PC - Origin
# EN Key] - English Only ». Un crochet qui porte « Key » ou la mention est du MOBILIER de
# livraison : il sort ENTIER du nom de résolution. Retirer la seule phrase ne suffit pas : le
# slug garde « -en-key », et « [… EN Key » lu par la grammaire « <CODE> Key » donnerait
# « forbidden region: EN » (mesuré le 2026-09-28).
_EN_ONLY_DELIVERY_BRACKET_RE = re.compile(
    r"\s*\[[^\]]*\b(?:Key|English[\s-]+only)\b[^\]]*\]", re.IGNORECASE)


def english_only_name(name: str) -> str:
    """Le nom de résolution d'une clé EA English only que [R63] entre : les crochets de
    livraison (« [… Key …] », « [… English only] ») retirés ENTIERS. Le matcher ne l'appelle
    QUE sur une ligne où la route [R63] est active ; il retire ensuite la phrase restante
    (« (English only) », « - English Only ») par ``common.strip_english_only``."""

    return re.sub(r"\s+", " ", _EN_ONLY_DELIVERY_BRACKET_RE.sub(" ", name or "")).strip() or name


# ── console hooks (R45, 2026-09-14) ──────────────────────────────────────────────────
# (regex on the lower-cased URL path, families, skip). The category names the LOWER
# generation only — a cross-gen title is filed under Xbox-One-Game-Keys, so the shared
# title phrase wins whenever it declares a generation. No Switch 2 category observed on
# MMOGA as of 2026-09-14 — a "Nintendo Switch 2" title phrase declares it; a category-only
# row under /Nintendo/Switch/ is a SWITCH declaration (the shared name-suffix guard refuses
# a "… - Nintendo Switch 2 Edition" filed there).
CONSOLE_CATEGORY_RULES: tuple[tuple[str, tuple[str, ...], str | None], ...] = (
    (r"/xbox-live/xbox-360-game-keys/", (), SKIP_XBOX_360),
    (r"/xbox-live/xbox-one-game-keys/", ("XBOX_ONE",), None),
    (r"/xbox-live/xbox-series-xs-game-keys/", ("XBOX_SERIES",), None),
    (r"/playstation-network/playstation-5-game-keys/", ("PS5",), None),
    (r"/playstation-network/playstation-4-game-keys/", ("PS4",), None),
    (r"/nintendo/switch/", ("SWITCH",), None),
)
# Card / subscription CATEGORY segments: the title may look like a game ("PSN Card 80 Euro
# [Austria] - Playstation Network Credit" — the shared title markers catch most; these
# catch the rest by category). "Xbox Game Pass Ultimate 1 Month [EU]" is filed under the
# Xbox-One / Xbox-360 GAME categories: the shared GAME PASS title marker catches it first.
NON_GAME_CATEGORY_RE = re.compile(
    r"/(psn-cards(?:-[a-z]+)?|nintendo-eshop-cards|playstation-plus|xbox-live-cards|xbox-live-gold)/"
)


def console_url_families(url: str) -> tuple[str, ...] | str | None:
    """The console platform the URL category declares — ("XBOX_ONE",), ("XBOX_SERIES",),
    ("PS5",), ("PS4",), ("SWITCH",) — or a skip ("console: Xbox 360 (R45)", "console: PSN
    CARDS AT — not a game (R45)"), or None when the category is not a console one."""

    path = urlsplit(url or "").path.lower()
    m = NON_GAME_CATEGORY_RE.search(path)
    if m:
        return skip_not_a_game(m.group(1).upper().replace("-", " "))
    for rx, families, skip in CONSOLE_CATEGORY_RULES:
        if re.search(rx, path):
            return skip if skip else families
    return None


def console_region_slot(name: str) -> str | None:
    """The region code MMOGA writes with its key word — "Medieval Dynasty - PS5 Download
    Code [EU]" → "EU", "Game (Xbox Series X|S Key EU)" → "EU", "… - US Key" → "US";
    None when there is no such code (the " - EU" dash tail is the shared read)."""

    return region_code(name)


CONFIG = MerchantConfig(
    "MMOGA",
    domain="mmoga.com",
    url_platform_prefixes=MMOGA_URL_PLATFORM_PREFIXES,  # URL category segment = platform
    precheck=precheck,
    title_region=title_region,
    resolve_name=resolve_name,
    english_only_name=english_only_name,   # [R63] crochet de livraison « [… Key - English Only] »
    # console grammar (R45, 2026-09-14): category segment, "<CODE> Key" slot, delivery phrase
    console_url_families=console_url_families,
    console_region_slot=console_region_slot,
    console_noise=("Download Code",),
    notes="feed store id 12 (&store=12); AKS page merchant id 40 (Romain 2026-09-10)",
)

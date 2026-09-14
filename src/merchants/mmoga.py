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
about MMOGA. The region code is an UPPERCASE 2-letter code right before the trailing
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
    "rockstar": "ROCKSTAR",  # no plain-key REGION_IDS entry → fail-closed skip, not Steam
    "battle.net": "BATTLENET",
    "blizzard": "BATTLENET",
    "windows": "MICROSOFT",  # no REGION_IDS entry → fail-closed skip, not Steam
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


def region_code(name: str) -> str | None:
    """The uppercase 2-letter code right before a trailing Key, or None ("Among Us Key" → None)."""

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


def precheck(name: str, url: str) -> str | None:
    """A forbidden or unmapped region code before Key is a lock we must never enter
    worldwide → categorical skip (fail-closed). Sellable codes pass (title_region maps them)."""

    code = region_code(name)
    if code is None or code in SELLABLE_CODES:
        return None
    return f"forbidden region: {FORBIDDEN_CODES.get(code, code)}"


def title_region(name: str) -> str | None:
    """"Borderlands 2 US Key" → "us"; "Borderlands 2 EU Key" → "eu"; no code → None (generic)."""

    return SELLABLE_CODES.get(region_code(name) or "")


def resolve_name(name: str) -> str:
    """The title handed to AKS resolution: the "<CODE> Key" tail peeled off, so the slug is
    "borderlands-2", not the 404 "borderlands-2-eu". Untouched when there is no code."""

    if not region_code(name):
        return name
    return REGION_CODE_TAIL_RE.sub("", REGION_CODE_KEY_RE.sub("", name)).rstrip()


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
    # console grammar (R45, 2026-09-14): category segment, "<CODE> Key" slot, delivery phrase
    console_url_families=console_url_families,
    console_region_slot=console_region_slot,
    console_noise=("Download Code",),
    notes="feed store id 12 (&store=12); AKS page merchant id 40 (Romain 2026-09-10)",
)

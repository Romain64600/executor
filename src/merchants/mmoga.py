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
"""

from __future__ import annotations

import re

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
    return m.group(1) if m else None


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

    return REGION_CODE_KEY_RE.sub("", name) if region_code(name) else name


CONFIG = MerchantConfig(
    "MMOGA",
    domain="mmoga.com",
    url_platform_prefixes=MMOGA_URL_PLATFORM_PREFIXES,  # URL category segment = platform
    precheck=precheck,
    title_region=title_region,
    resolve_name=resolve_name,
    notes="store id: to confirm on the live AKS feed dropdown (2026-09-10)",
)

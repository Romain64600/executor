"""Eneba — platform from the URL's leading path segment (R29, migrated 2026-08-28).

Eneba titles often omit the platform, but its URL convention
(``eneba.com/<platform>-<slug>``) declares it. Pure data + config — no resolver code,
no matcher import.
"""

from __future__ import annotations

from src.merchant_config import MerchantConfig

# Only prefixes we have a platform constant + region mapping for; console/currency/
# software prefixes (nintendo, xbox, psn, top, other, riot, …) are left unmapped —
# already caught by the console/currency/software-app categorical skips.
ENEBA_URL_PLATFORM_PREFIXES = {
    "steam": "STEAM",
    "gog": "GOG",
    "epic": "EPIC",
    "uplay": "UBISOFT",
    "origin": "EA",
    "blizzard": "BATTLENET",
    "windows": "MICROSOFT",  # no REGION_IDS entry -> fail-closed skip, not Steam
}

CONFIG = MerchantConfig(
    "Eneba",
    url_platform_prefixes=ENEBA_URL_PLATFORM_PREFIXES,  # URL leading segment = platform (R29)
)

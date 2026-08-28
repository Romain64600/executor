"""G2A — platform from the URL slug, not the (unreliable) title (R32b, migrated 2026-08-28).

G2A titles are unreliable for the platform; the slug carries it instead
(…-steam-key-…, …-ubisoft-connect-key-…, …-rockstar-…). A green-gift slug
(…-green-gift-key-…) carries NO platform token → None → fail-closed (its real platform
is only on the G2A offer page, which hard-blocks fetches — GMG handling is pending).
Pure config — no resolver code, no matcher import.
"""

from __future__ import annotations

from src.merchant_config import MerchantConfig

CONFIG = MerchantConfig(
    "G2A",
    title_is_platform_source=False,
    url_platform_scan=True,
    # G2A hard-blocks non-browser fetches (403), so a green-gift's real platform — only
    # on its offer page — is unverifiable yet → fail-closed skip until browser
    # page-opening lands (R32c). The maintained "can't open page" list.
    offer_page_readable=False,
)

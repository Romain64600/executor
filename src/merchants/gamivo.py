"""Gamivo — skip language-locked keys (migrated 2026-08-28).

A Gamivo URL path with an ``-en-`` segment ("…-steam-en-global") is an English-only
key → skip. Pure config — no resolver code, no matcher import.
"""

from __future__ import annotations

from src.merchant_config import MerchantConfig

CONFIG = MerchantConfig(
    "Gamivo",
    url_language_lock=r"(?:^|-)en(?:-|$)",  # "…-steam-en-global" = EN-only key → skip
)

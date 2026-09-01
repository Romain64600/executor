"""Gamivo — no merchant-specific rules left (MA7 language lock retired 2026-09-01).

A Gamivo URL path with an ``-en-`` segment ("…-steam-en-global") used to skip as an
English-only key. Romain 2026-09-01: "EN = english only … enterrable" — a language
variant is now entered as the SAME product (see ``matcher.LANGUAGE_TOKENS``). Kept
in the registry to document the vetted merchant. Pure config, no resolver code.
"""

from __future__ import annotations

from src.merchant_config import MerchantConfig

CONFIG = MerchantConfig("Gamivo")

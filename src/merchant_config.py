"""Per-merchant configuration — the merchant-specific instructions the pipeline
starts from (Romain 2026-08-11: "on part avec la config marchand").

Merchant-specific handling used to be scattered across the matcher. A
``MerchantConfig`` is the single declarative place for a merchant's rules;
``match_offer`` reads ``merchant_config(offer.merchant)`` and applies it. A
merchant WITHOUT a config falls through to the generic behaviour (platform/region/
edition from the feed title + URL), exactly as before.

Migrated (incremental, no regression): **Kinguin** domain, **Difmark** url-ignore,
**Instant Gaming** offer-page platform resolver, **Gamivo** URL language lock,
**Eneba** URL platform prefixes. Difmark's complex offer-page branch (accounts /
region maps) still lives in ``src.matcher`` and is represented by its config
entry — fold it in when next touched. The consuming code keeps each rule's scope
(e.g. Eneba prefixes apply only on eneba.com) and reads the DATA from here.

This module is pure data (no matcher import) to stay circular-import free — the
registry that binds resolvers lives in ``src.matcher``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional


@dataclass(frozen=True)
class MerchantOfferSignals:
    """What a merchant's own offer page yields (R32/R33 — Instant Gaming).
    - ``platform``: our platform token (STEAM/EPIC/…) or None (page named an
      unrecognized platform → the caller skips).
    - ``region_base``: region key (global/eu/us/uk) or None.
    - ``region_forbidden``: the page named a region we don't sell (Latin America /
      ROW / …) → the caller skips (never enters it as GLOBAL).
    A platform-only merchant returns region_base=None + region_forbidden=False, so
    the region stays title/URL-derived."""

    platform: Optional[str] = None
    region_base: Optional[str] = None
    region_forbidden: bool = False


@dataclass(frozen=True)
class MerchantConfig:
    name: str
    # The offer URL must be on this host (Kinguin → kinguin.net). None = no check.
    domain: Optional[str] = None
    # Merchant-specific URL boilerplate stripped before deriving region/edition
    # from the URL (Difmark → "buy-console-account-").
    url_ignore_substrings: tuple[str, ...] = ()
    # When platform/region are not in the feed title, read them from the
    # merchant's own offer page: ``offer_page_resolver(offer_url) ->
    # MerchantOfferSignals``. Raising means the page was unreadable → the caller
    # fails closed. (Instant Gaming: platform from data-platform, region from the
    # page <title> suffix.)
    offer_page_resolver: Optional[Callable[[str], "MerchantOfferSignals"]] = None
    # Eneba: the URL's leading path segment encodes the platform
    # ("eneba.com/steam-…" → STEAM). {prefix: platform token}.
    url_platform_prefixes: dict[str, str] = field(default_factory=dict)
    # Gamivo: a URL path that matches this regex is a language-locked key
    # ("…-steam-en-global" → EN-only) → skip. Applied within the merchant's scope.
    url_language_lock: Optional[str] = None
    # Free-form notes / extension point for future per-merchant knobs.
    notes: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

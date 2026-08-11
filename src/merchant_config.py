"""Per-merchant configuration — the merchant-specific instructions the pipeline
starts from (Romain 2026-08-11: "on part avec la config marchand").

Merchant-specific handling used to be scattered across the matcher (Kinguin's
domain rule, Difmark's offer-page resolver + maps, Gamivo's language lock,
Eneba's URL prefixes, Instant Gaming's page platform). A ``MerchantConfig`` is
the single declarative place for a merchant's rules; ``match_offer`` reads
``merchant_config(offer.merchant)`` and applies it. A merchant WITHOUT a config
falls through to the generic behaviour (platform/region/edition from the feed
title + URL), exactly as before.

This module is pure data (no matcher import) to stay circular-import free — the
registry that binds resolvers lives in ``src.matcher``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional


@dataclass(frozen=True)
class MerchantConfig:
    name: str
    # The offer URL must be on this host (Kinguin → kinguin.net). None = no check.
    domain: Optional[str] = None
    # Merchant-specific URL boilerplate stripped before deriving region/edition
    # from the URL (Difmark → "buy-console-account-").
    url_ignore_substrings: tuple[str, ...] = ()
    # When the real PLATFORM is not in the feed title, read it from the merchant's
    # own offer page: ``offer_platform_resolver(offer_url) -> platform token`` (e.g.
    # "STEAM") or None when the page names an unrecognized platform. Raising means
    # the page was unreadable → the caller fails closed. (Instant Gaming.)
    offer_platform_resolver: Optional[Callable[[str], Optional[str]]] = None
    # Free-form notes / extension point for future per-merchant knobs.
    notes: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

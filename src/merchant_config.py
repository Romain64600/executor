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
    # Eneba: the URL's leading path segment encodes the platform
    # ("eneba.com/steam-…" → STEAM). {prefix: platform token}.
    url_platform_prefixes: dict[str, str] = field(default_factory=dict)
    # Gamivo: a URL path that matches this regex is a language-locked key
    # ("…-steam-en-global" → EN-only) → skip. Applied within the merchant's scope.
    url_language_lock: Optional[str] = None
    # Free-form notes / extension point for future per-merchant knobs.
    notes: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

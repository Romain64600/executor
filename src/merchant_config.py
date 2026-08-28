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
    - ``platform``: our platform token (STEAM/EPIC/…) or None (unrecognized → skip).
    - ``region_resolved``: True when the page gave a region → it OVERRIDES the
      title/URL default. False → keep the title-derived region (platform-only).
    - When resolved, exactly one holds:
        * ``region_base`` set (global/eu/us/uk) → ENTER with that region;
        * ``region_base`` None → the offer is region-locked to a region we don't
          enter; ``region_label`` carries the raw region text so the caller emits a
          ``forbidden region: <label>`` skip. The blacklist-vs-park-vs-skip routing
          of that label is decided in ONE merchant-agnostic place
          (``aks_lists.suggest_target_list``) — LATAM / Brazil / Asia / Russia →
          Blacklist (Romain 2026-08-13), the rest → garder."""

    platform: Optional[str] = None
    region_resolved: bool = False
    region_base: Optional[str] = None
    region_label: str = ""


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
    # Platform-source control (R32b, 2026-08-27 — Romain: "ça dépend du marchand").
    # By default the merchant TITLE declares the platform. A merchant whose titles are
    # unreliable for the platform sets ``title_is_platform_source=False`` — then the
    # platform comes from the URL/page instead of the title (G2A). ``url_platform_scan``
    # scans the WHOLE URL path for a platform token collocated with the key marker
    # (G2A "…-steam-key-…"), as opposed to ``url_platform_prefixes``' leading segment
    # (Eneba). Kinguin is left title-sourced on purpose (Romain: it works today).
    title_is_platform_source: bool = True
    url_platform_scan: bool = False
    # The MAINTAINED list of "we can't open this merchant's offer page yet" (R32c,
    # 2026-08-28 — Romain: "les marchands [dont] on arrive pas à ouvrir la page … par la
    # suite on travaillera dessus"). G2A hard-blocks non-browser fetches (HTTP 403), so
    # a signal only on its offer page (a green-gift's real platform) is UNVERIFIABLE →
    # fail-closed skip, NOT a guess. Flip to True once page-opening via the browser (CDP)
    # lands. Default True (openable) preserves every other merchant.
    offer_page_readable: bool = True
    # Free-form notes / extension point for future per-merchant knobs.
    notes: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

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
registry that binds resolvers lives in ``src.merchants.registry`` (relocated from
``src.matcher`` on 2026-09-14 so that ``src.console_keys`` can consult the merchant hooks
without importing the matcher).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional, Pattern, Union


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
    # Generic-behaviour OVERRIDE hooks (Romain 2026-09-10: « un fichier de config marchand
    # par marchand, qui peut ajouter, overwrite, modifier des comportements génériques »).
    # Each is optional; the matcher calls it FIRST and falls through to the generic rule
    # when it returns None. All pure functions of the feed row (no network).
    #   precheck(name, url) -> skip reason | None   — an extra categorical skip, evaluated
    #       right after the domain check (before the generic console/region/category scans).
    #   title_region(name) -> "eu" | "us" | "uk" | "global" | None — the region the
    #       merchant's title grammar declares; wins over the generic title/URL scan.
    #   resolve_name(name) -> str — the text handed to AKS resolution (slug guessing +
    #       site search) instead of the raw title; e.g. a grammar tail peeled off.
    #   url_platform(url) -> platform token | None — the platform the merchant's URL
    #       grammar declares (our token STEAM/GOG/EPIC/UBISOFT/EA/BATTLENET/ROCKSTAR/
    #       MICROSOFT) or None; consulted FIRST by ``explicit_platform_from_url``, before
    #       the ``url_platform_prefixes`` / ``url_platform_scan`` modes ([R46], 2026-09-12:
    #       Gamivo "…-pc-steam-us-standard" — the platform run sits between the game slug
    #       and the region code, neither a leading segment nor collocated with "key").
    # MMOGA uses the first three ("<Product> <CODE> Key", src/merchants/mmoga.py); Gamivo
    # uses all four (src/merchants/gamivo.py).
    precheck: Optional[Callable[[str, str], Optional[str]]] = None
    title_region: Optional[Callable[[str], Optional[str]]] = None
    resolve_name: Optional[Callable[[str], str]] = None
    url_platform: Optional[Callable[[str], Optional[str]]] = None
    # Console-side hooks (R32 / R45, 2026-09-14 — Romain: « pour la détection région /
    # édition / plateforme, tu as un fichier de config par marchand. Et si tu ne l'as pas,
    # tu dois l'avoir. »). The shared classifier ``src.console_keys.classify_console`` owns
    # the SHARED vocabulary only (platform phrase grammar, families, buckets, non-game and
    # store/delivery markers, region text → base/label mapping); everything a merchant
    # writes in its OWN way is declared here. All optional, all pure functions of the feed
    # row (no network, no matcher import); a merchant without them gets the shared reading.
    #   console_url_families(url) -> tuple of families | skip reason | None — the
    #       families the merchant's URL grammar declares, in order (a subset of XBOX_ONE /
    #       XBOX_SERIES / PS4 / PS5 / SWITCH / SWITCH2 — never XBOX_PC), or a fail-closed
    #       "console: … (R45)" skip reason ("console: Xbox 360 (R45)", "console: PC-only
    #       Xbox Live key (R45)", "console: <MARKER> — not a game (R45)"), or None when the
    #       URL says nothing. Consulted ONLY when the title declares no family; it REPLACES
    #       the shared hyphen-run slug reading for that merchant (MMOGA category segment,
    #       Gamivo fused runs, Eneba slot before the store-key marker).
    #   console_pc_declared(name, url) -> bool — the merchant declares PC / Windows NEXT TO
    #       the console platform in its own grammar (Gamivo "-pc" / "-windows" runs, Eneba
    #       "-windows-" before the run); OR-ed with the shared title phrase check
    #       ("/ Windows", "PC/XBOX …"), which stays generic.
    #   console_region_slot(name) -> str | None — the region TEXT the merchant writes next
    #       to the platform phrase, verbatim ("US", "CA", "Europe", "United Kingdom",
    #       "Hong Kong", "EUROPE"); the mapping text → base (eu/us/uk/global) or forbidden
    #       label stays in ``src.console_keys`` (shared vocabulary). None → the classifier
    #       falls back to its shared tail / bracket reads.
    #   console_noise — merchant phrases stripped from ``resolve_name`` in addition to the
    #       shared store / delivery markers ("Download Code" MMOGA, "Digital Key" /
    #       "Digital Code" Driffle, "(valid until <Month> <Year>)" Kinguin). A ``str`` is a
    #       LITERAL phrase (case-insensitive, whole words, any whitespace between the
    #       words); a compiled ``re.Pattern`` is used as written (its own flags) — for the
    #       forms a literal cannot spell (Gamivo's "EN" / "EN/PL/CS" language tail).
    # MMOGA / Gamivo / Eneba declare theirs in src/merchants/<name>.py.
    console_url_families: Optional[Callable[[str], Optional[Union[tuple[str, ...], str]]]] = None
    console_pc_declared: Optional[Callable[[str, str], bool]] = None
    console_region_slot: Optional[Callable[[str], Optional[str]]] = None
    console_noise: tuple[Union[str, Pattern[str]], ...] = ()
    # Free-form notes / extension point for future per-merchant knobs.
    notes: str = ""
    extra: dict[str, Any] = field(default_factory=dict)
